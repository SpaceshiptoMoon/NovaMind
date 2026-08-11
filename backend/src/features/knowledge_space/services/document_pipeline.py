"""文档处理管道执行模块（从 document_service.py 巨石抽出的管道职责）。

集中承载文档处理 pipeline 的执行入口与模块级静态助手群：
- ``execute_document_pipeline``：四模态分流入口（文本/图片/视频/音频），由 arq worker
  或上层直接以模块级函数调用；按文件类型路由到文本管道 / 图片 VLM+OCR / 视频 / 音频分支。
- 模块级静态助手：``_process_image_document_static`` / ``_process_image_ocr_static`` /
  ``_build_es_chunks`` / ``_prepare_es_chunks_static`` / ``_run_post_parse_tail`` /
  ``_extract_parse_metadata_summary`` / ``_get_es_client_static`` /
  ``_get_document_processor_static`` / ``_generate_embeddings_static`` /
  ``_get_embedding_client_static`` / ``_generate_single_embedding_static`` /
  ``_generate_image_description`` / ``_generate_questions_for_chunks_static``。
- 取消语义：``DocumentCancelledError`` + ``_check_document_cancelled``（pipeline 关键节点提前终止）。
- 配置上下文：``PipelineContext`` + ``load_pipeline_context``（统一 space/kb/pipeline_config/embedding_config）。
- 解析全文持久化：``persist_parsed_text``（所有模态解析全文入 MinIO + 立即 commit 落库）。

文件类型常量收敛到 ``document_file_types``（中立模块），本模块按模态分流时引用。
对 ``media_processing`` 的调用（视频/音频/语义切分）保持延迟导入，避免顶层循环 import。
"""

from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING
from dataclasses import dataclass
import traceback
import tempfile
from novamind.shared.utils.time_utils import now_china
from pathlib import Path

if TYPE_CHECKING:
    # 仅用于类型注解（``Optional["DocumentTask"]`` 前向引用），避免运行期循环 import。
    from novamind.features.knowledge_space.models.document_task import DocumentTask

from sqlalchemy.ext.asyncio import AsyncSession

from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.exceptions import (
    DocumentProcessingError,
    EmbeddingError,
)
from novamind.shared.model_config_ports import ModelConfigPort
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.engines.document.pipeline import DocumentProcessor
from novamind.engines.document.media.audio import upload_parsed_text_to_minio
from novamind.engines.document.media.vlm import (
    build_vlm_image_messages,
    generate_vlm_text_with_fallback,
)
from novamind.shared.ai_models.embedding import OpenAICompatibleEmbedding as EmbeddingClient
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    build_runtime_parsing_config,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_EMBEDDING_BATCH_SIZE,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.core.middleware.structured_logging import get_logger

from novamind.features.knowledge_space.services.document_file_types import (
    IMAGE_FILE_TYPES,
    VIDEO_FILE_TYPES,
    AUDIO_FILE_TYPES,
)


class DocumentCancelledError(Exception):
    """文档处理被用户取消"""


async def _check_document_cancelled(document_id: int) -> None:
    """
    检查文档是否被取消，是则抛出 DocumentCancelledError

    在 pipeline 关键节点调用，实现提前终止。
    """
    from novamind.shared.mq.task_tracker import is_document_cancelled

    if await is_document_cancelled(document_id):
        raise DocumentCancelledError(f"文档 {document_id} 处理已被用户取消")


