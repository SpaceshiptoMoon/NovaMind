"""
媒体处理工具：视频关键帧提取 + 音频转写

- 视频：imageio + imageio-ffmpeg 按间隔提取帧（纯 pip 依赖，无需系统 ffmpeg）
- 音频：httpx 直调 OpenAI Whisper API / DashScope SDK 调用 Paraformer / 本地 faster-whisper
"""

import asyncio
import logging
import multiprocessing as mp
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from novamind.shared.config import AudioConfig


class AudioFileInvalidError(ValueError):
    """音频文件本身无效（过小/损坏/格式不支持/解码失败）。

    这类错误是**永久性**的——回退云端 ASR 也无法挽救：云端要么下载同一个损坏文件，
    要么文件根本不是有效音频。调用方（``media_processing``）应直接抛清晰错误引导用户
    重新上传，而不是回退云端把根因藏到 ``FILE_DOWNLOAD_FAILED`` 之后。

    与瞬时性错误区分：模型未找到（``RuntimeError``）、子进程崩溃
    （``BrokenProcessPool``）属环境/运行时问题，回退云端有意义。
    """


logger = logging.getLogger(__name__)


# 音频格式 Magic Bytes 检测表
_AUDIO_MAGIC_BYTES: list[tuple[bytes, str, str]] = [
    (b"RIFF", "wav", "audio/wav"),       # WAV
    (b"OggS", "ogg", "audio/ogg"),       # OGG Vorbis
    (b"fLaC", "flac", "audio/flac"),     # FLAC
    (b"ID3",  "mp3", "audio/mpeg"),      # MP3 (ID3 tag)
]

# ftyp 检测需要检查偏移 4-7（M4A/AAC/MP4 容器）
_FTYP_MIME = {
    b"M4A ": ("m4a", "audio/mp4"),
    b"mp42": ("m4a", "audio/mp4"),
}


def _detect_audio_format(file_content: bytes) -> tuple[str, str]:
    """
    通过 Magic Bytes 检测音频真实格式，不依赖文件扩展名

    Returns:
        (extension, mime_type) 例如 ("mp3", "audio/mpeg")
    """
    if len(file_content) < 12:
        return ("mp3", "audio/mpeg")  # 太短无法检测，默认 mp3

    # 检查文件头部 Magic Bytes
    for magic, ext, mime in _AUDIO_MAGIC_BYTES:
        if file_content[:len(magic)] == magic:
            return (ext, mime)

    # MP3: 无 ID3 标签，以帧同步头开头 (0xFF 0xFB / 0xFF 0xF3 / 0xFF 0xF2)
    if file_content[0] == 0xFF and file_content[1] in (0xFB, 0xF3, 0xF2):
        return ("mp3", "audio/mpeg")

    # AAC: 0xFF 0xF1 / 0xFF 0xF9
    if file_content[0] == 0xFF and file_content[1] in (0xF1, 0xF9):
        return ("aac", "audio/aac")

    # M4A / MP4 容器 (ftyp at offset 4)
    if file_content[4:8] == b"ftyp":
        brand = file_content[8:12]
        if brand in _FTYP_MIME:
            return _FTYP_MIME[brand]
        return ("m4a", "audio/mp4")

    # 默认回退
    return ("mp3", "audio/mpeg")


# ========== 本地 faster-whisper 模型 ==========

# 默认本地模型档位（面向生产 GPU/资源充足服务器）。
# 开发机（无 GPU / 低内存）不要改这个默认，而是在 YAML
# knowledge_base.parsing.local_whisper_model 显式降档（tiny/base/small）。
DEFAULT_LOCAL_WHISPER_MODEL = "large-v3"

# 本地模型档位白名单：faster-whisper-{slug} → HF 仓库 Systran/faster-whisper-{slug}
LOCAL_WHISPER_SUPPORTED_MODELS = ("tiny", "base", "small", "medium", "large-v2", "large-v3")
_LOCAL_MODEL_PREFIX = "faster-whisper-"


