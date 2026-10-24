"""切分策略装配工厂：策略名 → 参数挑选（缺省取默认）+ 依赖注入 → 配置好的切分器实例。

装配知识（每策略消费哪些参数、缺省取值）单一归属本模块；三条消费链
（``DocumentProcessor.split_text_items`` / ``load_with_strategy`` /
``pipeline_steps.split_md_text``）不再各自维护 if/elif 装配副本——历史上
三份手工同步拷贝已漂移出多处默认值不一致（扩展性审计批次 2 收敛）。

新增切分策略 = 写切分器类 + 本模块底部注册一行 builder + schema Literal
白名单加值，不再需要改任何消费链。

Args 约定：builder 收到的 params 是「已合并调用方显式值与调用方默认」的
dict，builder 只读自己消费的键、缺省取 config_defaults 常量——多余键
（如 parent_child 配置里的 window_size）静默忽略，与历史 kwargs 透传语义
一致。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from novamind.engines.document.pipeline.config_defaults import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DIRECT_CHUNK_OVERLAP,
    DEFAULT_DIRECT_CHUNK_SIZE,
    DEFAULT_DIRECT_MIN_CHUNK_SIZE,
    DEFAULT_EMBED_BATCH_SIZE,
    DEFAULT_FIXED_SIZE_OVERLAP,
    DEFAULT_HIERARCHICAL_MIN_CHUNK_SIZE,
    DEFAULT_MARKDOWN_MAX_CHUNK_SIZE,
    DEFAULT_MARKDOWN_MIN_CHUNK_SIZE,
    DEFAULT_MAX_CHUNK_SIZE,
    DEFAULT_MIN_CHUNK_SIZE,
    DEFAULT_PARENT_CHUNK_SIZE,
    DEFAULT_SEMANTIC_MAX_CHUNK_SIZE,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_WINDOW_SIZE,
)
from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.engines.document.splitters.delimiter_splitter import DelimiterSplitter
from novamind.engines.document.splitters.fixed_size_splitter import FixedSizeSplitter
from novamind.engines.document.splitters.hierarchical_splitter import HierarchicalSplitter
from novamind.engines.document.splitters.markdown_splitter import MarkdownSplitter
from novamind.engines.document.splitters.parent_child_splitter import ParentChildSplitter
from novamind.engines.document.splitters.recursive_splitter import RecursiveCharacterSplitter
from novamind.engines.document.splitters.semantic_splitter import SemanticSplitter
from novamind.engines.document.splitters.sentence_window_splitter import SentenceWindowSplitter

SplitterBuilder = Callable[[dict[str, Any], "SplitterDeps"], BaseSplitter]


@dataclass(slots=True)
class SplitterDeps:
    """切分器装配依赖。引擎层不 import 具体模型服务，宿主注入。

    Attributes:
        embedding_client: 嵌入模型客户端，仅 semantic 策略消费；
            None 时构造出的 SemanticSplitter 在切分时才会报错（与历史行为一致）。
    """

    embedding_client: Any | None = None


class UnknownSplitterStrategyError(ValueError):
    """策略名未注册装配；ValueError 子类保持既有调用方 except ValueError 兼容。"""


_BUILDERS: dict[str, SplitterBuilder] = {}


def register_splitter_builder(strategy: str, builder: SplitterBuilder) -> None:
    """注册策略装配器（模块导入期集中调用；同名重复注册覆盖）。"""
    _BUILDERS[strategy] = builder


def get_available_builder_strategies() -> list[str]:
    """返回已注册装配的策略名（排序后列表，供白名单派生与错误提示）。"""
    return sorted(_BUILDERS)


def build_splitter(
    strategy: str,
    params: dict[str, Any] | None,
    deps: SplitterDeps,
    *,
    defaults: dict[str, Any] | None = None,
) -> BaseSplitter:
    """按策略装配切分器实例。

    Args:
        strategy: 策略名（须已注册 builder）。
        params: 调用方显式参数（切分配置 dict 原样传入即可，多余键被 builder 忽略）。
        deps: 装配依赖（embedding client 等）。
        defaults: 调用方语境默认（params 中未出现的键用它补齐，如媒体路径的
            加大块默认）；显式 params 恒优先。

    Returns:
        配置好的切分器实例。

    Raises:
        UnknownSplitterStrategyError: 策略名未注册（显式拒绝而非静默兜底）。
    """
    builder = _BUILDERS.get(strategy)
    if builder is None:
        raise UnknownSplitterStrategyError(
            f"Unknown strategy: {strategy}（不支持的切分策略）. "
            f"Supported: {get_available_builder_strategies()}"
        )
    merged = {**(defaults or {}), **(params or {})}
    return builder(merged, deps)


def extract_splitting_params(splitting_config: dict[str, Any] | None) -> dict[str, Any]:
    """从 KB 切分配置提取切分链消费的参数，缺失键补 TEXT 组默认。

    与历史上 parse_document_result / external_ocr 分支的三处 10 参显式枚举
    逐参等价（缺失补 TEXT 组默认、separators 缺失为 None）；枚举只保留这一处。

    Args:
        splitting_config: KB 配置的 splitting 段（可为 None）。

    Returns:
        全键齐备的参数 dict，可直接 ``**`` 展开传给 split_text_items。
    """
    cfg = splitting_config or {}
    return {
        "chunk_size": cfg.get("chunk_size", DEFAULT_CHUNK_SIZE),
        "chunk_overlap": cfg.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
        "min_chunk_size": cfg.get("min_chunk_size", DEFAULT_MIN_CHUNK_SIZE),
        "max_chunk_size": cfg.get("max_chunk_size", DEFAULT_MAX_CHUNK_SIZE),
        "similarity_threshold": cfg.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
        "batch_size": cfg.get("batch_size", DEFAULT_EMBED_BATCH_SIZE),
        "separators": cfg.get("separators"),
        "window_size": cfg.get("window_size", DEFAULT_WINDOW_SIZE),
        "parent_chunk_size": cfg.get("parent_chunk_size", DEFAULT_PARENT_CHUNK_SIZE),
    }


def _register_default_builders() -> None:
    """集中注册内置策略装配器（新策略在此追加一行）。"""
    register_splitter_builder(
        "recursive",
        lambda p, _deps: RecursiveCharacterSplitter(
            chunk_size=p.get("chunk_size", DEFAULT_DIRECT_CHUNK_SIZE),
            chunk_overlap=p.get("chunk_overlap", DEFAULT_DIRECT_CHUNK_OVERLAP),
            min_chunk_size=p.get("min_chunk_size", DEFAULT_DIRECT_MIN_CHUNK_SIZE),
        ),
    )
    register_splitter_builder(
        "semantic",
        lambda p, deps: SemanticSplitter(
            embedding_client=deps.embedding_client,
            max_chunk_size=p.get("max_chunk_size", DEFAULT_SEMANTIC_MAX_CHUNK_SIZE),
            similarity_threshold=p.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
            batch_size=p.get("batch_size", DEFAULT_EMBED_BATCH_SIZE),
        ),
    )
    register_splitter_builder(
        "fixed_size",
        lambda p, _deps: FixedSizeSplitter(
            chunk_size=p.get("chunk_size", DEFAULT_DIRECT_CHUNK_SIZE),
            chunk_overlap=p.get("chunk_overlap", DEFAULT_FIXED_SIZE_OVERLAP),
        ),
    )
    register_splitter_builder(
        "markdown",
        lambda p, _deps: MarkdownSplitter(
            max_chunk_size=p.get("max_chunk_size", DEFAULT_MARKDOWN_MAX_CHUNK_SIZE),
            min_chunk_size=p.get("min_chunk_size", DEFAULT_MARKDOWN_MIN_CHUNK_SIZE),
        ),
    )
    register_splitter_builder(
        "delimiter",
        lambda p, _deps: DelimiterSplitter(
            chunk_size=p.get("chunk_size", DEFAULT_DIRECT_CHUNK_SIZE),
            chunk_overlap=p.get("chunk_overlap", DEFAULT_DIRECT_CHUNK_OVERLAP),
            min_chunk_size=p.get("min_chunk_size", DEFAULT_DIRECT_MIN_CHUNK_SIZE),
            separators=p.get("separators"),  # None → 引擎默认空行切分
        ),
    )
    register_splitter_builder(
        "sentence_window",
        lambda p, _deps: SentenceWindowSplitter(
            window_size=p.get("window_size", DEFAULT_WINDOW_SIZE),
            max_sentence_length=p.get("chunk_size", DEFAULT_CHUNK_SIZE),
        ),
    )
    register_splitter_builder(
        "parent_child",
        lambda p, _deps: ParentChildSplitter(
            chunk_size=p.get("chunk_size", DEFAULT_CHUNK_SIZE),
            chunk_overlap=p.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
            parent_chunk_size=p.get("parent_chunk_size", DEFAULT_PARENT_CHUNK_SIZE),
        ),
    )
    register_splitter_builder(
        "hierarchical",
        lambda p, _deps: HierarchicalSplitter(
            chunk_size=p.get("chunk_size", DEFAULT_CHUNK_SIZE),
            chunk_overlap=p.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP),
            min_chunk_size=p.get("min_chunk_size", DEFAULT_HIERARCHICAL_MIN_CHUNK_SIZE),
        ),
    )


_register_default_builders()
