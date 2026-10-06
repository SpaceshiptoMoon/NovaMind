"""hierarchical 检索期双向扩展回归测试（chunk_expansion_service 宿主层）。

验证：
1. 特殊对象命中 → content 追加章节锚点正文，原文保留 expansion.retrieved_content；
2. 正文锚点命中 → content 追加章节特殊对象列表；
3. 指针断链/锚点缺失 → 直通（能力缺失优于错误结果）；
4. 存量 chunk（无 hierarchical 元数据）零成本直通；
5. 幂等：已扩展命中重复进入不再二次扩展。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.services.chunk_expansion_service import (
    expand_search_results,
)
from novamind.features.knowledge_space.schemas.search_schema import ExpansionConfig

pytestmark = pytest.mark.unit


class _FakeESClient:
    """get_chunk/get_children_chunks 桩：chunk_id → 块 dict。"""

    def __init__(self, chunks: dict[str, dict], children: dict[str, list[dict]] | None = None):
        self.chunks = chunks
        self.children = children or {}

    async def get_chunk(self, space_id: int, chunk_id: str):
        return self.chunks.get(chunk_id)

    async def get_children_chunks(self, space_id: int, anchor_chunk_id: str, limit: int = 20):
        return self.children.get(anchor_chunk_id, [])


def _hit(chunk_id: str, content: str, meta: dict) -> dict:
    return {"chunk_id": chunk_id, "content": content, "metadata": meta}


class TestSpecialObjectExpansion:
    def test_code_hit_appends_section_context(self):
        """正例：代码块命中 content 追加锚点正文，原文进 expansion。"""
        es = _FakeESClient({"42_0": {"content": "# A 章节正文"}})
        hit = _hit("42_2", "```py\nx=1\n```", {
            "expansion_type": "hierarchical", "content_type": "code",
            "section_anchor_chunk_id": "42_0",
        })
        out = asyncio.run(expand_search_results(es, 1, [hit]))
        assert out[0]["content"].startswith("```py")
        assert "# A 章节正文" in out[0]["content"]
        exp = out[0]["metadata"]["expansion"]
        assert exp["type"] == "hierarchical"
        assert exp["retrieved_content"] == "```py\nx=1\n```"

    def test_broken_anchor_degrades(self):
        """反例：锚点缺失（重析后 id 失效）→ 保留对象原文不扩展。"""
        es = _FakeESClient({})  # 空索引
        original = "```py\nx=1\n```"
        hit = _hit("42_2", original, {
            "expansion_type": "hierarchical", "content_type": "code",
            "section_anchor_chunk_id": "42_0",
        })
        out = asyncio.run(expand_search_results(es, 1, [hit]))
        assert out[0]["content"] == original
        assert "expansion" not in out[0]["metadata"]


class TestAnchorExpansion:
    def test_anchor_hit_appends_related_objects(self):
        """正例：锚点命中追加本章节特殊对象列表。"""
        es = _FakeESClient({}, children={
            "42_0": [
                {"chunk_id": "42_2", "metadata": {"content_type": "code"}, "content": "x=1"},
                {"chunk_id": "42_3", "metadata": {"content_type": "table"}, "content": "| a |"},
            ],
        })
        hit = _hit("42_0", "# A 首段", {
            "expansion_type": "hierarchical", "content_type": "text",
        })
        out = asyncio.run(expand_search_results(es, 1, [hit]))
        assert out[0]["content"].startswith("# A 首段")
        assert "[code]" in out[0]["content"] and "x=1" in out[0]["content"]
        assert "[table]" in out[0]["content"]
        related = out[0]["metadata"]["expansion"]["related_objects"]
        assert len(related) == 2

    def test_pure_text_section_no_expansion(self):
        """反例：章节无特殊对象 → 锚点直通。"""
        es = _FakeESClient({}, children={"42_0": []})
        hit = _hit("42_0", "# A 首段", {
            "expansion_type": "hierarchical", "content_type": "text",
        })
        out = asyncio.run(expand_search_results(es, 1, [hit]))
        assert out[0]["content"] == "# A 首段"
        assert "expansion" not in out[0]["metadata"]


class TestPassthrough:
    def test_legacy_chunks_direct_passthrough(self):
        """相邻正常场景：存量 chunk（无扩展元数据）原样返回。"""
        es = _FakeESClient({})
        hit = _hit("9_1", "普通内容", {"content_hash": "h"})
        out = asyncio.run(expand_search_results(es, 1, [hit]))
        assert out[0]["content"] == "普通内容"
        assert "expansion" not in out[0]["metadata"]

    def test_idempotent_on_already_expanded(self):
        """幂等：带 expansion 标记的命中跳过（缓存复入防线）。"""
        es = _FakeESClient({"42_0": {"content": "# A"}})
        hit = _hit("42_2", "```py\nx=1\n```", {
            "expansion_type": "hierarchical", "content_type": "code",
            "section_anchor_chunk_id": "42_0", "expansion": {"type": "hierarchical"},
        })
        out = asyncio.run(expand_search_results(es, 1, [hit]))
        assert out[0]["content"] == "```py\nx=1\n```"


class TestExpansionConfig:
    def test_enabled_false_global_short_circuit(self):
        """enabled=False 整体短路：不调 ES、命中原样返回。"""
        es = _FakeESClient({"42_0": {"content": "# A 章节正文"}})
        hit = _hit("42_2", "```py\nx=1\n```", {
            "expansion_type": "hierarchical", "content_type": "code",
            "section_anchor_chunk_id": "42_0",
        })
        cfg = ExpansionConfig(enabled=False)
        out = asyncio.run(expand_search_results(es, 1, [hit], expansion_config=cfg))
        assert out[0]["content"] == "```py\nx=1\n```"
        assert "expansion" not in out[0]["metadata"]

    def test_none_config_expands(self):
        """None 配置（存量调用形态）= 全部启用，正常扩展。"""
        es = _FakeESClient({"42_0": {"content": "# A 章节正文"}})
        hit = _hit("42_2", "```py\nx=1\n```", {
            "expansion_type": "hierarchical", "content_type": "code",
            "section_anchor_chunk_id": "42_0",
        })
        out = asyncio.run(expand_search_results(es, 1, [hit], expansion_config=None))
        assert "# A 章节正文" in out[0]["content"]

    def test_include_hierarchical_false_skips_only_hierarchical(self):
        """include_hierarchical=False 只关 hierarchical：该类命中直通，不影响其他类型。"""
        es = _FakeESClient({"42_0": {"content": "# A 章节正文"}})
        hier_hit = _hit("42_2", "```py\nx=1\n```", {
            "expansion_type": "hierarchical", "content_type": "code",
            "section_anchor_chunk_id": "42_0",
        })
        pc_hit = _hit("42_5", "子块内容", {
            "chunk_role": "child", "parent_chunk_id": "42_4",
        })
        es.chunks["42_4"] = {"content": "父块全文"}
        cfg = ExpansionConfig(include_hierarchical=False)
        out = asyncio.run(expand_search_results(es, 1, [hier_hit, pc_hit], expansion_config=cfg))
        assert out[0]["content"] == "```py\nx=1\n```"  # hierarchical 被关，直通
        assert out[1]["content"] == "父块全文"  # parent_child 仍启用，回带生效

    def test_include_hierarchical_true_expands(self):
        """相邻正常场景：include_hierarchical=True（默认）双向扩展生效。"""
        es = _FakeESClient({"42_0": {"content": "# A 章节正文"}})
        hit = _hit("42_2", "```py\nx=1\n```", {
            "expansion_type": "hierarchical", "content_type": "code",
            "section_anchor_chunk_id": "42_0",
        })
        cfg = ExpansionConfig()
        out = asyncio.run(expand_search_results(es, 1, [hit], expansion_config=cfg))
        assert "# A 章节正文" in out[0]["content"]