async def execute_document_pipeline(
    session: AsyncSession,
    document_id: int,
    kb_id: int,
    space_id: int,
    file_content: bytes,
    filename: str,
    task: Optional["DocumentTask"] = None,
    model_config_port: Optional[ModelConfigPort] = None,
) -> None:
    """
    执行文档处理的核心 pipeline（独立函数，可被 arq worker 或直接调用）

    Args:
        session: 数据库会话
        document_id: 文档 ID
        kb_id: 知识库 ID
        space_id: 空间 ID
        file_content: 文件内容
        filename: 文件名
    """
    _logger = get_logger(__name__)
    doc_repo = DocumentRepository(session)
    kb_repo = KnowledgeBaseRepository(session)

    document = await doc_repo.get_by_id(document_id)
    if not document:
        return

    # 获取或确保任务记录
    from novamind.features.knowledge_space.models.document_task import TaskStatus

    if task is None:
        from novamind.features.knowledge_space.repository.document_task_repository import (
            DocumentTaskRepository,
        )

        _task_repo = DocumentTaskRepository(session)
        task = await _task_repo.get_by_document_id(document_id)
        if task is None:
            task = await _task_repo.create(
                {
                    "document_id": document_id,
                    "kb_id": kb_id,
                    "space_id": space_id,
                    "status": TaskStatus.PENDING,
                    "pipeline_config": None,
                    "queued_at": now_china(),
                }
            )
    if task.status != TaskStatus.PROCESSING:
        task.mark_processing()

    kb = await kb_repo.get_by_id(document.kb_id)
    if not kb:
        return

    # ===== 图片文档分支 =====
    file_ext = document.file_type.lower() if document.file_type else ""

    if file_ext in IMAGE_FILE_TYPES:
        await _process_image_document_static(
            document, file_content, session, _logger, task=task,
            model_config_port=model_config_port,
        )
        return

    # ===== 视频文档分支（新增） =====
    if file_ext in VIDEO_FILE_TYPES:
        from novamind.features.knowledge_space.services.media_processing import (
            process_video_document,
        )

        await process_video_document(
            document, file_content, session, _logger, task=task,
            model_config_port=model_config_port,
        )
        return

    # ===== 音频文档分支（新增） =====
    if file_ext in AUDIO_FILE_TYPES:
        from novamind.features.knowledge_space.services.media_processing import (
            process_audio_document,
        )

        await process_audio_document(
            document, file_content, session, _logger, task=task,
            model_config_port=model_config_port,
        )
        return

    # ===== 文本文档分支（现有逻辑）=====
    # 统一加载管道配置（space/kb/pipeline_config/embedding_config）
    ctx = await load_pipeline_context(session, document, task)

    # 获取 DocumentProcessor（传入空间配置的嵌入模型，确保语义切分使用正确模型）
    processor = await _get_document_processor_static(
        session, user_id=ctx.space_owner_id, model_name=ctx.embedding_model_name,
        model_config_port=model_config_port,
    )
    kb_config = ctx.pipeline_config
    splitting_config = kb_config.get("splitting", {})
    suffix = f".{document.file_type}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        # 先读取原始解析全文，避免将切块结果回拼成”伪全文”再落 MinIO。

        parsing_config = build_runtime_parsing_config(
            kb_config.get("parsing", {}), document.file_type
        )
        _logger.info(
            "文档解析配置已生成",
            document_id=document_id,
            file_type=document.file_type,
            parsing_strategy=parsing_config.get("strategy", "default"),
            deepdoc_parser_id=parsing_config.get("deepdoc_parser_id"),
            deepdoc_pdf_mode=parsing_config.get("deepdoc_pdf_mode"),
            ocr_enabled=parsing_config.get("ocr_enabled", False),
            vlm_description_enabled=parsing_config.get("vlm_description_enabled", False),
            splitting_strategy=splitting_config.get("strategy", "recursive"),
            splitting_chunk_size=splitting_config.get("chunk_size", 1000),
            splitting_chunk_overlap=splitting_config.get("chunk_overlap", 100),
        )
        task.start_step("parsed")
        parse_result = await processor.parse_document_result(
            tmp_path,
            parsing_config=parsing_config,
            splitting_config=splitting_config,
        )
        full_text = parse_result.full_text
        chunks = parse_result.chunks
        _logger.info(
            "文档解析结果",
            document_id=document_id,
            file_type=document.file_type,
            char_count=len(full_text),
            chunk_count=len(chunks),
            parse_metadata_keys=list(parse_result.metadata.keys())
            if parse_result.metadata
            else [],
            deepdoc_rechunked=parse_result.metadata.get("deepdoc_rechunked", False)
            if parse_result.metadata
            else False,
        )
        task.finish_step("parsed", metrics={"char_count": len(full_text), "chunk_count": len(chunks), "parse_strategy": parsing_config.get("strategy", "default"), "file_type": document.file_type})
        # 解析全文持久化到 MinIO（切块之前，立刻 commit 落库）
        await persist_parsed_text(document, full_text, session, _logger)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # 检查点 1：文档解析完成之后
    await _check_document_cancelled(document_id)

    # 2-5. 切分/向量化/问题生成/索引：交由共享后置尾（文本传结构化 prechunked_items）
    chunk_structure = list((parse_result.metadata or {}).get("chunk_structure") or [])
    prechunked_items = [
        (c, chunk_structure[i] if i < len(chunk_structure) else {})
        for i, c in enumerate(parse_result.chunks)
    ]
    tail_result = await _run_post_parse_tail(
        document=document,
        session=session,
        task=task,
        model_config_port=model_config_port,
        logger=_logger,
        chunk_type=ChunkType.TEXT,
        embedding_config=ctx.embedding_config,
        pipeline_config=ctx.pipeline_config,
        splitting_config=splitting_config,
        prechunked_items=prechunked_items,
        parse_metadata=parse_result.metadata,
        user_id=document.uploader_id,
    )
    parse_summary = _extract_parse_metadata_summary(parse_result.metadata)

    # 5. 标记任务完成
    task.mark_completed(
        result={
            "chunk_count": tail_result["chunk_count"],
            "total_tokens": sum(len(c.split()) for c in chunks),
            "parse_strategy": parsing_config.get("strategy", "default"),
            "split_strategy": splitting_config.get("strategy", "recursive"),
            "chunk_size": splitting_config.get("chunk_size", DEFAULT_CHUNK_SIZE),
            "chunk_overlap": splitting_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
            "parser_class": parse_result.metadata.get("parser_class", ""),
            "pdf_mode": parse_result.metadata.get("pdf_mode", ""),
            "layout_source": parse_result.metadata.get("layout_source", ""),
            "vision_strategy": parse_result.metadata.get("vision_strategy", ""),
            "table_region_count": parse_summary["table_region_count"],
            "figure_region_count": parse_summary["figure_region_count"],
            "reading_order_count": parse_summary["reading_order_count"],
            "indexed_at": now_china().isoformat(),
        }
    )
    await session.commit()

    _logger.info(
        "文档处理完成",
        document_id=document_id,
        chunk_count=len(chunks),
    )


