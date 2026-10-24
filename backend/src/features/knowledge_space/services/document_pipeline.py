"""文档处理管道执行模块：四模态分流入口 execute_document_pipeline 与模块级静态助手群（图片 OCR/VLM、ES 分块构建、后置收尾、embedding 生成、问题生成
等）。取消语义走 DocumentCancelledError + check_document_cancelled；配置上下文走 PipelineContext + load_pipelin
e_context；解析全文经 persist_parsed_text 入 MinIO 并立即落库。对 media_processing 的调用保持延迟导入，避免顶层循环 import。
"""

import asyncio
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
    from novamind.features.knowledge_space.services.pipeline_steps import PipelineContext

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.document.media.vlm import (
    build_vlm_image_messages,
    generate_vlm_text_with_fallback,
)
from novamind.engines.document.pipeline import DocumentProcessor
from novamind.engines.document.pipeline.config_defaults import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
)
from novamind.engines.document.pipeline.splitter_factory import extract_splitting_params
from novamind.features.knowledge_space.exceptions import (
    DocumentProcessingError,
    PermanentProcessingError,
)
from novamind.features.knowledge_space.services.media_processing import (
    is_vlm_quota_or_auth_error,
)
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    build_runtime_parsing_config,
)
from novamind.features.knowledge_space.services.document_file_types import (
    AUDIO_FILE_TYPES,
    IMAGE_FILE_TYPES,
    VIDEO_FILE_TYPES,
)
from novamind.features.knowledge_space.services.pipeline_steps import (
    TailInputs,
    begin_step,
    check_document_cancelled,
    extract_parse_metadata_summary,
    finish_step_committed,
    load_pipeline_context,
    persist_parsed_text,
    run_post_parse_tail,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from sqlalchemy.ext.asyncio import AsyncSession

# 文本文档解析策略合法值域（与 schema PdfParsingConfig/TextParsingConfig 的
# Literal 对齐；schema 校验正常拦截脏值，此处防御绕过 schema 的存量脏数据，
# 如手改 DB）。图片等非文本模态的 strategy 走各自分发，不经此函数。
_TEXT_PARSING_STRATEGIES = frozenset({"default", "deepdoc", "external_ocr"})


def resolve_text_parsing_strategy(parsing_config: dict[str, Any], document_id: int) -> str:
    """归一并校验文本文档解析策略，未知值显式拒绝（不可重试）。

    缺失/None 归一为 default；未知策略（如手改 DB 写入 "cloud_ocr"）历史上
    会静默落 default 分支按内置 reader 解析——扫描件抽出 0 字符才暴露，且
    错误信息误导用户去切 full 模式。

    Args:
        parsing_config: 运行时解析配置（build_runtime_parsing_config 产物或任务快照）。
        document_id: 文档 id，用于异常上下文。

    Returns:
        合法策略名（default / deepdoc / external_ocr）。

    Raises:
        PermanentProcessingError: 策略名不在合法值域（重试不可能成功）。
    """
    strategy = parsing_config.get("strategy")
    strategy = "default" if strategy is None else str(strategy)
    if strategy not in _TEXT_PARSING_STRATEGIES:
        raise PermanentProcessingError(
            document_id=document_id,
            error_message=(
                f"未知解析策略: {strategy}（合法值: {sorted(_TEXT_PARSING_STRATEGIES)}）。"
                "配置可能绕过了 schema 校验，请检查知识库解析配置"
            ),
        )
    return strategy


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
    filename: str,
    task: Optional["DocumentTask"] = None,
    model_config_port: ModelConfigService | None = None,
    *,
    file_content: Optional[bytes] = None,
    file_path: Optional[str] = None,
) -> None:
    """执行文档处理的核心 pipeline（独立函数，可被 arq worker 或直接调用）。

    Args:
        session: 数据库会话
        document_id: 文档 ID
        kb_id: 知识库 ID
        space_id: 空间 ID
        filename: 文件名
        task: 文档任务记录（None 时自动查找/创建）
        file_content: 文件内容（整包路径，与 file_path 二选一）
        file_path: 本地文件路径（大文件路径：worker 下载落盘后传路径，
            管道内按需 read_bytes，避免整包驻留内存；与 file_content 二选一）

    Raises:
        ValueError: file_content 与 file_path 同时给出或都缺失。
    """
    if (file_content is None) == (file_path is None):
        raise ValueError("file_content 与 file_path 必须二选一")

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

    # 大文件路径（file_path 给出）时按分支按需读取：视频分支透传路径给引擎
    # （抽帧/归一化全程用文件句柄），图像/音频分支一次性 read_bytes（后续
    # 管道本就要整包 bytes），文本分支直接复用路径（本就写临时文件）。
    image_content = file_content
    audio_content = file_content
    if file_path is not None:
        if file_ext in IMAGE_FILE_TYPES:
            image_content = await asyncio.to_thread(Path(file_path).read_bytes)
        elif file_ext in AUDIO_FILE_TYPES:
            audio_content = await asyncio.to_thread(Path(file_path).read_bytes)

    if file_ext in IMAGE_FILE_TYPES:
        await _process_image_document_static(
            document, image_content, session, _logger, task=task,
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
            file_path=file_path,
        )
        return

    # ===== 音频文档分支（新增） =====
    if file_ext in AUDIO_FILE_TYPES:
        from novamind.features.knowledge_space.services.media_processing import (
            process_audio_document,
        )

        await process_audio_document(
            document, audio_content, session, _logger, task=task,
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
    # 写盘入线程池：嵌入式 worker 与 API 共享事件循环，最大 100MB 的同步写
    # 会卡住全部并发请求（评审 P2-2）。file_path 已给出时直接复用（worker
    # 下载落盘的临时文件，消费方管线不变），不再复制一份。
    if file_path is not None:
        tmp_path = file_path
        _owns_tmp_path = False
    else:
        def _write_tmp() -> str:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_content)
                return tmp.name
        tmp_path = await asyncio.to_thread(_write_tmp)
        _owns_tmp_path = True

    # 断点续跑：解析指纹匹配即复用快照，跳过昂贵解析（VLM/OCR 可能已付费成功）。
    # fail-open：指纹不匹配/无快照/读失败一律走全量解析路径。
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        snapshots_enabled,
        build_parse_snapshot_payload,
        canonical_json,
        compute_parse_fingerprint,
        load_parse_snapshot,
        payload_fingerprint_matches,
        resolve_figure_short_paths,
        restore_frame_paths,
        restore_time_alignment,
        save_parse_snapshot,
        snapshot_fingerprint,
    )
    from novamind.shared.storage.client_factory import ClientFactory

    resume_minio_client = None
    parse_fingerprint = ""
    if snapshots_enabled():
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
    if snapshots_enabled() and parse_fingerprint and resume_minio_client is not None:
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

        # figure 链接短路径化（新快照已在首跑写入短文件名，此处对旧存量快照兜底）：
        # 按 region 的 minio_object_name 补算 image_url = basename。旧快照若存的
        # 是历史预签名 URL（无 minio_object_name 的更旧版本），map 为空按原文复用。
        image_url_map: dict[str, str] = {}
        try:
            image_url_map = resolve_figure_short_paths(
                parse_snapshot_payload, _logger,
            )
        except Exception as url_exc:
            _logger.warning(
                "figure 短路径补算失败（保留原文）", document_id=document_id, error=str(url_exc),
            )
        full_text = parse_snapshot_payload["full_text"]
        resume_chunks = [text for text, _meta in resume_prechunked]
        # 历史快照/上传失败残留的占位符剥除（不进 embedding/ES content）。
        # 旧快照正文里已替换的历史预签名 URL 不在占位符形态，无法回收——按原文
        # 复用（过期链接由重解析刷新）。
        full_text, resume_chunks = _restore_figure_links(full_text, resume_chunks, image_url_map)

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
        await finish_step_committed(session, task, "parsed", metrics={
                    "char_count": len(full_text),
                    "chunk_count": len(resume_chunks),
                    "parse_strategy": (resume_meta.get("strategy") if isinstance(resume_meta, dict) else None)
                    or "resumed",
                    "file_type": document.file_type,
                    "resumed": True,
                    **({"split_config_drifted": True} if split_config_drifted else {}),
        })
        from novamind.core.middleware import metrics as pipeline_metrics
        pipeline_metrics.inc("snapshot_parse_hits")
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
        _resume_tail_result = await run_post_parse_tail(TailInputs(
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
        ))
        parse_summary = extract_parse_metadata_summary(resume_meta if isinstance(resume_meta, dict) else {})
        # parse_duration_ms 口径 = 本次续跑尾段耗时（started_at 仍是原任务起点，
        # 快照命中的解析阶段被跳过，差额即尾段实际开销），与正常路径的全程口径不同源。
        parse_duration_ms = (
            int((now_china() - task.started_at).total_seconds() * 1000) if task.started_at else None
        )
        _resume_reading_orders = (
            resume_meta.get("reading_order") if isinstance(resume_meta, dict) else None
        )
        task.mark_completed(
            result=_build_completion_result(
                chunk_count=_resume_tail_result["chunk_count"],
                total_tokens=sum(len(c.split()) for c in resume_chunks),
                parse_strategy=(resume_meta.get("strategy") if isinstance(resume_meta, dict) else None) or "",
                splitting_config=splitting_config,
                parse_summary=parse_summary,
                reading_order_count=(
                    len(_resume_reading_orders) if _resume_reading_orders
                    else parse_summary["reading_order_count"]
                ),
                char_count=len(full_text),
                ctx=ctx,
                parse_duration_ms=parse_duration_ms,
                resumed_from_snapshot=True,
            )
        )
        await session.commit()
        _logger.info("文档处理完成（断点续跑）", document_id=document_id, chunk_count=len(resume_chunks))
        return

    # ===== 无快照命中：正常解析路径 =====
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
        vlm_description_enabled=parsing_config.get("vlm_description_enabled", False),
        splitting_strategy=splitting_config.get("strategy", "recursive"),
        splitting_chunk_size=splitting_config.get("chunk_size", 1000),
        splitting_chunk_overlap=splitting_config.get("chunk_overlap", 100),
    )
    await begin_step(session, task, "parsed")
    parsing_strategy = resolve_text_parsing_strategy(
        parsing_config, document_id=document_id
    )
    if parsing_strategy == "external_ocr":
        # 扫描件/图片型 PDF：文字层为空，外部 OCR 是唯一可用的文本来源。
        # 产物走与 default 分支相同的 splitter 链路（尊重用户切分配置），
        # 不混入 DeepDoc 的哨兵重切（那套依赖 reading_order 坐标）。
        parse_result = await _parse_pdf_with_external_ocr_static(
            document=document,
            file_content=file_content,
            file_path=file_path,
            parse_config=parsing_config,
            splitting_config=splitting_config,
            processor=processor,
            _logger=_logger,
        )
    else:
        parse_result = await processor.parse_document_result(
            tmp_path,
            parsing_config=parsing_config,
            splitting_config=splitting_config,
        )
    # 原始文件已解析完，立即释放临时文件。不把 unlink 挂 try/finally 到整个
    # 管道——此前快照命中分支提前 return 绕过 finally，每个续跑任务泄漏一个
    # tmp 文件；解析抛错时任务行会标 FAILED，OS tmp 目录由系统清理兜底。
    # file_path 模式（worker 落盘文件）由 worker 侧 finally 统一清理，
    # 此处不动——双处 unlink 无害但会掩盖归属。
    if _owns_tmp_path:
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
    await finish_step_committed(session, task, "parsed", metrics={"char_count": len(full_text), "chunk_count": len(chunks), "parse_strategy": parsing_config.get("strategy", "default"), "file_type": document.file_type})

    # 上传 PDF figure 图片到 MinIO 并把占位符替换为短文件名（figure_xxx.png）。
    # 仅 PDF full 模式会产出 figure_regions + image_blobs；上传在 persist 之前完成，
    # 保证最终落盘的完整 MD 与 ES chunk content 都已含图片短路径。
    # 短文件名不可变、无时效，快照与最终产物同版，无需再区分「占位符版」。
    figure_regions = list((parse_result.metadata or {}).get("figure_regions") or [])
    image_url_map: dict[str, str] = {}
    if figure_regions and document.file_type.lower() == "pdf":
        from novamind.shared.storage.client_factory import ClientFactory

        minio_client = await ClientFactory.get_minio_client()
        image_url_map = await _upload_figure_images_to_minio(
            document, figure_regions, _logger, minio_client=minio_client
        )
    if figure_regions or image_url_map:
        full_text, parse_result.chunks = _restore_figure_links(
            full_text, parse_result.chunks, image_url_map
        )
        chunks = parse_result.chunks
    if figure_regions:
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
    # deepdoc rechunk 后 chunk_structure 由 tagged_rechunk 重建（哨兵编码），与
    # chunks 条数一一对应，直接采用。仅当条数与 chunks 不齐（历史快照/旧路径
    # 残留的错位结构）才置空防张冠李戴——按 index 捡错位结构会拿到错误页码。
    if len(chunk_structure) != len(parse_result.chunks):
        if chunk_structure:
            _logger.info(
                "chunk_structure 条数与 chunks 不齐，置空防错位",
                document_id=document_id,
                structure_count=len(chunk_structure),
                chunk_count=len(parse_result.chunks),
            )
        chunk_structure = []
    # 关系元数据（sentence_window/parent_child 的 chunk_role/parent_slot/
    # expansion_type，由 parse_document_result 按位透出）：与 chunk_structure
    # 同一防错位逻辑，条数不齐置空。按 index 合并进 prechunked_items 的
    # per-chunk meta——切分快照原样往返，resume 不丢关系。
    structure_meta = list((parse_result.metadata or {}).get("chunk_structure_meta") or [])
    if len(structure_meta) != len(parse_result.chunks):
        if structure_meta:
            _logger.info(
                "chunk_structure_meta 条数与 chunks 不齐，置空防错位",
                document_id=document_id,
                meta_count=len(structure_meta),
                chunk_count=len(parse_result.chunks),
            )
        structure_meta = []
    prechunked_items = [
        (
            c,
            {
                **(chunk_structure[i] if i < len(chunk_structure) else {}),
                **(structure_meta[i] if i < len(structure_meta) else {}),
            },
        )
        for i, c in enumerate(parse_result.chunks)
    ]

    # 解析快照：persist 成功后保存（最终版全文 + 元数据 + 结构化分块 + 生效
    # 切分配置），供后续重试在指纹匹配时跳过昂贵解析。figure 短文件名不可变
    # 无时效，快照与最终产物同版。fail-open：保存失败不影响主流程。
    if snapshots_enabled() and parse_fingerprint and resume_minio_client is not None:
        snapshot_payload = build_parse_snapshot_payload(
            parse_fingerprint=parse_fingerprint,
            full_text=full_text,
            parse_metadata=parse_result.metadata,
            prechunked_items=prechunked_items,
            splitting_config=splitting_config or {},
        )
        await save_parse_snapshot(
            document, session, _logger,
            minio_client=resume_minio_client,
            parse_fingerprint=parse_fingerprint,
            payload=snapshot_payload,
        )

    tail_result = await run_post_parse_tail(TailInputs(
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
    ))
    parse_summary = extract_parse_metadata_summary(parse_result.metadata)

    # 5. 标记任务完成
    parse_duration_ms = (
        int((now_china() - task.started_at).total_seconds() * 1000) if task.started_at else None
    )
    task.mark_completed(
        result=_build_completion_result(
            chunk_count=tail_result["chunk_count"],
            total_tokens=sum(len(c.split()) for c in chunks),
            parse_strategy=parsing_config.get("strategy", "default"),
            splitting_config=splitting_config,
            parse_summary=parse_summary,
            reading_order_count=parse_summary["reading_order_count"],
            char_count=len(full_text),
            ctx=ctx,
            parse_duration_ms=parse_duration_ms,
        )
    )
    await session.commit()

    _logger.info(
        "文档处理完成",
        document_id=document_id,
        chunk_count=len(chunks),
    )



