"""哨兵标记重切（tagged rechunk）：让 DeepDoc 版面坐标穿越用户配置的切分器。

背景与动机
----------
DeepDoc full 模式解析 PDF 后，每个版面元素（文本行/表格/图片）的页码与坐标
只存在于 ``metadata.reading_order[]`` 的 position_tag / bbox 里；
``full_text`` 本身是干净的（无坐标标记）。当 loader 按用户切分配置对
full_text 重新切分（rechunk）时，重切出的 chunks 与原 chunk_structure
条数不再对应，页码坐标随之丢失（下游 ES ``chunk_pages`` 为空、QA 引用
无页码）。

原始 ``@@<page>\t<x0>\t<x1>\t<top>\t<bottom>##`` 标记无法直接喂给切分器：
recursive splitter 的分隔符含 ``.``（会切碎浮点坐标）且 ``text.split()``
丢弃分隔符字符。因此采用 **PUA 哨兵字符编码**：

1. 每个 reading_order entry 映射一个私有区单字符 ``U+E000 + i``
   （哨兵是不含任何分隔符的单字符，recursive/fixed/semantic/markdown
   四种切分器都无法把它切断，最多整体随文本移动或被丢进某个 chunk）；
2. ``tagged_text = 哨兵 + entry文本``，entries 间以 ``\\n\\n`` 连接——
   与 full_text 的构建方式（``_reading_order_entry_text`` join）逐 entry
   对齐，切分器看到的文本结构与真实全文一致；
3. 切完后在每个 chunk 里按 ``ord(c)`` 找回哨兵，聚合出该 chunk 覆盖的
   pages / source_ids / kinds / bboxes，再剥哨兵得到干净正文。

容量：U+E000–U+F7FF 共 6400 个码位。超限（整页位图 PDF 的 entry 数可能
极大）降级：超出的 entry 不编码哨兵，对应 chunk 无坐标——记 WARNING，
不中断解析。
"""
from __future__ import annotations

import re
from typing import Any

from novamind.shared.logging import get_logger

logger = get_logger(__name__)

# PUA-A（Private Use Area-A）可用码位：U+E000 – U+F7FF，共 6400 个
SENTINEL_BASE = 0xE000
SENTINEL_CAPACITY = 6400

# position_tag：@@<page>\t<x0>\t<x1>\t<top>\t<bottom>##（PDF pt 坐标，原点左上；
# 见 DeepDocPdfBox.line_tag，浮点 :.1f 格式化）。page 允许 "3-4" 跨页形态。
_POSITION_TAG_RE = re.compile(
    r"@@(?P<page>[0-9-]+)\t(?P<x0>[0-9.]+)\t(?P<x1>[0-9.]+)\t(?P<top>[0-9.]+)\t(?P<bottom>[0-9.]+)##"
)

# 重切 chunk_structure 的来源标记（写入 parse metadata，便于下游区分产物来源）
CHUNK_STRUCTURE_SOURCE = "tagged_rechunk"


def _reading_order_entry_text(entry: dict[str, Any]) -> str:
    """复刻 DeepDocPdfParser._reading_order_entry_text（pdf.py）的 entry 渲染。

    tagged_text 必须与 full_text 逐 entry 对齐（后者就是用该方法 join 出来的），
    因此这里不能只取 entry["text"]——figure 的 text 为空但渲染出 ``![alt](占位符)``、
    table 渲染 caption+HTML。漂移由 test_tagged_rechunk.py 的对齐测试守护
    （同 _POSITION_TAG_RE ↔ remove_tag 的守护模式）。
    """
    kind = str(entry.get("kind", "text"))
    if kind == "text":
        return str(entry.get("text", "")).strip()
    if kind == "table":
        caption = str(entry.get("caption", "")).strip()
        html = str(entry.get("html", "")).strip()
        if html:
            parts = [part for part in [caption, html] if part]
            return "\n\n".join(parts)
        text = str(entry.get("text", "")).strip()
        parts = [part for part in ["[TABLE]", caption, text] if part]
        return "\n".join(parts).strip()
    if kind == "figure":
        caption = str(entry.get("caption", "")).strip()
        artifact_id = str(entry.get("source_id", "") or "")
        placeholder = str(entry.get("image_placeholder", "") or "")
        alt = caption or f"Figure {artifact_id}" if artifact_id else "Figure"
        if placeholder:
            return f"![{alt}]({placeholder})"
        text = str(entry.get("text", "")).strip()
        parts = [part for part in ["[FIGURE]", caption, text] if part]
        return "\n".join(parts).strip()
    return str(entry.get("text", "")).strip()


