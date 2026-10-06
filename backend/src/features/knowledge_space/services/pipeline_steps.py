"""知识库解析管道步骤定义：解析→切分→嵌入→入库的步骤编排与快照记录。"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.engines.document.media.audio import upload_parsed_text_to_minio
from novamind.features.knowledge_space.exceptions import (
    DocumentProcessingError,
    EmbeddingError,
    PermanentProcessingError,
)
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.schemas.enums import ChunkType
from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
    DEFAULT_EMBEDDING_BATCH_SIZE,
)
from novamind.features.user.services.model_config_service import ModelConfigService
from novamind.shared.ai_models.embedding import OpenAICompatibleEmbedding as EmbeddingClient
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.shared.utils.time_utils import now_china
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from novamind.features.knowledge_space.models.document_task import DocumentTask


class DocumentCancelledError(Exception):
    """文档处理被用户取消"""


async def begin_step(session: AsyncSession, task: DocumentTask | None, name: str) -> None:
    """记录节点开始并立即落库。

    `task.start_step` 只改内存对象的 step_progress；若不在节点开始时立即 commit，
    一旦该节点执行中崩溃，内存里的 `{name: running}` 会随异常丢失，`_ensure_mark_failed`
    用独立 session 重载 task 时 step_progress 仍为 null，`mark_last_running_step_failed`
    找不到 running 节点 → 前端节点日志空白。每个 start_step 后立即 commit 保证 running 节点落库。
    """
    if task is None:
        return
    task.start_step(name)
    await session.commit()


async def finish_step_committed(
    session: AsyncSession, task: DocumentTask | None, name: str, metrics: dict | None = None
) -> None:
    """记录节点完成并立即落库（与 begin_step 对偶）。

    finish_step 原本依赖下一个 begin_step 或 mark_completed 搭车 commit——崩溃
    间隙里「已完成」的节点在 DB 仍是 running，孤儿恢复后 mark_last_running_step_failed
    会把实际已完成的步骤标 failed（如帧已上传 MinIO 但节点显示「帧提取失败」），
    前端节点日志失真（审计 P2 finish_step 搭车落库）。
    """
    if task is None:
        return
    task.finish_step(name, metrics=metrics)
    await session.commit()



async def check_document_cancelled(document_id: int) -> None:
    """
    检查文档是否被取消，是则抛出 DocumentCancelledError

    在 pipeline 关键节点调用，实现提前终止。
    """
    from novamind.features.knowledge_space.services.document_task_tracking import (
        is_document_cancelled,
    )


    if await is_document_cancelled(document_id):
        raise DocumentCancelledError(f"文档 {document_id} 处理已被用户取消")


@dataclass
class PipelineContext:
    """管道配置上下文，统一承载四个模态分支共用的配置读取结果。

    将 space / kb / pipeline_config / embedding_config 的读取集中到
    load_pipeline_context，避免「Task 快照优先」与「embedding_config 来源」
    规则在各分支各写一遍而漂移。
    """

    space: KnowledgeSpace | None
    kb: KnowledgeBase | None
    pipeline_config: dict[str, Any]
    embedding_config: dict[str, Any]

    @property
    def space_owner_id(self) -> int | None:
        """空间创建者 ID（空间缺失时为 None）。"""
        return self.space.owner_id if self.space else None

    @property
    def embedding_model_name(self) -> str | None:
        """空间绑定的 embedding 模型名（未配置为 None）。"""
        return self.embedding_config.get("model") if self.embedding_config else None

    @property
    def embedding_dim(self) -> int | None:
        """空间 embedding 向量维度（未配置为 None）。"""
        return self.embedding_config.get("dimension") if self.embedding_config else None


async def load_pipeline_context(
    session: AsyncSession,
    document: Document,
    task: DocumentTask | None = None,
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


def extract_parse_metadata_summary(parse_metadata: dict[str, Any]) -> dict[str, Any]:
    """从解析元数据提取轻量摘要（解析器类/模式/区域与文档结构计数），供任务进度展示。

    结构计数按解析器实际产出探测式提取：键缺失（该文件类型不产此元数据）
    返回 None，不误报 0；空列表同样视为「无此结构」返回 None。

    Args:
        parse_metadata: 解析阶段产出的元数据字典。

    Returns:
        含 parser_class/pdf_mode、表格/插图/阅读序区域计数，以及
        page_count/outline_count（PDF）与 section_count/table_count/image_count（DOCX）
        的字典，结构计数键可能为 None。
    """
    table_regions = list(parse_metadata.get("table_regions") or [])
    figure_regions = list(parse_metadata.get("figure_regions") or [])
    reading_order = list(parse_metadata.get("reading_order") or [])

    def _list_count(key: str) -> int | None:
        value = parse_metadata.get(key)
        return len(value) if isinstance(value, list) and value else None

    pages = parse_metadata.get("pages")
    images = parse_metadata.get("images")
    return {
        "parser_class": parse_metadata.get("parser_class", ""),
        "pdf_mode": parse_metadata.get("pdf_mode", ""),
        "layout_source": parse_metadata.get("layout_source", ""),
        "vision_strategy": parse_metadata.get("vision_strategy", ""),
        "table_region_count": len(table_regions),
        "figure_region_count": len(figure_regions),
        "reading_order_count": len(reading_order),
        "page_count": int(pages) if pages else None,
        "outline_count": _list_count("outlines"),
        "section_count": _list_count("sections"),
        "table_count": _list_count("tables"),
        "image_count": int(images) if images is not None else None,
    }


def build_es_chunks(
    document: Document,
    chunk_items: list[tuple[str, dict[str, Any]]],
    chunk_type: ChunkType,
    *,
    parse_metadata: dict[str, Any] | None = None,
    frame_paths: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """统一构造 ES 索引格式的分块字典列表（文本/音频/视频共用）。

    - 文本：富 metadata（parser/parse_summary/chunk_structure 的 entry_kinds/pages/...），仅 media_url。
    - 音频/视频：metadata 含 start_time/end_time，视频按 frame_indices 映射 frame_paths；media_url + image_url。
    - ``frame_paths`` 为 ``{frame_idx: minio_path}``，按 frame_idx 精确取帧，免疫抽帧空洞（见 media_processing.py 上传处说明）。

    `chunk_items` 为 [(text, per_chunk_meta), ...]；文本 per_chunk_meta 取自 parse_metadata["chunk_structure"][i]。
    """
    es_chunks = []
    storage_info = document.storage or {}
    parse_metadata = dict(parse_metadata or {})
    is_text = chunk_type == ChunkType.TEXT
    parse_summary = extract_parse_metadata_summary(parse_metadata) if is_text else {}
    media_url = storage_info.get("minio_object_name", "")

    # 两遍式 pass 0：父子槽位 → 最终列表位置预解析。parent_chunk_id 的绝对序号
    # 由下方主循环的 enumerate 生成，切分器只见相对槽位（parent_slot），故先扫
    # 一遍建「slot → 列表位置」映射，pass 1 据此写绝对指针。预扫描只读新策略
    # 的 meta 键，存量 chunk_items 无键 → 恒空映射、零开销。
    slot_to_position: dict[int, int] = {}
    # hierarchical 章节锚点解析：锚点块（content_type=text 且带 section_slot 且
    # 是该 slot 首个出现的块）→ 绝对 chunk_id。锚点即章节首个块，与 parent_slot
    # 不同的是它本身参与召回，指针只服务检索期「拉取关联特殊对象」方向。
    slot_to_anchor_position: dict[int, int] = {}
    if is_text:
        for pos, (_text, meta) in enumerate(chunk_items):
            if meta.get("chunk_role") == "parent" and isinstance(meta.get("parent_slot"), int):
                slot_to_position[meta["parent_slot"]] = pos
            if (
                meta.get("expansion_type") == "hierarchical"
                and meta.get("content_type") == "text"
                and isinstance(meta.get("section_slot"), int)
                and meta["section_slot"] not in slot_to_anchor_position
            ):
                slot_to_anchor_position[meta["section_slot"]] = pos

    for i, (text, meta) in enumerate(chunk_items):
        chunk_meta: dict[str, Any] = {"content_hash": document.file_hash}
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
            # QA 引用溯源主键：代表页 = chunk 首页（chunk_pages 升序首元素）。
            # ES mapping 已声明 metadata.page_number（integer），历史写入端从未
            # 落值导致 QA sources page 恒 None——此处补齐。无页码 chunk（老路径）
            # 不写，保持 None 语义。
            chunk_pages = list(meta.get("pages") or [])
            if chunk_pages:
                chunk_meta["page_number"] = int(chunk_pages[0])
            # 文档级 PDF figure 图片链接：每个文本 chunk 的 metadata 都保存该文档全部图片，
            # 便于检索时向 LLM/前端提供完整图文上下文，不局限于当前 chunk 包含的 figure。
            # image_url 为相对文档 figure 目录的短文件名（figure_xxx.png），渲染方经
            # figure 代理端点（/documents/{id}/figures/{file}）拼接完整 URL。
            figure_regions = list(parse_metadata.get("figure_regions") or [])
            if figure_regions:
                all_figure_links: list[dict[str, Any]] = [
                    {
                        "artifact_id": r["artifact_id"],
                        "minio_object_name": r.get("minio_object_name"),
                        "image_url": r.get("image_url"),
                        "page": r.get("page_start"),
                        "caption": r.get("caption", ""),
                    }
                    for r in figure_regions
                    if r.get("artifact_id")
                ]
                if all_figure_links:
                    chunk_meta["figure_image_links"] = all_figure_links
                    chunk_meta["figure_image_count"] = len(all_figure_links)
        else:
            # start_time/end_time 仅音视频分段有意义；图片无时间维度，不带
            if chunk_type != ChunkType.IMAGE:
                chunk_meta["start_time"] = meta.get("start_time")
                chunk_meta["end_time"] = meta.get("end_time")
            # ASR 质量元数据（批次②④，聚合在 1.4 步完成）：置信度 0~1 +
            # 说话人标签串（如 "0,1"）。无数据不写键，保持 None 语义。
            if meta.get("confidence") is not None:
                chunk_meta["confidence"] = float(meta["confidence"])
            if meta.get("speaker_id"):
                chunk_meta["speaker_id"] = str(meta["speaker_id"])
            if frame_paths and "frame_indices" in meta:
                # dict.get(idx)：抽帧空洞或上传失败的 idx 自动跳过，不错位、不越界
                chunk_meta["frame_paths"] = [
                    frame_paths[idx] for idx in meta["frame_indices"]
                    if frame_paths.get(idx)
                ]
        # 关系元数据白名单拾取（sentence_window/parent_child 产物）——公共段：
        # 文本与图片（line_aware=False）都可携带；音视频走 line_aware 回落
        # meta 恒空、拾取自然跳过。放 is_text 分支内会让图片文档选新策略时
        # 切分带出的 meta 在落库时被静默丢弃（验证轮案例 E 实测）。
        # parent_slot 是切分期相对槽位（瞬态），解析成绝对 id 后不入 ES；
        # slot 断链（父块缺失/被上游过滤）→ 不写指针，子块退化为普通块
        #（检索期不扩展——能力缺失优于错误指针）。
        chunk_role = meta.get("chunk_role")
        if chunk_role in ("parent", "child"):
            chunk_meta["chunk_role"] = chunk_role
        if chunk_role == "child" and isinstance(meta.get("parent_slot"), int):
            parent_pos = slot_to_position.get(meta["parent_slot"])
            if parent_pos is not None:
                chunk_meta["parent_chunk_id"] = f"{document.id}_{parent_pos}"
                chunk_meta["expansion_type"] = "parent_child"
        if meta.get("expansion_type") == "sentence_window":
            chunk_meta["expansion_type"] = "sentence_window"
            if isinstance(meta.get("expansion_window_size"), int):
                chunk_meta["expansion_window_size"] = meta["expansion_window_size"]
        # hierarchical：content_type 全块透传（检索过滤/前端徽标用）；特殊对象
        # 块补章节锚点指针（正文锚点块自身无需指针——它是被指向的一方）。
        # slot 断链（锚点缺失/被上游过滤）→ 不写指针，特殊对象退化为普通块
        #（检索期不扩展——能力缺失优于错误指针）。
        if meta.get("expansion_type") == "hierarchical" and meta.get("content_type") in ("text", "table", "code"):
            chunk_meta["content_type"] = meta["content_type"]
            if meta["content_type"] != "text" and isinstance(meta.get("section_slot"), int):
                anchor_pos = slot_to_anchor_position.get(meta["section_slot"])
                if anchor_pos is not None:
                    chunk_meta["section_anchor_chunk_id"] = f"{document.id}_{anchor_pos}"
        chunk_data = {
            "space_id": document.space_id,
            "kb_id": document.kb_id,
            "document_id": document.id,
            "chunk_id": f"{document.id}_{i}",
            "chunk_index": i,
            "content": text,
            "chunk_type": chunk_type,
            # 文档生命周期冗余（kb-ops B1）：检索侧按此字段排除式过滤。
            # 上传即 active（draft 是前端暂存概念，未入库前无 chunk）。
            "lifecycle_status": getattr(document, "lifecycle_status", None) or "active",
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
            # VIDEO chunk 的 image_url 取该 chunk 首帧的 MinIO path 作为缩略图（真实帧图），
            # 不再误导指向整个视频文件；无可用帧则空串。IMAGE 模态维持 media_url（图片文件本身）。
            if chunk_type == ChunkType.VIDEO:
                if frame_paths and meta.get("frame_indices"):
                    chunk_data["image_url"] = frame_paths.get(meta["frame_indices"][0], "") or ""
                else:
                    chunk_data["image_url"] = ""
            else:
                chunk_data["image_url"] = media_url
        es_chunks.append(chunk_data)
    return es_chunks


def prepare_es_chunks(
    document: Document,
    chunks: list[str],
    parse_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """将文本分块列表转换为 ES 索引格式的字典列表（薄 shim，委托 build_es_chunks）。

    保留旧签名以兼容现有调用与测试；行为与原实现一致。
    """
    chunk_structure = list((parse_metadata or {}).get("chunk_structure") or [])
    chunk_items = [
        (c, chunk_structure[i] if i < len(chunk_structure) else {})
        for i, c in enumerate(chunks)
    ]
    return build_es_chunks(document, chunk_items, ChunkType.TEXT, parse_metadata=parse_metadata)


def split_line_aware(md_text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """按行累积切分，绝不切进「[HH:MM:SS#idx] 描述」行内部，保证锚点不分家。

    供 fixed_size 与 recursive 在 line_aware=True 时共用（音视频带时间锚点文本）。
    单行超 chunk_size 时整行成一块（oversized），正确性优先于尺寸软上限。
    overlap 用「保留尾部若干行使其字符和 ≈ chunk_overlap」实现（行单位 overlap）。
    抽自原 fixed_size line_aware 内联实现，供 recursive 复用修复 B3/B4：
    grouped 组描述 >chunk_size 时原 recursive 分隔符层级退到行内，把行首锚点切到
    上一个 chunk、描述切到下一个 chunk，导致 align_chunk_times 丢时间对齐。
    """
    lines = md_text.split("\n")
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for line in lines:
        addition = len(line) + (1 if buf else 0)  # 非首行加 \n 连接符长度
        if buf and buf_len + addition > chunk_size:
            chunks.append("\n".join(buf))
            # overlap：从尾部回溯取若干行，使其字符和 ≥ chunk_overlap 即停
            tail: list[str] = []
            tail_len = 0
            for tl in reversed(buf):
                if tail and tail_len + len(tl) >= chunk_overlap:
                    break
                tail.insert(0, tl)
                tail_len += len(tl) + (1 if len(tail) > 1 else 0)
            buf = tail
            buf_len = sum(len(tl) for tl in tail) + max(0, len(tail) - 1)
        buf.append(line)
        buf_len += addition
    if buf:
        chunks.append("\n".join(buf))
    return [c for c in chunks if c.strip()]


async def split_md_text(
    md_text: str,
    strategy: str = "recursive",
    embedding_client=None,
    line_aware: bool = False,
    **kwargs,
) -> list[tuple[str, dict[str, Any]]]:
    """
    将 MD/纯文本按指定策略切分为 chunks

    Args:
        md_text: 待切分的文本内容
        strategy: 切分策略 (recursive / markdown / fixed_size / semantic / delimiter /
            sentence_window / parent_child / hierarchical)
        line_aware: 仅 fixed_size / recursive / delimiter / sentence_window / parent_child
            生效——True 时按行累积切分（音视频带 [HH:MM:SS#idx] 锚点文本，避免切进
            「[锚点] 描述」行内部导致锚点分家，窗口/父子元数据随之缺失 → 检索期
            不扩展）；False 时按句/字符/分隔符切（图片等无锚点文本）。由调用方据
            time_alignment 是否非空决定（音视频 True，图片/文本 False）。
        **kwargs: 策略相关参数 (chunk_size, chunk_overlap, min_chunk_size, max_chunk_size,
            window_size, parent_chunk_size 等)

    Returns:
        [(text, metadata_dict), ...] — sentence_window/parent_child/hierarchical 的
        metadata 携带关系元数据（expansion_type / chunk_role / parent_slot /
        content_type / section_slot），其余策略为空 dict
    """
    from novamind.engines.document.pipeline import DocumentRegistry

    splitter_class = DocumentRegistry.get_splitter_class(strategy)
    if splitter_class is None:
        raise ValueError(
            f"不支持的切分策略: {strategy}，可用策略: {DocumentRegistry.get_available_strategies()}"
        )

    if strategy == "recursive":
        chunk_size = kwargs.get("chunk_size", 2000)
        chunk_overlap = kwargs.get("chunk_overlap", 50)
        min_chunk_size = kwargs.get("min_chunk_size", 500)
        if line_aware:
            # 音视频带 [HH:MM:SS#idx] 锚点文本：按行边界切，避免组描述 >chunk_size 时
            # recursive 分隔符层级退到行内把锚点切分家（B3/B4）。min_chunk_size 不适用行模式。
            return [(c, {}) for c in split_line_aware(md_text, chunk_size, chunk_overlap)]
        splitter = splitter_class(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=min_chunk_size,
        )
        chunk_texts = await splitter._split_text(md_text)
        return [(text, {}) for text in chunk_texts if text.strip()]

    elif strategy == "markdown":
        from novamind.engines.document.splitters import MarkdownSplitter
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
        if line_aware:
            # 行边界对齐版（音视频带 [HH:MM:SS#idx] 锚点文本）：抽公共 split_line_aware，
            # 与 recursive 共用，绝不切进「[锚点] 描述」行内部，保证锚点反查不错位。
            return [(c, {}) for c in split_line_aware(md_text, chunk_size, chunk_overlap)]
        # 字符切（图片等无锚点文本）：原 FixedSizeSplitter 行为
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

    elif strategy == "semantic":
        max_chunk_size = kwargs.get("max_chunk_size", 1000)
        similarity_threshold = kwargs.get("similarity_threshold", 0.7)
        batch_size = kwargs.get("batch_size", 20)
        if embedding_client is None:
            raise ValueError("semantic splitting requires embedding_client")
        splitter = splitter_class(
            embedding_client=embedding_client,
            max_chunk_size=max_chunk_size,
            similarity_threshold=similarity_threshold,
            batch_size=batch_size,
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

    elif strategy == "delimiter":
        chunk_size = kwargs.get("chunk_size", 500)
        chunk_overlap = kwargs.get("chunk_overlap", 50)
        min_chunk_size = kwargs.get("min_chunk_size", 500)
        if line_aware:
            # 音视频带锚点文本：与 recursive/fixed_size 共用行边界切分。分隔符
            # 边界语义让位于锚点行完整性——硬切路径可能把「[锚点] 描述」行拦腰
            # 切开导致时间反查错位，锚点完整性优先（与 fixed_size 忽略 overlap
            # 是同性质取舍）。
            return [(c, {}) for c in split_line_aware(md_text, chunk_size, chunk_overlap)]
        splitter = splitter_class(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=min_chunk_size,
            separators=kwargs.get("separators"),  # None → 引擎默认空行切分
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

    elif strategy == "sentence_window":
        chunk_size = kwargs.get("chunk_size", 1000)
        chunk_overlap = kwargs.get("chunk_overlap", 0)
        window_size = kwargs.get("window_size", 2)
        if line_aware:
            # 音视频带锚点文本：与 recursive/fixed_size/delimiter 共用行边界
            # 切分，锚点行完整性优先；窗口元数据缺失 → 检索期不扩展（能力
            # 缺失优于错误结果）。
            return [(c, {}) for c in split_line_aware(md_text, chunk_size, chunk_overlap)]
        splitter = splitter_class(
            window_size=window_size,
            max_sentence_length=chunk_size,
        )
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "text",
        }]
        results = await splitter.split(doc_wrapper)
        return [
            (r["text"], r.get("meta") or {})
            for r in results if r.get("text", "").strip()
        ]

    elif strategy == "parent_child":
        chunk_size = kwargs.get("chunk_size", 1000)
        chunk_overlap = kwargs.get("chunk_overlap", 100)
        if line_aware:
            # 音视频带锚点文本：行边界切分优先，同 sentence_window 的锚点保护
            return [(c, {}) for c in split_line_aware(md_text, chunk_size, chunk_overlap)]
        splitter = splitter_class(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            parent_chunk_size=kwargs.get("parent_chunk_size", 2000),
        )
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "text",
        }]
        results = await splitter.split(doc_wrapper)
        return [
            (r["text"], r.get("meta") or {})
            for r in results if r.get("text", "").strip()
        ]

    elif strategy == "hierarchical":
        chunk_size = kwargs.get("chunk_size", 1000)
        chunk_overlap = kwargs.get("chunk_overlap", 100)
        if line_aware:
            # 音视频带锚点文本：行边界切分优先，同 sentence_window/parent_child
            # 的锚点保护；章节/特殊对象元数据缺失 → 检索期不扩展
            return [(c, {}) for c in split_line_aware(md_text, chunk_size, chunk_overlap)]
        splitter = splitter_class(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=kwargs.get("min_chunk_size", 200),
        )
        doc_wrapper = [{
            "text": md_text,
            "source": "media_pipeline",
            "page": 1,
            "doc_id": "0",
            "type": "text",
        }]
        results = await splitter.split(doc_wrapper)
        return [
            (r["text"], r.get("meta") or {})
            for r in results if r.get("text", "").strip()
        ]

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


async def maybe_semantic_embedding_client(
    strategy: str,
    embedding_config: dict[str, Any],
    session: AsyncSession,
    user_id: int,
    model_config_port: ModelConfigService | None = None,
):
    """strategy == "semantic" 时返回语义切分所需的 embedding_client，否则返回 None。

    get_embedding_client 已下沉本模块（原跨模块懒 import 解环后不再需要）。
    """
    if strategy != "semantic":
        return None
    return await get_embedding_client(
        session=session,
        user_id=user_id,
        model_name=embedding_config.get("model"),
        model_config_port=model_config_port,
    )


async def get_es_client() -> ElasticsearchClient:
    """获取 ES 客户端（静态方法用）"""
    from novamind.shared.storage.client_factory import ClientFactory

    return await ClientFactory.get_elasticsearch_client()


async def get_embedding_client(
    session: AsyncSession,
    user_id: int | None = None,
    model_name: str | None = None,
    model_config_port: ModelConfigService | None = None,
) -> EmbeddingClient:
    """获取 Embedding 客户端（静态方法用）

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
    return await model_config_service.get_embedding_client_by_model(
        user_id=effective_user_id, model=model_name
    )


async def generate_embeddings(
    texts: list[str],
    embedding_config: dict[str, Any],
    session: AsyncSession | None = None,
    user_id: int | None = None,
    model_config_port: ModelConfigService | None = None,
) -> list[list[float]]:
    """生成文本向量（静态方法用）

    整文档一次性交给客户端内部分批：客户端批大小遇服务商上限 400 时自适应
    缩批（解析报错中的上限数字原地重发），学到的批大小在全部批次间复用。
    此处不再外层切片——外层每片都会从配置批大小重新撞一遍上限
    （doc 574 实测：每个外层 32 条批次各付一次 400，32→25→20 反复触发）。
    """
    if not session:
        raise DocumentProcessingError(document_id=0, error_message="生成向量需要数据库会话")

    model_name = embedding_config.get("model")
    embedding_client = await get_embedding_client(
        session, user_id, model_name, model_config_port=model_config_port
    )

    batch_size = embedding_config.get("batch_size", DEFAULT_EMBEDDING_BATCH_SIZE)
    try:
        return await embedding_client.generate_embeddings_batch(texts, batch_size=batch_size)
    except Exception as e:
        _log = get_logger(__name__)
        _log.error(
            "Embedding 批量生成失败",
            model_name=model_name,
            batch_size=batch_size,
            total_texts=len(texts),
            error=str(e),
            traceback=traceback.format_exc(),
        )
        raise EmbeddingError(
            f"Embedding 生成失败: model={model_name or 'unknown'}, total_texts={len(texts)}, error={e}"
        ) from e


async def generate_single_embedding(
    text: str,
    embedding_config: dict[str, Any],
    session: AsyncSession,
    user_id: int | None = None,
    model_config_port: ModelConfigService | None = None,
) -> list[float] | None:
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
        embedding_client = await get_embedding_client(
            session, user_id, model_name, model_config_port=model_config_port
        )
        embeddings = await embedding_client.generate_embeddings_batch([text])
        return embeddings[0] if embeddings else None
    except Exception as e:
        _log = get_logger(__name__)
        _log.warning("单条文本嵌入生成失败", error=str(e), traceback=traceback.format_exc())
        return None


async def generate_questions_for_chunks(
    chunks: list[str],
    document_title: str,
    kb_config: dict[str, Any],
    embedding_config: dict[str, Any],
    user_id: int | None = None,
    session: AsyncSession | None = None,
    model_config_port: ModelConfigService | None = None,
) -> tuple:
    """
    为所有分块生成假设问题，并生成问题向量

    Returns:
        (questions_list, question_embeddings_list, qg_stats)
        questions_list: List[List[str]] — 每个分块对应的问题文本列表
        question_embeddings_list: List[List[List[float]]] — 每个分块对应的问题向量列表
        qg_stats: BatchGenerationStats — 批次级统计（含失败/降级批次数），供节点 metrics 透出
    """
    from novamind.features.knowledge_space.schemas.knowledge_base_schema import (
        QuestionGenerationConfig,
    )
    from novamind.features.knowledge_space.services.question_generation_service import (
        QuestionGenerationService,
    )

    _logger = get_logger(__name__)

    qg_config_dict = kb_config.get("question_generation", {})
    qg_config = (
        QuestionGenerationConfig(**qg_config_dict) if qg_config_dict else QuestionGenerationConfig()
    )

    if not qg_config.enabled:
        _logger.info("假设问题生成未启用，跳过")
        from novamind.features.knowledge_space.services.question_generation_service import (
            BatchGenerationStats,
        )

        return [], [], BatchGenerationStats()

    qg_service = QuestionGenerationService(
        session=session, config=qg_config, model_config_service=model_config_port
    )

    # generate_questions_batch 接受 List[Tuple[str, Optional[str]]] 格式
    chunk_tuples = [(chunk, document_title) for chunk in chunks]
    batch_results, qg_stats = await qg_service.generate_questions_batch(
        chunks=chunk_tuples,
        user_id=user_id,
    )

    # 提取问题文本
    questions_list: list[list[str]] = []
    all_questions_flat: list[str] = []

    for chunk_questions in batch_results:
        texts = [q.question for q in chunk_questions]
        questions_list.append(texts)
        all_questions_flat.extend(texts)

    # 生成问题向量
    question_embeddings_list: list[list[list[float]]] = []
    if all_questions_flat:
        try:
            all_q_embeddings = await generate_embeddings(
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

    return questions_list, question_embeddings_list, qg_stats


async def run_post_parse_tail(
    *,
    document: Document,
    session: AsyncSession,
    task: DocumentTask,
    model_config_port: ModelConfigService | None,
    logger,
    chunk_type: ChunkType,
    embedding_config: dict[str, Any],
    pipeline_config: dict[str, Any],
    splitting_config: dict[str, Any],
    full_text: str = "",
    prechunked_items: list[tuple[str, dict[str, Any]]] | None = None,
    steps_items: list[tuple[str, dict[str, Any]]] | None = None,
    parse_metadata: dict[str, Any] | None = None,
    frame_paths: dict[int, str] | None = None,
    time_alignment: dict[str, Any] | None = None,
    parse_fingerprint: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """共享后置尾：切分 → 构造 ES chunks → 向量化 → 问题生成 → 索引。

    文本/音频/视频三模态共用此尾，统一节点名 split/embedded/question_generation/indexed。
    - 转换器若已产出结构化分块（如 DeepDoc），传 prechunked_items，尾直接采用，不再二次切分；
      否则传 full_text，尾用 split_md_text 切分（音频/视频走此分支）。
    - steps_items（视频步骤综合产物）：带锚点的步骤条目，在切分后、时间对齐前
      append 到 chunk_items——照常经 align_chunk_times 获得 start/end/frame_indices
      与锚点剥离，与帧级 chunks 共用同一 ES 元数据管道；传 None 无行为变化。
    - QG 由 pipeline_config["question_generation"]["enabled"] 控制，失败跳过、留空，与文本管道原逻辑一致。
    - parse_fingerprint 非 None 时启用断点续跑：split/embed 指纹匹配即复用快照产物，
      不匹配则在完成后写快照。None = 不启用（兼容现有测试）。

    Returns:
        {chunk_count, indexed_count, total_questions, split_strategy}，供调用方写 mark_completed。
    """
    from novamind.features.knowledge_space.services.pipeline_snapshots import (
        SNAPSHOTS_ENABLED,
        compute_embed_fingerprint,
        compute_split_fingerprint,
        load_embeddings_snapshot,
        load_split_snapshot,
        save_embeddings_snapshot,
        save_split_snapshot,
        snapshot_fingerprint,
    )
    from novamind.shared.storage.client_factory import ClientFactory

    # 断点续跑前置：MinIO 客户端 + 各级指纹（懒获取，失败降级为不启用）
    resume_minio = None
    split_fingerprint = ""
    embed_fingerprint = ""
    if SNAPSHOTS_ENABLED and parse_fingerprint:
        try:
            resume_minio = await ClientFactory.get_minio_client()
            # 切分模式并入停顿阈值有效值（音频 pause_topic 的边界参数）：
            # 它决定切分边界却不在顶层 splitting_config 里，不进指纹则改阈值
            # 后 RETRY 仍命中旧分块（参数静默失效）。触发条件与有效值语义
            # 镜像 media_processing.process_audio_document（None → 引擎默认 0.8）。
            split_mode = (
                "structural" if prechunked_items is not None
                else str(splitting_config.get("strategy", "recursive"))
            )
            audio_cfg = (pipeline_config.get("parsing", {}) or {}).get("audio", {}) or {}
            if prechunked_items is not None and audio_cfg.get("split_mode") == "pause_topic":
                pause_gap = audio_cfg.get("pause_gap_seconds")
                effective_gap = float(pause_gap) if pause_gap is not None else 0.8
                split_mode = f"pause_topic:{effective_gap}"
            split_fingerprint = compute_split_fingerprint(
                parse_fingerprint, split_mode, splitting_config,
            )
            embed_fingerprint = compute_embed_fingerprint(split_fingerprint, embedding_config)
        except Exception as fp_exc:
            logger.warning(
                "切分/向量指纹计算失败，本次不启用快照复用",
                document_id=document.id, error=str(fp_exc),
            )

    # 1. 切分
    await begin_step(session, task, "split")
    resumed_split = False
    chunk_items: list[tuple[str, dict[str, Any]]] = []
    if split_fingerprint and resume_minio is not None:
        if snapshot_fingerprint(document, "split") == split_fingerprint:
            snap = await load_split_snapshot(document, resume_minio, logger)
            if snap and snap.get("chunk_items"):
                chunk_items = snap["chunk_items"]
                resumed_split = True
                logger.info(
                    "切分快照命中，复用分块（跳过切分）",
                    document_id=document.id,
                    chunk_count=len(chunk_items),
                    alignment_applied=snap.get("alignment_applied", False),
                )
    split_strategy = "structural" if prechunked_items is not None else str(splitting_config.get("strategy", "recursive"))
    if not resumed_split:
        if prechunked_items is not None:
            chunk_items = list(prechunked_items)
        else:
            sc = dict(splitting_config)
            strategy = sc.pop("strategy", "recursive")
            embedding_client = await maybe_semantic_embedding_client(
                strategy, embedding_config, session, document.uploader_id,
                model_config_port=model_config_port,
            )
            chunk_items = await split_md_text(
                full_text, strategy=strategy, embedding_client=embedding_client,
                line_aware=time_alignment is not None, **sc,
            )
            split_strategy = strategy
    chunk_count = len(chunk_items)
    # 步骤综合产物 append（视频步骤 chunks）：在对齐前注入，与帧级 chunks 共用
    # align_chunk_times 的时间反查/锚点剥离与 build_es_chunks 元数据管道。
    if steps_items:
        chunk_items = list(chunk_items) + list(steps_items)
        chunk_count = len(chunk_items)
    await finish_step_committed(session, task, "split", metrics={
        "chunk_count": chunk_count,
        "split_strategy": split_strategy,
        "chunk_size": splitting_config.get("chunk_size"),
        **({"resumed": True} if resumed_split else {}),
    })
    await check_document_cancelled(document.id)

    # 1.4. 音频质量元数据聚合（批次②④，须在 align_chunk_times 剥离锚点前）：
    # 按 chunk 文本里的锚点 idx 聚合 segment 置信度（sigmoid(avg_logprob) 均值）
    # 与说话人标签，写进 per-chunk meta——build_es_chunks 原样透传进
    # ES metadata.confidence/speaker_id；切分快照保存前完成，resume 免重聚合。
    audio_segments = (time_alignment or {}).get("audio_segments")
    if audio_segments and not resumed_split:
        from novamind.engines.document.media.audio import (
            finalize_segment_meta,
            merge_segment_meta,
        )
        import re as _re

        for text, meta in chunk_items:
            idxs = [int(m) for m in _re.findall(r"#(\d+)", text)]
            if not idxs:
                continue
            merged: dict = {}
            for idx in idxs:
                merged = merge_segment_meta(audio_segments, idx, merged)
            meta.update(finalize_segment_meta(merged))

    # 1.5. 媒体时间对齐：切分后正则反查 [HH:MM:SS#idx] 锚点 → 填 start_time/end_time/frame_indices
    # + 剥离锚点得到纯描述 content（进 embedding）。仅音视频传 time_alignment；文本/图片 None 跳过。
    # 对齐纯逻辑下沉在 engines/document/media/chunk_time_alignment.align_chunk_times。
    alignment_applied = False
    if time_alignment:
        from novamind.engines.document.media import align_chunk_times
        chunk_items = align_chunk_times(
            chunk_items,
            time_alignment["timeline_map"],
            bool(time_alignment["is_video"]),
            frame_groups=time_alignment.get("frame_groups"),
        )
        alignment_applied = True

    # 切分快照：对齐之后写（含 alignment_applied 标记，防止 resume 时二次对齐）
    if split_fingerprint and resume_minio is not None and not resumed_split:
        await save_split_snapshot(
            document, session, logger,
            minio_client=resume_minio,
            split_fingerprint=split_fingerprint,
            chunk_items=chunk_items,
            alignment_applied=alignment_applied,
        )

    # 2. 构造 ES chunks（文本/媒体 metadata 由 build_es_chunks 按 chunk_type 分支处理）
    es_chunks = build_es_chunks(
        document, chunk_items, chunk_type,
        parse_metadata=parse_metadata, frame_paths=frame_paths,
    )

    # 3. 向量化
    await begin_step(session, task, "embedded")
    resumed_embed = False
    embeddings: list[list[float] | None] = []
    if embed_fingerprint and resume_minio is not None:
        if snapshot_fingerprint(document, "embed") == embed_fingerprint:
            snap = await load_embeddings_snapshot(document, resume_minio, logger)
            if snap and isinstance(snap.get("embeddings"), list) and len(snap["embeddings"]) == len(es_chunks):
                embeddings = snap["embeddings"]
                resumed_embed = True
                logger.info(
                    "向量快照命中，复用向量（跳过 embedding 调用）",
                    document_id=document.id,
                    embedding_count=len(embeddings),
                    embedding_model=snap.get("embedding_model", ""),
                )
    if not resumed_embed:
        # 父块（parent_child 产物）只作检索期回带容器、不参与召回，跳过
        # embedding 省成本；槽位留 None 定长占位——快照的 len(es_chunks) 契约
        # 与下方 `if emb:` 回填守卫均无需改动（ES dense_vector 缺字段合法）。
        embed_positions = [
            i for i, c in enumerate(es_chunks)
            if (c.get("metadata") or {}).get("chunk_role") != "parent"
        ]
        embed_results = (
            await generate_embeddings(
                [es_chunks[i]["content"] for i in embed_positions], embedding_config,
                session=session, user_id=user_id or document.uploader_id,
                model_config_port=model_config_port,
            )
            if embed_positions else []
        )
        embeddings = [None] * len(es_chunks)
        for pos, emb in zip(embed_positions, embed_results):
            embeddings[pos] = emb
        if embed_fingerprint and resume_minio is not None:
            await save_embeddings_snapshot(
                document, session, logger,
                minio_client=resume_minio,
                embed_fingerprint=embed_fingerprint,
                embeddings=embeddings,
                embedding_model=str(embedding_config.get("model") or ""),
            )
    for i, emb in enumerate(embeddings):
        if emb:
            es_chunks[i]["embedding"] = emb
    await finish_step_committed(session, task, "embedded", metrics={
        "embedding_count": len(embeddings),
        "dimension": embedding_config.get("dimension"),
        **({"resumed": True} if resumed_embed else {}),
    })
    await check_document_cancelled(document.id)

    # 4. 问题生成（由 KB 配置控制；失败跳过、留空）
    await begin_step(session, task, "question_generation")
    qg_config = pipeline_config.get("question_generation", {})
    should_generate = qg_config.get("enabled", False) if qg_config else False
    qg_stats = None
    # 父块无 embedding 也不生成假设问题（父块不参与召回，问题向量无意义）——
    # QG 只覆盖非父块；metrics 分母同口径，否则「缺口告警」在有父块时恒触发。
    qg_positions = [
        i for i, c in enumerate(es_chunks)
        if (c.get("metadata") or {}).get("chunk_role") != "parent"
    ]
    for chunk in es_chunks:
        chunk["questions"] = []
        chunk["question_embeddings"] = []
    if should_generate:
        try:
            questions_list, question_embeddings_list, qg_stats = await generate_questions_for_chunks(
                chunks=[es_chunks[i]["content"] for i in qg_positions],
                document_title=document.filename,
                kb_config=pipeline_config,
                embedding_config=embedding_config,
                user_id=document.uploader_id,
                session=session,
                model_config_port=model_config_port,
            )
            for pos, (questions, q_embeddings) in zip(
                qg_positions, zip(questions_list, question_embeddings_list)
            ):
                es_chunks[pos]["questions"] = questions
                es_chunks[pos]["question_embeddings"] = [{"vector": emb} for emb in q_embeddings]
        except Exception as e:
            logger.warning(
                "假设问题生成失败，跳过继续处理",
                document_id=document.id, error=str(e),
            )
    total_questions = sum(len(c.get("questions") or []) for c in es_chunks)
    # 覆盖率透出：指标只报总数会让「部分批次超时留空」伪装成健康完成
    # （doc787 实例：total=20 看似正常，实际 12/16 分块因批次超时为空）。
    qg_metrics: dict = {
        "enabled": should_generate,
        "total_questions": total_questions,
        "chunks_total": len(qg_positions),
        "chunks_with_questions": sum(
            1 for i in qg_positions if es_chunks[i].get("questions")
        ),
    }
    if qg_stats is not None and should_generate:
        qg_metrics.update(qg_stats.to_metrics())
    # 缺口判定与分母同口径（非父块）：父块本就无问题，掺进分母会恒触发告警。
    if should_generate and qg_metrics["chunks_with_questions"] < len(qg_positions):
        logger.warning(
            "假设问题生成存在缺口",
            document_id=document.id,
            chunks_with_questions=qg_metrics["chunks_with_questions"],
            chunks_total=len(qg_positions),
            **({"batches_failed": qg_stats.batches_failed} if qg_stats else {}),
        )
    await finish_step_committed(session, task, "question_generation", metrics=qg_metrics)
    await check_document_cancelled(document.id)

    # 5. 索引到 ES
    await begin_step(session, task, "indexed")
    es_client = await get_es_client()
    # delete-before-write：bulk 是按 chunk_id 的 upsert，分块数变少时旧
    # {doc}_{高序号} chunk 会永久残留进检索（审计 P1#4——指纹失效重建路径
    # 只有 REPROCESS/删除/取消清 ES，RETRY 成功路径不清）。索引前按文档
    # 清一次本份额度，幂等且与分块数无关。
    # 清理失败必须中止而非降级 upsert：残留旧 chunk 是"错误结果"方向（旧
    # 内容继续进检索且无人再清）；任务置失败可重试（arq max_tries / 手动
    # RETRY）才是安全方向——重试会重新走到这里再清一次。
    try:
        await es_client.delete_document_chunks(
            space_id=document.space_id, document_id=document.id,
        )
    except Exception as pre_del_err:
        logger.error(
            "索引前清理旧分块失败，中止索引（可重试）",
            document_id=document.id, error=str(pre_del_err),
        )
        raise RuntimeError(
            f"索引前清理旧分块失败，为避免残留旧 chunk 中止本次索引: {pre_del_err}"
        ) from pre_del_err
    indexed_count = await es_client.bulk_index_chunks(
        space_id=document.space_id,
        chunks=es_chunks,
        embedding_dim=embedding_config.get("dimension"),
    )
    # 部分失败不再静默（审计 P1#5）：bulk 内部失败只计成功数不抛错，此前
    # indexed_count != 0 即 COMPLETED，缺失块永久无感知。要求全量写入。
    if es_chunks and indexed_count < len(es_chunks):
        raise RuntimeError(
            f"ES 索引部分写入失败: {indexed_count}/{len(es_chunks)} 个分块成功写入"
        )
    if indexed_count == 0 and es_chunks:
        raise RuntimeError(f"ES 索引写入失败: {len(es_chunks)} 个分块均未成功写入")
    await finish_step_committed(session, task, "indexed", metrics={
        "indexed_count": indexed_count, "chunk_count": len(es_chunks),
    })

    return {
        "chunk_count": chunk_count,
        "indexed_count": indexed_count,
        "total_questions": total_questions,
        "split_strategy": split_strategy,
    }