async def persist_parsed_text(
    document: Document,
    full_text: str,
    session: AsyncSession,
    logger,
) -> str:
    """将解析/转写后的原始全文上传到 MinIO 并立即 commit 落库。

    所有模态（文本/图片/音频/视频）解析产出的源文本都经此入口持久化，
    确保「解析全文入 MinIO」这一不变量集中表达，且切分/向量化前已落库，
    后续管道失败也不会丢失解析结果。

    Returns:
        MinIO object_name；文本为空或上传失败时返回空字符串。
    """
    # persist_parsed_text 属于 feature 层（非 engines/），经 ClientFactory 取 MinIO 客户端；
    # upload_parsed_text_to_minio 负责实际上传，随后立即 commit 落库。
    from novamind.shared.storage.client_factory import ClientFactory
    minio_client = await ClientFactory.get_minio_client()
    object_name = await upload_parsed_text_to_minio(
        document, full_text, logger, minio_client=minio_client
    )
    await session.commit()
    return object_name


@dataclass
class PipelineContext:
    """管道配置上下文，统一承载四个模态分支共用的配置读取结果。

    将 space / kb / pipeline_config / embedding_config 的读取集中到
    load_pipeline_context，避免「Task 快照优先」与「embedding_config 来源」
    规则在各分支各写一遍而漂移。
    """

    space: Optional[KnowledgeSpace]
    kb: Optional[KnowledgeBase]
    pipeline_config: Dict[str, Any]
    embedding_config: Dict[str, Any]

    @property
    def space_owner_id(self) -> Optional[int]:
        return self.space.owner_id if self.space else None

    @property
    def embedding_model_name(self) -> Optional[str]:
        return self.embedding_config.get("model") if self.embedding_config else None

    @property
    def embedding_dim(self) -> Optional[int]:
        return self.embedding_config.get("dimension") if self.embedding_config else None


async def load_pipeline_context(
    session: AsyncSession,
    document: Document,
    task: Optional["DocumentTask"] = None,
) -> PipelineContext:
    """统一加载管道配置：space / kb / pipeline_config / embedding_config。

    - pipeline_config 优先取 task.pipeline_config 快照（入队时配置），回退 kb 实时配置
    - embedding_config 取空间级 space.embedding_config，缺失时为空 dict
    """
    space = await session.get(KnowledgeSpace, document.space_id)
    kb_repo = KnowledgeBaseRepository(session)
    kb = await kb_repo.get_by_id(document.kb_id)
    pipeline_config = (
        task.pipeline_config
        if (task and task.pipeline_config)
        else (kb.get_config() if kb else {})
    )
    embedding_config = (space.embedding_config if space else None) or {}
    return PipelineContext(
        space=space,
        kb=kb,
        pipeline_config=pipeline_config,
        embedding_config=embedding_config,
    )


