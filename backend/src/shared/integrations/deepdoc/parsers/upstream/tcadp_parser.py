from src.shared.integrations.deepdoc.parsers.remote.tcadp import (
    TencentCloudAPIClient,
    RAGFlowTCADPParser,
)


class TCADPParser(RAGFlowTCADPParser):
    pass


__all__ = [
    "TencentCloudAPIClient",
    "TCADPParser",
]
