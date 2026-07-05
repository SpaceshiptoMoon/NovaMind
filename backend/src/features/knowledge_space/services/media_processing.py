"""
音视频文档处理管道

处理流程：
- 视频: 提取关键帧 → VLM逐帧描述 → 聚合文本 → Embedding → ES
- 音频: ASR转写 → 分句切片 → Embedding → ES
"""

import base64
from typing import List, Tuple, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.features.knowledge_space.models.document import Document
from src.features.knowledge_space.services.document_service import _check_document_cancelled
from src.shared.utils.media_utils import extract_video_frames, transcribe_audio_with_timestamps
from src.shared.utils.time_utils import now_china


async def process_video_document(
    document: Document,
    file_content: bytes,
    session: AsyncSession,
    logger,
) -> None:
    """
    视频文档处理管道

    1. 提取关键帧（按 KB parsing 配置的间隔和最大帧数）
    2. 逐帧调 VLM 生成描述
    3. 聚合所有帧描述 → 构建 text chunks
    4. 走文本管道（Embedding → ES）
    """
    from src.features.user.services.model_config_service import ModelConfigService
    from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
    from src.features.knowledge_space.models.knowledge_space import KnowledgeSpace

    space = await session.get(KnowledgeSpace, document.space_id)
    kb_repo = KnowledgeBaseRepository(session)
    kb = await kb_repo.get_by_id(document.kb_id)

    # 读取视频处理配置
    parsing_config = kb.get_parsing_config() if kb else {}
    video_config = parsing_config.get("video", {})
    frame_interval = video_config.get("frame_interval", 5)
    max_frames = video_config.get("max_frames", 60)

    mcs = ModelConfigService(session)

    # 1. 提取帧
    logger.info(
        "视频帧提取开始", document_id=document.id,
        interval=frame_interval, max_frames=max_frames,
    )
    frames = await extract_video_frames(file_content, frame_interval, max_frames)
    logger.info(
        "视频帧提取完成", document_id=document.id, frame_count=len(frames),
    )

    # 检查点1：帧提取完成
    await _check_document_cancelled(document.id)

    if not frames:
        raise ValueError(f"视频 {document.filename} 未能提取到任何帧")

    # 1.5. 帧持久化到 MinIO（在 VLM 调用前上传，避免 VLM 失败后帧丢失）
    from src.shared.clients import ClientFactory
    minio_client = await ClientFactory.get_minio_client()
    storage_info = document.storage or {}
    base_object = storage_info.get("minio_object_name", "")

    frame_paths = []
    for frame_bytes, ts, frame_idx in frames:
        try:
            object_name = f"{base_object}_frames/frame_{frame_idx:04d}.jpg"
            await minio_client.upload_file(object_name, frame_bytes, "image/jpeg")
            frame_paths.append(object_name)
            logger.debug("帧已上传 MinIO", object_name=object_name, timestamp=ts)
        except Exception as e:
            logger.error("帧上传 MinIO 失败", document_id=document.id,
                         frame_idx=frame_idx, timestamp=ts, error=str(e))
            # 上传失败不阻塞整体（极少数帧丢失不影响搜索）
            frame_paths.append("")

    # 2. 逐帧 VLM 描述（每5帧检查一次取消信号）
    descriptions = []
    for i, (frame_bytes, ts, frame_idx) in enumerate(frames):
        if i > 0 and i % 5 == 0:
            await _check_document_cancelled(document.id)
        try:
            desc = await _describe_single_frame(
                frame_bytes=frame_bytes,
                frame_index=frame_idx,
                timestamp=ts,
                document=document,
                mcs=mcs,
                logger=logger,
            )
            if desc:
                descriptions.append((desc, ts, frame_idx))
        except Exception as e:
            logger.warning(
                "视频帧VLM描述失败, 跳过", document_id=document.id,
                frame_index=frame_idx, timestamp=ts, error=str(e),
            )

    if not descriptions:
        raise ValueError(f"视频 {document.filename} 所有帧的VLM描述均失败")

    # 3. 聚合为 text chunks（按总长度切分）
    chunks = _aggregate_descriptions(descriptions, max_chunk_size=1500)

    # 4. Embedding + ES（复用文本管道）
    embedding_config = space.embedding_config if space else {}
    await _index_text_chunks(
        document=document,
        chunks=chunks,
        chunk_type="video",
        embedding_config=embedding_config,
        session=session,
        logger=logger,
        frame_paths=frame_paths,
    )

    # 5. 标记完成
    document.mark_completed()
    document.storage = {
        **(document.storage or {}),
        "frames": [p for p in frame_paths if p],  # 过滤上传失败的空字符串
    }
    document.doc_metadata = {
        **(document.doc_metadata or {}),
        "chunk_count": len(chunks),
        "chunk_type": "video",
        "frame_count": len(frames),
        "indexed_at": now_china().isoformat(),
    }
    await session.commit()

    logger.info(
        "视频文档处理完成", document_id=document.id,
        chunks=len(chunks), frames=len(frames), frame_paths=len(frame_paths),
    )


