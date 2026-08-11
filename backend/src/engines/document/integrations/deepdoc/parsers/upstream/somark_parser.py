"""DeepDoc SoMark 上游解析器适配。"""
from novamind.engines.document.integrations.deepdoc.parsers.remote.somark import (
    SoMarkAPIError,
    SoMarkBlockType,
    RAGFlowSoMarkParser,
)


class SoMarkParser(RAGFlowSoMarkParser):
    pass


__all__ = [
    "SoMarkAPIError",
    "SoMarkBlockType",
    "SoMarkParser",
]
