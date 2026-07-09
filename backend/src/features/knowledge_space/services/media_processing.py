"""
音视频文档处理管道

处理流程：
- 视频: 提取关键帧 → VLM逐帧描述 → MD文本 → 统一文本切分 → Embedding → ES
- 音频: ASR转写 → MD文本 → 统一文本切分 → Embedding → ES
"""

import base64
from typing import List, Tuple, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.features.knowledge_space.models.document import Document
from src.features.knowledge_space.models.document_task import DocumentTask, TaskStatus
from src.features.knowledge_space.services.document_service import _check_document_cancelled
from src.shared.utils.media_utils import (
    extract_video_frames,
    transcribe_audio_with_timestamps,
    upload_parsed_text_to_minio,
    transcribe_audio_local,
)
from src.shared.utils.time_utils import now_china


async def process_video_document(
    document: Document,
    file_content: bytes,
    session: AsyncSession,
    logger,
    task: Optional[DocumentTask] = None,
) -> None:
    """
    视频文档处理管道

    1. 提取关键帧（按 pipeline 配置的间隔和最大帧数）
    2. 逐帧调 VLM 生成描述
    3. MD 拼接全文 → 上传 MinIO
    4. 统一文本切分
    5. Embedding → ES 索引
    """
    from src.features.user.services.model_config_service import ModelConfigService
    from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
    from src.features.knowledge_space.models.knowledge_space import KnowledgeSpace

    space = await session.get(KnowledgeSpace, document.space_id)
    kb_repo = KnowledgeBaseRepository(session)
    kb = await kb_repo.get_by_id(document.kb_id)

    # 读取 pipeline 配置（优先 Task 快照，回退到 KB 实时配置）
    # 注：迁移完成后 pipeline_config 应仅从 Task 快照读取
    pipeline_config = (
        task.pipeline_config
        if (task and task.pipeline_config)
        else (kb.get_config() if kb else {})
    )
    parsing_config = pipeline_config.get("parsing", {})
    splitting_config = dict(pipeline_config.get("splitting", {}))
    video_config = pipeline_config.get("parsing", {}).get("video", {})
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

    if task:
        task.set_step("frames_extracted")

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
                vlm_model_name=parsing_config.get("vlm_model"),
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

    # 帧描述全文 MD 拼接并持久化到 MinIO（立刻 commit 落库）
    full_text_lines = []
    for desc, ts, frame_idx in descriptions:
        full_text_lines.append(f"[{_format_time(ts)}] {desc}")
    full_text = "\n\n".join(full_text_lines)
    await upload_parsed_text_to_minio(document, full_text, logger)
    await session.commit()

    if task:
        task.set_step("descriptions_generated")

    # 3. 统一文本切分（替代旧 _aggregate_descriptions）
    # 切分配置从 pipeline_config 读取（优先 Task 快照）
    splitting_config.update(splitting_config.pop("video", {}))
    strategy = splitting_config.pop("strategy", "recursive")
    splitting_kwargs = splitting_config
    chunks = await _split_md_text(full_text, strategy=strategy, **splitting_kwargs)

    if task:
        task.set_step("text_split")

    # 4. Embedding + ES（embedding_config 从空间级别读取）
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

    if task:
        task.set_step("indexed")

    # 5. 写入处理结果到 Task
    document.storage = {
        **(document.storage or {}),
        "frames": [p for p in frame_paths if p],  # 过滤上传失败的空字符串
    }
    if task:
        task.mark_completed(result={
            "chunk_count": len(chunks),
            "chunk_type": "video",
            "frame_count": len(frames),
            "indexed_at": now_china().isoformat(),
        })
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
    task: Optional[DocumentTask] = None,
) -> None:
    """
    音频文档处理管道

    1. ASR 转写（OpenAI Whisper API，带时间戳）
    2. MD 文本拼接 → 上传 MinIO
    3. 统一文本切分
    4. Embedding → ES 索引
    """
    from src.features.knowledge_space.repository.knowledge_base_repository import KnowledgeBaseRepository
    from src.features.knowledge_space.models.knowledge_space import KnowledgeSpace

    space = await session.get(KnowledgeSpace, document.space_id)
    kb_repo = KnowledgeBaseRepository(session)
    kb = await kb_repo.get_by_id(document.kb_id)

    # 读取 pipeline 配置（优先 Task 快照，回退到 KB 实时配置）
    # 注：迁移完成后 pipeline_config 应仅从 Task 快照读取
    pipeline_config = (
        task.pipeline_config
        if (task and task.pipeline_config)
        else (kb.get_config() if kb else {})
    )
    audio_config = pipeline_config.get("parsing", {}).get("audio", {})
    space_asr_cfg = (space.config or {}).get("asr", {}) if space else {}
    asr_model = audio_config.get("asr_model") or space_asr_cfg.get("model") or "whisper-1"
    language = audio_config.get("language")

    # 1. ASR 转写（根据协议路由：openai → Whisper / dashscope → Paraformer / local → faster-whisper）
    from src.features.user.services.model_config_service import ModelConfigService
    from src.shared.utils.media_utils import transcribe_audio_with_dashscope

    # 检查点：ASR 调用前（转写可能耗时较长，允许用户在此处取消）
    await _check_document_cancelled(document.id)

    mcs = ModelConfigService(session)

    # 从模型配置系统查找 ASR 凭证（优先精确匹配，找不到用该用户任意 ASR 配置兜底）
    asr_api_key: Optional[str] = None
    asr_base_url: Optional[str] = None
    asr_protocol = "openai"  # 默认

    asr_creds = await mcs.get_credentials_by_model(document.uploader_id, "asr", asr_model)
    if not asr_creds:
        # 兜底：用户配的 ASR 模型名与 KB 默认名不一致，取该用户第一个 ASR 配置
        asr_configs = await mcs.repo.list_by_user(document.uploader_id, "asr")
        if asr_configs:
            asr_creds = await mcs.get_credentials_by_model(document.uploader_id, "asr", asr_configs[0].model)
    if asr_creds:
        asr_api_key = asr_creds.api_key
        asr_base_url = asr_creds.base_url
        asr_protocol = asr_creds.protocol or "openai"
        asr_model = asr_creds.model or asr_model  # 以实际凭证的模型名为准

    logger.info(
        "音频转写开始", document_id=document.id,
        file_type=document.file_type, model=asr_model, protocol=asr_protocol,
    )

    if asr_protocol == "local":
        # 本地 faster-whisper 模型 — 无需 API Key，无需网络
        segments = await transcribe_audio_local(
            file_content=file_content,
            file_type=document.file_type,
            language=language,
        )
    elif asr_protocol == "dashscope":
        storage_info = document.get_storage_info()
        language_hints = [language] if language else None
        segments = await transcribe_audio_with_dashscope(
            file_content=file_content,
            file_type=document.file_type,
            model=asr_model,
            api_key=asr_api_key,
            base_url=asr_base_url,
            minio_bucket=storage_info.get("minio_bucket"),
            language_hints=language_hints,
        )
    else:
        segments = await transcribe_audio_with_timestamps(
            file_content=file_content,
            file_type=document.file_type,
            model=asr_model,
            api_key=asr_api_key,
            base_url=asr_base_url,
            language=language,
        )
    logger.info(
        "音频转写完成", document_id=document.id, segment_count=len(segments),
    )

    # 检查点1：ASR 转写完成
    await _check_document_cancelled(document.id)

    if not segments:
        raise ValueError(f"音频 {document.filename} 转写结果为空")

    # 转写全文 MD 拼接并持久化到 MinIO（立刻 commit 落库）
    transcript_lines = [
        f"[{_format_time(seg.get('start', 0))}] {seg['text']}"
        for seg in segments if seg.get("text", "").strip()
    ]
    if not transcript_lines:
        raise ValueError(f"音频 {document.filename} 转写结果均为空文本")

    full_text = "\n".join(transcript_lines)
    await upload_parsed_text_to_minio(document, full_text, logger)
    await session.commit()

    if task:
        task.set_step("transcription_done")

    # 2. 统一文本切分，splitting.audio 覆盖通用切分参数
    splitting_config = dict(pipeline_config.get("splitting", {}))
    # 应用音频专属切分覆盖（chunk_size, strategy 等）
    splitting_config.update(splitting_config.pop("audio", {}))
    strategy = splitting_config.pop("strategy", "recursive")
    chunks = await _split_md_text(full_text, strategy=strategy, **splitting_config)

    if task:
        task.set_step("text_split")

    # 检查点2：文本切分完成，Embedding + ES 索引前
    await _check_document_cancelled(document.id)

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

    if task:
        task.set_step("indexed")

    # 4. 写入处理结果到 Task
    if task:
        task.mark_completed(result={
            "chunk_count": len(chunks),
            "chunk_type": "audio",
            "segment_count": len(segments),
            "indexed_at": now_china().isoformat(),
        })
    await session.commit()

    logger.info(
        "音频文档处理完成", document_id=document.id,
        chunks=len(chunks), segments=len(segments),
    )


