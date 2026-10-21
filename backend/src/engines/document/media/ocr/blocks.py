"""OCR 统一中间表示：跨协议归一的内容块与 Markdown 渲染。

不同 OCR 供应商的原始输出形态各异（版面 layouts / 纯文本 / 框+行文本），
统一收敛为 OcrBlock 列表后，Markdown 只是众多渲染目标之一——版面结构
（页码/块类型/坐标）在中间表示层保留，供阅读顺序、切分等下游消费。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 已知块类型白名单；供应商返回的其它类型一律归 "text"
KNOWN_BLOCK_TYPES = frozenset({"title", "text", "formula"})

# bbox 四元组 (x0, y0, x1, y1)
Bbox = tuple[float, float, float, float]


def bbox_from_quad(quad: list[dict[str, Any]] | None) -> Bbox | None:
    """四角点列表 [{x,y}×4] 收拢为包围盒 (x0, y0, x1, y1)。

    Args:
        quad: 供应商返回的四角点列表；允许畸形输入。

    Returns:
        包围盒四元组；输入缺失、非 dict 元素或坐标不可解析时返回 None
        （能力缺失优于错误坐标）。
    """
    if not quad:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for point in quad:
        if not isinstance(point, dict):
            return None
        try:
            xs.append(float(point["x"]))
            ys.append(float(point["y"]))
        except (KeyError, TypeError, ValueError):
            return None
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True)
class OcrBlock:
    """单个 OCR 内容块（跨协议统一中间表示）。"""

    block_type: str  # title / text / formula（未知类型归 text）
    page_num: int  # 0-based 页码（单图恒为 0）
    bbox: Bbox | None = None
    text: str = ""  # 纯文本兜底
    markdown: str = ""  # markdownContent 优先（document_parsing 路径）

    def preferred_text(self) -> str:
        """取首选展示文本：markdown 优先，text 兜底。"""
        return (self.markdown.strip() or self.text.strip())


@dataclass(frozen=True)
class OcrResult:
    """一次 OCR 调用的归一化结果。"""

    blocks: list[OcrBlock]
    page_count: int = 1  # 总页数（document_parsing 取 max(page_num)+1；单图恒 1）
    model: str = ""  # 实际模型名（日志/指纹用）
    protocol: str = ""  # openai / dashscope
    raw_pages: list[str] = field(default_factory=list)  # 逐页原始文本（纯文本通路保留）

    def render_markdown(self) -> str:
        """按阅读顺序（页码 → 页内 y 坐标）渲染为 Markdown。

        渲染规则：title 加 `# ` 前缀；formula 未含 $$ 时包裹为展示块；
        text 原样输出。空块丢弃；无 bbox 的块排在同页有 bbox 块之后。
        """
        non_empty = [b for b in self.blocks if b.preferred_text()]
        ordered = sorted(
            non_empty,
            key=lambda b: (
                b.page_num,
                float("inf") if b.bbox is None else (b.bbox[1] + b.bbox[3]) / 2,
            ),
        )
        parts: list[str] = []
        for block in ordered:
            text = block.preferred_text()
            if block.block_type == "title":
                parts.append(f"# {text}")
            elif block.block_type == "formula":
                if "$$" in text:
                    parts.append(text)
                else:
                    parts.append(f"$$\n{text}\n$$")
            else:
                parts.append(text)
        return "\n\n".join(parts)
