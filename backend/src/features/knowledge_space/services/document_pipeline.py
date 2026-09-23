"""文档处理管道执行模块（从 document_service.py 巨石抽出的管道职责）。

集中承载文档处理 pipeline 的执行入口与模块级静态助手群：
- ``execute_document_pipeline``：四模态分流入口（文本/图片/视频/音频），由 arq worker
  或上层直接以模块级函数调用；按文件类型路由到文本管道 / 图片 VLM+OCR / 视频 / 音频分支。
- 模块级静态助手：``_process_image_document_static`` / ``_process_image_ocr_static`` /
  ``build_es_chunks`` / ``prepare_es_chunks`` / ``run_post_parse_tail`` /
  ``extract_parse_metadata_summary`` / ``get_es_client`` /
  ``_get_document_processor_static`` / ``generate_embeddings`` /
  ``get_embedding_client`` / ``generate_single_embedding`` /
  ``_generate_image_description`` / ``generate_questions_for_chunks``。
- 取消语义：``DocumentCancelledError`` + ``check_document_cancelled``（pipeline 关键节点提前终止）。
- 配置上下文：``PipelineContext`` + ``load_pipeline_context``（统一 space/kb/pipeline_config/embedding_config）。
- 解析全文持久化：``persist_parsed_text``（所有模态解析全文入 MinIO + 立即 commit 落库）。

文件类型常量收敛到 ``document_file_types``（中立模块），本模块按模态分流时引用。
对 ``media_processing`` 的调用（视频/音频/语义切分）保持延迟导入，避免顶层循环 import。
"""

import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from novamind.shared.utils.time_utils import now_china

# figure 占位符模式：__FIGURE_URL__{artifact_id}__，artifact_id 为非空白且
# 不含 __ 连续下划线的标识串（解析器 artifact_id 形如 fig_1_3 / a1b2c3）
_FIGURE_PLACEHOLDER_RE = re.compile(r"__FIGURE_URL__(?!__)[^\s_]*(?:_[^\s_]+)*__")