def split_local_whisper_model_name(model_name: str | None) -> str | None:
    """识别 faster-whisper-* 家族模型名并返回档位 slug；非家族名返回 None。

    Args:
        model_name: ASR 模型名，如 ``faster-whisper-small``、``paraformer-v2``。

    Returns:
        家族名对应的档位 slug（如 ``small``）；空值或非家族名返回 None
        （由调用方按云端模型处理）。

    Raises:
        ValueError: 是家族名但档位不在支持列表（用户配置错误，须显式报错）。
    """
    if not model_name or not model_name.startswith(_LOCAL_MODEL_PREFIX):
        return None
    slug = model_name[len(_LOCAL_MODEL_PREFIX):]
    if slug not in LOCAL_WHISPER_SUPPORTED_MODELS:
        raise ValueError(
            f"不支持的本地 ASR 模型档位「{slug}」。"
            f"支持的档位: {', '.join(LOCAL_WHISPER_SUPPORTED_MODELS)}"
        )
    return slug


# 本地 ASR 幻觉段过滤阈值（segment 级兜底）。
# 判据为 OpenAI Whisper 官方同款推荐值：无语音概率高 且 平均对数概率低 → 判为幻觉丢弃。
# faster-whisper 在解码窗口层已有同款阈值（no_speech_threshold=0.6 /
# log_prob_threshold=-1.0），这里拦截的是跨窗口的编造与 VAD 未拦住的噪声段，
# 阈值取上游同款依据，非本地案例拟合。
_HALLUCINATION_NO_SPEECH_PROB = 0.6
_HALLUCINATION_AVG_LOGPROB = -1.0

# faster-whisper 通过 PyAV (FFmpeg) 解码，支持的音频格式
# 参考: https://github.com/SYSTRAN/faster-whisper
_LOCAL_ASR_SUPPORTED_EXTENSIONS: set[str] = {
    "wav", "mp3", "flac", "ogg", "m4a", "aac", "wma", "opus", "webm",
}
# Magic bytes 与扩展名的映射（仅包含 _detect_audio_format 能识别的）
_MAGIC_EXT_TO_FORMAT = {
    "wav": "WAV",
    "mp3": "MP3",
    "aac": "AAC",
    "m4a": "M4A/MP4",
    "ogg": "OGG Vorbis",
    "flac": "FLAC",
}

# ASR 专用单进程 executor（子进程隔离）。
# 原因：faster-whisper 的 WhisperModel.transcribe 不支持同一实例并发调用，
#       并发会触发 CTranslate2 原生层崩溃（进程无声猝死，无 Python traceback）。
#       单进程串行化转写，既消除并发崩溃，又把 CPU-bound int8 推理从主进程
#       事件循环剥离——同进程线程 executor 仍与事件循环线程争用 CPU/GIL，
#       长转写会饿死 HTTP 请求；子进程做 OS 级 CPU/GIL 隔离，主进程事件循环
#       彻底不受影响。CTranslate2 崩溃也只杀子进程，不杀主进程。
# 取舍：max_workers=1 意味着音频任务串行，吞吐下降；但本机 CPU 推理本身
#       就慢，安全与隔离远比并发吞吐重要。需要真并行再上多进程池。
# spawn 上下文：Windows 必须；Linux/macOS 用 spawn 统一行为（fork 在 asyncio
#       + C 扩展 + 模型加载有坑）。worker 子进程 import 本模块时模块级会再
#       创建一个 ProcessPoolExecutor 对象，但 worker 不提交任务 → 不 spawn
#       孙进程，无递归，对象随 worker 退出清理，无害。
_asr_executor = ProcessPoolExecutor(
    max_workers=1, mp_context=mp.get_context("spawn"),
)

# 进程池崩溃重建锁（BrokenProcessPool 后串行化重建，避免竞态）
_asr_executor_lock = asyncio.Lock()

# ASR 忙碌锁：转写进行中时 locked，空闲时 unlocked。
# 两个用途：
# 1. 上游 media_processing.py 通过 acquire_asr_or_busy() 尝试非阻塞获取锁，
#    获取不到即说明 ASR 忙碌，抛 LocalASRBusyError 让 arq worker 延后重入队。
# 2. transcribe_audio_local() 持有此锁期间执行转写，保证串行化。
_asr_busy_lock = asyncio.Lock()


def is_local_asr_busy() -> bool:
    """本地 ASR 是否正在转写（非阻塞检查）。

    供日志/监控使用。上游路由决策应使用 acquire_asr_or_busy()，
    后者是非阻塞原子操作，消除 is_local_asr_busy() + acquire 之间的竞态。
    """
    return _asr_busy_lock.locked()


