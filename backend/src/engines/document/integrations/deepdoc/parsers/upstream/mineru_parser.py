"""DeepDoc MinerU 上游解析器适配。"""
from novamind.engines.document.integrations.deepdoc.parsers.remote.mineru import (
    LANGUAGE_TO_MINERU_MAP,
    MinerUBackend,
    MinerUContentType,
    MinerULanguage,
    MinerUParseMethod,
    MinerUParseOptions,
    RAGFlowMinerUParser,
)


class MinerUParser(RAGFlowMinerUParser):
    pass


__all__ = [
    "LANGUAGE_TO_MINERU_MAP",
    "MinerUBackend",
    "MinerUContentType",
    "MinerULanguage",
    "MinerUParseMethod",
    "MinerUParseOptions",
    "MinerUParser",
]
