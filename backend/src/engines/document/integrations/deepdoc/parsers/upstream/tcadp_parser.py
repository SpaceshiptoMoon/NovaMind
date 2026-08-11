"""DeepDoc TCADP 上游解析器适配。"""
from novamind.engines.document.integrations.deepdoc.parsers.remote.tcadp import (
    TencentCloudAPIClient,
    RAGFlowTCADPParser,
)


class TCADPParser(RAGFlowTCADPParser):
    pass


__all__ = [
    "TencentCloudAPIClient",
    "TCADPParser",
]