async def acquire_asr_or_busy() -> bool:
    """非阻塞尝试获取 ASR 忙碌锁。

    使用 asyncio.Lock 的 acquire() 配合极短超时模拟非阻塞获取。
    相比 locked() + acquire() 两步操作，这种方式是原子的——
    要么成功获取锁，要么超时返回 False，没有竞态窗口。

    Returns:
        True — 锁已获取，调用方应正常执行转写，完成后释放锁。
        False — ASR 正在转写，调用方应抛出 LocalASRBusyError 让 arq 延后重入队。
    """
    try:
        await asyncio.wait_for(_asr_busy_lock.acquire(), timeout=0.05)
        return True
    except TimeoutError:
        return False


def force_release_asr_slot() -> None:
    """强制释放 ASR 忙碌锁（供云端 ASR 回退路径的 finally 清理）。

    幂等：未持锁时无操作（locked 检查防 RuntimeError）。
    批次 4.4：替代上游直接 import ``_asr_busy_lock`` 私有锁的写法。
    """
    if _asr_busy_lock.locked():
        _asr_busy_lock.release()


def _segments_to_dict(segments_result) -> list[dict]:
    """将 faster-whisper 的 segments 迭代器转为标准字典列表。

    除 text/start/end 外同时采集 avg_logprob/no_speech_prob（转写置信度），
    供幻觉段过滤与下游元数据使用。
    """
    result = []
    for seg in segments_result:
        text = seg.text.strip() if seg.text else ""
        if text:
            result.append({
                "text": text,
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "avg_logprob": getattr(seg, "avg_logprob", None),
                "no_speech_prob": getattr(seg, "no_speech_prob", None),
            })
    return result


def default_faster_whisper_cache_dir(model_slug: str = DEFAULT_LOCAL_WHISPER_MODEL) -> Path:
    """faster-whisper 模型缓存目录命名约定（运行时解析与下载脚本共用同一事实源）。

    Args:
        model_slug: 模型档位 slug（tiny/base/small/medium/large-v2/large-v3）。

    Returns:
        ``backend/.cache/faster-whisper/{slug}``（仓库根缓存，与 deepdoc 同约定；
        Docker 形态该目录被 compose 挂载为 /app/.cache/faster-whisper）。
    """
    from novamind.engines.document.integrations.deepdoc.vision.model_manager import (
        default_model_dir,
    )

    return default_model_dir().parent / "faster-whisper" / model_slug


def _resolve_local_whisper_model_dir(
    audio_config: AudioConfig | None = None,
) -> Path:
    """解析本地 faster-whisper 模型目录。

    优先级：
      1. ``AudioConfig.local_whisper_model_dir``（显式目录，宿主从 YAML
         ``knowledge_base.parsing.local_whisper_model_dir`` 构造注入——存量
         部署已配置具体路径的兼容通道，最高优先）
      2. ``AudioConfig.local_whisper_model``（档位名，如 ``large-v3``）→
         ``backend/.cache/faster-whisper/{档位}``（与下载脚本/部署预装同约定）
      3. YAML ``asr.local_whisper_model_dir``（第二回退目录配置，值可来自
         ``${VAR}`` 环境占位符——存量兼容）
      4. 档位名缺省时用 ``DEFAULT_LOCAL_WHISPER_MODEL``（生产默认 large-v3；
         开发机在 YAML 显式降档）

    引擎侧不再 import `novamind.setting`；YAML 配置由宿主构造 ``AudioConfig``
    注入，从而切断 `shared/knowledge` -> `setting` 的导入边。
    """
    # 1. 显式目录（存量部署兼容通道，最高优先）
    configured = getattr(audio_config, "local_whisper_model_dir", None) if audio_config else None
    if configured:
        return Path(str(configured)).expanduser()

    # 2. 档位名 → 缓存目录命名约定（下载脚本/部署预装默认下载到同一基准）
    model_slug = getattr(audio_config, "local_whisper_model", None) if audio_config else None
    if model_slug:
        return default_faster_whisper_cache_dir(model_slug)

    # 3. 配置中心第二回退（asr.local_whisper_model_dir；值可来自 ${VAR} 占位）
    from novamind.setting.yaml_config import get_config

    cfg_dir = get_config().asr.local_whisper_model_dir
    if cfg_dir:
        return Path(cfg_dir).expanduser()

    # 4. 默认档位
    return default_faster_whisper_cache_dir(DEFAULT_LOCAL_WHISPER_MODEL)


