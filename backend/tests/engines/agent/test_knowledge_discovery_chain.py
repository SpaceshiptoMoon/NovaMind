"""KB 发现链依赖测试：list_spaces → list_knowledge_bases → document_list → knowledge_search。

验证 DEPENDS ON 声明的 id 流动是真实可走通的：上游输出的 JSON 字段名
（spaces[].id / knowledge_bases[].id）与下游参数（space_id / kb_id）逐跳衔接，
list_all_knowledge_bases 捷径入口一次给出 space_id + kb_id 双 id。
端口用 fake 实现（检索管线需 ES，链测试只验证工具层的 id 流动与字段契约）。
"""
import json
from types import SimpleNamespace

import pytest
from novamind.engines.agent.tool.builtins.knowledge_search import KnowledgeSearchTool
from novamind.engines.agent.tool.context import ToolContext
from novamind.engines.agent.tool.ports import KnowledgePipelineConfig, KnowledgeSearchPort

pytestmark = pytest.mark.unit

SPACE_ID = 3
KB_ID = 7
DOC_ID = 11


class FakeDiscoveryPort(KnowledgeSearchPort):
    """最小端口桩：固定返回一套 space/kb/doc，记录 pipeline_search 收到的 id。"""

    def __init__(self) -> None:
        self.pipeline_kwargs: dict | None = None

    async def list_spaces(self, user_id):
        return [SimpleNamespace(id=SPACE_ID, name="空间S", description="d")]

    async def can_access_space(self, space_id, user_id):
        return True

    async def list_knowledge_bases(self, space_id, user_id):
        return [
            SimpleNamespace(id=KB_ID, name="知识库K", space_id=space_id, description="kd")
        ]

    async def list_all_knowledge_bases(self, user_id):
        return [
            SimpleNamespace(
                id=KB_ID, name="知识库K", space_id=SPACE_ID, space_name="空间S",
                description="kd",
            )
        ]

    async def list_documents(self, space_id, kb_id, user_id, page, page_size):
        return SimpleNamespace(
            total=1,
            documents=[SimpleNamespace(id=DOC_ID, filename="report.pdf")],
        )

    async def search(self, user_id, query, top_k, search_mode):
        return []

    async def pipeline_search(self, **kwargs):
        self.pipeline_kwargs = kwargs
        return {
            "items": [],
            "insufficient_evidence": False,
            "rewritten_query": kwargs.get("query", ""),
            "rewrite_degraded": False,
            "grade_traces": [],
        }


def _ctx(port) -> ToolContext:
    return ToolContext(
        db_session=None,
        user_id=8,
        agent_id=1,
        knowledge_search_port=port,
        knowledge_pipeline=KnowledgePipelineConfig(),
    )


@pytest.mark.asyncio
async def test_kb_discovery_chain_ids_flow():
    """发现链逐跳走通：space_id/kb_id 从上游输出流入下游参数。"""
    tool = KnowledgeSearchTool()
    port = FakeDiscoveryPort()
    ctx = _ctx(port)

    # 第 1 跳：list_spaces → 提取 space id
    spaces = json.loads(await tool.execute_tool("list_spaces", {}, ctx))
    assert spaces["total"] == 1
    space_id = spaces["spaces"][0]["id"]
    assert space_id == SPACE_ID

    # 第 2 跳：space_id 流入 list_knowledge_bases → 提取 kb id
    kbs = json.loads(
        await tool.execute_tool("list_knowledge_bases", {"space_id": space_id}, ctx)
    )
    assert kbs["space_id"] == space_id
    kb_id = kbs["knowledge_bases"][0]["id"]
    assert kb_id == KB_ID

    # 第 3 跳：space_id + kb_id 流入 document_list → 拿到文档 id
    docs = json.loads(
        await tool.execute_tool(
            "document_list", {"space_id": space_id, "kb_id": kb_id}, ctx
        )
    )
    assert docs["total"] == 1
    assert docs["documents"][0]["id"] == DOC_ID
    assert docs["documents"][0]["filename"] == "report.pdf"

    # 第 4 跳：检索——链上提取的两个 id 原样进入检索端口
    result = json.loads(
        await tool.execute_tool(
            "knowledge_search",
            {"space_id": space_id, "kb_id": kb_id, "query": "测试查询"},
            ctx,
        )
    )
    assert port.pipeline_kwargs is not None
    assert port.pipeline_kwargs["space_id"] == SPACE_ID
    assert port.pipeline_kwargs["kb_ids"] == [KB_ID]
    assert "message" in result  # 空结果走 message 路径（fake 管线无命中）


@pytest.mark.asyncio
async def test_list_all_shortcut_yields_both_ids():
    """捷径入口：list_all 一次调用同时给出 kb_id 与 space_id（检索链所需双 id）。"""
    tool = KnowledgeSearchTool()
    port = FakeDiscoveryPort()
    ctx = _ctx(port)

    shortcut = json.loads(await tool.execute_tool("list_all_knowledge_bases", {}, ctx))
    kb = shortcut["knowledge_bases"][0]
    assert kb["id"] == KB_ID
    assert kb["space_id"] == SPACE_ID

    # 捷径提取的双 id 直接驱动检索，与逐跳链等价
    await tool.execute_tool(
        "knowledge_search",
        {"space_id": kb["space_id"], "kb_id": kb["id"], "query": "q"},
        ctx,
    )
    assert port.pipeline_kwargs["space_id"] == SPACE_ID
    assert port.pipeline_kwargs["kb_ids"] == [KB_ID]