def _restore_figure_links(
    full_text: str, chunks: list[str], image_url_map: dict[str, str]
) -> tuple[str, list[str]]:
    """figure 占位符统一处理（正常/resume 双分支共享，批次 4）：有 map 先替换
    为短路径 URL，再无条件剥除未解析占位符（上传失败项/历史残留——审计 P1#7，
    占位符进 embedding 污染向量、检索命中原样返回给用户/LLM）。无占位符文本
    strip 为正则无匹配 no-op。"""
    if image_url_map:
        full_text = _replace_figure_placeholders(full_text, image_url_map)
        chunks = [_replace_figure_placeholders(c, image_url_map) for c in chunks]
    full_text = _replace_figure_placeholders(full_text, {}, strip_unresolved=True)
    chunks = [_replace_figure_placeholders(c, {}, strip_unresolved=True) for c in chunks]
    return full_text, chunks


def _build_completion_result(
    *,
    chunk_count: int,
    total_tokens: int,
    parse_strategy: str,
    splitting_config: dict[str, Any],
    parse_summary: dict[str, Any],
    reading_order_count: int,
    char_count: int,
    ctx: "PipelineContext",
    parse_duration_ms: int | None,
    resumed_from_snapshot: bool = False,
) -> dict[str, Any]:
    """构造 mark_completed 的 result dict（正常/resume 双分支共享，批次 4）。

    此前两分支各写一份近 30 键 dict，新增键需双处人工同步——resume 侧漏改
    无编译期报错，前端展示契约静默缺键。两分支全部差异点已参数化（策略名、
    reading_order 兜底、resumed 标记）。

    Args:
        parse_summary: extract_parse_metadata_summary 产物（parser_class 等
            字符串键与各 count 均从中取，与原两分支逐键等价）。
        reading_order_count: reading_order 键数；resume 分支带快照兜底逻辑，
            正常分支传 parse_summary 的同名值。
    """
    result: dict[str, Any] = {
        "chunk_count": chunk_count,
        "total_tokens": total_tokens,
        "parse_strategy": parse_strategy,
        "split_strategy": splitting_config.get("strategy", "recursive"),
        "chunk_size": splitting_config.get("chunk_size", DEFAULT_CHUNK_SIZE),
        "chunk_overlap": splitting_config.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
        "parser_class": parse_summary["parser_class"],
        "pdf_mode": parse_summary["pdf_mode"],
        "layout_source": parse_summary["layout_source"],
        "vision_strategy": parse_summary["vision_strategy"],
        "table_region_count": parse_summary["table_region_count"],
        "figure_region_count": parse_summary["figure_region_count"],
        "reading_order_count": reading_order_count,
        "page_count": parse_summary["page_count"],
        "outline_count": parse_summary["outline_count"],
        "section_count": parse_summary["section_count"],
        "table_count": parse_summary["table_count"],
        "image_count": parse_summary["image_count"],
        "char_count": char_count,
        "embedding_model": ctx.embedding_model_name,
        "embedding_dim": ctx.embedding_dim,
        "parse_duration_ms": parse_duration_ms,
        "indexed_at": now_china().isoformat(),
    }
    if resumed_from_snapshot:
        result["resumed_from_snapshot"] = True
    return result


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
    """上传 PDF figure 图片到 MinIO，返回 {artifact_id: figure 短文件名}。

    每个 figure region 必须有 ``image_blobs``（PNG bytes 列表），取首张
    （``_encode_crops`` 的合成图或单页图）上传。上传成功后在 region 字典
    里写入 ``minio_object_name``（完整对象路径）和 ``image_url``（短文件名，
    相对 ``{base}_figures/`` 目录）；首个成功上传同时把目录锚点
    ``figures_object_dir`` 写进 ``document.storage``，figure 代理端点据此
    把短文件名还原成完整 object name。
    """
    image_url_map: dict[str, str] = {}
    storage = document.storage or {}
    base = storage.get("minio_object_name", "")
    if not base or not figure_regions:
        return image_url_map

    from io import BytesIO

    from PIL import Image as PILImage

    figures_dir = f"{base}_figures"

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
        figure_file = f"figure_{safe_id}_{page}.png"
        object_name = f"{figures_dir}/{figure_file}"
        try:
            await minio_client.upload_file(object_name, image_bytes, "image/png")
            # image_url 存短文件名（相对文档 figure 目录），不再存预签名 URL：
            # 签名串 ~300 字符且 1 小时过期，进 MD/ES/embedding 既污染检索与
            # 向量又必然失效。原始完整路径在 minio_object_name / figures_object_dir，
            # 渲染方经 figure 代理端点拼接。上传失败剥占位符语义不变。
            region["minio_object_name"] = object_name
            region["image_url"] = figure_file
            image_url_map[artifact_id] = figure_file
            region.pop("image_blobs", None)
            # MySQL 目录锚点（幂等写入）：figure 代理端点按它把短文件名还原成
            # 完整 object name；persist_parsed_text 随后的 commit 一并落库。
            if storage.get("figures_object_dir") != figures_dir:
                document.storage = {**storage, "figures_object_dir": figures_dir}
                storage = document.storage
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
    """图片文档解析：VLM 描述或 OCR 转文本后走文本 embedding

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

    # VLM 模型名只认嵌套 image.vlm_model：扁平 result["vlm_model"] 被 image/video
    # 共写（video 后写覆盖 image），图片文档解析时 video 留空不覆盖、但 video 配了
    # 模型时图片会静默串用视频的 VLM（跨模态污染、路径不可追踪）。与视频路径 B10
    # 修复同款：媒体各模态只读自己的嵌套配置，不读共享扁平键。
    image_nested_cfg = (ctx.pipeline_config.get("parsing", {}) or {}).get("image", {}) or {}
    image_vlm_model = str(image_nested_cfg.get("vlm_model") or "")
    # 备用 VLM 与配额失败跳过（批次2 配置对齐：与视频路径同名参数同语义）。
    # fallback：主模型配额/鉴权失败换备用重试一次；skip_on_quota：主备均失败时
    # 写占位描述继续（文档不失败）。默认关闭=fail fast 可修复配置后重试。
    image_vlm_fallback_model = str(image_nested_cfg.get("vlm_fallback_model") or "") or None
    image_vlm_skip_on_quota = bool(image_nested_cfg.get("vlm_skip_on_quota_error", False))

    # 检查点 0：配置读取后
    await check_document_cancelled(document.id)

    # ===== 断点续跑：解析快照命中即复用描述文本，跳过 VLM/OCR 昂贵调用 =====
    # fail-open：指纹不匹配/无快照/读失败一律走全量解析路径。此前图片路径只写
    # 快照、从不做命中检查（「只写不读」），RETRY 永远重跑 VLM/OCR——与文本分支
    # 同型的 P1#2 缺口。命中判定（重算指纹 → DB 指针 → payload 内嵌指纹三重校验）
    # 与 execute_document_pipeline 文本分支完全同构。
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        snapshots_enabled as _snap_enabled,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        build_parse_snapshot_payload as _build_snap_payload,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        compute_parse_fingerprint as _compute_parse_fp,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        load_parse_snapshot as _load_parse_snap,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        payload_fingerprint_matches as _fp_matches,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        save_parse_snapshot as _save_parse_snap,
    )
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        snapshot_fingerprint as _snapshot_fp,
    )
    from novamind.shared.storage.client_factory import ClientFactory as _SnapCF

    # 图片解析指纹（VLM/OCR 描述昂贵，重试时指纹匹配即免重跑）。指纹入参注入
    # 策略名+主 VLM 模型+备用 VLM 模型（全部读嵌套 image.*，与消费侧同源——
    # 扁平 vlm_model 被 video 覆盖后会把指纹也带偏），命中检查与保存侧共用同一次
    # 计算（单一事实源），指纹形状漂移在结构上不可能发生。skip_on_quota 只影响
    # 失败时的降级行为不影响成功产物，不进指纹。
    image_parse_fp = ""
    snap_minio = None
    if _snap_enabled:
        try:
            snap_minio = await _SnapCF.get_minio_client()
            image_fp_cfg = dict(parsing_config)
            image_fp_cfg["strategy"] = (
                f"image:{image_strategy}:{image_vlm_model}:{image_vlm_fallback_model or ''}"
                f":{image_nested_cfg.get('ocr_task') or ''}"
            )
            image_parse_fp = _compute_parse_fp(document, image_fp_cfg)
        except Exception as fp_exc:
            _logger.warning("图片解析指纹计算失败，不启用快照", document_id=document.id, error=str(fp_exc))

    resumed_description = ""
    if image_parse_fp and snap_minio is not None and _snapshot_fp(document, "parse") == image_parse_fp:
        snap = await _load_parse_snap(document, snap_minio, _logger)
        # payload 内嵌指纹校验：防双 worker 交错写同名对象后指针/内容错配（与文本分支一致）
        if snap and _fp_matches(snap, "parse_fingerprint", image_parse_fp):
            snap_text = str(snap.get("full_text") or "")
            if snap_text.strip():
                resumed_description = snap_text
                _logger.info(
                    "图片解析快照命中，复用描述文本（跳过 VLM/OCR）",
                    document_id=document.id,
                    description_length=len(resumed_description),
                )

    # 图片「解析」阶段 = VLM/OCR 提取描述文本（等价文本管道的 parsed）。
    # 此前图片路径全程不写 step_progress，导致任务列表流程日志显示「-」。
    await begin_step(session, task, "parsed")

    # 2. 根据策略选择文本提取方式（快照命中即复用，跳过 VLM/OCR 调用）
    description_text = resumed_description
    resumed = bool(resumed_description)

    if resumed:
        pass  # 快照命中：描述文本已复用，跳过 VLM/OCR 调用
    elif image_strategy == "deepdoc_ocr":
        description_text = await _process_image_ocr_static(
            document=document,
            file_content=file_content,
            session=session,
            _logger=_logger,
        )
    elif image_strategy == "external_ocr":
        description_text = await _process_image_ocr_external_static(
            document=document,
            file_content=file_content,
            session=session,
            _logger=_logger,
            ocr_task=image_nested_cfg.get("ocr_task"),
        )
    elif image_strategy == "combined":
        # OCR + VLM caption 合并：逐字层（图中文字/实体）双通道交叉、语义层来自
        # caption，重叠以 OCR 全文为准去重。VLM 失败时降级纯 OCR（失败方向安全：
        # 能力缺失而非错误结果），OCR 也失败才让文档失败。
        description_text = await _process_image_combined_static(
            document=document,
            file_content=file_content,
            session=session,
            _logger=_logger,
            model_config_port=model_config_port,
            vlm_model_name=image_vlm_model,
            vlm_fallback_model=image_vlm_fallback_model,
            task=task,
        )
        if not description_text:
            raise PermanentProcessingError(
                document_id=document.id,
                error_message="combined 策略下 OCR 与 VLM 均未产出文本",
            )
    else:
        # VLM 路径（默认）。vlm_model 必须由用户在解析配置中显式选择；
        # 不做"留空回退用户默认 VLM"的兜底——兜底会让解析路径不可追踪
        # （无法从配置看出实际用了哪个模型）。留空即显式抛错。
        vlm_model_name = image_vlm_model

        if not vlm_model_name:
            raise PermanentProcessingError(
                document_id=document.id,
                error_message="图片文档处理需要 VLM（视觉语言模型）来生成描述文本，请在知识库解析配置中启用 VLM 描述并选择模型",
            )

        # 批次 5b：用注入的 ModelConfigService，不再内部自建 ModelConfigService
        mcs = model_config_port
        try:
            description_text = await _generate_image_description(
                file_content=file_content,
                document=document,
                mcs=mcs,
                _logger=_logger,
                vlm_model_name=vlm_model_name,
                vlm_fallback_model=image_vlm_fallback_model,
            )
        except Exception as vlm_exc:
            # 主备均失败且用户开启跳过：写占位描述继续（文档不失败）。占位文本
            # 进索引但内容自述无信息量——失败方向安全（用户显式选择了降级），
            # 任务 metrics 记录供 kb-ops 质量基线统计。未开启则原样上抛 fail fast。
            if not image_vlm_skip_on_quota or not is_vlm_quota_or_auth_error(vlm_exc):
                raise
            _logger.warning(
                "图片VLM主备模型均配额/鉴权失败，按配置写占位描述继续",
                error=str(vlm_exc),
                document_id=document.id,
            )
            description_text = (
                "【主体描述】图片描述生成失败（VLM 配额/鉴权错误），当前为占位内容，"
                "请重试解析以获取真实描述。\n【图中文字】无\n【图表数据】无\n"
                "【实体】无\n【视觉特征】无\n【场景类型】照片"
            )

        if not description_text:
            raise PermanentProcessingError(
                document_id=document.id,
                error_message=f"VLM 模型 {vlm_model_name} 未能生成图片描述文本",
            )

    # 3. 图片文本持久化到 MinIO（立刻 commit 落库）
    await persist_parsed_text(document, description_text, session, _logger)
    if task:
        await finish_step_committed(session, task, "parsed", metrics={
                    "image_strategy": image_strategy,
                    "description_length": len(description_text),
                })

    # 断点续跑：快照未命中（全量解析完成）时保存解析快照。命中侧与保存侧共用
    # 上方同一 image_parse_fp/snap_minio（单一事实源），形状漂移不可能发生。
    if image_parse_fp and not resumed and snap_minio is not None:
        try:
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
    tail_result = await run_post_parse_tail(TailInputs(
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
    ))

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


# combined 策略下并入 caption 的 OCR 文本上限（字符）。OCR 全文超过该值时截尾
# 并入——图片内文字量超过 3000 字符属极端场景（整页文档照片），保护性截断防止
# caption+OCR 合并文本爆掉切分与 embedding。
_COMBINED_OCR_MAX_CHARS = 3000


async def _process_image_ocr_external_static(
    document: Document,
    file_content: bytes,
    session,
    _logger,
    ocr_task: str | None = None,
) -> str:
    """使用外部 OCR 服务（配置中心 ocr 段，如 qwen3.5-ocr）提取文字。

    统一经 OcrConnector：PDF 走 document_parsing 整本直传（版面结构经
    render_markdown 转入库文本），图片走 multi_lan 单图识别。异常映射与
    ASR 路径同风格——配置错/文件损坏为永久性，服务瞬时失败为可重试。
    """
    from novamind.engines.document.media.ocr import (
        OcrConnector,
        OcrCredentialsMissingError,
        OcrFileInvalidError,
        OcrRequestError,
    )
    from novamind.features.knowledge_space.services.media_processing import (
        build_engine_ocr_config,
    )

    file_type = (document.file_type or "png").lower()
    _logger.info(
        "外部 OCR 图片解析开始",
        document_id=document.id,
        file_type=file_type,
        ocr_task=ocr_task or "auto",
    )

    connector = OcrConnector(build_engine_ocr_config())
    try:
        result = await connector.recognize(
            file_content=file_content, file_type=file_type, ocr_task=ocr_task
        )
    except (OcrCredentialsMissingError, OcrFileInvalidError) as exc:
        raise PermanentProcessingError(
            document_id=document.id,
            error_message=f"外部 OCR 配置或文件错误：{exc}",
        ) from exc
    except OcrRequestError as exc:
        raise DocumentProcessingError(
            document_id=document.id,
            error_message=f"外部 OCR 服务调用失败（可重试）：{exc}",
        ) from exc

    text = result.render_markdown().strip()
    _logger.info(
        "外部 OCR 图片解析完成",
        document_id=document.id,
        protocol=result.protocol,
        page_count=result.page_count,
        char_count=len(text),
    )
    return text


async def _parse_pdf_with_external_ocr_static(
    document: Document,
    file_content: bytes | None,
    file_path: str | None,
    parse_config: dict[str, Any],
    splitting_config: dict[str, Any],
    processor,
    _logger,
):
    """PDF strategy=external_ocr：整本对外部 OCR 识别后按用户切分配置分块。

    与图片分支的区别在于产物必须与文本分支同构——后续 figure/快照/切分
    快照/后置尾复用同一条链路，因此这里产出 DeepDocParseResult 而非裸文本。
    file_path 由调用方透传：大文件（worker 落盘）直接读盘，避免整包驻留内存。
    """
    from novamind.engines.document.integrations.deepdoc.core.models import DeepDocParseResult
    from novamind.engines.document.media.ocr import (
        OcrConnector,
        OcrCredentialsMissingError,
        OcrFileInvalidError,
        OcrRequestError,
    )
    from novamind.features.knowledge_space.services.media_processing import (
        build_engine_ocr_config,
    )

    ocr_task = parse_config.get("pdf_ocr_task")
    _logger.info(
        "外部 OCR PDF 解析开始",
        document_id=document.id,
        file_type=document.file_type,
        ocr_task=ocr_task or "document_parsing",
    )

    if file_path is not None:
        content = await asyncio.to_thread(Path(file_path).read_bytes)
    else:
        content = file_content or b""

    connector = OcrConnector(build_engine_ocr_config())
    try:
        ocr_result = await connector.recognize(
            file_content=content,
            file_type=(document.file_type or "pdf").lower(),
            ocr_task=ocr_task,
        )
    except (OcrCredentialsMissingError, OcrFileInvalidError) as exc:
        raise PermanentProcessingError(
            document_id=document.id,
            error_message=f"外部 OCR 配置或文件错误：{exc}",
        ) from exc
    except OcrRequestError as exc:
        raise DocumentProcessingError(
            document_id=document.id,
            error_message=f"外部 OCR 服务调用失败（可重试）：{exc}",
        ) from exc

    full_text = ocr_result.render_markdown().strip()
    split_items = await processor.split_text_items(
        full_text,
        strategy=str(splitting_config.get("strategy", "recursive")),
        **extract_splitting_params(splitting_config),
    )
    chunks = [t for t, _meta in split_items]
    chunk_structure_meta = [m for _t, m in split_items]
    metadata: dict[str, Any] = {
        "parser": "external_ocr",
        "file_type": (document.file_type or "pdf").lower(),
        "split_strategy": str(splitting_config.get("strategy", "recursive")),
        "ocr_protocol": ocr_result.protocol,
        "ocr_page_count": ocr_result.page_count,
    }
    # 关系元数据仅在非空时写键，与 parse_document_result 的默认分支同约定
    if any(chunk_structure_meta):
        metadata["chunk_structure_meta"] = chunk_structure_meta
    _logger.info(
        "外部 OCR PDF 解析完成",
        document_id=document.id,
        protocol=ocr_result.protocol,
        page_count=ocr_result.page_count,
        char_count=len(full_text),
        chunk_count=len(chunks),
    )
    return DeepDocParseResult(full_text=full_text, chunks=chunks, metadata=metadata)


async def _process_image_combined_static(
    document: Document,
    file_content: bytes,
    session,
    _logger,
    model_config_port,
    vlm_model_name: str | None = None,
    vlm_fallback_model: str | None = None,
    task=None,
) -> str:
    """combined 策略：DeepDoc OCR + VLM 结构化 caption 合并入库。

    组合逻辑：
    - VLM caption 成功：merged = 结构化 caption + OCR 补充段（caption 中
      【图中文字】已逐字转录的常规场景下 OCR 补充多为空——按重叠词去重）。
      caption 的【实体】【图表数据】中数字/型号在 OCR 全文完全无踪 → 幻觉
      信号写日志与任务 metrics（warning-only，不改写入库文本）。
    - VLM 失败（含配额类全部失败）：降级纯 OCR 继续（能力缺失方向安全）。
    - OCR 失败：不阻塞——caption 单独可用（与 vlm 策略等价）。
    - 双双失败：返回空串，由调用方抛错。

    Returns:
        合并后的入库文本；双失败返回空串。
    """
    # 1. OCR 先行（本地推理、无配额；失败不阻塞 caption 通道）
    ocr_text = ""
    try:
        ocr_text = await _process_image_ocr_static(
            document=document,
            file_content=file_content,
            session=session,
            _logger=_logger,
        )
    except Exception as ocr_exc:
        _logger.warning(
            "combined 策略 OCR 失败，降级纯 VLM caption",
            document_id=document.id,
            error=str(ocr_exc),
        )

    # 2. VLM caption（与 vlm 策略同一生成函数，fallback/空描述语义一致）
    caption_text = ""
    try:
        if not vlm_model_name:
            raise ValueError("combined 策略需要 VLM 模型，请在解析配置中选择")
        caption_text = await _generate_image_description(
            file_content=file_content,
            document=document,
            mcs=model_config_port,
            _logger=_logger,
            vlm_model_name=vlm_model_name,
            vlm_fallback_model=vlm_fallback_model,
        )
    except Exception as vlm_exc:
        _logger.warning(
            "combined 策略 VLM caption 失败，降级纯 OCR",
            document_id=document.id,
            error=str(vlm_exc),
        )
        if task is not None and hasattr(task, "metrics") and isinstance(task.metrics, dict):
            task.metrics["image_combined_vlm_failed"] = True

    # 3. 双失败：空串交由调用方抛错
    if not caption_text and not ocr_text:
        return ""

    # 4. 单通道成功：直接用（失败方向安全——有一路真实产物就不丢文档）
    if not caption_text:
        return ocr_text
    if not ocr_text:
        return caption_text

    # 5. 双通道成功：caption + OCR 补充（重叠去重）+ 幻觉交叉校验
    caption_body = _extract_caption_text_portion(caption_text)
    merged_parts = [caption_text]
    if not _text_subsumed(caption_body, ocr_text):
        merged_parts.append("【OCR 补充】" + ocr_text[:_COMBINED_OCR_MAX_CHARS])

    hallucination_signals = _check_caption_hallucination(caption_text, ocr_text)
    if hallucination_signals:
        _logger.warning(
            "图片 caption 与 OCR 交叉校验发现幻觉信号（warning-only，不改写入库文本）",
            document_id=document.id,
            signals=hallucination_signals,
        )
        if task is not None and hasattr(task, "metrics") and isinstance(task.metrics, dict):
            task.metrics["image_caption_hallucination_signals"] = hallucination_signals
    return "\n".join(merged_parts)


def _extract_caption_text_portion(caption_text: str) -> str:
    """取 caption 的【图中文字】段体（与 OCR 全文做重叠判定的基准）。无该段返回全文。"""
    for name, body in _split_image_caption_sections(caption_text):
        if name == "【图中文字】":
            return body
    return caption_text


def _text_subsumed(caption_portion: str, ocr_text: str, min_overlap_ratio: float = 0.6) -> bool:
    """OCR 全文是否已被 caption 基本覆盖（重叠词比例判定）。

    对 OCR 全文按长度 ≥2 的片段抽样（中文 4 字滑窗 + 英数 token），统计出现在
    caption 中的比例；≥ min_overlap_ratio 视为 caption 已转录了 OCR 内容，
    不再并入【OCR 补充】（防同内容双份入库稀释 embedding）。纯标点/空白
    OCR 结果视为已覆盖（无可补充内容）。

    Args:
        caption_portion: caption 的【图中文字】段体（比对基准）。
        ocr_text: OCR 全文。
        min_overlap_ratio: 覆盖率阈值，默认 0.6。

    Returns:
        True = caption 已基本覆盖 OCR 内容，无需并入补充段。
    """
    import re as _re

    cleaned_ocr = ocr_text.strip()
    if not cleaned_ocr:
        return True
    # 归一：去空白后比对（OCR 常见多余空格/换行）
    caption_norm = _re.sub(r"\s+", "", caption_portion)
    ocr_norm = _re.sub(r"\s+", "", cleaned_ocr)
    if not ocr_norm:
        return True

    # 中文字符滑窗（4 字）+ 英数连续段（≥2 字符）
    tokens = _re.findall(r"[一-鿿]{4}|[A-Za-z0-9]{2,}", ocr_norm)
    if not tokens:
        # 短 OCR（不足一个 4 字窗也无英数 token）：整串包含判定
        return ocr_norm in caption_norm
    hits = sum(1 for t in tokens if t in caption_norm)
    return hits / len(tokens) >= min_overlap_ratio


def _check_caption_hallucination(caption_text: str, ocr_text: str) -> list[str]:
    """caption↔OCR 交叉校验：caption 逐字段中的实体/数字在 OCR 全文无踪 → 幻觉信号。

    只校验「OCR 全文非空且 caption 声称图中文字丰富」的场景——OCR 为空时无
    反证基准（可能是图片真无文字，也可能 OCR 漏检），不产信号（失败方向安全：
    宁漏报不误报）。返回信号列表（human-readable），空列表=无信号。
    """
    import re as _re

    if not ocr_text.strip():
        return []

    ocr_norm = _re.sub(r"\s+", "", ocr_text)
    sections = dict(_split_image_caption_sections(caption_text))
    entities = sections.get("【实体】", "")
    # 「无」/空段不是声称，跳过
    if not entities or entities.strip() in ("无", ""):
        return []

    # 实体段按顿号/逗号拆项，逐项在 OCR 全文中找踪迹（子串归一匹配）
    items = [x.strip() for x in _re.split(r"[、，,;；]", entities) if x.strip() and x.strip() != "无"]
    missing = [
        item for item in items
        if len(_re.sub(r"\s+", "", item)) >= 2 and _re.sub(r"\s+", "", item) not in ocr_norm
    ]
    if not missing:
        return []
    # OCR 全文很短时反证力弱（漏检概率高），只报显著缺失（≥3 项缺失才产信号）
    if len(items) >= 3 and len(missing) < 3:
        return []
    return [f"caption 实体 {len(missing)}/{len(items)} 项在 OCR 全文无踪: {'、'.join(missing[:5])}"]








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





# 结构化 caption 的分段标题（与 image_description 模板严格对应）。
# 逐字层段落（图中文字/实体/图表数据）是 BM25 精确命中的来源，截断时必须保留。
_IMAGE_CAPTION_LITERAL_SECTIONS = ("【图中文字】", "【实体】", "【图表数据】")
_IMAGE_CAPTION_SECTIONS = ("【主体描述】",) + _IMAGE_CAPTION_LITERAL_SECTIONS + (
    "【视觉特征】", "【场景类型】",
)


def _truncate_image_description(text: str, _logger) -> str:
    """结构化 caption 的保护性截断（分段感知，非硬切尾）。

    超限时先砍最长的可牺牲段（主体描述/视觉特征——语义层信息在向量检索里
    有容错），保逐字层段落（图中文字/实体/图表数据——BM25 精确命中的唯一
    来源，砍掉即该图的型号/数字永远检索不到）。全部段都在限内时原样返回。

    Args:
        text: VLM 输出的结构化 caption。
        _logger: 日志器。

    Returns:
        截断后的文本；无分段结构时退化为尾部硬切（旧格式兼容）。
    """
    max_chars = _image_caption_max_chars()
    if len(text) <= max_chars:
        return text

    sections = _split_image_caption_sections(text)
    # 无分段结构（旧模板产物/模型不守格式）：退化为尾部硬切，不报错
    if len(sections) <= 1:
        _logger.warning(
            "图片描述超限且无分段结构，退化尾部硬切",
            original_len=len(text),
            max_chars=max_chars,
        )
        return text[:max_chars]

    # 保护性裁剪：逐字层不可动；非逐字段从最长者开始整段丢弃（整段丢弃保持
    # 段落结构完整——半段比缺段更伤害检索与阅读）
    dropped: list[str] = []
    flexible = [
        name for name, _body in sections if name not in _IMAGE_CAPTION_LITERAL_SECTIONS
    ]
    kept = dict(sections)
    while sum(len(v) for v in kept.values()) > max_chars and flexible:
        longest = max(flexible, key=lambda n: len(kept[n]))
        dropped.append(longest)
        del kept[longest]
        flexible.remove(longest)

    result = "".join(f"{name}{body}" for name, body in kept.items())
    if dropped:
        _logger.warning(
            "图片描述超限触发保护性截断（丢弃非逐字段）",
            dropped_sections=dropped,
            original_len=len(text),
            truncated_len=len(result),
            max_chars=max_chars,
        )
    # 全部可牺牲段丢光仍超限（逐字段自身巨大）：按段序保前 N 段，尾部硬切兜底
    if len(result) > max_chars:
        result = result[:max_chars]
    return result


def _split_image_caption_sections(text: str) -> list[tuple[str, str]]:
    """把结构化 caption 按【段名】切成 (段名, 段体) 列表（保序）。

    无任何已知段名时返回空列表（调用方退化尾部硬切）。同段名二次出现时，
    其段体并入**前一个保留段**尾部（就近归属，语义与首段一致）。
    """
    positions: list[tuple[int, str]] = []
    for name in _IMAGE_CAPTION_SECTIONS:
        idx = 0
        while True:
            idx = text.find(name, idx)
            if idx < 0:
                break
            positions.append((idx, name))
            idx += len(name)
    if not positions:
        return []
    positions.sort()
    # 同段名只保留首次位置；二次出现位置不作为切段边界（其文本归前一段）
    seen: set[str] = set()
    boundaries: list[tuple[int, str]] = []
    for pos, name in positions:
        if name not in seen:
            seen.add(name)
            boundaries.append((pos, name))
    if not boundaries:
        return []
    sections: list[tuple[str, str]] = []
    for i, (pos, name) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        body = text[pos + len(name):end]
        sections.append((name, body))
    return sections


def _image_caption_max_chars() -> int:
    """图片描述入库文本上限（字符）。YAML knowledge_base.parsing 配置，默认 4000。

    结构化 caption（含图中文字逐字转录）比旧自由文本长，2000 硬顶会把
    【实体】【图表数据】整段切掉。上限是宿主资源旋钮（embedding token 限制
    /索引体积），生产可按 embedding 模型上下文调整。
    """
    from novamind.setting.yaml_config.loader import get_config

    parsing_cfg = getattr(getattr(get_config(), "knowledge_base", None), "parsing", None)
    configured = getattr(parsing_cfg, "image_caption_max_chars", None) if parsing_cfg else None
    if configured and int(configured) > 0:
        return int(configured)
    return 4000


async def _generate_image_description(
    file_content: bytes,
    document: Document,
    mcs,  # ModelConfigService
    _logger,
    vlm_model_name: str | None = None,
    vlm_fallback_model: str | None = None,
) -> str:
    """调用 VLM 生成图片描述文本（结构化 caption，保护性截断，配额失败回退备用模型）

    Args:
        file_content: 图片二进制内容
        document: 文档对象
        mcs: ModelConfigService 实例
        _logger: 日志器
        vlm_model_name: VLM 主模型名（调用方保证非空，不兜底）
        vlm_fallback_model: 备用 VLM 模型名；主模型因配额/鉴权类错误失败时
            换该模型重试一次（与视频路径同名参数语义一致）。空/未配置不回退。

    Returns:
        结构化描述文本（经 _truncate_image_description 保护性截断）

    Raises:
        ValueError: VLM 未配置或返回空描述。
        Exception: 主/备模型均失败（调用方按 vlm_skip_on_quota_error 决定占位或抛错）。
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

    # 2. 获取结构化 caption prompt（固定分段：主体/文字/图表/实体/视觉/场景类型）
    description_prompt = PromptManager.get_template("image_description")

    # 3. 构建多模态消息（OpenAI 兼容格式）
    messages = build_vlm_image_messages(
        file_bytes=file_content,
        mime_type=mime_type,
        text_prompt=description_prompt,
    )

    # 4. 调用 VLM 生成描述。max_tokens 上限给足结构化分段空间
    #    （主体+逐字文字转录+图表数据+实体，密集表格图可到 2-3k tokens）
    log_ctx = {
        "document_id": document.id,
        "file_type": document.file_type,
    }
    try:
        description = await generate_vlm_text_with_fallback(
            vlm_client=vlm_client,
            messages=messages,
            max_tokens=3072,
            temperature=0.3,
            logger=_logger,
            vlm_model=vlm_model_name,
            log_context=log_ctx,
        )
    except Exception as exc:
        # 主模型配额/鉴权类失败且配置了备用模型：惰性取备用 client 重试一次
        # （与视频 describe_single 的 fallback 语义一致；非配额错误不触碰备用
        # 模型凭证）。其它错误原样上抛。
        if not (is_vlm_quota_or_auth_error(exc) and vlm_fallback_model):
            raise
        _logger.warning(
            "图片VLM主模型配额/鉴权失败，回退备用模型重试",
            fallback_model=vlm_fallback_model,
            error=str(exc),
            **log_ctx,
        )
        vlm_fallback_client = await mcs.get_vlm_client_by_model(
            document.uploader_id, vlm_fallback_model
        )
        description = await generate_vlm_text_with_fallback(
            vlm_client=vlm_fallback_client,
            messages=messages,
            max_tokens=3072,
            temperature=0.3,
            logger=_logger,
            vlm_model=vlm_fallback_model or "",
            log_context=log_ctx,
        )

    if not description or not description.strip():
        raise ValueError(f"VLM 返回空描述，模型: {vlm_model_name}")

    # 5. 保护性截断（分段感知，非硬切）
    return _truncate_image_description(description.strip(), _logger)