async def process_audio_document(
    document: Document,
    file_content: bytes,
    session: AsyncSession,
    logger,
) -> None:
    """
    音频文档处理管道

    1. ASR 转写（OpenAI Whisper API，带时间戳）
    2. 按句子/段落构建 chunks
    3. 走文本管道（Embedding → ES）
    """
    from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
    from src.features.knowledge_space.models.knowledge_space import KnowledgeSpace

    space = await session.get(KnowledgeSpace, document.space_id)
    kb_repo = KnowledgeBaseRepository(session)
    kb = await kb_repo.get_by_id(document.kb_id)

    # 读取音频处理配置
    parsing_config = kb.get_parsing_config() if kb else {}
    audio_config = parsing_config.get("audio", {})
    asr_model = audio_config.get("asr_model", "whisper-1")
    chunk_strategy = audio_config.get("chunk_split_strategy", "sentence")
    chunk_size = audio_config.get("chunk_size", 1000)

    # 1. ASR 转写
    logger.info(
        "音频转写开始", document_id=document.id,
        file_type=document.file_type, model=asr_model,
    )
    segments = await transcribe_audio_with_timestamps(
        file_content=file_content,
        file_type=document.file_type,
        model=asr_model,
    )
    logger.info(
        "音频转写完成", document_id=document.id, segment_count=len(segments),
    )

    # 检查点1：ASR 转写完成
    await _check_document_cancelled(document.id)

    if not segments:
        raise ValueError(f"音频 {document.filename} 转写结果为空")

    # 2. 按策略切片
    if chunk_strategy == "fixed":
        chunks = _merge_segments_by_size(segments, chunk_size)
    else:
        # sentence: 每个 segment 作为一个 chunk
        chunks = [
            (seg["text"], {"start_time": seg.get("start"), "end_time": seg.get("end")})
            for seg in segments if seg["text"].strip()
        ]

    # 3. Embedding + ES
    embedding_config = space.embedding_config if space else {}
    await _index_text_chunks(
        document=document,
        chunks=chunks,
        chunk_type="audio",
        embedding_config=embedding_config,
        session=session,
        logger=logger,
    )

    # 4. 标记完成
    document.mark_completed()
    document.doc_metadata = {
        **(document.doc_metadata or {}),
        "chunk_count": len(chunks),
        "chunk_type": "audio",
        "segment_count": len(segments),
        "indexed_at": now_china().isoformat(),
    }
    await session.commit()

    logger.info(
        "音频文档处理完成", document_id=document.id,
        chunks=len(chunks), segments=len(segments),
    )


# ========== 内部辅助函数 ==========


async def _describe_single_frame(
    frame_bytes: bytes,
    frame_index: int,
    timestamp: float,
    document: Document,
    mcs,
    logger,
) -> str:
    """对单帧调用 VLM 生成描述（复用图片描述逻辑）"""
    from src.shared.prompts.templates import PromptManager, PromptTemplate

    # 获取 VLM 客户端
    vlm_model = await mcs.get_user_default_model_name(document.uploader_id, "vlm")
    if not vlm_model:
        raise ValueError("未配置 VLM 模型")

    vlm_client = await mcs.get_vlm_client_by_model(document.uploader_id, vlm_model)

    # 构建 base64 图片
    base64_data = base64.b64encode(frame_bytes).decode("utf-8")
    mime_type = "image/jpeg"

    # 获取视频帧描述 Prompt
    description_prompt = PromptManager.get_template(
        PromptTemplate.VIDEO_FRAME_DESCRIPTION.value
    )

    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}},
            {"type": "text", "text": description_prompt},
        ],
    }]

    description = await vlm_client.generate_text(
        prompt=messages, max_tokens=1024, temperature=0.3,
    )

    if not description or not description.strip():
        return ""

    return description.strip()[:500]