def _resolve_cpu_threads(audio_config: AudioConfig | None = None) -> int:
    """解析本地 ASR 推理使用的 CPU 线程数。

    优先级：
      1. ``AudioConfig.local_whisper_cpu_threads``（宿主从 YAML
         ``knowledge_base.parsing.local_whisper_cpu_threads`` 构造注入）
      2. 默认 ``max(1, logical//2 - 1)``（按物理核估算并留至少 1 物理核）

    子进程的 cpu_threads 限制的是**子进程** CPU，与主进程 OS 级隔离——
    主进程事件循环独占其余核，不受 ASR 推理影响。
    """
    _configured = (
        getattr(audio_config, "local_whisper_cpu_threads", None)
        if audio_config
        else None
    )
    if isinstance(_configured, int) and _configured > 0:
        return _configured
    _logical = os.cpu_count() or 2
    return max(1, (_logical // 2) - 1)


# 子进程内 faster-whisper 模型缓存（仅子进程使用，worker 进程持久复用）。
# 键为 (model_dir, device, compute_type)：配置变化（如切档位/设备）后不会
# 复用旧模型实例，也不因键不同互相挤掉（单 worker 串行下同一键恒命中）。
# 注意：这是子进程模块级全局，主进程不持有模型；spawn worker 首次执行任务时
#       加载，后续复用。必须放在模块级以便子进程 import 时定义。
_subprocess_models: dict[tuple[str, str, str], Any] = {}


def _transcribe_in_subprocess(
    tmp_path: str,
    language: str | None,
    model_dir: str,
    cpu_threads: int,
    *,
    device: str = "auto",
    compute_type: str = "auto",
    beam_size: int = 5,
    vad_enabled: bool = True,
    hotwords: str | None = None,
) -> dict[str, Any]:
    """子进程内执行：加载模型（子进程键控缓存）+ transcribe + 返回可 pickle 结果。

    必须是模块级函数（spawn worker 经 pickle 引用，需可 import）。
    返回纯 dict（segments + info 关键字段），经 IPC 回传主进程。

    转写参数的幻觉抑制组合（均有上游同款依据，见各注释）：
      - vad_filter：silero VAD 前置切掉静音/噪声，省算力且抑制静音段幻觉；
      - condition_on_previous_text=False：切断跨窗口上下文——长音频里上一窗口
        的错误会被复制放大成整段重复文本，是 Whisper 类幻觉的最大来源；
      - 解码层 no_speech_threshold/log_prob_threshold 用上游默认值，
        跨窗口残留的坏段再由 ``_filter_hallucinated_segments`` 兜底。

    Args:
        tmp_path: 主进程写入的临时音频文件路径（子进程读文件，避免传 bytes）
        language: 语言提示，None 表示自动检测
        model_dir: faster-whisper 模型目录（主进程解析后传入）
        cpu_threads: 子进程推理 CPU 线程数（主进程解析后传入）
        device: 推理设备（auto/cpu/cuda），auto 由 CTranslate2 探测 CUDA
        compute_type: 量化类型（auto/int8/float16 等），auto 随设备选择
        beam_size: 束搜索宽度
        vad_enabled: 是否启用 silero VAD 前置过滤
        hotwords: 热词串（空格分隔），None 表示不注入

    Returns:
        {"segments": [{"text","start","end","avg_logprob","no_speech_prob"},...],
         "language": str, "language_probability": float, "duration": float,
         "filtered_count": int}
    """
    global _subprocess_models
    from faster_whisper import WhisperModel

    cache_key = (model_dir, device, compute_type)
    model = _subprocess_models.get(cache_key)
    if model is None:
        model = WhisperModel(
            model_dir,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=1,
            local_files_only=True,
        )
        _subprocess_models[cache_key] = model
        logger.info(
            "子进程 faster-whisper 模型已加载, path=%s, device=%s, compute_type=%s",
            model_dir, device, compute_type,
        )

    logger.info(
        "子进程 ASR 转写开始, file=%s, vad=%s, hotwords=%d词, beam_size=%d",
        tmp_path, vad_enabled, len((hotwords or "").split()), beam_size,
    )
    segments_result, info = model.transcribe(
        tmp_path,
        beam_size=beam_size,
        word_timestamps=False,
        language=language,
        vad_filter=vad_enabled,
        condition_on_previous_text=False,
        hotwords=hotwords,
    )
    logger.info(
        "子进程 ASR 转写完成, language=%s, probability=%.2f, duration=%.1fs",
        info.language, info.language_probability, info.duration,
    )
    raw_segments = _segments_to_dict(segments_result)
    segments, filtered_count = _filter_hallucinated_segments(raw_segments)
    if filtered_count:
        logger.info(
            "子进程 ASR 幻觉段过滤: 丢弃 %d/%d 段", filtered_count, len(raw_segments),
        )
    return {
        "segments": segments,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "filtered_count": filtered_count,
    }


def _filter_hallucinated_segments(
    segments: list[dict],
) -> tuple[list[dict], int]:
    """过滤幻觉段 + 折叠相邻重复段，返回 (保留列表, 丢弃数)。

    两类通用判据（非黑名单、非案例拟合）：
      1. 无语音概率高且平均对数概率低 → 模型自己对这段没把握，多为静音/噪声
         上编造的文本；阈值取 OpenAI Whisper 官方同款（0.6 / -1.0）。
      2. 相邻 segment 文本完全相同 → Whisper 在静音/音乐段的典型重复幻觉；
         折叠为一条。非相邻的重复（正常文档里合法出现）不受影响。

    Args:
        segments: 已归一的 segment 字典列表（含 avg_logprob/no_speech_prob）。

    Returns:
        (过滤后的 segments, 丢弃的段数)。
    """
    kept: list[dict] = []
    dropped = 0
    for seg in segments:
        no_speech = float(seg.get("no_speech_prob") or 0.0)
        avg_logprob = float(seg.get("avg_logprob") or 0.0)
        if no_speech > _HALLUCINATION_NO_SPEECH_PROB and avg_logprob < _HALLUCINATION_AVG_LOGPROB:
            dropped += 1
            continue
        # 相邻重复折叠：与前一条保留项文本完全相同才折叠
        if kept and seg.get("text") == kept[-1].get("text"):
            dropped += 1
            continue
        kept.append(seg)
    return kept, dropped


async def _rebuild_asr_executor() -> None:
    """进程池崩溃后重建（BrokenProcessPool 后调用）。

    CTranslate2 原生层 segfault 会杀子进程 → ProcessPoolExecutor 抛
    BrokenProcessPool。重建池后下次任务重新加载模型；本次抛错由上游
    media_processing 回退云端 ASR。
    """
    global _asr_executor
    async with _asr_executor_lock:
        try:
            _asr_executor.shutdown(wait=False)
        except Exception:
            pass
        _asr_executor = ProcessPoolExecutor(
            max_workers=1, mp_context=mp.get_context("spawn"),
        )
        logger.warning("ASR 进程池已重建（前一个子进程崩溃）")


def _validate_audio_for_local_asr(file_content: bytes) -> tuple[str, str]:
    """
    在调用本地 ASR 前校验音频格式

    faster-whisper 通过 PyAV (FFmpeg) 解码音频，理论支持所有 FFmpeg 可解码的格式。
    但某些专有/损坏格式可能无法解码，这里做前端校验给出明确错误信息。

    Returns:
        (ext, mime_type) 如果格式可接受

    Raises:
        AudioFileInvalidError: 格式不支持或文件无效
    """
    if not file_content or len(file_content) < 12:
        raise AudioFileInvalidError("音频文件太小或为空，无法识别格式 (最小 12 bytes)")

    ext, mime = _detect_audio_format(file_content)

    # 检查是否在本地 ASR 支持列表中
    if ext not in _LOCAL_ASR_SUPPORTED_EXTENSIONS:
        # 尝试给出更详细的诊断
        detected_desc = _MAGIC_EXT_TO_FORMAT.get(ext, f"未知格式 (.{ext})")
        raise AudioFileInvalidError(
            f"本地 ASR 不支持此音频格式: {detected_desc}。"
            f"支持的格式: {', '.join(sorted(_LOCAL_ASR_SUPPORTED_EXTENSIONS))}"
        )

    return ext, mime


async def transcribe_audio_local(
    file_content: bytes,
    file_type: str = "mp3",
    language: str | None = None,
    audio_config: AudioConfig | None = None,
    hotwords: list[str] | None = None,
) -> list[dict]:
    """
    使用本地 faster-whisper 模型转写音频，返回带时间戳的段落

    无需 API Key、无需网络，模型通过 PyAV (FFmpeg) 自动处理音频解码和重采样。

    Args:
        file_content: 音频文件二进制内容
        file_type: 提示用，实际格式通过 Magic Bytes 检测
        audio_config: 引擎音频配置，宿主从 YAML 构造注入（模型目录/档位/
            device/compute_type/beam_size/VAD 开关）；
            仅在模型首次加载时生效。
        hotwords: 领域热词列表（如产品名/人名/术语），空格拼接后经
            faster-whisper 原生 ``hotwords`` 参数注入解码，提升专有名词命中率；
            空列表/None 表示不注入。

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2, "avg_logprob": ...,
          "no_speech_prob": ...}, ...]（幻觉段已过滤、相邻重复已折叠）

    Raises:
        AudioFileInvalidError: 音频格式不支持或文件无效（永久性，调用方不应回退云端）
        RuntimeError: 模型未找到或转写失败（瞬时性，可回退云端）
    """
    # 1. 格式校验 + 音频时长预检（在进入模型前拒绝无效文件）
    ext, _mime = _validate_audio_for_local_asr(file_content)
    logger.info(
        "本地 ASR: 格式校验通过 ext=%s, file_type_hint=%s, size=%d",
        ext, file_type, len(file_content),
    )

    # 1.5 极小文件拦截：低于 1KB 的音频文件几乎不可能包含有效语音内容，
    #     且极可能触发 CTranslate2/PyAV 原生层崩溃（segfault，无 Python traceback，
    #     直接杀死进程）。在进入线程池之前提前拒绝，保护进程安全。
    MIN_AUDIO_SIZE = 1024  # 1KB
    if len(file_content) < MIN_AUDIO_SIZE:
        raise AudioFileInvalidError(
            f"音频文件过小 ({len(file_content)} bytes)，"
            f"本地 ASR 要求至少 {MIN_AUDIO_SIZE} bytes 才能安全转写。"
            f"请确认文件完整且包含有效音频数据。"
        )

    # 2. 写入临时文件（faster-whisper 当前版本仅支持文件路径，不支持 BytesIO）
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        # 3. 解析模型目录 + 推理参数（主进程），校验模型存在
        model_dir = _resolve_local_whisper_model_dir(audio_config)
        if not model_dir.exists():
            raise RuntimeError(
                f"本地 ASR 模型未找到: {model_dir}，"
                f"请运行 python scripts/download_faster_whisper_model.py --model "
                f"{getattr(audio_config, 'local_whisper_model', None) or DEFAULT_LOCAL_WHISPER_MODEL} "
                f"预装，或在配置 knowledge_base.parsing.local_whisper_model_dir 指定路径。"
            )
        cpu_threads = _resolve_cpu_threads(audio_config)
        device = getattr(audio_config, "local_whisper_device", None) or "auto"
        compute_type = getattr(audio_config, "local_whisper_compute_type", None) or "auto"
        beam_size = getattr(audio_config, "local_whisper_beam_size", None) or 5
        vad_enabled = getattr(audio_config, "local_whisper_vad_enabled", True)
        hotwords_str = " ".join(hotwords) if hotwords else None

        logger.info(
            "本地 ASR 转写开始, file=%s, size=%d, model_dir=%s, device=%s, "
            "compute_type=%s, beam_size=%d, vad=%s, hotwords=%d词",
            tmp_path, len(file_content), model_dir, device, compute_type,
            beam_size, vad_enabled, len(hotwords or []),
        )
        # 走专用单进程 executor：子进程内加载模型 + transcribe，OS 级 CPU/GIL 隔离，
        # 主进程事件循环不受 int8 推理饿死；单进程串行避免并发同一模型实例崩溃。
        loop = asyncio.get_running_loop()

        def _invoke_subprocess(lang: str | None):
            return loop.run_in_executor(
                _asr_executor,
                _transcribe_in_subprocess,
                tmp_path,
                lang,
                str(model_dir),
                cpu_threads,
                {
                    "device": device,
                    "compute_type": compute_type,
                    "beam_size": beam_size,
                    "vad_enabled": vad_enabled,
                    "hotwords": hotwords_str,
                },
            )

        try:
            result = await _invoke_subprocess(language)
        except BrokenProcessPool:
            # 子进程崩溃（CTranslate2 segfault 等）→ 重建池，本次抛错让上游回退云端
            await _rebuild_asr_executor()
            raise

        logger.info(
            "本地 ASR 转写完成, language=%s, probability=%.2f, duration=%.1fs, "
            "hallucination_filtered=%d",
            result["language"], result["language_probability"], result["duration"],
            result.get("filtered_count", 0),
        )

        # 4. 结果格式已由子进程归一为 segments dict
        segments = result["segments"]

        # 5. 结果为空且语言自动检测置信度低时，用中文重试
        #    tiny 模型容易把中文误判为英语（probability < 0.5），导致转写为空。
        #    显式指定 zh 可以大幅提升中文识别率。
        #    注意：仅在首次转写结果为空时重试，已有内容则不再浪费 ASR 子进程。
        if not segments and language is None and result["language_probability"] < 0.5:
            logger.warning(
                "本地 ASR 语言检测置信度低 (language=%s, probability=%.2f)，用中文重试",
                result["language"], result["language_probability"],
            )
            try:
                result = await _invoke_subprocess("zh")
            except BrokenProcessPool:
                await _rebuild_asr_executor()
                raise
            logger.info(
                "本地 ASR 中文重试完成, language=%s, probability=%.2f, duration=%.1fs",
                result["language"], result["language_probability"], result["duration"],
            )
            segments = result["segments"]

        if not segments:
            logger.warning(
                "本地 ASR 转写结果为空, language=%s, duration=%.1fs",
                result["language"], result["duration"],
            )

        return segments

    except Exception as e:
        # 捕获 PyAV 解码错误等，转换为明确的错误信息
        error_msg = str(e)
        if "av." in type(e).__module__ or "PyAV" in type(e).__name__:
            raise AudioFileInvalidError(
                f"音频解码失败，文件可能已损坏或编码不兼容: {error_msg[:200]}"
            ) from e
        raise

    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def upload_parsed_text_to_minio(document, full_text: str, logger, *, minio_client) -> str:
    """
    将解析/转写后的原始全文上传到 MinIO，并在 document.storage JSON 中记录路径

    存储路径: {原始文件路径}_parsed/full_text.md

    Args:
        document: Document ORM 对象（需有 .storage JSON 字段）
        full_text: 完整的解析/转写文本
        logger: 日志记录器
        minio_client: MinIO 客户端（关键字注入，批次 6a-5 切断对
            ``shared.clients.ClientFactory`` 的惰性 import；调用方负责经宿主装配获取）

    Returns:
        MinIO object_name，如果上传失败或文本为空则返回空字符串
    """
    if not full_text or not full_text.strip():
        logger.warning("解析全文为空，跳过 MinIO 上传", document_id=document.id)
        return ""

    try:
        storage = document.storage or {}
        base = storage.get("minio_object_name", "")
        if not base:
            logger.warning("文档无 minio_object_name，跳过解析全文上传", document_id=document.id)
            return ""

        object_name = f"{base}_parsed/full_text.md"
        # Windows 下很多查看器会优先按本地代码页猜测编码，UTF-8 BOM 能显著提升识别率
        data = full_text.encode("utf-8-sig")

        await minio_client.upload_file(object_name, data, "text/markdown; charset=utf-8")

        document.storage = {
            **storage,
            "parsed_text_object": object_name,
        }

        logger.info(
            "解析全文已上传 MinIO", document_id=document.id,
            object_name=object_name, size_chars=len(full_text),
        )
        return object_name

    except Exception as e:
        logger.error(
            "解析全文上传 MinIO 失败", document_id=document.id,
            error=str(e),
        )
        return ""


async def transcribe_audio_with_timestamps(
    file_content: bytes,
    file_type: str = "mp3",
    model: str = "whisper-1",
    api_key: str | None = None,
    base_url: str | None = None,
    language: str | None = None,
) -> list[dict]:
    """
    使用 httpx 直调 OpenAI Whisper API 转写音频，返回带时间戳的段落

    不依赖 openai 包，纯 httpx multipart/form-data 请求。

    Args:
        file_content: 音频文件二进制内容
        file_type: 音频文件类型 (mp3/wav/flac/ogg/m4a)
        model: Whisper 模型名，默认 whisper-1
        api_key: OpenAI API Key，不传则从环境变量读取
        base_url: API Base URL，不传则用默认

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2}, ...]
    """
    import httpx

    if not api_key or not base_url:
        from novamind.setting.yaml_config import get_config

        asr_cfg = get_config().asr
        api_key = api_key or asr_cfg.openai_api_key
        base_url = base_url or asr_cfg.openai_base_url
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY（asr.openai_api_key），无法使用 Whisper API")

    # 通过 Magic Bytes 检测真实音频格式，不再依赖文件扩展名
    ext, mime_type = _detect_audio_format(file_content)
    suffix = f".{ext}"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        url = f"{base_url.rstrip('/')}/audio/transcriptions"

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            with open(tmp_path, "rb") as f:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={
                        "model": model,
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment",
                        **({"language": language} if language else {}),
                    },
                    files={"file": (f"audio{suffix}", f, mime_type)},
                )
                response.raise_for_status()
                data = response.json()

        segments = []
        for seg in data.get("segments", []):
            text = seg.get("text", "").strip()
            if text:
                segments.append({
                    "text": text,
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                })

        return segments

    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def transcribe_audio_with_dashscope(
    file_content: bytes,
    file_type: str = "mp3",
    model: str = "paraformer-v2",
    api_key: str | None = None,
    base_url: str | None = None,
    minio_bucket: str | None = None,
    language_hints: list[str] | None = None,
    *,
    minio_client,
) -> list[dict]:
    """
    使用 DashScope SDK 调用 Paraformer 转写音频，返回带时间戳的段落

    流程：字节 → 临时文件 → MinIO 上传（预签名URL）→ Transcription.async_call(HTTP URL) → wait

    Args:
        file_content: 音频文件二进制内容
        file_type: 音频文件类型 (mp3/wav/flac/ogg/m4a)
        model: DashScope ASR 模型名，默认 paraformer-v2
        api_key: DashScope API Key，不传则从环境变量读取
        base_url: DashScope/百炼 平台 API 地址，不传则使用 SDK 默认
        minio_bucket: MinIO 桶名，用于上传临时文件生成预签名 URL
        language_hints: 语言提示列表，如 ['zh', 'en']，仅 paraformer-v2 支持
        minio_client: MinIO 客户端（关键字注入，批次 6a-5 切断对
            ``shared.clients.ClientFactory`` 的惰性 import；调用方负责经宿主装配获取）

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2}, ...]
    """
    import uuid

    import dashscope
    from novamind.shared.ai_models.asr import (
        await_transcription_async,
        configure_dashscope,
        extract_segments,
        submit_transcription,
    )

    if not api_key:
        from novamind.setting.yaml_config import get_config

        api_key = get_config().asr.dashscope_api_key
        if not api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY（asr.dashscope_api_key），无法使用 DashScope Paraformer API")
    configure_dashscope(api_key, base_url)

    # 通过 Magic Bytes 检测真实音频格式，不再依赖文件扩展名
    ext, _mime = _detect_audio_format(file_content)
    suffix = f".{ext}"
    logger.info(
        "DashScope 音频转写: 检测到格式=%s, 文件大小=%d bytes, 模型=%s, base_url=%s",
        ext, len(file_content), model, dashscope.base_http_api_url,
    )

    # 1. 写入临时文件
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    temp_object_name = None
    try:
        # 2. 上传到 MinIO 获取预签名 URL（百炼平台不支持 fileid://）
        bucket = minio_bucket or "novamind"
        temp_object_name = f"_asr_temp/{uuid.uuid4().hex}.{ext}"
        await minio_client.upload_file(temp_object_name, file_content, f"audio/{ext}")
        uploaded_url = await minio_client.get_public_file_url(bucket, temp_object_name, expires=3600)
        logger.info("音频已上传 MinIO 临时位置: %s, url=%s...", temp_object_name, uploaded_url[:80])

        # 3-5. 提交 → 轮询 → 解析（协议胶水唯一实现：shared/ai_models/asr/dashscope_client）
        # 轮询走 async 包装：to_thread 隔离 + 总超时，SDK wait 是同步 sleep 循环，
        # 直接调用会冻结整个 worker 事件循环（2026-09 链路审计 P0）。
        task_response = submit_transcription(
            model=model, file_urls=[uploaded_url], language_hints=language_hints
        )
        output_dict = await await_transcription_async(task_response.output.task_id)
        logger.info("DashScope 转写原始结果: %s", str(output_dict)[:2000])

        segments = extract_segments(output_dict)
        return segments

    finally:
        Path(tmp_path).unlink(missing_ok=True)
        # 清理 MinIO 临时文件
        if temp_object_name:
            try:
                _bucket = minio_bucket or "novamind"
                await asyncio.to_thread(minio_client.client.remove_object, _bucket, temp_object_name)
                logger.debug("已清理 MinIO 临时文件: %s", temp_object_name)
            except Exception as e:
                logger.warning("清理 MinIO 临时文件失败: %s, error=%s", temp_object_name, str(e))