async def _process_image_document_static(
    document: Document,
    file_content: bytes,
    session,
    _logger,
    task=None,
    model_config_port: Optional[ModelConfigPort] = None,
):
    """处理图片类型文档

    支持两种策略：
    - vlm: 通过 VLM 生成图片描述文本，再走文本 Embedding 索引到 ES
    - deepdoc_ocr: 通过 DeepDoc OCR 提取图片文字，再走文本 Embedding 索引到 ES

    批次 5b：model_config_port 由调用方（execute_document_pipeline）注入，
    本模块级静态助手不再内部自建 ModelConfigService，以满足引擎接缝（零具体类导入）。
    """
    # 1. 统一加载管道配置（space/kb/pipeline_config/embedding_config）
    ctx = await load_pipeline_context(session, document, task)
    if not ctx.space:
        return
    embedding_config = ctx.embedding_config
    model_name = ctx.embedding_model_name

    if not model_name:
        raise DocumentProcessingError(
            document_id=document.id,
            error_message="该空间未配置嵌入模型，无法处理图片文件",
        )

    # 读取图片解析策略（从知识库的解析配置读取，优先 task.pipeline_config 快照）
    parsing_config = build_runtime_parsing_config(
        ctx.pipeline_config.get("parsing", {}), document.file_type
    )
    image_strategy = parsing_config.get("image_strategy", "vlm")

    # 检查点 0：配置读取后
    await _check_document_cancelled(document.id)

    # 图片「解析」阶段 = VLM/OCR 提取描述文本（等价文本管道的 parsed）。
    # 此前图片路径全程不写 step_progress，导致任务列表流程日志显示「-」。
    if task:
        task.start_step("parsed")

    # 2. 根据策略选择文本提取方式
    description_text = ""

    if image_strategy == "deepdoc_ocr":
        description_text = await _process_image_ocr_static(
            document=document,
            file_content=file_content,
            session=session,
            _logger=_logger,
        )
    else:
        # VLM 路径（默认）
        vlm_model_name = parsing_config.get("vlm_model")

        if not vlm_model_name:
            raise DocumentProcessingError(
                document_id=document.id,
                error_message="图片文档处理需要 VLM（视觉语言模型）来生成描述文本，请在知识库解析配置中启用 VLM 描述并选择模型",
            )

        # 批次 5b：用注入的 ModelConfigPort，不再内部自建 ModelConfigService
        mcs = model_config_port
        description_text = await _generate_image_description(
            file_content=file_content,
            document=document,
            mcs=mcs,
            _logger=_logger,
            vlm_model_name=vlm_model_name,
        )

        if not description_text:
            raise DocumentProcessingError(
                document_id=document.id,
                error_message=f"VLM 模型 {vlm_model_name} 未能生成图片描述文本",
            )

    # 3. 图片文本持久化到 MinIO（立刻 commit 落库）
    await persist_parsed_text(document, description_text, session, _logger)
    if task:
        task.finish_step("parsed", metrics={
            "image_strategy": image_strategy,
            "description_length": len(description_text),
        })

    _logger.info(
        "图片文本提取成功",
        document_id=document.id,
        image_strategy=image_strategy,
        description_length=len(description_text),
    )

    # 4. 空 OCR/VLM 结果：文档以空内容完成
    if not description_text or not description_text.strip():
        _logger.warning(
            "图片文本提取结果为空，文档将以空内容完成",
            document_id=document.id,
            filename=document.filename,
            image_strategy=image_strategy,
        )
        if task:
            task.mark_completed(result={
                "chunk_count": 0,
                "chunk_type": ChunkType.IMAGE,
                "image_strategy": image_strategy,
                "indexed_at": now_china().isoformat(),
            })
        await session.commit()
        return

    # 5-8. 向量化/问题生成/索引：交由共享后置尾（与文本/音频/视频同路径）
    #      图片经 VLM/OCR 归一为描述文本后，后续逻辑全部共享，自动获得 question_generation
    #      等共享能力——修复此前图片路径自写 embedded/indexed 导致相似问不生成的缺口。
    #      图片语义为「一图一 chunk」：描述文本整体作为单个结构化分块（prechunked_items）
    #      传入共享尾，跳过 _split_md_text 切分。既还原原版图片单块语义，又避免 splitting
    #      配置中的脏策略值（如遗留 ``single``）经 apply_modality_splitting_override 合并到
    #      顶层后触发 _split_md_text「不支持的切分策略」报错。splitting 无 image 子键 schema，
    #      故不调 apply_modality_splitting_override（与 audio/video 不同）。
    tail_result = await _run_post_parse_tail(
        document=document,
        session=session,
        task=task,
        model_config_port=model_config_port,
        logger=_logger,
        chunk_type=ChunkType.IMAGE,
        embedding_config=embedding_config,
        pipeline_config=ctx.pipeline_config,
        splitting_config=ctx.pipeline_config.get("splitting", {}),
        prechunked_items=[(description_text, {})],
        user_id=document.uploader_id,
    )

    # 9. 标记任务完成
    result = {
        "chunk_count": tail_result["chunk_count"],
        "indexed_at": now_china().isoformat(),
        "chunk_type": ChunkType.IMAGE,
        "image_strategy": image_strategy,
        "description_length": len(description_text),
        "total_questions": tail_result.get("total_questions", 0),
    }
    if task:
        task.mark_completed(result=result)
    await session.commit()

    _logger.info(
        "图片文档处理完成",
        document_id=document.id,
        model=model_name,
        image_strategy=image_strategy,
        description_length=len(description_text),
        chunks=tail_result["chunk_count"],
    )


