"""统一文档块模型：跨格式一致的产物契约与 Markdown 序列化出口。

各格式解析器的内部产物形态各异（docx sections、xlsx HTML 块、pdf chunks），
下游（检索/预览/引用）不应为每种格式写一套适配。UnifiedBlock 是跨格式的
最小公共块契约；blocks_to_markdown 把块列表序列化为 LLM 友好的 Markdown，
使解析产物不被锁死在单一消费链里。

第一版边界：块粒度跟随各格式现有产物粒度（pdf 为 chunk 级），坐标溯源
（bbox/页码）仅在格式原生携带时进 meta——不伪造不存在的位置信息。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any

# 块类型全集（kind 取值；新增类型须同步消费方）
KIND_HEADING = "heading"
KIND_TEXT = "text"
KIND_TABLE = "table"
KIND_FIGURE = "figure"
KIND_CHART = "chart"
KIND_TEXTBOX = "textbox"
KIND_HEADER = "header"
KIND_FOOTER = "footer"


@dataclass
class UnifiedBlock:
    """跨格式统一文档块。

    Attributes:
        kind: 块类型（heading/text/table/figure/chart/textbox/header/footer）。
        text: 块文本；表格为行文本或 HTML（is_html=True 时）。
        level: 标题层级 1-6（仅 heading）。
        caption: 图表/表格的引用说明（如 ``Sheet!A1:F18``）。
        meta: 格式特有扩展（坐标/页码/样式名等，JSON 可序列化）。
        is_html: text 是否为 HTML 载荷（序列化时转换）。
    """

    kind: str
    text: str
    level: int | None = None
    caption: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    is_html: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转 JSON 安全 dict（metadata 出账用）。"""
        return asdict(self)


class _HTMLTableParser(HTMLParser):
    """最小 HTML 表格提取器：caption + 行列文本（th/td，含 rowspan 忽略）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.caption = ""
        self.rows: list[list[str]] = []
        self._in_caption = False
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "caption":
            self._in_caption = True
        elif tag == "tr":
            self.rows.append([])
        elif tag in ("th", "td"):
            self._cell_parts = []
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append("<br/>")

    def handle_endtag(self, tag: str) -> None:
        if tag == "caption":
            self._in_caption = False
        elif tag in ("th", "td") and self._cell_parts is not None:
            if self.rows:
                self.rows[-1].append("".join(self._cell_parts).strip())
            self._cell_parts = None

    def handle_data(self, data: str) -> None:
        if self._in_caption:
            self.caption += data
        elif self._cell_parts is not None:
            self._cell_parts.append(data)


def html_table_to_markdown(html: str) -> str:
    """HTML 表格转 Markdown 表格（caption 并入表格上方的斜体行）。

    单元格内 ``<br/>`` 保留为 Markdown 表格内的换行标记；竖线转义防破表。
    解析失败（非法片段）原样返回 HTML——失败方向安全：产物可读性降级优于
    内容丢失。
    """
    try:
        parser = _HTMLTableParser()
        parser.feed(html)
        parser.close()
    except Exception:
        return html
    lines: list[str] = []
    caption = parser.caption.strip()
    if caption:
        lines.append(f"*{caption}*")
    rows = [row for row in parser.rows if row]
    if not rows:
        return "\n".join(lines) if lines else html
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    escape = lambda cell: unescape(cell).replace("|", "\\|").replace("\n", " ")
    header = normalized[0]
    lines.append("| " + " | ".join(escape(cell) or " " for cell in header) + " |")
    lines.append("|" + "|".join([" --- "] * width) + "|")
    for row in normalized[1:]:
        lines.append("| " + " | ".join(escape(cell) or " " for cell in row) + " |")
    return "\n".join(lines)


def block_to_markdown(block: UnifiedBlock) -> str:
    """单块转 Markdown 片段。"""
    if block.kind == KIND_HEADING:
        prefix = "#" * min(block.level or 1, 6)
        return f"{prefix} {block.text}"
    if block.kind == KIND_TABLE:
        if block.is_html:
            return html_table_to_markdown(block.text)
        return block.text
    if block.kind == KIND_FIGURE:
        caption = block.caption or block.text or "图片"
        return f"![{caption}]({block.text})" if block.text else f"![{caption}]"
    if block.kind == KIND_CHART:
        return block.text
    return block.text


def blocks_to_markdown(blocks: list[UnifiedBlock]) -> str:
    """块列表序列化为 Markdown 文档（块间空行分隔）。"""
    parts = [
        piece
        for piece in (block_to_markdown(block).strip() for block in blocks)
        if piece
    ]
    return "\n\n".join(parts)


def chunks_to_markdown(chunks: list[str]) -> str:
    """chunk 列表转 Markdown：HTML 表格块转换，其余原样（空行分隔）。

    无块结构的格式（pdf/文本族）的统一出口由此承担；含内嵌 HTML 表格的
    chunk（html/xlsx 兜底产物）在转换后对 LLM 与预览更友好。
    """
    parts = []
    for chunk in chunks:
        text = (chunk or "").strip()
        if not text:
            continue
        if "<table" in text.lower():
            text = html_table_to_markdown(text)
        parts.append(text)
    return "\n\n".join(parts)
