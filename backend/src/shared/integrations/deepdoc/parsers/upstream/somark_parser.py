from src.shared.integrations.deepdoc.parsers.remote.somark import (
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