async def _process_image_ocr_static(
    document: Document,
    file_content: bytes,
    session,
    _logger,
) -> str:
    """使用 DeepDoc OCR 提取图片文字。

    通过 DeepDoc 的 RAGFlowFigureParser（内含 PaddleOCR）提取图片中的文字，
    返回提取的文本。OCR 推理在独立线程中执行（asyncio.to_thread）。
    """
    from novamind.engines.document.integrations.deepdoc.core.engine import DeepDocParser

    file_type = (document.file_type or "png").lower()
    _logger.info(
        "DeepDoc OCR 图片解析开始",
        document_id=document.id,
        file_type=file_type,
    )

    engine = DeepDocParser()

    try:
        result = await engine.aparse_bytes(
            file_bytes=file_content,
            file_type=file_type,
            parser_id="figure",
        )
    except Exception as exc:
        _logger.warning(
            "DeepDoc OCR 图片解析失败，文档将以空内容完成",
            document_id=document.id,
            error=str(exc),
        )
        return ""

    ocr_text = result.full_text.strip() if result else ""

    _logger.info(
        "DeepDoc OCR 图片解析完成",
        document_id=document.id,
        char_count=len(ocr_text),
        chunk_count=len(result.chunks) if result else 0,
    )

    return ocr_text


def _build_es_chunks(
    document: Document,
    chunk_items: List[Tuple[str, Dict[str, Any]]],
    chunk_type: ChunkType,
    *,
    parse_metadata: Optional[Dict[str, Any]] = None,
    frame_paths: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """统一构造 ES 索引格式的分块字典列表（文本/音频/视频共用）。

    - 文本：富 metadata（parser/parse_summary/chunk_structure 的 entry_kinds/pages/...），仅 media_url。
    - 音频/视频：metadata 含 start_time/end_time，视频按 frame_indices 映射 frame_paths；media_url + image_url。

    `chunk_items` 为 [(text, per_chunk_meta), ...]；文本 per_chunk_meta 取自 parse_metadata["chunk_structure"][i]。
    """
    es_chunks = []
    storage_info = document.storage or {}
    parse_metadata = dict(parse_metadata or {})
    is_text = chunk_type == ChunkType.TEXT
    parse_summary = _extract_parse_metadata_summary(parse_metadata) if is_text else {}
    media_url = storage_info.get("minio_object_name", "")
    for i, (text, meta) in enumerate(chunk_items):
        chunk_meta: Dict[str, Any] = {"content_hash": document.file_hash}
        if is_text:
            chunk_meta.update({
                "parser": parse_metadata.get("parser", ""),
                "file_type": parse_metadata.get("file_type", document.file_type),
                **parse_summary,
                "chunk_entry_kinds": list(meta.get("entry_kinds") or []),
                "chunk_entry_source_ids": list(meta.get("entry_source_ids") or []),
                "chunk_pages": list(meta.get("pages") or []),
                "chunk_entry_count": int(meta.get("entry_count") or 0),
            })
        else:
            # start_time/end_time 仅音视频分段有意义；图片无时间维度，不带
            if chunk_type != ChunkType.IMAGE:
                chunk_meta["start_time"] = meta.get("start_time")
                chunk_meta["end_time"] = meta.get("end_time")
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
            "media_url": media_url,
            "file_info": {
                "filename": document.filename,
                "file_type": document.file_type,
            },
            "metadata": chunk_meta,
            "questions": [],
            "question_embeddings": [],
            "created_at": now_china().isoformat(),
        }
        if not is_text:
            chunk_data["image_url"] = media_url
        es_chunks.append(chunk_data)
    return es_chunks