def parse_position_tag(tag: str) -> dict[str, Any] | None:
    """解析 ``@@<page>\\t<x0>\\t<x1>\\t<top>\\t<bottom>##`` 为结构化坐标。

    返回 ``{"page": int, "bbox": {"x0","x1","top","bottom"}}``；
    不匹配（含跨页 "3-4" 取首页）返回 None 或降级页码。
    """
    if not tag:
        return None
    m = _POSITION_TAG_RE.match(tag.strip())
    if not m:
        return None
    page_raw = m.group("page")
    # 跨页 tag（如 @@3-4）取首页作为代表页（与 _build_reading_order_metadata 的
    # page_start 语义一致）；非法数字静默放弃
    page_part = page_raw.split("-")[0]
    try:
        page = int(page_part)
        bbox = {
            "x0": float(m.group("x0")),
            "x1": float(m.group("x1")),
            "top": float(m.group("top")),
            "bottom": float(m.group("bottom")),
        }
    except ValueError:
        return None
    return {"page": page, "bbox": bbox}


def _entry_position(entry: dict[str, Any]) -> dict[str, Any] | None:
    """从 reading_order entry 提取代表坐标：优先 position_tag，其次 bbox + page。"""
    parsed = parse_position_tag(str(entry.get("position_tag") or ""))
    if parsed:
        return parsed
    bbox = entry.get("bbox")
    if isinstance(bbox, dict) and bbox:
        try:
            return {
                "page": int(entry.get("page", 0)),
                "bbox": {
                    "x0": float(bbox.get("x0", 0.0)),
                    "x1": float(bbox.get("x1", 0.0)),
                    "top": float(bbox.get("top", 0.0)),
                    "bottom": float(bbox.get("bottom", 0.0)),
                },
            }
        except (TypeError, ValueError):
            return None
    return None


def build_tagged_text(
    reading_order: list[dict[str, Any]],
) -> tuple[str, dict[int, dict[str, Any]], int, int]:
    """把 reading_order 编码为哨兵标记全文。

    Returns:
        (tagged_text, sentinel_map, encoded_count)

        - tagged_text: ``哨兵 + entry文本`` 按序 ``\\n\\n`` 连接（与 full_text
          同构，切分器视角与真实全文一致）
        - sentinel_map: ``{entry_index: entry}``，仅含**成功编码**的 entry
          （ord(char) - SENTINEL_BASE 即 entry_index）
        - encoded_count: 成功编码的 entry 数（用于 WARNING 判断）

        - degraded_count: 超容量降级（无坐标）的 entry 数——写入 metadata
          暴露给文档详情/运维，避免「后半本无页码」只有日志可见。

    超过 SENTINEL_CAPACITY 的 entry 不编码（无哨兵 → 切分后无法归属坐标），
    整体降级为部分 chunk 无页码，不中断。
    """
    parts: list[str] = []
    sentinel_map: dict[int, dict[str, Any]] = {}
    degraded = 0
    for i, entry in enumerate(reading_order):
        text = _reading_order_entry_text(entry)
        # 与 DeepDocPdfParser._reading_order_entry_text 对齐：渲染为空 text 的
        # entry 不占位，保证 tagged_text 与 full_text 逐 entry 对应
        if not text:
            continue
        if i < SENTINEL_CAPACITY:
            sentinel = chr(SENTINEL_BASE + i)
            sentinel_map[i] = entry
            parts.append(f"{sentinel}{text}")
        else:
            degraded += 1
            parts.append(text)
    if degraded:
        logger.warning(
            "reading_order 条目超出哨兵容量，超出部分降级为无坐标 chunk",
            entry_count=len(reading_order),
            capacity=SENTINEL_CAPACITY,
            degraded_count=degraded,
        )
    return "\n\n".join(parts), sentinel_map, len(sentinel_map), degraded


def strip_sentinels(text: str) -> str:
    """移除文本中的全部 PUA 哨兵字符（U+E000–U+F7FF）。"""
    if not text:
        return text
    return "".join(c for c in text if not (SENTINEL_BASE <= ord(c) < SENTINEL_BASE + SENTINEL_CAPACITY))