# ========== 统一文本切分 ==========


async def _split_md_text(
    md_text: str,
    strategy: str = "recursive",
    **kwargs,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    将 MD/纯文本按指定策略切分为 chunks

    Args:
        md_text: 待切分的文本内容
        strategy: 切分策略 (recursive / markdown / fixed_size)
        **kwargs: 策略相关参数 (chunk_size, chunk_overlap, min_chunk_size, max_chunk_size 等)

    Returns:
        [(text, metadata_dict), ...] — metadata 目前为空 dict，后续可扩展携带标题/层级
    """
    from src.shared.utils.document_readers.document_loader import DocumentRegistry

    splitter_class = DocumentRegistry.get_splitter_class(strategy)
    if splitter_class is None:
        raise ValueError(
            f"不支持的切分策略: {strategy}，可用策略: {DocumentRegistry.get_available_strategies()}"
        )

    if strategy == "recursive":
        chunk_size = kwargs.get("chunk_size", 2000)
        chunk_overlap = kwargs.get("chunk_overlap", 50)
        min_chunk_size = kwargs.get("min_chunk_size", 500)
        splitter = splitter_class(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=min_chunk_size,
        )
        chunk_texts = await splitter._split_text(md_text)
        return [(text, {}) for text in chunk_texts if text.strip()]

    elif strategy == "markdown":
        from src.shared.utils.document_readers.splitters.markdown_splitter import MarkdownSplitter
        max_chunk_size = kwargs.get("max_chunk_size", 1000)
        min_chunk_size = kwargs.get("min_chunk_size", 50)
        splitter = MarkdownSplitter(
            max_chunk_size=max_chunk_size,
            min_chunk_size=min_chunk_size,
        )
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "markdown",
            "title": "",
        }]
        results = await splitter.split(doc_wrapper)
        return [(r["text"], {}) for r in results if r.get("text", "").strip()]

    elif strategy == "fixed_size":
        chunk_size = kwargs.get("chunk_size", 500)
        chunk_overlap = kwargs.get("chunk_overlap", 0)
        splitter = splitter_class(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "text",
        }]
        results = await splitter.split(doc_wrapper)
        return [(r["text"], {}) for r in results if r.get("text", "").strip()]

    else:
        # 其他策略兜底：尝试作为文档切分器处理
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "text",
        }]
        splitter = splitter_class(**kwargs)
        results = await splitter.split(doc_wrapper)
        return [(r["text"], {}) for r in results if r.get("text", "").strip()]


# ========== 内部辅助函数 ==========


async def _describe_single_frame(
    frame_bytes: bytes,
    frame_index: int,
    timestamp: float,
    document: Document,
    mcs,
    logger,
    vlm_model_name: Optional[str] = None,
) -> str:
    """对单帧调用 VLM 生成描述（复用图片描述逻辑）"""
    from src.shared.prompts.templates import PromptManager, PromptTemplate

    # 获取 VLM 客户端
    vlm_model = vlm_model_name or await mcs.get_user_default_model_name(document.uploader_id, "vlm")
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


async def _index_text_chunks(
    document: Document,
    chunks: List[Tuple[str, Dict[str, Any]]],
    chunk_type: str,
    embedding_config: Dict[str, Any],
    session: AsyncSession,
    logger,
    frame_paths: Optional[List[str]] = None,
    task: Optional[DocumentTask] = None,
):
    """
    将文本 chunks 写入 ES（复用文本管道逻辑）

    注：pipeline_config（切分策略等）可从 task.pipeline_config 快照获取，
    embedding_config 从空间配置读取，二者来源不同。
    """
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
