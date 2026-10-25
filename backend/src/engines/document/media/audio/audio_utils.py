"""
媒体处理工具：视频关键帧提取 + 音频转写

- 视频：imageio + imageio-ffmpeg 按间隔提取帧（纯 pip 依赖，无需系统 ffmpeg）
- 音频：httpx 直调 OpenAI Whisper API / DashScope SDK 调用 Paraformer / 本地 faster-whisper
"""

import asyncio
import functools
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

# 声学能量交叉验证参数。
# 短文本段的能量判据：Whisper 在近静音段编造的文本几乎总是极短的套话
# （「谢谢观看」「Bye.」），真实语音段很少有 <15 字符的孤立短段落在纯底噪上；
# 长短语文本大概率是真实轻声/远场内容，能量判据只对短文本做交叉验证，
# 避免误伤。
_HALLUCINATION_SHORT_TEXT_CHARS = 15


def _segment_rms_dbfs(
    audio: Any,
    start: float,
    end: float,
    sample_rate: int = 16000,
) -> float | None:
    """计算音频某一时间窗的 RMS 电平（dBFS）。

    dBFS = 20*log10(sqrt(mean(x^2)))，满幅正弦为 0。量级参考：正常语音
    -30~-20 dBFS，底噪 -45~-40 dBFS，数字静音段为 -inf（均值 0）。

    Args:
        audio: float32/int32 ndarray（faster-whisper decode_audio 输出，单声道）。
        start: 窗口起点（秒）。
        end: 窗口终点（秒）。
        sample_rate: 采样率（Hz），默认 16000（faster-whisper 解码约定）。

    Returns:
        RMS dBFS 值；窗口越界/空窗/数值异常时返回 None（调用方按「无法验证」
        处理，不丢弃——失败方向安全：能力缺失优于错误结果）。
    """
    try:
        import numpy as np

        if audio is None or getattr(audio, "size", 0) == 0:
            return None
        lo = max(0, int(start * sample_rate))
        hi = min(len(audio), int(end * sample_rate))
        if hi <= lo:
            return None
        window = np.asarray(audio[lo:hi], dtype=np.float64)
        rms = float(np.sqrt(np.mean(np.square(window))))
        if rms <= 0.0:
            return float("-inf")
        return 20.0 * float(np.log10(rms))
    except Exception:  # noqa: BLE001 - 能量校验失败按「无法验证」处理，绝不抛错阻断转写
        return None


def _filter_low_energy_segments(
    segments: list[dict],
    audio: Any,
    min_dbfs: float,
    sample_rate: int = 16000,
) -> tuple[list[dict], int]:
    """声学能量交叉验证：丢弃「短文本 + 能量低于阈值」的段。

    只对 ≤``_HALLUCINATION_SHORT_TEXT_CHARS`` 字符的段做能量验证——长文本
    即使能量低也保留（真实轻声内容优先保真）。能量无法计算（窗口越界/
    解码失败）时保留段，失败方向安全。

    Args:
        segments: 已归一的 segment 字典列表（含 start/end）。
        audio: 已解码 PCM ndarray（None 时跳过校验，全部保留）。
        min_dbfs: RMS dBFS 下限，低于该值判为非语音。
        sample_rate: 采样率。

    Returns:
        (过滤后的 segments, 丢弃的段数)。
    """
    if audio is None or min_dbfs is None:
        return segments, 0
    kept: list[dict] = []
    dropped = 0
    for seg in segments:
        text = seg.get("text") or ""
        if len(text) > _HALLUCINATION_SHORT_TEXT_CHARS:
            kept.append(seg)
            continue
        dbfs = _segment_rms_dbfs(audio, seg.get("start", 0.0), seg.get("end", 0.0), sample_rate)
        if dbfs is not None and dbfs < min_dbfs:
            dropped += 1
            logger.info(
                "声学能量过滤: 丢弃低能量短段 (%.2f dBFS < %.2f), text=%r, [%.2f-%.2f]",
                dbfs, min_dbfs, text[:20], seg.get("start", 0.0), seg.get("end", 0.0),
            )
            continue
        kept.append(seg)
    return kept, dropped

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
    """本进程内 ASR 是否正在转写（非阻塞检查；跨进程租约状态另见 asr_lease.lease_held）。

    供日志/监控使用。上游路由决策应使用 acquire_asr_or_busy()，
    后者是非阻塞原子操作，消除 is_local_asr_busy() + acquire 之间的竞态。
    """
    return _asr_busy_lock.locked()