def extract_chunk_structure(
    tagged_chunk: str,
    sentinel_map: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """从带哨兵的 chunk 文本中聚合该 chunk 覆盖的版面结构。

    Returns:
        与 DeepDoc ``_build_structured_chunks`` 产物同形，另加 entry_bboxes：

        ``{chunk_index, entry_kinds[], entry_source_ids[], pages[],
        entry_count, entry_bboxes[]}``

        chunk_index 由调用方补填（此处恒 0）；无哨兵（降级/普通文本）返回
        空结构 ``entry_count=0``。
    """
    entry_indexes: list[int] = []
    seen: set[int] = set()
    for c in tagged_chunk:
        code = ord(c)
        if SENTINEL_BASE <= code < SENTINEL_BASE + SENTINEL_CAPACITY:
            idx = code - SENTINEL_BASE
            if idx in sentinel_map and idx not in seen:
                seen.add(idx)
                entry_indexes.append(idx)

    entry_indexes.sort()  # 按阅读序聚合（reading_order 序即文档阅读序）
    entries = [sentinel_map[i] for i in entry_indexes]

    kinds: list[str] = []
    source_ids: list[str] = []
    pages_set: set[int] = set()
    bboxes: list[dict[str, Any]] = []
    for entry in entries:
        kinds.append(str(entry.get("kind", "text")))
        source_ids.append(str(entry.get("source_id", "") or ""))
        pos = _entry_position(entry)
        if pos:
            pages_set.add(int(pos["page"]))
            bboxes.append({"page": pos["page"], **pos["bbox"]})
        else:
            pages_set.add(int(entry.get("page", 0) or 0))

    return {
        "chunk_index": 0,
        "entry_kinds": kinds,
        "entry_source_ids": source_ids,
        "pages": sorted(pages_set),
        "entry_count": len(entries),
        "entry_bboxes": bboxes,
    }


def rechunk_with_structure(
    tagged_chunks: list[str],
    sentinel_map: dict[int, dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]], str]:
    """对切分器产出的带哨兵 chunks 剥哨兵并聚合结构。

    Returns:
        (clean_chunks, chunk_structure, source)

        - clean_chunks: 剥哨兵后的干净正文（进 embedding / ES content）
        - chunk_structure: 与 clean_chunks 一一对应（含 entry_bboxes 扩展键；
          完全无哨兵的 chunk 也会产出 entry_count=0 占位结构，保证条数对齐）
        - source: 恒 ``tagged_rechunk``，写入 parse metadata 供下游甄别
    """
    clean_chunks: list[str] = []
    chunk_structure: list[dict[str, Any]] = []
    # 孤儿哨兵前递：哨兵是 entry 文本的前缀。极端切分参数（字符级兜底）会把
    # 哨兵与其正文切成两个 chunk——孤儿哨兵 chunk 剥哨兵后正文为空被丢弃时，
    # 其 entry 结构必须前递给下一个非空 chunk（正文在后续 chunk 里），否则
    # 该 entry 的页码坐标永久丢失。
    pending: dict[str, Any] | None = None
    for tagged in tagged_chunks:
        clean = strip_sentinels(tagged).strip()
        structure = extract_chunk_structure(tagged, sentinel_map)
        if pending is not None:
            # 前递结构按序并入当前 chunk（保持阅读序，去重防 overlap 双计）
            structure = _merge_structures(pending, structure)
            pending = None
        if not clean:
            if structure["entry_count"]:
                pending = structure
            continue
        structure["chunk_index"] = len(clean_chunks)
        clean_chunks.append(clean)
        chunk_structure.append(structure)
    # 尾部孤儿：哨兵在最后一块且其后无非空 chunk——挂到上一块（若有）
    if pending is not None and chunk_structure:
        chunk_structure[-1] = _merge_structures(chunk_structure[-1], pending)
    return clean_chunks, chunk_structure, CHUNK_STRUCTURE_SOURCE


def _merge_structures(
    a: dict[str, Any], b: dict[str, Any]
) -> dict[str, Any]:
    """合并两个 chunk 结构（孤儿哨兵前递用）：按 entry_source_ids 去重保持序。"""
    seen: set[str] = set()
    kinds: list[str] = []
    source_ids: list[str] = []
    for structure in (a, b):
        for kind, sid in zip(structure["entry_kinds"], structure["entry_source_ids"]):
            if sid in seen:
                continue
            seen.add(sid)
            kinds.append(kind)
            source_ids.append(sid)
    pages = sorted(set(a["pages"]) | set(b["pages"]))
    bboxes = {sid: bbox for sid, bbox in zip(a["entry_source_ids"], a["entry_bboxes"])}
    bboxes.update({sid: bbox for sid, bbox in zip(b["entry_source_ids"], b["entry_bboxes"])})
    ordered_bboxes = [bboxes[sid] for sid in source_ids if sid in bboxes]
    return {
        "chunk_index": a.get("chunk_index", b.get("chunk_index", 0)),
        "entry_kinds": kinds,
        "entry_source_ids": source_ids,
        "pages": pages,
        "entry_count": len(source_ids),
        "entry_bboxes": ordered_bboxes,
    }
