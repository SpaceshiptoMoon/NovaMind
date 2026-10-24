"""切分策略分派链守护测试（扩展性重构批次 0 安全网）。

三条装配链当前是三份 if/elif 手工同步副本——
A. ``DocumentProcessor.split_text_items``（文本主链路，deepdoc 哨兵重切与默认
   reader 路径都经它）；
B. ``DocumentProcessor.load_with_strategy``（agent 附件等组合入口）；
C. ``pipeline_steps.split_md_text``（音视频/图片媒体路径，含 line_aware 锚点
   保护特例）——批次 2 将收敛为统一的 SplitterFactory。本文件在重构前锁定
   两条事实，重构后被断言必须原样成立或显式更新：

1. **装配快照**：每条链对每个策略传给切分器构造函数的参数。表中的默认值
   漂移（recursive chunk_size 500 vs 2000、delimiter min_chunk_size 50 vs
   500、链 C recursive 直调 ``_split_text`` 绕过 split()）是**已知现状**，
   先显式记录再消除——重构后这些差异行应收敛为单一值。
2. **行为金样**：真实切分器对固定文本的切分产物（文本块 + 关系元数据）。
   重构只允许换装配方式，不允许改变切分产物；快照不一致即回归。

金样重生成：环境变量 ``SPLITTER_GOLDEN_GENERATE=1`` 运行本文件，
快照写入 goldens/splitter_dispatch_golden.json（人工审阅后入库）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.document.pipeline.document_loader import (
    DocumentProcessor,
    DocumentRegistry,
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

# ---------------------------------------------------------------------------
# 装配快照期望表：三条链各自「空 kwargs 时」传给切分器构造函数的参数。
# 漂移行已用注释标注——这是现状记录，不是期望规范。
# ---------------------------------------------------------------------------
CHAIN_A_DEFAULTS = {  # split_text_items：文本主链路
    "recursive": {"chunk_size": 500, "chunk_overlap": 50, "min_chunk_size": 50},
    # semantic 额外携带 embedding_client 键，单独断言（见 test_..._semantic）
    "fixed_size": {"chunk_size": 500, "chunk_overlap": 0},
    "markdown": {"max_chunk_size": 1000, "min_chunk_size": 50},
    "delimiter": {"chunk_size": 500, "chunk_overlap": 50, "min_chunk_size": 50, "separators": None},
    "sentence_window": {"window_size": 2, "max_sentence_length": 1000},
    "parent_child": {"chunk_size": 1000, "chunk_overlap": 100, "parent_chunk_size": 2000},
    "hierarchical": {"chunk_size": 1000, "chunk_overlap": 100, "min_chunk_size": 200},
}
CHAIN_C_DEFAULTS = {  # split_md_text：媒体路径
    # 漂移：recursive 默认 2000（链 A 是 500）、min_chunk_size 500（链 A 是 50）
    "recursive": {"chunk_size": 2000, "chunk_overlap": 50, "min_chunk_size": 500},
    "fixed_size": {"chunk_size": 500, "chunk_overlap": 0},
    "markdown": {"max_chunk_size": 1000, "min_chunk_size": 50},
    # 漂移：delimiter min_chunk_size 500（链 A 是 50）
    "delimiter": {"chunk_size": 500, "chunk_overlap": 50, "min_chunk_size": 500, "separators": None},
    "sentence_window": {"window_size": 2, "max_sentence_length": 1000},
    "parent_child": {"chunk_size": 1000, "chunk_overlap": 100, "parent_chunk_size": 2000},
    "hierarchical": {"chunk_size": 1000, "chunk_overlap": 100, "min_chunk_size": 200},
}
# 链 B（load_with_strategy）与链 A 逐参相同（纯拷贝副本），直接复用期望表。
# 链 C 的 meta 透传分叉（漂移记录）：只有关系策略拾取切分器 meta，其余策略
# （recursive/fixed_size/markdown/delimiter）输出恒空 dict——桩切分器携带的
# {"stub": True} 会被吃掉。链 A 对全部策略统一透传 meta。
CHAIN_C_META_PASSTHROUGH = {
    "recursive": False,
    "fixed_size": False,
    "markdown": False,
    "delimiter": False,
    "sentence_window": True,
    "parent_child": True,
    "hierarchical": True,
}


class RecordingSplitter(BaseSplitter):
    """捕获构造参数与调用路径的桩切分器（替换注册表内全部策略）。"""

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
def recording_registry():
    """把注册表内全部策略临时替换为 RecordingSplitter，结束后原样恢复。"""
    saved = dict(DocumentRegistry._splitters_registry)
    for name in saved:
        DocumentRegistry.register_splitter(name, RecordingSplitter)
    RecordingSplitter.last_init_kwargs = None
    RecordingSplitter.split_called = False
    RecordingSplitter.split_text_called = False
    yield
    DocumentRegistry._splitters_registry.clear()
    DocumentRegistry._splitters_registry.update(saved)


def _processor() -> DocumentProcessor:
    return DocumentProcessor(embedding_client=None)


class TestChainAAssembly:
    """链 A：split_text_items 的装配快照。"""

    @pytest.mark.parametrize("strategy", [s for s in STRATEGIES if s != "semantic"])
    def test_default_kwargs(self, recording_registry, strategy):
        asyncio.run(_processor().split_text_items("文本内容。", strategy=strategy))
        assert RecordingSplitter.last_init_kwargs == CHAIN_A_DEFAULTS[strategy]
        assert RecordingSplitter.split_called is True

    def test_semantic_receives_embedding_client(self, recording_registry):
        """semantic 构造除数值参数外还携带 embedding_client（None 也显式传）。"""
        asyncio.run(_processor().split_text_items("文本内容。", strategy="semantic"))
        assert RecordingSplitter.last_init_kwargs == {
            "embedding_client": None,
            "max_chunk_size": 1000,
            "similarity_threshold": 0.7,
            "batch_size": 20,
        }

    def test_explicit_kwargs_win_over_defaults(self, recording_registry):
        """显式参数覆盖默认值（recursive）。"""
        asyncio.run(
            _processor().split_text_items(
                "文本内容。", strategy="recursive", chunk_size=123,
            )
        )
        assert RecordingSplitter.last_init_kwargs["chunk_size"] == 123

    def test_unknown_strategy_raises(self, recording_registry):
        """未注册策略显式 ValueError（含可用策略清单）。"""
        with pytest.raises(ValueError, match="Unknown strategy"):
            asyncio.run(_processor().split_text_items("文本", strategy="nonexistent"))


class TestChainBAssembly:
    """链 B：load_with_strategy 的装配快照（与链 A 逐参相同的纯拷贝副本）。"""

    @pytest.mark.parametrize("strategy", [s for s in STRATEGIES if s != "semantic"])
    def test_default_kwargs(self, recording_registry, strategy, tmp_path):
        doc = tmp_path / "doc.txt"
        doc.write_text("文件内容。", encoding="utf-8")
        asyncio.run(_processor().load_with_strategy(doc, strategy=strategy))
        assert RecordingSplitter.last_init_kwargs == CHAIN_A_DEFAULTS[strategy]

    def test_semantic_receives_embedding_client(self, recording_registry, tmp_path):
        doc = tmp_path / "doc.txt"
        doc.write_text("文件内容。", encoding="utf-8")
        asyncio.run(_processor().load_with_strategy(doc, strategy="semantic"))
        assert RecordingSplitter.last_init_kwargs == {
            "embedding_client": None,
            "max_chunk_size": 1000,
            "similarity_threshold": 0.7,
            "batch_size": 20,
        }


class TestChainCAssembly:
    """链 C：split_md_text 的装配快照（媒体路径，含 line_aware 特例）。"""

    @pytest.mark.parametrize(
        "strategy", [s for s in STRATEGIES if s not in ("semantic", "markdown")]
    )
    def test_default_kwargs(self, recording_registry, strategy):
        items = asyncio.run(split_md_text("媒体文本。", strategy=strategy))
        assert RecordingSplitter.last_init_kwargs == CHAIN_C_DEFAULTS[strategy]
        expected_meta = {"stub": True} if CHAIN_C_META_PASSTHROUGH[strategy] else {}
        assert items == [("桩块", expected_meta)]

    def test_markdown_bypasses_registry(self):
        """漂移记录：链 C 的 markdown 分支不经注册表取类，直接局部 import
        MarkdownSplitter 构造——替换注册表条目对它无效。批次 2 工厂化时消除。"""
        from novamind.engines.document.splitters import MarkdownSplitter

        items = asyncio.run(
            split_md_text("# 标题\n\n正文段落。", strategy="markdown",
                          max_chunk_size=100, min_chunk_size=10)
        )
        assert items, "markdown 分支应产出非空块"
        assert MarkdownSplitter is DocumentRegistry.get_splitter_class("markdown")

    def test_recursive_bypasses_split(self, recording_registry):
        """漂移记录：链 C 的 recursive 非 line_aware 时直调 _split_text，
        绕过 split()（即绕过小碎块合并与 doc_id 编号）；其余策略走 split()。"""
        asyncio.run(split_md_text("媒体文本。", strategy="recursive"))
        assert RecordingSplitter.split_text_called is True
        assert RecordingSplitter.split_called is False

    def test_line_aware_bypasses_splitter(self, recording_registry):
        """line_aware=True 时音视频锚点保护生效：切分器完全不被构造/调用，
        走 split_line_aware 行切分。"""

        class NoInitSplitter(RecordingSplitter):
            def __init__(self, **kwargs):  # noqa: ARG002 — 构造即视为违规
                raise AssertionError("line_aware 路径不得构造切分器")

        saved = dict(DocumentRegistry._splitters_registry)
        for name in saved:
            DocumentRegistry.register_splitter(name, NoInitSplitter)
        try:
            anchored = "\n".join(
                f"[00:00:{i:02d}#0] 第{i}句描述文本内容" for i in range(10)
            )
            items = asyncio.run(
                split_md_text(anchored, strategy="recursive", line_aware=True,
                              chunk_size=40, chunk_overlap=10)
            )
        finally:
            DocumentRegistry._splitters_registry.clear()
            DocumentRegistry._splitters_registry.update(saved)
        assert items, "行切分应产出非空块"
        assert all("[00:00" in text for text, _meta in items), "锚点行不得被拦腰切开"

    def test_semantic_without_client_raises(self):
        """链 C 的 semantic 无 embedding_client 时显式报错（与链 A 静默传 None 不同）。"""
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

# 每策略显式参数（行为金样锁定「切分器产物」而非默认值；默认值漂移由装配快照管）。
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
    for strategy in ("recursive", "fixed_size", "delimiter", "sentence_window",
                     "parent_child", "hierarchical"):
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