if TYPE_CHECKING:
    # 仅用于类型注解（``Optional["DocumentTask"]`` 前向引用），避免运行期循环 import。
    from novamind.features.knowledge_space.models.document_task import DocumentTask

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.document.media.vlm import (
    build_vlm_image_messages,
    generate_vlm_text_with_fallback,
)
from novamind.engines.document.pipeline import DocumentProcessor
from novamind.features.knowledge_space.exceptions import (
    DocumentProcessingError,
    PermanentProcessingError,
)
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    build_runtime_parsing_config,
)
from novamind.features.knowledge_space.services.document_file_types import (
    AUDIO_FILE_TYPES,
    IMAGE_FILE_TYPES,
    VIDEO_FILE_TYPES,
)
from novamind.features.knowledge_space.services.pipeline_steps import (
    begin_step,
    check_document_cancelled,
    extract_parse_metadata_summary,
    load_pipeline_context,
    persist_parsed_text,
    run_post_parse_tail,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from sqlalchemy.ext.asyncio import AsyncSession


def _raise_on_empty_parse(
    full_text: str,
    parse_result: Any,
    parsing_config: dict[str, Any],
    document_id: int,
) -> None:
    """解析跑完但 0 字符 → 抛 DocumentProcessingError，不静默当成功。

    full 模式（上游对齐的逐框融合：文字层 + OCR 回退）跑完仍 0 字符，意味着文字层为空
    且 OCR 也未识别到文字——可能是 OCR 模型未就绪或页面本就是纯无字图片。plain 模式 /
    default 策略仅抽文字层，0 字符意味着无文字层（扫描件），建议切 full。

    守"没选就不兜底"原则：不自动回退到其它模式，由用户显式切换（保证解析路径可追踪）。
    """
    if full_text.strip():
        return
    meta = parse_result.metadata or {}
    pages = meta.get("pages")
    strategy = parsing_config.get("strategy", "default")
    pdf_mode = meta.get("pdf_mode") or parsing_config.get("deepdoc_pdf_mode") or ""
    mode_desc = f"{strategy}/{pdf_mode}" if pdf_mode else strategy
    if pdf_mode == "plain" or strategy == "default":
        hint = (
            f"解析抽出 0 字符：{mode_desc} 模式仅抽取文字层、未做 OCR，"
            f"但该 PDF（{pages or '?'} 页）文字层为空（疑似扫描件或图片 PDF）。"
            f"建议将 PDF 解析器改用 full 模式（含逐框文字层/OCR 融合）以获取文本。"
        )
    else:
        ocr_sources = meta.get("ocr_sources") or []
        hint = (
            f"解析抽出 0 字符：{mode_desc} 模式已完成逐框文字层/OCR 融合仍无文本"
            f"（pages={pages or '?'}, ocr_sources={ocr_sources}）——"
            f"文字层为空且 OCR 未识别到文字。请检查 OCR 模型是否就绪"
            f"（运行 scripts/download_deepdoc_models.py --check）或确认页面非纯无字图片。"
        )
    raise PermanentProcessingError(document_id=document_id, error_message=hint)



async def execute_document_pipeline(
    session: AsyncSession,
    document_id: int,
    kb_id: int,
    space_id: int,
    file_content: bytes,
    filename: str,
    task: Optional["DocumentTask"] = None,
    model_config_port: ModelConfigService | None = None,
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

    # 断点续跑：解析指纹匹配即复用快照，跳过昂贵解析（VLM/OCR 可能已付费成功）。
    # fail-open：指纹不匹配/无快照/读失败一律走全量解析路径。
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOTS_ENABLED,
        build_parse_snapshot_payload,
        canonical_json,
        compute_parse_fingerprint,
        load_parse_snapshot,
        payload_fingerprint_matches,
        refresh_figure_image_urls,
        restore_frame_paths,
        restore_time_alignment,
        save_parse_snapshot,
        snapshot_fingerprint,
    )
    from novamind.shared.storage.client_factory import ClientFactory

    resume_minio_client = None
    parse_fingerprint = ""
    if SNAPSHOTS_ENABLED:
        try:
            resume_minio_client = await ClientFactory.get_minio_client()
            parsing_config_for_fp = build_runtime_parsing_config(
                kb_config.get("parsing", {}), document.file_type
            )
            parse_fingerprint = compute_parse_fingerprint(document, parsing_config_for_fp)
        except Exception as fp_exc:
            _logger.warning(
                "解析指纹计算失败，本次按无快照处理", document_id=document_id, error=str(fp_exc),
            )

    parse_snapshot_payload: dict[str, Any] | None = None
    if SNAPSHOTS_ENABLED and parse_fingerprint and resume_minio_client is not None:
        if snapshot_fingerprint(document, "parse") == parse_fingerprint:
            snap = await load_parse_snapshot(document, resume_minio_client, _logger)
            # payload 内嵌指纹校验（防双 worker 交错写同名对象后指针/内容错配）
            if snap and payload_fingerprint_matches(snap, "parse_fingerprint", parse_fingerprint):
                if isinstance(snap.get("full_text"), str) and snap["full_text"].strip():
                    parse_snapshot_payload = snap

    if parse_snapshot_payload is not None:
        # ===== 快照命中：复用解析产物，跳过解析/图片上传 =====
        resume_meta = parse_snapshot_payload.get("parse_metadata") or {}
        resume_prechunked = [
            (str(text), dict(meta or {}))
            for text, meta in (parse_snapshot_payload.get("prechunked_items") or [])
        ]
        resumed_time_alignment = parse_snapshot_payload.get("time_alignment")
        resumed_frame_paths = restore_frame_paths(parse_snapshot_payload.get("frame_paths"))

        # 切分配置漂移检测（审计 P1#3）：文本切分实际发生在 parse 阶段内
        # （DeepDoc rechunk），parse 指纹不含切分配置。快照记录了产出
        # prechunked_items 时的生效切分配置，与当前配置不一致时放弃旧分块、
        # 改走 full_text 重切（run_post_parse_tail 的非 prechunked 分支），
        # 贵的解析产物仍然复用。
        snap_splitting = parse_snapshot_payload.get("splitting_config")
        split_config_drifted = (
            snap_splitting is not None
            and canonical_json(snap_splitting) != canonical_json(splitting_config or {})
        )

        # figure 图片预签名 URL 已过期，按 minio_object_name 重签并替换正文占位符。
        # 快照存的是**占位符版**全文/分块（build_parse_snapshot_payload 契约），
        # 这里重签后二次替换；旧快照若已含替换后 URL（历史数据），占位符匹配
        # 不中为 no-op，按原文复用（链接过期由 refresh_figure_image_urls 修
        # metadata 结构化链接）。
        image_url_map: dict[str, str] = {}
        try:
            image_url_map = await refresh_figure_image_urls(
                document, parse_snapshot_payload, resume_minio_client, _logger,
            )
        except Exception as url_exc:
            _logger.warning(
                "figure 图片 URL 重签失败（保留占位符）", document_id=document_id, error=str(url_exc),
            )
        full_text = parse_snapshot_payload["full_text"]
        if image_url_map:
            full_text = _replace_figure_placeholders(full_text, image_url_map)
        # 历史快照/上传失败残留的占位符剥除（不进 embedding/ES content）
        full_text = _replace_figure_placeholders(full_text, {}, strip_unresolved=True)

        resume_chunks = [text for text, _meta in resume_prechunked]
        if image_url_map:
            resume_chunks = [_replace_figure_placeholders(c, image_url_map) for c in resume_chunks]
        resume_chunks = [
            _replace_figure_placeholders(c, {}, strip_unresolved=True) for c in resume_chunks
        ]

        if split_config_drifted:
            _logger.info(
                "切分配置已变更，放弃快照旧分块、按 full_text 重切（解析产物仍复用）",
                document_id=document_id,
            )
            resume_prechunked = None
            resume_chunks = []
            # 重切后 per-chunk 元数据失效，置空防张冠李戴（与批 H 的 rechunk 防错位一致）
            resume_meta = {k: v for k, v in (resume_meta if isinstance(resume_meta, dict) else {}).items()
                           if k != "chunk_structure"}

        await begin_step(session, task, "parsed")
        task.finish_step("parsed", metrics={
            "char_count": len(full_text),
            "chunk_count": len(resume_chunks),
            "parse_strategy": (resume_meta.get("strategy") if isinstance(resume_meta, dict) else None)
            or "resumed",
            "file_type": document.file_type,
            "resumed": True,
            **({"split_config_drifted": True} if split_config_drifted else {}),
        })
        _logger.info(
            "解析快照命中，复用解析产物（跳过解析）",
            document_id=document_id,
            parse_fingerprint=parse_fingerprint,
            char_count=len(full_text),
            chunk_count=len(resume_chunks) if resume_prechunked is not None else None,
        )
        # resume 路径同样要落解析全文（审计 P2：首跑 persist 失败时无自愈路径；
        # 快照全文是占位符版，重签 URL 后落盘即最终形态）
        await persist_parsed_text(document, full_text, session, _logger)
        _resume_tail_result = await run_post_parse_tail(
            document=document,
            session=session,
            task=task,
            model_config_port=model_config_port,
            logger=_logger,
            chunk_type=ChunkType.TEXT,
            embedding_config=ctx.embedding_config,
            pipeline_config=ctx.pipeline_config,
            splitting_config=splitting_config,
            # drifted 时 prechunked_items=None + full_text 兜底 → tail 走重切分支
            prechunked_items=resume_prechunked,
            full_text=full_text if resume_prechunked is None else "",
            parse_metadata=resume_meta if isinstance(resume_meta, dict) else {},
            parse_fingerprint=parse_fingerprint,
            frame_paths=resumed_frame_paths or None,
            time_alignment=restore_time_alignment(resumed_time_alignment),
            user_id=document.uploader_id,
        )
        parse_summary = extract_parse_metadata_summary(resume_meta if isinstance(resume_meta, dict) else {})
        task.mark_completed(
            result={
                "chunk_count": _resume_tail_result["chunk_count"],
                "total_tokens": sum(len(c.split()) for c in resume_chunks),
                "parse_strategy": (resume_meta.get("strategy") if isinstance(resume_meta, dict) else None) or "",
                "split_strategy": splitting_config.get("strategy", "recursive"),
                "chunk_size": splitting_config.get("chunk_size", DEFAULT_CHUNK_SIZE),
                "chunk_overlap": splitting_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
                "parser_class": parse_summary["parser_class"],
                "pdf_mode": parse_summary["pdf_mode"],
                "layout_source": parse_summary["layout_source"],
                "vision_strategy": parse_summary["vision_strategy"],
                "table_region_count": parse_summary["table_region_count"],
                "figure_region_count": parse_summary["figure_region_count"],
                "reading_order_count": resume_meta.get("reading_order") and len(resume_meta.get("reading_order") or []) or parse_summary["reading_order_count"],
                "resumed_from_snapshot": True,
                "indexed_at": now_china().isoformat(),
            }
        )
        await session.commit()
        _logger.info("文档处理完成（断点续跑）", document_id=document_id, chunk_count=len(resume_chunks))
        return

    # ===== 无快照命中：正常解析路径 =====
    if True:  # 保留原缩进层级，减少此文件 diff 噪声
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
        await begin_step(session, task, "parsed")
        parse_result = await processor.parse_document_result(
            tmp_path,
            parsing_config=parsing_config,
            splitting_config=splitting_config,
        )
        # 原始文件已解析完，立即释放临时文件。不把 unlink 挂 try/finally 到整个
        # 管道——此前快照命中分支提前 return 绕过 finally，每个续跑任务泄漏一个
        # tmp 文件；解析抛错时任务行会标 FAILED，OS tmp 目录由系统清理兜底。
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
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
        # 空文本检测：解析跑完但 0 字符——不静默当成功（否则前端看到"成功但无内容"的假成功）。
        # 守"没选就不兜底"原则：不自动回退到其它模式，抛错并给出可操作建议，让用户显式切换模式。
        _raise_on_empty_parse(full_text, parse_result, parsing_config, document_id)
        task.finish_step("parsed", metrics={"char_count": len(full_text), "chunk_count": len(chunks), "parse_strategy": parsing_config.get("strategy", "default"), "file_type": document.file_type})

        # 上传 PDF figure 图片到 MinIO 并替换占位符为真实 URL。
        # 仅 PDF full 模式会产出 figure_regions + image_blobs；上传在 persist 之前完成，
        # 保证最终落盘的完整 MD 与 ES chunk content 都已含可访问图片链接。
        figure_regions = list((parse_result.metadata or {}).get("figure_regions") or [])
        image_url_map: dict[str, str] = {}
        # 快照用占位符版全文/分块：预签名 URL 只有 1 小时时效，替换后版本
        # 焊进快照/ES 会让 resume 产物全部带过期链接（审计 P2 URL 过期链）。
        full_text_for_snapshot = full_text
        chunks_for_snapshot = list(parse_result.chunks)
        if figure_regions and document.file_type.lower() == "pdf":
            from novamind.shared.storage.client_factory import ClientFactory

            minio_client = await ClientFactory.get_minio_client()
            image_url_map = await _upload_figure_images_to_minio(
                document, figure_regions, _logger, minio_client=minio_client
            )
        if image_url_map:
            full_text = _replace_figure_placeholders(full_text, image_url_map)
            parse_result.chunks = [
                _replace_figure_placeholders(chunk, image_url_map)
                for chunk in parse_result.chunks
            ]
            chunks = parse_result.chunks
        # 上传失败的 figure 占位符必须剥除（审计 P1#7）：垃圾串进 embedding
        # 污染向量、检索命中原样返回给用户/LLM。有 figure_regions 但 map 不含
        # 的即失败项——全文与分块统一 strip_unresolved 兜底剥除。
        if figure_regions:
            full_text = _replace_figure_placeholders(full_text, {}, strip_unresolved=True)
            parse_result.chunks = [
                _replace_figure_placeholders(c, {}, strip_unresolved=True)
                for c in parse_result.chunks
            ]
            chunks = parse_result.chunks
            if len(image_url_map) < len(figure_regions):
                _logger.warning(
                    "部分 PDF figure 图片上传失败，残留占位符已剥除（figure 能力降级）",
                    document_id=document_id,
                    failed_count=len(figure_regions) - len(image_url_map),
                )
        if image_url_map:
            # 上传完成后清除原始 PNG bytes，降低大 PDF 多图场景的内存占用。
            for region in figure_regions:
                region.pop("image_blobs", None)
            _logger.info(
                "PDF figure 图片占位符已替换",
                document_id=document_id,
                replaced_count=len(image_url_map),
                figure_region_count=len(figure_regions),
            )

        # 解析全文持久化到 MinIO（切块之前，立刻 commit 落库）
        await persist_parsed_text(document, full_text, session, _logger)

    # 检查点 1：文档解析完成之后
    await check_document_cancelled(document_id)
    # 2-5. 切分/向量化/问题生成/索引：交由共享后置尾（文本传结构化 prechunked_items）
    chunk_structure = list((parse_result.metadata or {}).get("chunk_structure") or [])
    # deepdoc rechunk 时 chunks 是对 full_text 的重切，条数与 chunk_structure
    # 不再一一对应——按 index 捡会拿到错误页码/条目类型（张冠李戴），置空防错位。
    if (parse_result.metadata or {}).get("deepdoc_rechunked"):
        chunk_structure = []
    prechunked_items = [
        (c, chunk_structure[i] if i < len(chunk_structure) else {})
        for i, c in enumerate(parse_result.chunks)
    ]
    # 快照存占位符版分块（同 full_text_for_snapshot 的理由）
    prechunked_for_snapshot = (
        [(c, {}) for c in chunks_for_snapshot]
        if image_url_map
        else prechunked_items
    )

    # 解析快照：persist 成功后保存（占位符版全文 + 元数据 + 结构化分块 + 生效
    # 切分配置），供后续重试在指纹匹配时跳过昂贵解析。fail-open：保存失败不影响主流程。
    if SNAPSHOTS_ENABLED and parse_fingerprint and resume_minio_client is not None:
        snapshot_payload = build_parse_snapshot_payload(
            parse_fingerprint=parse_fingerprint,
            full_text=full_text_for_snapshot if image_url_map else full_text,
            parse_metadata=parse_result.metadata,
            prechunked_items=prechunked_for_snapshot,
            splitting_config=splitting_config or {},
        )
        await save_parse_snapshot(
            document, session, _logger,
            minio_client=resume_minio_client,
            parse_fingerprint=parse_fingerprint,
            payload=snapshot_payload,
        )

    tail_result = await run_post_parse_tail(
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
        parse_fingerprint=parse_fingerprint,
        user_id=document.uploader_id,
    )
    parse_summary = extract_parse_metadata_summary(parse_result.metadata)

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



def _replace_figure_placeholders(
    text: str,
    image_url_map: dict[str, str],
    *,
    strip_unresolved: bool = False,
) -> str:
    """把 full_text / chunk content 里的 __FIGURE_URL__{artifact_id}__ 替换为真实 URL。

    strip_unresolved=True 时同时剥除 map 中不存在的占位符（上传失败的 figure），
    防垃圾串进 embedding 与 ES content（审计 P1#7——检索命中会把
    ``__FIGURE_URL__xxx__`` 原样返回给用户/LLM，且占位符污染向量）。
    """
    if not text:
        return text
    if image_url_map:
        for artifact_id, image_url in image_url_map.items():
            placeholder = f"__FIGURE_URL__{artifact_id}__"
            text = text.replace(placeholder, image_url)
    if strip_unresolved:
        text = _FIGURE_PLACEHOLDER_RE.sub("", text)
    return text


async def _upload_figure_images_to_minio(
    document: Document,
    figure_regions: list[dict[str, Any]],
    logger,
    minio_client,
) -> dict[str, str]:
    """上传 PDF figure 图片到 MinIO，返回 {artifact_id: image_url}。

    每个 figure region 必须有 ``image_blobs``（PNG bytes 列表），取首张
    （``_encode_crops`` 的合成图或单页图）上传。上传成功后在 region 字典
    里写入 ``minio_object_name`` 和 ``image_url``。
    """
    image_url_map: dict[str, str] = {}
    storage = document.storage or {}
    base = storage.get("minio_object_name", "")
    if not base or not figure_regions:
        return image_url_map

    from io import BytesIO

    from PIL import Image as PILImage

    bucket_name = getattr(minio_client, "default_bucket", "knowledge-base")

    for region in figure_regions:
        artifact_id = str(region.get("artifact_id") or "")
        if not artifact_id:
            continue
        blobs = list(region.get("image_blobs") or [])
        if not blobs:
            continue
        image_bytes = blobs[0]
        if len(image_bytes) < 100:
            logger.warning(
                "PDF figure 图片数据量过小，跳过上传",
                document_id=document.id,
                artifact_id=artifact_id,
                size_bytes=len(image_bytes),
                min_bytes=100,
            )
            continue
        try:
            img = PILImage.open(BytesIO(image_bytes))
            if img.width < 32 or img.height < 32:
                logger.warning(
                    "PDF figure 图片尺寸过小，跳过上传",
                    document_id=document.id,
                    artifact_id=artifact_id,
                    width=img.width,
                    height=img.height,
                )
                continue
        except Exception as exc:
            logger.warning(
                "PDF figure 图片格式检测失败，跳过上传",
                document_id=document.id,
                artifact_id=artifact_id,
                error=str(exc),
            )
            continue

        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", artifact_id)
        page = int(region.get("page_start") or 0)
        object_name = f"{base}_figures/figure_{safe_id}_{page}.png"
        try:
            await minio_client.upload_file(object_name, image_bytes, "image/png")
            image_url = await minio_client.get_file_url(
                bucket_name=bucket_name,
                object_name=object_name,
                expires=3600,
            )
            region["minio_object_name"] = object_name
            region["image_url"] = image_url
            image_url_map[artifact_id] = image_url
            region.pop("image_blobs", None)
            logger.info(
                "PDF figure 图片上传成功",
                document_id=document.id,
                artifact_id=artifact_id,
                object_name=object_name,
            )
        except Exception as exc:
            logger.warning(
                "PDF figure 图片上传失败",
                document_id=document.id,
                artifact_id=artifact_id,
                object_name=object_name,
                error=str(exc),
            )
            continue

    return image_url_map




async def _process_image_document_static(
    document: Document,
    file_content: bytes,
    session,
    _logger,
    task=None,
    model_config_port: ModelConfigService | None = None,
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
        raise PermanentProcessingError(
            document_id=document.id,
            error_message="该空间未配置嵌入模型，无法处理图片文件",
        )

    # 读取图片解析策略（从知识库的解析配置读取，优先 task.pipeline_config 快照）
    parsing_config = build_runtime_parsing_config(
        ctx.pipeline_config.get("parsing", {}), document.file_type
    )
    image_strategy = parsing_config.get("image_strategy", "vlm")

    # 检查点 0：配置读取后
    await check_document_cancelled(document.id)

    # 图片「解析」阶段 = VLM/OCR 提取描述文本（等价文本管道的 parsed）。
    # 此前图片路径全程不写 step_progress，导致任务列表流程日志显示「-」。
    await begin_step(session, task, "parsed")

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
        # VLM 路径（默认）。vlm_model 必须由用户在解析配置中显式选择；
        # 不做"留空回退用户默认 VLM"的兜底——兜底会让解析路径不可追踪
        # （无法从配置看出实际用了哪个模型）。留空即显式抛错。
        vlm_model_name = parsing_config.get("vlm_model")

        if not vlm_model_name:
            raise PermanentProcessingError(
                document_id=document.id,
                error_message="图片文档处理需要 VLM（视觉语言模型）来生成描述文本，请在知识库解析配置中启用 VLM 描述并选择模型",
            )

        # 批次 5b：用注入的 ModelConfigService，不再内部自建 ModelConfigService
        mcs = model_config_port
        description_text = await _generate_image_description(
            file_content=file_content,
            document=document,
            mcs=mcs,
            _logger=_logger,
            vlm_model_name=vlm_model_name,
        )

        if not description_text:
            raise PermanentProcessingError(
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

    # 断点续跑：图片解析指纹（VLM/OCR 描述昂贵，重试时指纹匹配即免重跑）。
    # 指纹入参注入策略名，区分 vlm 与 deepdoc_ocr 产出。
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOTS_ENABLED as _SNAP_ENABLED,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        build_parse_snapshot_payload as _build_snap_payload,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_parse_fingerprint as _compute_parse_fp,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        save_parse_snapshot as _save_parse_snap,
    )
    from novamind.shared.storage.client_factory import ClientFactory as _SnapCF

    image_parse_fp = ""
    if _SNAP_ENABLED:
        try:
            image_fp_cfg = dict(parsing_config)
            image_fp_cfg["strategy"] = f"image:{image_strategy}:{parsing_config.get('vlm_model') or ''}"
            image_parse_fp = _compute_parse_fp(document, image_fp_cfg)
        except Exception as fp_exc:
            _logger.warning("图片解析指纹计算失败，不启用快照", document_id=document.id, error=str(fp_exc))
        if image_parse_fp:
            try:
                snap_minio = await _SnapCF.get_minio_client()
                await _save_parse_snap(
                    document, session, _logger,
                    minio_client=snap_minio,
                    parse_fingerprint=image_parse_fp,
                    payload=_build_snap_payload(
                        parse_fingerprint=image_parse_fp,
                        full_text=description_text,
                        parse_metadata={"strategy": image_strategy},
                    ),
                )
            except Exception as snap_exc:
                _logger.warning("图片解析快照保存失败（不影响主流程）", document_id=document.id, error=str(snap_exc))

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

    # 5-8. 切分/向量化/问题生成/索引：交由共享后置尾（与文本/音频/视频同路径）
    #      图片经 VLM/OCR 归一为描述文本后，后续逻辑全部共享，自动获得 question_generation
    #      等共享能力——修复此前图片路径自写 embedded/indexed 导致相似问不生成的缺口。
    #      切分统一走顶层通用策略（recursive/markdown/fixed_size/semantic），不再有模态子键
    #      覆盖。防御性丢弃遗留脏 image 子键（如旧版 image.strategy="single"），避免历史配置
    #      残留干扰；audio/video 子键同理由 SplittingConfig extra=ignore 在配置层丢弃。
    splitting_config = dict(ctx.pipeline_config.get("splitting", {}))
    splitting_config.pop("image", None)
    tail_result = await run_post_parse_tail(
        document=document,
        session=session,
        task=task,
        model_config_port=model_config_port,
        logger=_logger,
        chunk_type=ChunkType.IMAGE,
        embedding_config=embedding_config,
        pipeline_config=ctx.pipeline_config,
        splitting_config=splitting_config,
        full_text=description_text,
        parse_fingerprint=image_parse_fp or None,
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
        # DeepDocParser 按 file_type 扩展名路由到 _parse_figure_sync（runtime_parser.py:156），
        # 不接受 parser_id 参数；此前误调 aparse_bytes（DeepDocEngine 的方法）导致
        # AttributeError 被下方 except 静默吞成空文本，文档以 0 chunk"成功"完成。
        result = await engine.parse_bytes(
            file_bytes=file_content,
            file_type=file_type,
        )
    except Exception as exc:
        # 不再静默吞错：依赖缺失（figure.py 顶层 import cv2 失败）、引擎异常等必须上抛为
        # 任务 FAILED，让用户看到清晰错误而非"成功但空内容"。图片本身无文字（result 为空）
        # 不是异常，由调用方 _process_image_document_static:467 的"空内容完成"分支处理。
        raise DocumentProcessingError(
            document_id=document.id,
            error_message=f"DeepDoc OCR 解析失败：{exc}",
        ) from exc

    ocr_text = result.full_text.strip() if result else ""

    _logger.info(
        "DeepDoc OCR 图片解析完成",
        document_id=document.id,
        char_count=len(ocr_text),
        chunk_count=len(result.chunks) if result else 0,
    )

    return ocr_text








async def _get_document_processor_static(
    session: AsyncSession,
    user_id: int | None = None,
    model_name: str | None = None,
    model_config_port: ModelConfigService | None = None,
) -> DocumentProcessor:
    """获取文档处理器（静态方法用）

    批次 5b：model_config_port 由调用方注入，不再内部自建 ModelConfigService。
    """
    model_config_service = model_config_port
    if not model_name and user_id:
        model_name = await model_config_service.get_user_default_model_name(user_id, "embedding")
    if not model_name:
        raise PermanentProcessingError(
            document_id=0,
            error_message="未配置 Embedding 模型，请在模型配置中添加",
        )
    effective_user_id = user_id or 0
    embedding_client = await model_config_service.get_embedding_client_by_model(
        user_id=effective_user_id, model=model_name
    )
    return DocumentProcessor(embedding_client=embedding_client)





async def _generate_image_description(
    file_content: bytes,
    document: Document,
    mcs,  # ModelConfigService
    _logger,
    vlm_model_name: str | None = None,
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

    # 1. 获取 VLM 客户端。vlm_model_name 由调用方 _process_image_document_static 保证非空
    #    （留空时已抛 DocumentProcessingError）；此处不做"回退用户默认 VLM"兜底，保证
    #    解析路径可追踪。
    if not vlm_model_name:
        raise ValueError("未配置 VLM 模型，请在模型配置中添加视觉模型")

    vlm_client = await mcs.get_vlm_client_by_model(document.uploader_id, vlm_model_name)

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
        vlm_model=vlm_model_name,
        log_context={
            "document_id": document.id,
            "file_type": document.file_type,
        },
    )

    if not description or not description.strip():
        raise ValueError(f"VLM 返回空描述，模型: {vlm_model_name}")

    # 6. 截断到 2000 字符
    description = description.strip()[:2000]

    return description


