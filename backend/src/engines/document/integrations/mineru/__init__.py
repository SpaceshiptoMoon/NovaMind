"""MinerU 外部解析引擎适配层（PDF strategy=mineru）。

职责边界：子进程调用隔离环境中的 MinerU CLI、收集产物、显式暴露失败；
配置由宿主（knowledge_space）从 YAML mineru 段构造注入，本包不读环境、
不做降级、不感知业务。
"""

from novamind.engines.document.integrations.mineru.client import (
    MineruEngineConfig,
    MineruExecutionError,
    MineruNotAvailableError,
    MineruParseResult,
    parse_pdf,
    parse_pdf_sync,
)

__all__ = [
    "MineruEngineConfig",
    "MineruExecutionError",
    "MineruNotAvailableError",
    "MineruParseResult",
    "parse_pdf",
    "parse_pdf_sync",
]
