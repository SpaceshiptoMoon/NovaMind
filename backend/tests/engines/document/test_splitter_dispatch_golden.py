"""切分策略装配守护测试（批次 2 工厂化后的结构锁定）。

装配知识单一归属 ``splitter_factory`` 注册表后，本文件锁定三层事实：

1. **工厂默认值**：``build_splitter`` 对空参数产出的真实切分器实例属性
   （默认值从三份 if/elif 拷贝收敛到 builder 后的权威值——DIRECT/TEXT 组）。
2. **调用层零夹带**：链 A/B（split_text_items / load_with_strategy）不再
   在调用层 prefill 默认——桩切分器捕获的构造参数恒为调用方显式值；
   链 C（split_md_text）唯一有权 prefill 媒体语境默认（recursive 加大块、
   delimiter 合并阈值放大），媒体默认表由此锁定。
3. **行为金样**：真实切分器对固定文本的切分产物逐字节一致（重构只许换
   装配方式，不许改切分行为）。

金样重生成：``SPLITTER_GOLDEN_GENERATE=1`` 运行本文件，快照写入
goldens/splitter_dispatch_golden.json（人工审阅后入库）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.pipeline import splitter_factory
from novamind.engines.document.pipeline.document_loader import DocumentProcessor
from novamind.engines.document.pipeline.splitter_factory import (
    SplitterDeps,
    UnknownSplitterStrategyError,
    build_splitter,
)
from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.features.knowledge_space.services.pipeline_steps import split_md_text

pytestmark = pytest.mark.unit

GOLDEN_PATH = Path(__file__).parent / "goldens" / "splitter_dispatch_golden.json"
GENERATE_GOLDEN = os.environ.get("SPLITTER_GOLDEN_GENERATE") == "1"

STRATEGIES = [
    "recursive",
    "semantic",
    "fixed_size",
    "markdown",
    "delimiter",
    "sentence_window",
    "parent_child",
    "hierarchical",
]

# 工厂默认值（真实切分器实例属性；= 历史上链 A 的装配结果，DRIFT 已收敛归属）
FACTORY_DEFAULTS: dict[str, dict[str, Any]] = {
    "recursive": {"chunk_size": 500, "chunk_overlap": 50, "min_chunk_size": 50},
    "semantic": {"max_chunk_size": 1000, "similarity_threshold": 0.7, "batch_size": 20},
    "fixed_size": {"chunk_size": 500, "chunk_overlap": 0},
    "markdown": {"max_chunk_size": 1000, "min_chunk_size": 50},
    "delimiter": {"chunk_size": 500, "chunk_overlap": 50, "min_chunk_size": 50},
    "sentence_window": {"window_size": 2, "max_sentence_length": 1000},
    "parent_child": {"chunk_size": 1000, "chunk_overlap": 100, "parent_chunk_size": 2000},
    "hierarchical": {"chunk_size": 1000, "chunk_overlap": 100, "min_chunk_size": 200},
}

# 链 C 媒体语境默认（split_md_text prefill 后桩切分器捕获的构造参数；
# 与工厂默认的差异点 = 媒体默认表内容）
CHAIN_C_MEDIA_DEFAULTS: dict[str, dict[str, Any]] = {
    "recursive": {"chunk_size": 2000, "chunk_overlap": 50, "min_chunk_size": 500},
    "fixed_size": {"chunk_size": 500, "chunk_overlap": 0},
    "delimiter": {"chunk_size": 500, "chunk_overlap": 50, "min_chunk_size": 500},
    "sentence_window": {"chunk_size": 1000, "chunk_overlap": 0, "window_size": 2},
    "parent_child": {"chunk_size": 1000, "chunk_overlap": 100, "parent_chunk_size": 2000},
    "hierarchical": {"chunk_size": 1000, "chunk_overlap": 100, "min_chunk_size": 200},
    "markdown": {"max_chunk_size": 1000, "min_chunk_size": 50},
    "semantic": {"max_chunk_size": 1000, "similarity_threshold": 0.7, "batch_size": 20},
}

# line_aware 行切分支持策略（与 pipeline_steps._LINE_AWARE_STRATEGIES 对齐；
# 拆分到本测试避免 import 私有符号）
LINE_AWARE_STRATEGIES = frozenset({
    "recursive", "fixed_size", "delimiter", "sentence_window", "parent_child", "hierarchical",
})


class RecordingSplitter(BaseSplitter):
    """捕获构造参数与调用路径的桩切分器（替换工厂 builder 表）。"""

    last_init_kwargs: dict[str, Any] | None = None
    split_called: bool = False
    split_text_called: bool = False

    def __init__(self, **kwargs):
        type(self).last_init_kwargs = dict(kwargs)

    async def split(self, documents):
        type(self).split_called = True
        return [{"text": "桩块", "content": "桩块", "meta": {"stub": True}}]

    async def _split_text(self, text):
        type(self).split_text_called = True
        return ["桩块"]


@pytest.fixture()
def recording_builders():
    """把工厂 builder 表临时替换为 RecordingSplitter 装配器，结束后原样恢复。"""
    saved = dict(splitter_factory._BUILDERS)
    for name in saved:
        splitter_factory.register_splitter_builder(
            name, lambda p, deps, _n=name: RecordingSplitter(**p)
        )
    RecordingSplitter.last_init_kwargs = None
    RecordingSplitter.split_called = False
    RecordingSplitter.split_text_called = False
    yield
    splitter_factory._BUILDERS.clear()
    splitter_factory._BUILDERS.update(saved)


def _processor() -> DocumentProcessor:
    return DocumentProcessor(embedding_client=None)


class TestFactoryDefaults:
    """工厂默认值：空参数装配出的真实切分器实例属性（权威默认单一归属）。"""

    @pytest.mark.parametrize("strategy", STRATEGIES)
    def test_defaults(self, strategy):
        splitter = build_splitter(strategy, {}, SplitterDeps(embedding_client=None))
        for attr, expected in FACTORY_DEFAULTS[strategy].items():
            assert getattr(splitter, attr) == expected, (
                f"{strategy}.{attr} 默认值漂移：{getattr(splitter, attr)} != {expected}"
            )

    def test_unknown_strategy_raises(self):
        with pytest.raises(UnknownSplitterStrategyError, match="Unknown strategy"):
            build_splitter("nonexistent", {}, SplitterDeps())

    def test_registry_and_factory_strategies_aligned(self):
        """类注册表与工厂 builder 表策略集合一致（防两套注册漂移）。"""
        from novamind.engines.document.pipeline.document_loader import DocumentRegistry

        assert set(DocumentRegistry.get_available_strategies()) == set(
            splitter_factory.get_available_builder_strategies()
        )


class TestChainAAssembly:
    """链 A：split_text_items 调用层零夹带（默认全在 builder）。"""

    @pytest.mark.parametrize("strategy", STRATEGIES)
    def test_no_prefill_by_caller(self, recording_builders, strategy):
        asyncio.run(_processor().split_text_items("文本内容。", strategy=strategy))
        assert RecordingSplitter.last_init_kwargs == {}, (
            "调用层不应 prefill 默认值（缺省取值单一归属 builder）"
        )
        assert RecordingSplitter.split_called is True

    def test_explicit_kwargs_pass_through(self, recording_builders):
        asyncio.run(
            _processor().split_text_items("文本内容。", strategy="recursive", chunk_size=123)
        )
        assert RecordingSplitter.last_init_kwargs == {"chunk_size": 123}

    def test_unknown_strategy_propagates(self, recording_builders):
        with pytest.raises(UnknownSplitterStrategyError, match="Unknown strategy"):
            asyncio.run(_processor().split_text_items("文本", strategy="nonexistent"))


class TestChainBAssembly:
    """链 B：load_with_strategy 与链 A 同源（共享工厂）。"""

    @pytest.mark.parametrize("strategy", STRATEGIES)
    def test_no_prefill_by_caller(self, recording_builders, strategy, tmp_path):
        doc = tmp_path / "doc.txt"
        doc.write_text("文件内容。", encoding="utf-8")
        asyncio.run(_processor().load_with_strategy(doc, strategy=strategy))
        assert RecordingSplitter.last_init_kwargs == {}


class TestChainCMediaDefaults:
    """链 C：split_md_text 的媒体语境默认表（唯一有权 prefill 的调用层）。"""

    @pytest.mark.parametrize(
        "strategy", [s for s in STRATEGIES if s not in ("semantic",)]
    )
    def test_media_defaults_prefilled(self, recording_builders, strategy):
        asyncio.run(split_md_text("媒体文本。", strategy=strategy))
        assert RecordingSplitter.last_init_kwargs == CHAIN_C_MEDIA_DEFAULTS[strategy]

    def test_explicit_kwargs_win_over_media_defaults(self, recording_builders):
        asyncio.run(
            split_md_text("媒体文本。", strategy="recursive", chunk_size=777)
        )
        assert RecordingSplitter.last_init_kwargs["chunk_size"] == 777

    def test_recursive_bypasses_split(self, recording_builders):
        """漂移记录：链 C 的 recursive 非 line_aware 时直调 _split_text，
        绕过 split()（即绕过小碎块合并与 doc_id 编号）；其余策略走 split()。"""
        asyncio.run(split_md_text("媒体文本。", strategy="recursive"))
        assert RecordingSplitter.split_text_called is True
        assert RecordingSplitter.split_called is False

    def test_all_strategies_route_through_factory(self, recording_builders):
        """markdown 不再绕过注册表局部 import（历史分叉已消除）。"""
        asyncio.run(split_md_text("# 标题\n\n正文。", strategy="markdown"))
        assert RecordingSplitter.last_init_kwargs is not None

    def test_line_aware_bypasses_splitter(self, recording_builders):
        """line_aware=True 时锚点保护前置：切分器完全不被构造/调用。"""

        class NoInitSplitter(RecordingSplitter):
            def __init__(self, **kwargs):  # noqa: ARG002 — 构造即视为违规
                raise AssertionError("line_aware 路径不得构造切分器")

        saved = dict(splitter_factory._BUILDERS)
        for name in saved:
            splitter_factory.register_splitter_builder(
                name, lambda p, deps: NoInitSplitter(**p)
            )
        try:
            anchored = "\n".join(
                f"[00:00:{i:02d}#0] 第{i}句描述文本内容" for i in range(10)
            )
            items = asyncio.run(
                split_md_text(anchored, strategy="recursive", line_aware=True,
                              chunk_size=40, chunk_overlap=10)
            )
        finally:
            splitter_factory._BUILDERS.clear()
            splitter_factory._BUILDERS.update(saved)
        assert items, "行切分应产出非空块"
        assert all("[00:00" in text for text, _meta in items), "锚点行不得被拦腰切开"

    @pytest.mark.parametrize("strategy", sorted(LINE_AWARE_STRATEGIES))
    def test_line_aware_supported_strategies(self, strategy):
        """line_aware 支持集合与常量对齐（media_defaults 表覆盖全部支持策略）。"""
        from novamind.features.knowledge_space.services.pipeline_steps import (
            _LINE_AWARE_STRATEGIES,
        )

        assert strategy in _LINE_AWARE_STRATEGIES
        assert strategy in CHAIN_C_MEDIA_DEFAULTS, (
            f"{strategy} 支持 line_aware 但媒体默认表缺 chunk_size/chunk_overlap 前置取参"
        )

    def test_semantic_without_client_raises(self):
        with pytest.raises(ValueError, match="embedding_client"):
            asyncio.run(split_md_text("媒体文本。", strategy="semantic"))


# ---------------------------------------------------------------------------
# 行为金样：真实切分器 + 固定文本 → 产物快照比对。
# ---------------------------------------------------------------------------
GOLDEN_TEXT = (
    "# 标题一\n\n"
    "这是第一段正文，包含中文与 English mixed content。"
    "这句话用来测试句子边界切分！句子之间有标点。\n\n"
    "## 标题二\n\n"
    "- 列表项甲：知识库解析管道\n"
    "- 列表项乙：切分策略守护测试\n\n"
    "The quick brown fox jumps over the lazy dog. "
    "Pack my box with five dozen liquor jugs. "
    "How vexingly quick daft zebras jump!\n\n"
    + "长句压测文本用于触发尺寸上限切分。" * 60
)

# 每策略显式参数（行为金样锁定「切分器产物」而非默认值；默认值由工厂默认测试管）。
GOLDEN_PARAMS: dict[str, dict[str, Any]] = {
    "recursive": {"chunk_size": 200, "chunk_overlap": 20, "min_chunk_size": 50},
    "fixed_size": {"chunk_size": 200, "chunk_overlap": 20},
    "markdown": {"max_chunk_size": 200, "min_chunk_size": 30},
    "delimiter": {"chunk_size": 200, "chunk_overlap": 20, "min_chunk_size": 30},
    "sentence_window": {"window_size": 2, "chunk_size": 300},
    "parent_child": {"chunk_size": 200, "chunk_overlap": 20, "parent_chunk_size": 400},
    "hierarchical": {"chunk_size": 200, "chunk_overlap": 20, "min_chunk_size": 50},
    "semantic": {"max_chunk_size": 200, "similarity_threshold": 0.5, "batch_size": 4},
}


class DeterministicEmbedding:
    """确定性假 embedding：字符 bigram MD5 计数向量，稳定且区分相邻文本。"""

    async def generate_embeddings_batch(self, texts, batch_size=None):  # noqa: ARG002
        return [self._embed(t) for t in texts]

    @staticmethod
    def _embed(text: str, dim: int = 64) -> list[float]:
        vec = [0.0] * dim
        for i in range(len(text) - 1):
            digest = hashlib.md5(text[i : i + 2].encode("utf-8")).hexdigest()
            vec[int(digest, 16) % dim] += 1.0
        return vec


def _snapshot_outputs() -> dict[str, Any]:
    """跑全部策略 × 两条链，产出可 JSON 化的金样快照。"""
    snapshot: dict[str, Any] = {"chain_a": {}, "chain_c": {}, "chain_c_line_aware": {}}
    processor = DocumentProcessor(embedding_client=DeterministicEmbedding())
    for strategy in STRATEGIES:
        items = asyncio.run(
            processor.split_text_items(GOLDEN_TEXT, strategy=strategy, **GOLDEN_PARAMS[strategy])
        )
        snapshot["chain_a"][strategy] = [[t, m] for t, m in items]

        if strategy == "semantic":
            # 链 C semantic 需显式传 embedding_client
            items = asyncio.run(
                split_md_text(GOLDEN_TEXT, strategy=strategy,
                              embedding_client=DeterministicEmbedding(),
                              **GOLDEN_PARAMS[strategy])
            )
        else:
            items = asyncio.run(
                split_md_text(GOLDEN_TEXT, strategy=strategy, **GOLDEN_PARAMS[strategy])
            )
        snapshot["chain_c"][strategy] = [[t, m] for t, m in items]

    # line_aware 仅部分策略支持（音视频锚点保护）
    anchored = "\n".join(
        f"[00:00:{i:02d}#0] 第{i}句描述文本内容用于行切分压测" for i in range(30)
    )
    for strategy in sorted(LINE_AWARE_STRATEGIES):
        items = asyncio.run(
            split_md_text(anchored, strategy=strategy, line_aware=True,
                          chunk_size=80, chunk_overlap=10,
                          **({"min_chunk_size": 20} if strategy in ("recursive", "delimiter", "hierarchical") else {}))
        )
        snapshot["chain_c_line_aware"][strategy] = [[t, m] for t, m in items]
    return snapshot


class TestBehaviorGolden:
    """行为金样：重构前后切分产物必须逐字节一致。"""

    def test_golden_snapshot(self):
        snapshot = _snapshot_outputs()
        if GENERATE_GOLDEN:
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True),
                encoding="utf-8",
            )
            pytest.skip(f"金样已重生成：{GOLDEN_PATH}，请人工审阅后入库")
        assert GOLDEN_PATH.exists(), (
            f"金样不存在：先 SPLITTER_GOLDEN_GENERATE=1 生成并审阅入库 {GOLDEN_PATH}"
        )
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        assert snapshot == expected, (
            "切分产物与金样不一致——若为装配重构导致，检查是否改变了切分行为；"
            "若为有意的行为变更，需 SPLITTER_GOLDEN_GENERATE=1 重生成并审阅 diff"
        )

    def test_all_strategies_produce_nonempty_chunks(self):
        """反例守护：任一策略对非空文本产出 0 块即为回归（历史上 markdown
        分支曾静默丢弃无句读段，丢 370/2345 字）。"""
        snapshot = _snapshot_outputs()
        for chain, by_strategy in snapshot.items():
            for strategy, items in by_strategy.items():
                assert items, f"{chain}/{strategy} 产出 0 块"
                for text, _meta in items:
                    assert text.strip(), f"{chain}/{strategy} 产出空白块"
