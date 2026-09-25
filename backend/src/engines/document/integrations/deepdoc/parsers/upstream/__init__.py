"""DeepDoc 上游解析器适配层：保留下游仍消费的上游镜像的懒导出。

批次 G 修剪后 `parsers/upstream/` 只剩 4 个镜像：
- `figure_parser`（`parsers/figure.py` 继承 VisionFigureParser）
- `html_parser`（`parsers/epub.py` 消费）
- `markdown_parser`（`parsers/text.py` 消费）
- `utils`（`parsers/txt.py` 的 get_text + vendor stub 的书签提取）

docx/excel/epub/ppt/txt/json 的 fork 版（`parsers/<format>.py`）已独立实现，
对应上游镜像已删除。
"""
from __future__ import annotations

from importlib import import_module

_EXPORT_MAP = {
    "FigureParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.figure_parser", "FigureParser"),
    "HtmlParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.html_parser", "RAGFlowHtmlParser"),
    "MarkdownElementExtractor": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.markdown_parser", "MarkdownElementExtractor"),
    "MarkdownParser": ("novamind.engines.document.integrations.deepdoc.parsers.upstream.markdown_parser", "RAGFlowMarkdownParser"),
}

__all__ = list(_EXPORT_MAP.keys())


def __getattr__(name):
    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)
