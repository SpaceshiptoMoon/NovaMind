"""
媒体处理工具：视频关键帧提取 + 音频转写

- 视频：imageio + imageio-ffmpeg 按间隔提取帧（纯 pip 依赖，无需系统 ffmpeg）
- 音频：httpx 直调 OpenAI Whisper API / DashScope SDK 调用 Paraformer / 本地 faster-whisper
"""

import asyncio
import os
import logging
import tempfile
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Set

logger = logging.getLogger(__name__)


# 音频格式 Magic Bytes 检测表
_AUDIO_MAGIC_BYTES: List[Tuple[bytes, str, str]] = [
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


def _detect_audio_format(file_content: bytes) -> Tuple[str, str]:
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

# faster-whisper 通过 PyAV (FFmpeg) 解码，支持的音频格式
# 参考: https://github.com/SYSTRAN/faster-whisper
_LOCAL_ASR_SUPPORTED_EXTENSIONS: Set[str] = {
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

_model_lock = asyncio.Lock()
_local_whisper_model = None


async def _get_local_whisper_model():
    """懒加载 faster-whisper 模型（单例，异步安全）"""
    global _local_whisper_model
    if _local_whisper_model is None:
        async with _model_lock:
            if _local_whisper_model is None:
                from faster_whisper import WhisperModel

                # 模型路径：项目根 backend/models/faster-whisper/tiny/
                model_dir = Path(__file__).resolve().parent.parent.parent.parent / "models" / "faster-whisper" / "tiny"
                if not model_dir.exists():
                    raise RuntimeError(
                        f"本地 ASR 模型未找到: {model_dir}，"
                        f"请确保 models/faster-whisper/tiny/ 目录存在且包含 model.bin"
                    )

                _local_whisper_model = WhisperModel(
                    str(model_dir),
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                )
                logger.info("本地 faster-whisper 模型已加载, path=%s", str(model_dir))
    return _local_whisper_model


def _validate_audio_for_local_asr(file_content: bytes) -> Tuple[str, str]:
    """
    在调用本地 ASR 前校验音频格式

    faster-whisper 通过 PyAV (FFmpeg) 解码音频，理论支持所有 FFmpeg 可解码的格式。
    但某些专有/损坏格式可能无法解码，这里做前端校验给出明确错误信息。

    Returns:
        (ext, mime_type) 如果格式可接受

    Raises:
        ValueError: 格式不支持或文件无效
    """
    if not file_content or len(file_content) < 12:
        raise ValueError("音频文件太小或为空，无法识别格式 (最小 12 bytes)")

    ext, mime = _detect_audio_format(file_content)

    # 检查是否在本地 ASR 支持列表中
    if ext not in _LOCAL_ASR_SUPPORTED_EXTENSIONS:
        # 尝试给出更详细的诊断
        detected_desc = _MAGIC_EXT_TO_FORMAT.get(ext, f"未知格式 (.{ext})")
        raise ValueError(
            f"本地 ASR 不支持此音频格式: {detected_desc}。"
            f"支持的格式: {', '.join(sorted(_LOCAL_ASR_SUPPORTED_EXTENSIONS))}"
        )

    return ext, mime


async def transcribe_audio_local(
    file_content: bytes,
    file_type: str = "mp3",
) -> List[Dict]:
    """
    使用本地 faster-whisper 模型转写音频，返回带时间戳的段落

    无需 API Key、无需网络，模型通过 PyAV (FFmpeg) 自动处理音频解码和重采样。

    Args:
        file_content: 音频文件二进制内容
        file_type: 提示用，实际格式通过 Magic Bytes 检测

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2}, ...]

    Raises:
        ValueError: 音频格式不支持或文件无效
        RuntimeError: 模型未找到或转写失败
    """
    # 1. 格式校验（在进入模型前拒绝不支持的文件）
    ext, _mime = _validate_audio_for_local_asr(file_content)
    logger.info(
        "本地 ASR: 格式校验通过 ext=%s, file_type_hint=%s, size=%d",
        ext, file_type, len(file_content),
    )

    # 2. 写入临时文件（faster-whisper 当前版本仅支持文件路径，不支持 BytesIO）
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        # 3. 加载模型 + 转写
        model = await _get_local_whisper_model()

        logger.info("本地 ASR 转写开始, file=%s, size=%d", tmp_path, len(file_content))
        segments_result, info = await asyncio.to_thread(
            model.transcribe,
            tmp_path,
            beam_size=5,
            word_timestamps=False,
        )

        # info 包含: language, language_probability, duration, etc.
        logger.info(
            "本地 ASR 转写完成, language=%s, probability=%.2f, duration=%.1fs",
            info.language, info.language_probability, info.duration,
        )

        # 4. 转换结果格式（与 OpenAI/DashScope 返回格式统一）
        segments = []
        for seg in segments_result:
            text = seg.text.strip() if seg.text else ""
            if text:
                segments.append({
                    "text": text,
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                })

        if not segments:
            logger.warning(
                "本地 ASR 转写结果为空, language=%s, duration=%.1fs",
                info.language, info.duration,
            )

        return segments

    except Exception as e:
        # 捕获 PyAV 解码错误等，转换为明确的错误信息
        error_msg = str(e)
        if "av." in type(e).__module__ or "PyAV" in type(e).__name__:
            raise ValueError(
                f"音频解码失败，文件可能已损坏或编码不兼容: {error_msg[:200]}"
            ) from e
        raise

    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def upload_parsed_text_to_minio(document, full_text: str, logger) -> str:
    """
    将解析/转写后的原始全文上传到 MinIO，并在 document.storage JSON 中记录路径

    存储路径: {原始文件路径}_parsed/full_text.md

    Args:
        document: Document ORM 对象（需有 .storage JSON 字段）
        full_text: 完整的解析/转写文本
        logger: 日志记录器

    Returns:
        MinIO object_name，如果上传失败或文本为空则返回空字符串
    """
    if not full_text or not full_text.strip():
        logger.warning("解析全文为空，跳过 MinIO 上传", document_id=document.id)
        return ""

    try:
        from src.shared.clients import ClientFactory

        storage = document.storage or {}
        base = storage.get("minio_object_name", "")
        if not base:
            logger.warning("文档无 minio_object_name，跳过解析全文上传", document_id=document.id)
            return ""

        object_name = f"{base}_parsed/full_text.md"
        data = full_text.encode("utf-8")

        minio_client = await ClientFactory.get_minio_client()
        await minio_client.upload_file(object_name, data, "text/markdown; charset=utf-8")

        storage["parsed_text_object"] = object_name
        document.storage = storage

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


async def extract_video_frames(
    file_content: bytes,
    interval: float = 5.0,
    max_frames: int = 60,
) -> List[Tuple[bytes, float, int]]:
    """
    从视频中按固定间隔提取帧

    使用 imageio + imageio-ffmpeg（自包含 ffmpeg 二进制，无需系统安装）。

    Args:
        file_content: 视频文件二进制内容
        interval: 提取间隔（秒），默认每5秒一帧
        max_frames: 最多提取帧数，默认60

    Returns:
        [(frame_bytes, timestamp_seconds, frame_index), ...] 按时间顺序排列
    """
    import asyncio
    import numpy as np
    from PIL import Image

    # 写入临时文件（imageio 需要文件路径）
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        # 用 imageio 读取视频元数据
        metadata = await asyncio.to_thread(_read_video_metadata, tmp_path)
        duration = metadata.get("duration", 0)
        fps = metadata.get("fps", 30)

        if duration <= 0:
            raise ValueError("无法读取视频时长，文件可能已损坏")

        # 计算提取时间点
        frame_count = min(int(duration / interval), max_frames)
        if frame_count == 0:
            frame_count = 1  # 极短视频至少取一帧

        timestamps = [i * interval for i in range(frame_count)]

        # 逐帧提取（imageio 按时间点读取）
        frames = []
        for frame_idx, ts in enumerate(timestamps):
            try:
                frame = await asyncio.to_thread(_read_frame_at, tmp_path, ts, fps)
                if frame is not None:
                    # PIL Image → JPEG bytes
                    buf = tempfile.BytesIO()
                    frame.save(buf, format="JPEG", quality=85)
                    frames.append((buf.getvalue(), ts, frame_idx))
            except Exception:
                # 单帧失败不阻塞整体
                continue

            if len(frames) >= max_frames:
                break

        return frames

    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _read_video_metadata(filepath: str) -> Dict:
    """读取视频时长和帧率（同步，在线程池执行）"""
    import imageio.v3 as iio

    props = iio.improps(filepath, plugin="pyav")
    duration = getattr(props, "duration", 0)
    fps = getattr(props, "fps", 30)

    if not duration and hasattr(props, "n_images"):
        # 部分格式 duration 不可靠，用帧数/fps 估算
        n_images = props.n_images
        if n_images and n_images > 0 and fps > 0:
            duration = n_images / fps

    return {"duration": duration, "fps": fps}


def _read_frame_at(filepath: str, timestamp: float, fps: float):
    """在指定时间点读取一帧，返回 PIL Image（同步，在线程池执行）"""
    import imageio.v3 as iio
    from PIL import Image
    import numpy as np

    # 计算目标帧索引
    frame_idx = int(timestamp * fps)

    try:
        # imageio 按索引读取帧
        frame = iio.imread(filepath, index=frame_idx, plugin="pyav")
        if isinstance(frame, np.ndarray):
            return Image.fromarray(frame)
        return None
    except (IndexError, OSError):
        # 索引越界或解码失败，尝试 read 最后一帧
        try:
            # 回退：读第一帧（至少有一帧）
            frame = iio.imread(filepath, index=0, plugin="pyav")
            if isinstance(frame, np.ndarray):
                return Image.fromarray(frame)
        except Exception:
            pass
        return None


async def transcribe_audio_with_timestamps(
    file_content: bytes,
    file_type: str = "mp3",
    model: str = "whisper-1",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> List[Dict]:
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

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法使用 Whisper API")

    if not base_url:
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # 通过 Magic Bytes 检测真实音频格式，不再依赖文件扩展名
    ext, mime_type = _detect_audio_format(file_content)

    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        url = f"{base_url.rstrip('/')}/audio/transcriptions"

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            with open(tmp_path, "rb") as f:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"model": model, "response_format": "verbose_json",
                          "timestamp_granularities[]": "segment"},
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
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    minio_bucket: Optional[str] = None,
    language_hints: Optional[List[str]] = None,
) -> List[Dict]:
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

    Returns:
        [{"text": "...", "start": 0.0, "end": 5.2}, ...]
    """
    from http import HTTPStatus
    import uuid
    import dashscope
    from dashscope.audio.asr import Transcription
    from src.shared.clients import ClientFactory

    if api_key:
        dashscope.api_key = api_key
    elif not os.environ.get("DASHSCOPE_API_KEY"):
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法使用 DashScope Paraformer API")

    # 百炼平台需要设置 workspace 级别的 base URL
    if base_url:
        url = base_url.rstrip("/")
        # 去掉用户误填的兼容模式路径（/compatible-mode/v1 → OpenAI 协议用的）
        if url.endswith("/compatible-mode/v1"):
            url = url[:-len("/compatible-mode/v1")]
        if not url.endswith("/api/v1"):
            url += "/api/v1"
        dashscope.base_http_api_url = url

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
        minio_client = await ClientFactory.get_minio_client()
        bucket = minio_bucket or "novamind"
        temp_object_name = f"_asr_temp/{uuid.uuid4().hex}.{ext}"
        await minio_client.upload_file(temp_object_name, file_content, f"audio/{ext}")
        uploaded_url = await minio_client.get_public_file_url(bucket, temp_object_name, expires=3600)
        logger.info("音频已上传 MinIO 临时位置: %s, url=%s...", temp_object_name, uploaded_url[:80])

        # 3. 提交转写任务（使用 HTTP URL，不是 fileid://）
        call_kwargs: Dict = {
            "model": model,
            "file_urls": [uploaded_url],
        }
        if language_hints:
            call_kwargs["language_hints"] = language_hints

        task_response = Transcription.async_call(**call_kwargs)

        if task_response.output is None:
            raise RuntimeError(
                f"DashScope 转写任务提交失败: status={task_response.status_code}, "
                f"message={getattr(task_response, 'message', 'unknown')}"
            )

        if task_response.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"DashScope 转写任务提交失败: status={task_response.status_code}, "
                f"message={getattr(task_response, 'message', 'unknown')}"
            )

        # 4. 等待完成
        transcribe_response = Transcription.wait(task=task_response.output.task_id)

        if transcribe_response.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"DashScope 转写失败: status={transcribe_response.status_code}, "
                f"message={getattr(transcribe_response, 'message', 'unknown')}"
            )

        # 5. 解析结果：句子级时间戳
        output = transcribe_response.output
        # 兼容 output 为 dict 或对象两种形式
        if isinstance(output, dict):
            output_dict = output
        else:
            output_dict = {k: v for k, v in output.__dict__.items() if not k.startswith("_")}
        logger.info("DashScope 转写原始结果: %s", str(output_dict)[:2000])

        # 从 output 中提取 results（必须在 FAILED 检查之前）
        results = output_dict.get("results", [])

        # 检查任务状态
        task_status = output_dict.get("task_status", "")
        if task_status == "FAILED":
            error_code = output_dict.get("code", "UNKNOWN")

            # 从嵌套 results 中提取更详细的错误信息
            detail_parts: list[str] = []
            for item in results:
                item_dict = item if isinstance(item, dict) else {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
                item_code = item_dict.get("code", "")
                item_status = item_dict.get("subtask_status", "")
                if item_code or item_status:
                    detail_parts.append(f"subtask[{item_code or item_status}]")
                # 再深入一层 output.results
                output_data = item_dict.get("output", {})
                if isinstance(output_data, dict):
                    inner_results = output_data.get("results", [])
                elif hasattr(output_data, "results"):
                    inner_results = getattr(output_data, "results", [])
                else:
                    inner_results = []
                for ir in inner_results:
                    ir_dict = ir if isinstance(ir, dict) else {k: v for k, v in ir.__dict__.items() if not k.startswith("_")}
                    ir_code = ir_dict.get("code", "")
                    ir_status = ir_dict.get("subtask_status", "")
                    if ir_code or ir_status:
                        detail_parts.append(f"inner[{ir_code or ir_status}]")

            detail = ", ".join(detail_parts) if detail_parts else "no details"
            raise RuntimeError(
                f"DashScope 转写任务失败: code={error_code}, "
                f"task_id={output_dict.get('task_id', 'unknown')}, "
                f"details={detail}"
            )

        segments = []
        for item in results:
            # 兼容 dict 和对象
            item_dict = item if isinstance(item, dict) else {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
            sentences = item_dict.get("sentences", [])
            if sentences:
                for sent in sentences:
                    sent_dict = sent if isinstance(sent, dict) else {k: v for k, v in sent.__dict__.items() if not k.startswith("_")}
                    text = sent_dict.get("text", "").strip()
                    if text:
                        segments.append({
                            "text": text,
                            "start": sent_dict.get("begin_time", 0) / 1000.0,
                            "end": sent_dict.get("end_time", 0) / 1000.0,
                        })
            else:
                text = item_dict.get("transcription", "").strip()
                if text:
                    segments.append({
                        "text": text,
                        "start": 0.0,
                        "end": 0.0,
                    })

        return segments

    finally:
        Path(tmp_path).unlink(missing_ok=True)
        # 清理 MinIO 临时文件
        if temp_object_name:
            try:
                from src.shared.clients import ClientFactory as _CF
                _minio = await _CF.get_minio_client()
                _bucket = minio_bucket or "novamind"
                await asyncio.to_thread(_minio.client.remove_object, _bucket, temp_object_name)
                logger.debug("已清理 MinIO 临时文件: %s", temp_object_name)
            except Exception as e:
                logger.warning("清理 MinIO 临时文件失败: %s, error=%s", temp_object_name, str(e))