async def acquire_asr_or_busy() -> bool:
    """非阻塞尝试获取 ASR 忙碌权：Redis 跨进程租约优先，退化进程内锁。

    双层语义（批次 6.1）：多 worker 进程部署下同一 GPU 至多一个本地 ASR
    由 Redis 租约保证（TTL 兜底僵尸租约，见 asr_lease 模块说明）；Redis
    不可用时退化 asyncio.Lock（单进程部署语义不变）。进程内锁的获取用
    acquire() 配合极短超时模拟非阻塞——原子，无 locked()+acquire() 竞态窗口。

    Returns:
        True — 忙碌权已获取，调用方应正常执行转写，完成后 force_release_asr_slot()。
        False — ASR 正在转写，调用方应抛出 LocalASRBusyError 让 arq 延后重入队。
    """
    from novamind.engines.document.media.audio import asr_lease

    if await asr_lease.acquire_lease():
        return True
    if await asr_lease.lease_held():
        # 租约确实被其他进程持有——忙碌明确，不再竞争进程内锁
        return False
    try:
        await asyncio.wait_for(_asr_busy_lock.acquire(), timeout=0.05)
        return True
    except TimeoutError:
        return False


async def release_asr_slot() -> None:
    """释放 ASR 忙碌权：跨进程租约 + 进程内锁（异步上下文的规范释放口）。

    两者各自幂等：本进程未持租约时 release_lease 无操作（token 防误删），
    未持本地锁时 locked 检查防 RuntimeError。
    """
    from novamind.engines.document.media.audio import asr_lease

    await asr_lease.release_lease()
    if _asr_busy_lock.locked():
        _asr_busy_lock.release()


def force_release_asr_slot() -> None:
    """同步上下文的释放口：本地锁立即释放，租约 fire-and-forget 释放。

    供同步 finally 等无 await 位置调用；租约释放任务若因进程退出未执行，
    由租约 TTL（略超 arq job_timeout）兜底过期，不会永久锁死。
    """
    import asyncio as _asyncio

    if _asr_busy_lock.locked():
        _asr_busy_lock.release()
    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        return
    from novamind.engines.document.media.audio import asr_lease

    loop.create_task(asr_lease.release_lease())


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
      3. 档位名缺省时用 ``DEFAULT_LOCAL_WHISPER_MODEL``（生产默认 large-v3；
         开发机在 YAML 显式降档）

    YAML ``asr.local_whisper_model_dir`` 的第二回退已上移宿主
    （``_build_engine_audio_config`` 合并进 ``AudioConfig.local_whisper_model_dir``
    的构造）——引擎层零 ``novamind.setting`` 依赖，可独立发包（发包模式改造）。

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

    # 3. 默认档位（发包纪律：引擎零 setting 依赖——原第 3 级 YAML
    # asr.local_whisper_model_dir 回退已上移宿主 _build_engine_audio_config）
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


