"""DeepDoc 数据模型：解析请求 / 响应 / 版面 / 区块等核心数据结构。"""
import re
from dataclasses import dataclass, field
from typing import Any

# DeepDoc 各 parser 在 full_text 里以 ``@@<page>\t<x0>\t<x1>\t<top>\t<bottom>##``
# 标记每个文本行的版面坐标（layout/vision 模式）。这些标记只应作为位置元数据
# 使用，不应进入 chunk 正文 / embedding。下方正则与 ``DeepDocPdfBox.remove_tag``
# 一致，作为解析结果的规范化入口。
_POSITION_TAG_RE = re.compile(r"@@[\t0-9.-]+?##")


def strip_position_tags(text: str) -> str:
    """移除 DeepDoc full_text 中的 ``@@...##`` 版面坐标标记。

    用于在按用户 splitting 参数重新切分 full_text 之前清洗文本，避免坐标标记
    泄漏进 chunk 内容（进而污染 ES / embedding）。
    """
    if not text:
        return text
    return _POSITION_TAG_RE.sub("", text)


@dataclass(slots=True)
class DeepDocParseResult:
    """DeepDoc 解析结果契约：全文/chunks/metadata 三元组。
    
    metadata 携带 reading_order/chunk_structure/table_regions 等引擎特有
    信息；strip_position_tags 用于产出不含坐标标记的干净文本。
    """
    full_text: str
    chunks: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