def _prepare_es_chunks_static(
    document: Document,
    chunks: List[str],
    parse_metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """将文本分块列表转换为 ES 索引格式的字典列表（薄 shim，委托 _build_es_chunks）。

    保留旧签名以兼容现有调用与测试；行为与原实现一致。
    """
    chunk_structure = list((parse_metadata or {}).get("chunk_structure") or [])
    chunk_items = [
        (c, chunk_structure[i] if i < len(chunk_structure) else {})
        for i, c in enumerate(chunks)
    ]
    return _build_es_chunks(document, chunk_items, ChunkType.TEXT, parse_metadata=parse_metadata)


async def _run_post_parse_tail(
    *,
    document: Document,
    session: AsyncSession,
    task: "DocumentTask",
    model_config_port: Optional[ModelConfigPort],
    logger,
    chunk_type: ChunkType,
    embedding_config: Dict[str, Any],
    pipeline_config: Dict[str, Any],
    splitting_config: Dict[str, Any],
    full_text: str = "",
    prechunked_items: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
    parse_metadata: Optional[Dict[str, Any]] = None,
    frame_paths: Optional[List[str]] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """共享后置尾：切分 → 构造 ES chunks → 向量化 → 问题生成 → 索引。

    文本/音频/视频三模态共用此尾，统一节点名 split/embedded/question_generation/indexed。
    - 转换器若已产出结构化分块（如 DeepDoc），传 prechunked_items，尾直接采用，不再二次切分；
      否则传 full_text，尾用 _split_md_text 切分（音频/视频走此分支）。
    - QG 由 pipeline_config["question_generation"]["enabled"] 控制，失败跳过、留空，与文本管道原逻辑一致。

    Returns:
        {chunk_count, indexed_count, total_questions, split_strategy}，供调用方写 mark_completed。
    """
    # 1. 切分
    task.start_step("split")
    if prechunked_items is not None:
        chunk_items = list(prechunked_items)
        split_strategy = "structural"
    else:
        from novamind.features.knowledge_space.services.media_processing import (
            _split_md_text,
            maybe_semantic_embedding_client,
        )
        sc = dict(splitting_config)
        strategy = sc.pop("strategy", "recursive")
        embedding_client = await maybe_semantic_embedding_client(
            strategy, embedding_config, session, document.uploader_id,
            model_config_port=model_config_port,
        )
        chunk_items = await _split_md_text(
            full_text, strategy=strategy, embedding_client=embedding_client, **sc,
        )
        split_strategy = strategy
    chunk_count = len(chunk_items)
    task.finish_step("split", metrics={
        "chunk_count": chunk_count,
        "split_strategy": split_strategy,
        "chunk_size": splitting_config.get("chunk_size"),
    })
    await _check_document_cancelled(document.id)

    # 2. 构造 ES chunks（文本/媒体 metadata 由 _build_es_chunks 按 chunk_type 分支处理）
    es_chunks = _build_es_chunks(
        document, chunk_items, chunk_type,
        parse_metadata=parse_metadata, frame_paths=frame_paths,
    )

    # 3. 向量化
    task.start_step("embedded")
    embeddings = await _generate_embeddings_static(
        [c["content"] for c in es_chunks], embedding_config,
        session=session, user_id=user_id or document.uploader_id,
        model_config_port=model_config_port,
    )
    for i, emb in enumerate(embeddings):
        if emb:
            es_chunks[i]["embedding"] = emb
    task.finish_step("embedded", metrics={
        "embedding_count": len(embeddings),
        "dimension": embedding_config.get("dimension"),
    })
    await _check_document_cancelled(document.id)

    # 4. 问题生成（由 KB 配置控制；失败跳过、留空）
    task.start_step("question_generation")
    qg_config = pipeline_config.get("question_generation", {})
    should_generate = qg_config.get("enabled", False) if qg_config else False
    if should_generate:
        try:
            questions_list, question_embeddings_list = await _generate_questions_for_chunks_static(
                chunks=[c["content"] for c in es_chunks],
                document_title=document.filename,
                kb_config=pipeline_config,
                embedding_config=embedding_config,
                user_id=document.uploader_id,
                session=session,
                model_config_port=model_config_port,
            )
            for i, (questions, q_embeddings) in enumerate(
                zip(questions_list, question_embeddings_list)
            ):
                es_chunks[i]["questions"] = questions
                es_chunks[i]["question_embeddings"] = [{"vector": emb} for emb in q_embeddings]
        except Exception as e:
            logger.warning(
                "假设问题生成失败，跳过继续处理",
                document_id=document.id, error=str(e),
            )
            for chunk in es_chunks:
                chunk["questions"] = []
                chunk["question_embeddings"] = []
    else:
        for chunk in es_chunks:
            chunk["questions"] = []
            chunk["question_embeddings"] = []
    total_questions = sum(len(c.get("questions") or []) for c in es_chunks)
    task.finish_step("question_generation", metrics={
        "enabled": should_generate, "total_questions": total_questions,
    })
    await _check_document_cancelled(document.id)

    # 5. 索引到 ES
    task.start_step("indexed")
    es_client = await _get_es_client_static()
    indexed_count = await es_client.bulk_index_chunks(
        space_id=document.space_id,
        chunks=es_chunks,
        embedding_dim=embedding_config.get("dimension"),
    )
    if indexed_count == 0 and es_chunks:
        raise RuntimeError(f"ES 索引写入失败: {len(es_chunks)} 个分块均未成功写入")
    task.finish_step("indexed", metrics={
        "indexed_count": indexed_count, "chunk_count": len(es_chunks),
    })

    return {
        "chunk_count": chunk_count,
        "indexed_count": indexed_count,
        "total_questions": total_questions,
        "split_strategy": split_strategy,
    }



def _extract_parse_metadata_summary(parse_metadata: Dict[str, Any]) -> Dict[str, Any]:
    table_regions = list(parse_metadata.get("table_regions") or [])
    figure_regions = list(parse_metadata.get("figure_regions") or [])
    reading_order = list(parse_metadata.get("reading_order") or [])
    return {
        "parser_class": parse_metadata.get("parser_class", ""),
        "pdf_mode": parse_metadata.get("pdf_mode", ""),
        "layout_source": parse_metadata.get("layout_source", ""),
        "vision_strategy": parse_metadata.get("vision_strategy", ""),
        "table_region_count": len(table_regions),
        "figure_region_count": len(figure_regions),
        "reading_order_count": len(reading_order),
    }


async def _get_es_client_static() -> ElasticsearchClient:
    """获取 ES 客户端（静态方法用）"""
    from novamind.shared.storage.client_factory import ClientFactory

    return await ClientFactory.get_elasticsearch_client()


async def _get_document_processor_static(
    session: AsyncSession,
    user_id: Optional[int] = None,
    model_name: Optional[str] = None,
    model_config_port: Optional[ModelConfigPort] = None,
) -> DocumentProcessor:
    """获取文档处理器（静态方法用）

    批次 5b：model_config_port 由调用方注入，不再内部自建 ModelConfigService。
    """
    model_config_service = model_config_port
    if not model_name and user_id:
        model_name = await model_config_service.get_user_default_model_name(user_id, "embedding")
    if not model_name:
        raise DocumentProcessingError(
            document_id=0,
            error_message="未配置 Embedding 模型，请在模型配置中添加",
        )
    effective_user_id = user_id or 0
    embedding_client = await model_config_service.get_embedding_client_by_model(
        user_id=effective_user_id, model=model_name
    )
    return DocumentProcessor(embedding_client=embedding_client)


async def _generate_embeddings_static(
    texts: List[str],
    embedding_config: Dict[str, Any],
    session: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
    model_config_port: Optional[ModelConfigPort] = None,
) -> List[List[float]]:
    """生成文本向量（静态方法用）"""
    if not session:
        raise DocumentProcessingError(document_id=0, error_message="生成向量需要数据库会话")

    model_name = embedding_config.get("model")
    embedding_client = await _get_embedding_client_static(
        session, user_id, model_name, model_config_port=model_config_port
    )

    batch_size = embedding_config.get("batch_size", DEFAULT_EMBEDDING_BATCH_SIZE)
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            embeddings = await embedding_client.generate_embeddings_batch(batch)
        except Exception as e:
            _log = get_logger(__name__)
            _log.error(
                "Embedding 批量生成失败",
                model_name=model_name,
                batch_start=i,
                batch_size=len(batch),
                error=str(e),
                traceback=traceback.format_exc(),
            )
            raise EmbeddingError(
                f"Embedding 生成失败: model={model_name or 'unknown'}, batch_start={i}, error={e}"
            ) from e
        all_embeddings.extend(embeddings)
    return all_embeddings


async def _get_embedding_client_static(
    session: AsyncSession,
    user_id: Optional[int] = None,
    model_name: Optional[str] = None,
    model_config_port: Optional[ModelConfigPort] = None,
) -> EmbeddingClient:
    """获取 Embedding 客户端（静态方法用）

    批次 5b：model_config_port 由调用方注入，不再内部自建 ModelConfigService。
    """
    model_config_service = model_config_port
    if not model_name and user_id:
        model_name = await model_config_service.get_user_default_model_name(user_id, "embedding")
    if not model_name:
        raise DocumentProcessingError(
            document_id=0,
            error_message="未配置 Embedding 模型，请在模型配置中添加",
        )
    effective_user_id = user_id or 0
    return await model_config_service.get_embedding_client_by_model(
        user_id=effective_user_id, model=model_name
    )


async def _generate_single_embedding_static(
    text: str,
    embedding_config: Dict[str, Any],
    session: AsyncSession,
    user_id: Optional[int] = None,
    model_config_port: Optional[ModelConfigPort] = None,
) -> Optional[List[float]]:
    """生成单条文本的嵌入向量（用于 VLM 描述文本）

    Args:
        text: 文本内容
        embedding_config: 嵌入模型配置（含 model 名称）
        session: 数据库会话
        user_id: 用户 ID

    Returns:
        嵌入向量，失败返回 None
    """
    try:
        model_name = embedding_config.get("model")
        embedding_client = await _get_embedding_client_static(
            session, user_id, model_name, model_config_port=model_config_port
        )
        embeddings = await embedding_client.generate_embeddings_batch([text])
        return embeddings[0] if embeddings else None
    except Exception as e:
        _log = get_logger(__name__)
        _log.warning("单条文本嵌入生成失败", error=str(e), traceback=traceback.format_exc())
        return None


async def _generate_image_description(
    file_content: bytes,
    document: Document,
    mcs,  # ModelConfigService
    _logger,
    vlm_model_name: Optional[str] = None,
) -> str:
    """调用 VLM 生成图片描述文本

    Args:
        file_content: 图片二进制内容
        document: 文档对象
        mcs: ModelConfigService 实例
        _logger: 日志器

    Returns:
        描述文本（截断到 2000 字符），失败抛异常由调用方处理
    """
    from novamind.shared.prompts.templates import PromptManager

    # 1. 获取 VLM 客户端
    vlm_model = vlm_model_name or await mcs.get_user_default_model_name(document.uploader_id, "vlm")
    if not vlm_model:
        raise ValueError("未配置 VLM 模型，请在模型配置中添加视觉模型")

    vlm_client = await mcs.get_vlm_client_by_model(document.uploader_id, vlm_model)

    file_ext = (document.file_type or "png").lower()
    mime_type = f"image/{file_ext}" if file_ext != "jpg" else "image/jpeg"

    # 3. 获取描述 Prompt
    description_prompt = PromptManager.get_template("image_description")

    # 4. 构建多模态消息（OpenAI 兼容格式）
    messages = build_vlm_image_messages(
        file_bytes=file_content,
        mime_type=mime_type,
        text_prompt=description_prompt,
    )

    # 5. 调用 VLM 生成描述
    description = await generate_vlm_text_with_fallback(
        vlm_client=vlm_client,
        messages=messages,
        max_tokens=1024,
        temperature=0.3,
        logger=_logger,
        vlm_model=vlm_model,
        log_context={
            "document_id": document.id,
            "file_type": document.file_type,
        },
    )

    if not description or not description.strip():
        raise ValueError(f"VLM 返回空描述，模型: {vlm_model}")

    # 6. 截断到 2000 字符
    description = description.strip()[:2000]

    return description


async def _generate_questions_for_chunks_static(
    chunks: List[str],
    document_title: str,
    kb_config: Dict[str, Any],
    embedding_config: Dict[str, Any],
    user_id: Optional[int] = None,
    session: Optional[AsyncSession] = None,
    model_config_port: Optional[ModelConfigPort] = None,
) -> tuple:
    """
    为所有分块生成假设问题，并生成问题向量

    Returns:
        (questions_list, question_embeddings_list)
        questions_list: List[List[str]] — 每个分块对应的问题文本列表
        question_embeddings_list: List[List[List[float]]] — 每个分块对应的问题向量列表
    """
    from novamind.features.knowledge_space.services.question_generation_service import (
        QuestionGenerationService,
    )
    from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
        QuestionGenerationConfig,
    )

    _logger = get_logger(__name__)

    qg_config_dict = kb_config.get("question_generation", {})
    qg_config = (
        QuestionGenerationConfig(**qg_config_dict) if qg_config_dict else QuestionGenerationConfig()
    )

    if not qg_config.enabled:
        _logger.info("假设问题生成未启用，跳过")
        return [], []

    qg_service = QuestionGenerationService(
        session=session, config=qg_config, model_config_service=model_config_port
    )

    # generate_questions_batch 接受 List[Tuple[str, Optional[str]]] 格式
    chunk_tuples = [(chunk, document_title) for chunk in chunks]
    batch_results = await qg_service.generate_questions_batch(
        chunks=chunk_tuples,
        user_id=user_id,
    )

    # 提取问题文本
    questions_list: List[List[str]] = []
    all_questions_flat: List[str] = []

    for chunk_questions in batch_results:
        texts = [q.question for q in chunk_questions]
        questions_list.append(texts)
        all_questions_flat.extend(texts)

    # 生成问题向量
    question_embeddings_list: List[List[List[float]]] = []
    if all_questions_flat:
        try:
            all_q_embeddings = await _generate_embeddings_static(
                all_questions_flat,
                embedding_config,
                session=session,
                user_id=user_id,
                model_config_port=model_config_port,
            )
            # 将扁平的向量列表按每个分块的问题数量分组
            idx = 0
            for chunk_questions in batch_results:
                count = len(chunk_questions)
                question_embeddings_list.append(all_q_embeddings[idx : idx + count])
                idx += count
        except Exception as e:
            _logger.warning("问题向量生成失败，跳过向量", error=str(e))
            question_embeddings_list = [[] for _ in batch_results]
    else:
        question_embeddings_list = [[] for _ in batch_results]

    return questions_list, question_embeddings_list