def _precheck_hotwords(model: Any, hotwords: str | None) -> str | None:
    """热词 tokenizer 预检：热词含模型词表无法编码的字符时降级丢弃。

    faster-whisper 经 tokenizer 编码热词注入解码 prompt，热词含生僻符号/乱码
    字符时部分版本会在编码层抛异常直接打断转写。预检只探测不拦截正常输入——
    预检失败降级为不注入热词（能力缺失），绝不让可选增强阻断主流程。

    Args:
        model: WhisperModel 实例（探测 ``hf_tokenizer``/``tokenizer`` 属性）。
        hotwords: 热词串（空格分隔），None 直接透传。

    Returns:
        原热词串（可正常编码）或 None（预检失败/无法探测/热词为空）。
    """
    if not hotwords:
        return hotwords
    tokenizer = getattr(model, "hf_tokenizer", None) or getattr(model, "tokenizer", None)
    if tokenizer is None:
        # 无法探测 tokenizer（版本差异）：不预检，交由 faster-whisper 原行为
        return hotwords
    try:
        tokenizer.encode(hotwords)
    except Exception as e:  # noqa: BLE001 - 热词编码失败必须降级而非阻断转写
        logger.warning("热词编码预检失败，本次转写不注入热词: %s, hotwords=%r", e, hotwords[:50])
        return None
    return hotwords


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
    min_speech_dbfs: float | None = -40.0,
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
        min_speech_dbfs: 段级声学能量下限（RMS dBFS），低于该值的短文本段判为
            幻觉丢弃；None 表示禁用能量交叉验证

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
    hotwords = _precheck_hotwords(model, hotwords)
    # 解码一次两用：transcribe 直接吃 PCM ndarray（省一次 PyAV 解码），
    # 同时给能量交叉验证提供波形。解码失败（PyAV 不认的容器等）不阻断转写——
    # 回退传文件路径由 faster-whisper 自行解码，能量校验自动跳过（失败方向安全）。
    audio_pcm = None
    if min_speech_dbfs is not None:
        try:
            from faster_whisper.audio import decode_audio

            audio_pcm = decode_audio(tmp_path, sampling_rate=16000)
        except Exception:  # noqa: BLE001 - 解码失败仅放弃能量校验，不放弃转写
            logger.warning("音频预解码失败，跳过声学能量校验, file=%s", tmp_path)
    segments_result, info = model.transcribe(
        audio_pcm if audio_pcm is not None else tmp_path,
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
    segments, phrase_dropped = _filter_stock_phrase_segments(segments)
    if phrase_dropped:
        filtered_count += phrase_dropped
        logger.info("子进程 ASR 套话过滤: 丢弃 %d 段", phrase_dropped)
    if min_speech_dbfs is not None:
        segments, energy_dropped = _filter_low_energy_segments(
            segments, audio_pcm, min_speech_dbfs
        )
        if energy_dropped:
            filtered_count += energy_dropped
            logger.info(
                "子进程 ASR 能量过滤: 丢弃 %d 段 (阈值 %.1f dBFS)",
                energy_dropped, min_speech_dbfs,
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


# 幻觉短语双门控参数。
# 结构门控阈值：Whisper 幻觉套话几乎总发生在片头/片尾的静音/音乐残留上，特征是
# 「很短的时长 + 很短的文本 + 与相邻段之间有大段空白」。三项同时满足才进入
# 短语比对，正常视频/播客里的口头禅（如剪辑师真说了「谢谢观看」）因上下文
# 密集不满足结构条件，不会被误伤。
# 量级依据：典型幻觉段 <4s（片尾曲残留窗口），套话本身 <30 字，幻觉与正片
# 之间的静音/音乐间隔普遍 >2s（远大于正常段间 0.2~1s 换气停顿）。
_PHRASE_GATE_MAX_DUR_S = 4.0
_PHRASE_GATE_MAX_CHARS = 30
_PHRASE_GATE_MIN_GAP_S = 2.0

# 幻觉套话短语表（仅作结构门控命中后的二次确认，不单独构成丢弃依据）。
# 来源：HF sachaarbonel/whisper-hallucinations 与 r/LocalLLama 社区高频反馈
# 汇总（中英都收），均为 Whisper 训练数据（字幕/YouTube）尾部残留的高频套话。
# 未列入的罕见套话由统计判据（no_speech_prob/avg_logprob）与能量判据兜底。
_HALLUCINATION_PHRASES: tuple[str, ...] = (
    # 中文
    "谢谢观看",
    "谢谢收看",
    "谢谢大家",
    "感谢观看",
    "感谢收看",
    "下期再见",
    "我们下期再见",
    "拜拜",
    "请订阅",
    "订阅频道",
    "关注我们",
    "点赞关注",
    "字幕",
    "字幕由",
    "字幕提供",
    "翻译",
    "以下是字幕",
    "明镜需要您的支持",
    "明镜与您不再分离",
    "订阅我们的频道",
    # 英文
    "thanks for watching",
    "thank you for watching",
    "thanks for listening",
    "see you next time",
    "subscribe",
    "please subscribe",
    "don't forget to subscribe",
    "like and subscribe",
    "bye",
    "bye bye",
    "goodbye",
    "amara.org community",
    "subtitles by",
    "subtitles by the amara.org community",
    "transcription by",
    "english subtitles by",
)


def _is_phrase_gate_structural_hit(seg: dict, prev: dict | None, nxt: dict | None) -> bool:
    """结构门控：段是否满足「孤立超短段」的幻觉形态（三项判据与短语无关）。

    Args:
        seg: 当前段（含 text/start/end）。
        prev: 前一个相邻段（无则视为边界静音，满足间隔条件）。
        nxt: 后一个相邻段（无则视为边界静音，满足间隔条件）。

    Returns:
        True 表示结构形态符合幻觉段特征，可进入短语二次确认。
    """
    text = (seg.get("text") or "").strip()
    duration = float(seg.get("end", 0.0)) - float(seg.get("start", 0.0))
    if duration > _PHRASE_GATE_MAX_DUR_S or len(text) > _PHRASE_GATE_MAX_CHARS:
        return False
    for neighbor in (prev, nxt):
        if neighbor is None:
            continue
        gap = (
            float(seg.get("start", 0.0)) - float(neighbor.get("end", 0.0))
            if float(neighbor.get("start", 0.0)) <= float(seg.get("start", 0.0))
            else float(neighbor.get("start", 0.0)) - float(seg.get("end", 0.0))
        )
        if gap < _PHRASE_GATE_MIN_GAP_S:
            return False
    return True


def _filter_stock_phrase_segments(segments: list[dict]) -> tuple[list[dict], int]:
    """幻觉套话双门控过滤：结构形态命中后才查短语表，子串匹配丢弃。

    判据分两层，避免黑名单误伤正常内容：
      1. 结构门控（与内容无关）：时长 ≤4s 且文本 ≤30 字且与两侧相邻段间隔
         ≥2s（边界段视为邻接静音）——孤立超短段才是幻觉形态；
      2. 短语确认（内容相关）：文本（小写归一）包含短语表条目即丢弃。

    Args:
        segments: 已归一的 segment 字典列表（须按时间顺序）。

    Returns:
        (过滤后的 segments, 丢弃的段数)。
    """
    kept: list[dict] = []
    dropped = 0
    for i, seg in enumerate(segments):
        prev = kept[-1] if kept else None
        nxt = segments[i + 1] if i + 1 < len(segments) else None
        if _is_phrase_gate_structural_hit(seg, prev, nxt):
            normalized = (seg.get("text") or "").strip().lower()
            if any(phrase in normalized for phrase in _HALLUCINATION_PHRASES):
                dropped += 1
                logger.info(
                    "幻觉套话过滤: 丢弃孤立短语段, text=%r, [%.2f-%.2f]",
                    normalized[:30], seg.get("start", 0.0), seg.get("end", 0.0),
                )
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
        min_speech_dbfs = getattr(audio_config, "local_whisper_min_speech_dbfs", -40.0)

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
            """以当前引擎参数向子进程提交一次转写（首次与重试共用）。

            用 partial + 关键字传参：``_transcribe_in_subprocess`` 在
            ``cpu_threads`` 之后是 keyword-only 签名，位置实参传 dict 会
            TypeError（且 spawn 子进程经 pickle 引用 partial，仍需模块级函数）。
            """
            return loop.run_in_executor(
                _asr_executor,
                functools.partial(
                    _transcribe_in_subprocess,
                    tmp_path,
                    lang,
                    str(model_dir),
                    cpu_threads,
                    device=device,
                    compute_type=compute_type,
                    beam_size=beam_size,
                    vad_enabled=vad_enabled,
                    hotwords=hotwords_str,
                    min_speech_dbfs=min_speech_dbfs,
                ),
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

        # 5. 结果为空且语言自动检测置信度低时，按配置的重试语言重试一次。
        #    tiny/small 档容易把短中文音频误判为英语（probability < 0.5），
        #    导致转写为空；显式指定语言可大幅提升识别率。
        #    默认 None = 不重试（与上游 faster-whisper 行为一致）；配置
        #    local_whisper_empty_result_retry_language（如 zh）后启用。
        #    注意：仅在首次转写结果为空时重试，已有内容则不再浪费 ASR 子进程。
        retry_lang = getattr(
            audio_config, "local_whisper_empty_result_retry_language", None
        )
        if (
            not segments
            and language is None
            and retry_lang
            and result["language_probability"] < 0.5
        ):
            logger.warning(
                "本地 ASR 语言检测置信度低 (language=%s, probability=%.2f)，按 %s 重试",
                result["language"], result["language_probability"], retry_lang,
            )
            try:
                result = await _invoke_subprocess(retry_lang)
            except BrokenProcessPool:
                await _rebuild_asr_executor()
                raise
            logger.info(
                "本地 ASR %s 重试完成, language=%s, probability=%.2f, duration=%.1fs",
                retry_lang, result["language"], result["language_probability"],
                result["duration"],
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
    model: str = "",
    api_key: str | None = None,
    base_url: str = "",
    language: str | None = None,
) -> list[dict]:
    """
    使用 httpx 直调 OpenAI Whisper API 转写音频，返回带时间戳的段落

    不依赖 openai 包，纯 httpx multipart/form-data 请求。

    Args:
        file_content: 音频文件二进制内容
        file_type: 音频文件类型 (mp3/wav/flac/ogg/m4a)
        model: Whisper 模型名（必传，宿主从用户模型配置/YAML 解析）
        api_key: OpenAI API Key（必传，宿主透传）
        base_url: API Base URL（必传，宿主从 YAML asr.openai_base_url 解析）

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2}, ...]
    """
    import httpx

    # 发包纪律（批次：发包模式）：凭据/模型名/端点由调用方透传，引擎不回读
    # 全局配置（原 YAML asr 段兜底已上移宿主 _resolve_asr_route）
    if not model or not api_key or not base_url:
        raise RuntimeError(
            "云端 Whisper 转写需要调用方透传 model/api_key/base_url"
            "（部署级默认端点由宿主路由层从 YAML asr.openai_base_url 解析），当前缺失"
        )

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
    model: str = "",
    api_key: str | None = None,
    base_url: str | None = None,
    minio_bucket: str | None = None,
    language_hints: list[str] | None = None,
    diarization_enabled: bool | None = None,
    speaker_count: int | None = None,
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
        diarization_enabled: 说话人分离（批次④）；仅单声道音频支持，建议 ≤2h。
            None = 不传（服务端默认关闭）。开启后 segment 带 speaker_id。
        speaker_count: 说话人数量参考值（2~100），仅 diarization_enabled 时生效。
        minio_client: MinIO 客户端（关键字注入，批次 6a-5 切断对
            ``shared.clients.ClientFactory`` 的惰性 import；调用方负责经宿主装配获取）

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2, ("speaker_id": 0), ...}]
    """
    import uuid

    import dashscope
    from novamind.shared.ai_models.asr import (
        await_transcription_async,
        configure_dashscope,
        extract_segments,
        submit_transcription,
    )

    # 发包纪律：api_key 由调用方透传（原 YAML asr 段兜底已上移宿主路由层）
    if not model or not api_key:
        raise RuntimeError(
            "云端 DashScope 转写需要调用方透传 model 与 api_key"
            "（部署级兜底由宿主路由层从 YAML asr 段解析），当前缺失"
        )
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
            model=model, file_urls=[uploaded_url], language_hints=language_hints,
            diarization_enabled=diarization_enabled, speaker_count=speaker_count,
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


# ========== 转写产物质量元数据（批次②：置信度贯穿 chunk metadata） ==========


def sigmoid_confidence(avg_logprob: float | None) -> float | None:
    """把 ASR segment 的 avg_logprob（对数域，负值）映射为 0~1 置信度。

    语言无关的通用判据：log-probability 经 sigmoid 归一，-1.0（幻觉过滤阈值）
    映射到约 0.27，-0.3（高置信）映射到约 0.57——单调保持相对高低关系，
    绝对值只作排序/过滤参考，不作绝对准确率解读。

    Args:
        avg_logprob: segment 平均对数概率（None/缺失返回 None）。

    Returns:
        0~1 置信度（round 3 位）；入参无效返回 None。
    """
    if avg_logprob is None:
        return None
    import math

    try:
        return round(1.0 / (1.0 + math.exp(-float(avg_logprob))), 3)
    except (TypeError, ValueError, OverflowError):
        return None


def merge_segment_meta(
    segments: list[dict],
    seg_idx: int,
    meta: dict | None,
) -> dict:
    """把单个 segment 的质量元数据合并进 chunk 元数据聚合（就地更新）。

    当前聚合：confidence（sigmoid(avg_logprob) 均值）、speaker_id（去重排序的
    说话人标签列表，来自批次④ DashScope diarization）。

    Args:
        segments: ASR segment 列表（元素可含 avg_logprob/speaker_id）。
        seg_idx: 本 chunk 覆盖的 segment 在原列表中的序号。
        meta: chunk 级聚合元数据 dict（None 时新建）。
    """
    meta = meta if meta is not None else {}
    if seg_idx >= len(segments):
        return meta
    seg = segments[seg_idx]
    conf = sigmoid_confidence(seg.get("avg_logprob"))
    if conf is not None:
        running = meta.get("_confidence_sum")
        if running is None:
            meta["_confidence_sum"] = conf
            meta["_confidence_n"] = 1
        else:
            meta["_confidence_sum"] = running + conf
            meta["_confidence_n"] = int(meta.get("_confidence_n") or 0) + 1
    speaker = seg.get("speaker_id")
    if speaker is not None:
        speakers = list(meta.get("_speakers") or [])
        if speaker not in speakers:
            speakers.append(speaker)
            meta["_speakers"] = speakers
    return meta


def finalize_segment_meta(meta: dict | None) -> dict:
    """把聚合中间值收敛为最终 metadata 键（confidence/speaker_id），清理内部键。

    Args:
        meta: 经 merge_segment_meta 累积的 chunk 元数据（None 时返回空 dict）。

    Returns:
        仅含对外键的 dict：confidence（无置信度数据时无此键）、
        speaker_id（无说话人数据时无此键；多说话人用逗号串——ES keyword）。
    """
    out: dict = {}
    meta = meta or {}
    n = meta.get("_confidence_n") or 0
    if n:
        out["confidence"] = round(meta["_confidence_sum"] / n, 3)
    speakers = meta.get("_speakers") or []
    if speakers:
        out["speaker_id"] = ",".join(str(s) for s in sorted(speakers))
    return out


# ========== 音频专用切分（批次③：停顿边界 + 目标尺寸合并） ==========


def group_transcript_segments(
    segments: list[dict],
    *,
    target_chunk_size: int = 800,
    pause_gap_seconds: float = 0.8,
) -> list[list[int]]:
    """把 ASR segments 按停顿边界聚组（纯逻辑，批次③音频专用切分核心）。

    第一性判据：
      1. **停顿边界**：相邻 segment 间隙（next.start - prev.end）≥
         pause_gap_seconds → 强制切组。说话人换气/换话题的自然停顿是语义
         边界最可靠的物理信号，与语言/内容无关。
      2. **目标尺寸合并**：边界之间不足 target_chunk_size 字符的相邻组
         合并（避免碎片 chunk 进检索）；超过的单组不拆——segment 原子性
         优先（单 segment 超 target 也整段成组，由上层 line_aware 切分兜底
         防超长）。

    Args:
        segments: ASR segment 列表（元素含 text/start/end 秒）。
        target_chunk_size: 组目标字符数（对应知识库 splitting.chunk_size）。
        pause_gap_seconds: 停顿间隙阈值（秒）。

    Returns:
        segment 序号分组列表（每组为递增 idx 列表，覆盖 0..len(segments)-1
        中的全部非空段；空文本段跳过不占组）。
    """
    # 非空段的 (idx, len) 有序表
    usable = [
        (i, len(str(seg.get("text") or "")))
        for i, seg in enumerate(segments)
        if str(seg.get("text") or "").strip()
    ]
    if not usable:
        return []

    # 第一遍：按停顿边界切粗组（边界是硬墙，尺寸合并不跨边界）
    groups: list[list[int]] = []
    current: list[int] = [usable[0][0]]
    for pos in range(1, len(usable)):
        prev_i = current[-1]
        idx, chars = usable[pos]
        prev_seg = segments[prev_i]
        seg = segments[idx]
        gap_ok = (
            seg.get("start") is not None
            and prev_seg.get("end") is not None
            and (float(seg["start"]) - float(prev_seg["end"])) >= pause_gap_seconds
        )
        if gap_ok:
            groups.append(current)
            current = [idx]
        else:
            current.append(idx)
    groups.append(current)

    # 第二遍（边界内尺寸聚合）：每个停顿边界组内部按目标尺寸切分——
    # 累积到 target_chunk_size 就封组（防单话题组超长）；边界组本身过小
    # 不跨边界合并（停顿边界优先于尺寸——碎片略多优于话题错切）。
    final: list[list[int]] = []
    for group in groups:
        current: list[int] = []
        current_chars = 0
        for idx in group:
            chars = _group_chars(segments, [idx])
            if current and current_chars + chars > target_chunk_size:
                final.append(current)
                current = []
                current_chars = 0
            current.append(idx)
            current_chars += chars
        if current:
            final.append(current)
    return final


def _group_chars(segments: list[dict], idxs: list[int]) -> int:
    """组内 segment 文本总字符数。"""
    return sum(len(str(segments[i].get("text") or "")) for i in idxs)