def _format_time(seconds: float) -> str:
    """格式化秒数为 HH:MM:SS"""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _aggregate_descriptions(
    descriptions: List[Tuple[str, float, int]],
    max_chunk_size: int = 1500,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    将帧描述聚合为 chunks，每个 chunk 不超过 max_chunk_size 字符

    Returns:
        [(text, metadata), ...]
        metadata: {"start_time", "end_time", "frame_indices"}
    """
    chunks = []
    current_lines = []
    current_length = 0
    current_start_time = None
    current_end_time = None
    current_frame_indices = []

    for desc, timestamp, frame_idx in descriptions:
        line = f"[{_format_time(timestamp)}] {desc}"
        line_len = len(line)

        # 判断是否需要开始新 chunk
        if current_lines and current_length + line_len > max_chunk_size:
            chunks.append((
                "\n\n".join(current_lines),
                {
                    "start_time": current_start_time,
                    "end_time": current_end_time,
                    "frame_indices": current_frame_indices,
                },
            ))
            current_lines = []
            current_length = 0
            current_start_time = None
            current_frame_indices = []

        if current_start_time is None:
            current_start_time = timestamp
        current_end_time = timestamp + 5  # 默认帧间隔5秒
        current_lines.append(line)
        current_length += line_len
        current_frame_indices.append(frame_idx)

    # 最后一个 chunk
    if current_lines:
        chunks.append((
            "\n\n".join(current_lines),
            {
                "start_time": current_start_time,
                "end_time": current_end_time,
                "frame_indices": current_frame_indices,
            },
        ))

    return chunks


def _merge_segments_by_size(
    segments: List[Dict],
    chunk_size: int = 1000,
) -> List[Tuple[str, Dict[str, Any]]]:
    """按固定字符数合并 ASR segments"""
    chunks = []
    buffer_texts = []
    start_time = None
    end_time = None
    current_len = 0

    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        if not buffer_texts:
            start_time = seg.get("start", 0.0)
        buffer_texts.append(text)
        end_time = seg.get("end", 0.0)
        current_len += len(text)

        if current_len >= chunk_size:
            chunks.append((
                " ".join(buffer_texts),
                {"start_time": start_time, "end_time": end_time},
            ))
            buffer_texts = []
            current_len = 0
            start_time = None

    # 剩余部分
    if buffer_texts:
        chunks.append((
            " ".join(buffer_texts),
            {"start_time": start_time, "end_time": end_time},
        ))

    return chunks


async def _index_text_chunks(
    document: Document,
    chunks: List[Tuple[str, Dict[str, Any]]],
    chunk_type: str,
    embedding_config: Dict[str, Any],
    session: AsyncSession,
    logger,
    frame_paths: Optional[List[str]] = None,
):
    """将文本 chunks 写入 ES（复用文本管道逻辑）"""
    from src.features.knowledge_space.services.document_service import (
        _generate_embeddings_static,
        _get_es_client_static,
    )

    # 构建 ES chunks
    es_chunks = []
    for i, (text, meta) in enumerate(chunks):
        chunk_meta = {
            "content_hash": document.file_hash,
            "start_time": meta.get("start_time"),
            "end_time": meta.get("end_time"),
        }

        # 视频：将 frame_indices 映射为 MinIO 路径
        if frame_paths and "frame_indices" in meta:
            chunk_meta["frame_paths"] = [
                frame_paths[idx]
                for idx in meta["frame_indices"]
                if idx < len(frame_paths) and frame_paths[idx]
            ]

        chunk_data = {
            "space_id": document.space_id,
            "kb_id": document.kb_id,
            "document_id": document.id,
            "chunk_id": f"{document.id}_{i}",
            "chunk_index": i,
            "content": text,
            "chunk_type": chunk_type,
            "media_url": (document.storage or {}).get("minio_object_name", ""),
            "image_url": (document.storage or {}).get("minio_object_name", ""),
            "file_info": {
                "filename": document.filename,
                "file_type": document.file_type,
            },
            "metadata": chunk_meta,
            "questions": [],
            "question_embeddings": [],
            "created_at": now_china().isoformat(),
        }
        es_chunks.append(chunk_data)

    # 向量化
    texts = [c["content"] for c in es_chunks]
    embeddings = await _generate_embeddings_static(
        texts, embedding_config, session=session, user_id=document.uploader_id,
    )

    for i, emb in enumerate(embeddings):
        if emb:
            es_chunks[i]["embedding"] = emb

    # 写入 ES
    es_client = await _get_es_client_static()
    indexed = await es_client.bulk_index_chunks(
        space_id=document.space_id,
        chunks=es_chunks,
        embedding_dim=embedding_config.get("dimension"),
    )

    if indexed == 0 and es_chunks:
        raise RuntimeError(f"ES 索引写入失败: {len(es_chunks)} 个分块均未成功写入")

    logger.info(
        "text chunks索引完成", document_id=document.id,
        chunk_type=chunk_type, indexed_count=indexed,
    )
