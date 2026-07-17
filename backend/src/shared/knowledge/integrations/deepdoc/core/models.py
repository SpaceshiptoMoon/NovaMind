from dataclasses import dataclass, field
from typing import Any, Dict, List
import re


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
    full_text: str
    chunks: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_documents(self, source: str = "") -> List[Dict[str, Any]]:
        documents: List[Dict[str, Any]] = []
        for index, chunk in enumerate(self.chunks):
            documents.append(
                {
                    "text": chunk,
                    "content": chunk,
                    "chunk_index": index,
                    "source": source,
                    "metadata": dict(self.metadata),
                }
            )
        return documents
