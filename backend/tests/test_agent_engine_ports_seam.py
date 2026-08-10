"""批次 3 接缝不变式回归测试。

守护 Agent 引擎端口化的关键不变式：
1. 引擎模块（agent/core/* 的 web_search/knowledge_search/memory 工具与
   long_term/memory_manager）不再 import 被切割的宿主依赖
   （features.knowledge_space/features.user/features.deep_research/
   shared.clients/features.agent.repository/shared.prompts/AgentMemory ORM）。
2. 工具经 context["*_port"] 调用端口，端口缺失时返回「未配置」错误而非崩溃。
3. LongTermMemory 经 LongTermMemoryStorePort/PromptProvider 工作，不接触 repository/ORM。
4. 宿主适配器满足端口协议。
"""
import ast
import asyncio
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.engines.agent.tool.builtins.web_search import WebSearchTool
from novamind.engines.agent.tool.builtins.knowledge_search import (
    KnowledgeSearchTool,
)
from novamind.engines.agent.tool.builtins.memory import MemoryTool
# 仅为把引擎模块预加载进 sys.modules 供 _engine_module() 取源码，名字本身不使用。
from novamind.engines.agent.memory import long_term as long_term_module  # noqa: F401
from novamind.engines.agent.memory import memory_manager as memory_manager_module  # noqa: F401
from novamind.engines.agent.memory.interfaces import LongTermMemoryEntry
from novamind.engines.agent.ports import (
    KnowledgeSearchItem,
    SpaceInfo,
    DocumentListResult,
    DocumentInfo,
    WebSearchResult,
)


# ==================== 不变式 1：引擎模块不再 import 被切割的宿主依赖 ====================

# 每个引擎模块 → 禁止出现的 import 子串
_FORBIDDEN_IMPORTS = {
    "novamind.engines.agent.tool.builtins.web_search": [
        "features.deep_research",
    ],
    "novamind.engines.agent.tool.builtins.knowledge_search": [
        "features.knowledge_space",
        "features.user",
        "shared.clients",
    ],
    "novamind.engines.agent.tool.builtins.memory": [
        "features.agent.repository",
        "features.user.services.model_config_service",
        "shared.clients",
        "features.agent.models.memory",
    ],
    "novamind.engines.agent.memory.long_term": [
        "features.agent.repository",
        "shared.prompts",
        "features.agent.models.memory",
        "sqlalchemy",
    ],
    "novamind.engines.agent.memory.memory_manager": [
        "features.agent.repository",
        "shared.prompts",
    ],
}


def _engine_module(mod_path: str):
    mod = sys.modules[mod_path]
    return mod


def _imported_modules(mod) -> set:
    """用 AST 解析模块源码，提取所有 import 语句引用的顶层模块名。

    只看真实 import 节点，忽略 docstring/注释里的描述性文字（避免误判）。
    """
    tree = ast.parse(inspect.getsource(mod))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                names.add(node.module.split(".")[0])
    return names


def test_engine_modules_no_forbidden_imports():
    """引擎模块不得再 import 被切割的宿主依赖（AST 精确检查，忽略注释/docstring）。"""
    for mod_path, forbidden in _FORBIDDEN_IMPORTS.items():
        mod = _engine_module(mod_path)
        imported = _imported_modules(mod)
        for needle in forbidden:
            # needle 是被切割依赖的子路径（如 features.agent.repository）；
            # 实际 import 形如 novamind.features.agent.repository.xxx，
            # 用子串包含判定（忽略注释/docstring，只看真实 import 节点）。
            hit = any(needle in imp for imp in imported)
            assert not hit, (
                f"{mod_path} 仍 import 被切割的依赖 {needle!r}，批次 3 接缝被破坏；"
                f"实际 import: {sorted(imported)}"
            )


# ==================== 不变式 2：工具经 context 端口工作，缺失时优雅报错 ====================


def _run(coro):
    return asyncio.run(coro)


def test_web_search_tool_missing_port_returns_error():
    tool = WebSearchTool()
    out = _run(tool.execute_tool("web_search", {"query": "x"}, context={}))
    assert "未配置" in out


def test_web_search_tool_uses_port():
    tool = WebSearchTool()
    fake_port = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                WebSearchResult(title="t", url="u", snippet="s"),
            ]
        )
    )
    out = _run(
        tool.execute_tool(
            "web_search",
            {"query": "q", "max_results": 3},
            context={"web_search_port": fake_port},
        )
    )
    fake_port.search.assert_awaited_once_with(query="q", max_results=3)
    data = json.loads(out)
    assert data["total"] == 1
    assert data["results"][0]["title"] == "t"


def test_knowledge_search_tool_missing_port_returns_error():
    tool = KnowledgeSearchTool()
    out = _run(tool.execute_tool("list_spaces", {}, context={}))
    assert "未配置" in out


def test_knowledge_search_tool_list_spaces_uses_port():
    tool = KnowledgeSearchTool()
    fake_port = SimpleNamespace(
        list_spaces=AsyncMock(
            return_value=[SpaceInfo(id=1, name="S", description="d")]
        ),
    )
    out = _run(
        tool.execute_tool("list_spaces", {}, context={"knowledge_search_port": fake_port, "user_id": 7})
    )
    fake_port.list_spaces.assert_awaited_once_with(7)
    data = json.loads(out)
    assert data["spaces"][0]["id"] == 1


def test_knowledge_search_tool_list_kbs_access_denied():
    tool = KnowledgeSearchTool()
    fake_port = SimpleNamespace(
        can_access_space=AsyncMock(return_value=False),
        list_knowledge_bases=AsyncMock(return_value=[]),
    )
    out = _run(
        tool.execute_tool(
            "list_knowledge_bases",
            {"space_id": 5},
            context={"knowledge_search_port": fake_port, "user_id": 7},
        )
    )
    fake_port.can_access_space.assert_awaited_once_with(5, 7)
    assert "无权访问" in out


def test_knowledge_search_tool_search_uses_port():
    tool = KnowledgeSearchTool()
    fake_port = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                KnowledgeSearchItem(
                    content="answer", score=0.91, document_id=2, chunk_id="c1",
                    file_info={"filename": "f.md"},
                )
            ]
        ),
    )
    out = _run(
        tool.execute_tool(
            "knowledge_search",
            {"space_id": 1, "query": "q", "kb_id": 9, "top_k": 5},
            context={"knowledge_search_port": fake_port, "user_id": 7},
        )
    )
    fake_port.search.assert_awaited_once_with(
        space_id=1, user_id=7, query="q", top_k=5,
        search_mode="content_hybrid", kb_id=9,
    )
    data = json.loads(out)
    assert data["results"][0]["filename"] == "f.md"
    assert data["results"][0]["content"] == "answer"  # 短内容不截断


def test_knowledge_search_tool_search_truncates_long_content():
    tool = KnowledgeSearchTool()
    long_text = "x" * 1000
    fake_port = SimpleNamespace(
        search=AsyncMock(
            return_value=[KnowledgeSearchItem(content=long_text, score=0.5)]
        ),
    )
    out = _run(
        tool.execute_tool(
            "knowledge_search",
            {"space_id": 1, "query": "q"},
            context={"knowledge_search_port": fake_port, "user_id": 7},
        )
    )
    data = json.loads(out)
    assert len(data["results"][0]["content"]) == 500


def test_knowledge_search_tool_document_list_uses_port():
    tool = KnowledgeSearchTool()
    fake_port = SimpleNamespace(
        can_access_space=AsyncMock(return_value=True),
        list_documents=AsyncMock(
            return_value=DocumentListResult(
                total=1,
                documents=[DocumentInfo(id=3, filename="a.pdf", status="completed", chunk_count=5)],
            )
        ),
    )
    out = _run(
        tool.execute_tool(
            "document_list",
            {"space_id": 1, "kb_id": 2},
            context={"knowledge_search_port": fake_port, "user_id": 7},
        )
    )
    data = json.loads(out)
    assert data["total"] == 1
    assert data["documents"][0]["chunk_count"] == 5


def test_memory_tool_missing_port_returns_error():
    tool = MemoryTool()
    out = _run(tool.execute_tool("memory", {"action": "add", "category": "fact"}, context={}))
    assert "未配置" in out


def test_memory_tool_add_uses_port():
    tool = MemoryTool()
    entry = LongTermMemoryEntry(
        id=42, agent_id=1, user_id=7, category="fact", content="c",
    )
    fake_store = SimpleNamespace(
        list_by_agent=AsyncMock(return_value=([], 0)),
        find_similar=AsyncMock(return_value=None),
        create=AsyncMock(return_value=entry),
        flush=AsyncMock(return_value=None),
    )
    # memory 工具 _add 会调用 scan_memory_content，再调 store
    out = _run(
        tool.execute_tool(
            "memory",
            {"action": "add", "category": "fact", "content": "hello"},
            context={"memory_store_port": fake_store, "user_id": 7, "agent_id": 1},
        )
    )
    data = json.loads(out)
    assert data["message"] == "记忆已添加"
    assert data["id"] == 42
    fake_store.create.assert_awaited_once()


def test_memory_tool_remove_uses_port_and_search_port():
    tool = MemoryTool()
    entry = LongTermMemoryEntry(
        id=42, agent_id=1, user_id=7, category="fact", content="c",
    )
    fake_store = SimpleNamespace(
        find_by_content_contains=AsyncMock(return_value=entry),
        delete=AsyncMock(return_value=True),
        flush=AsyncMock(return_value=None),
    )
    fake_search = SimpleNamespace(delete_memory=AsyncMock(return_value=True))
    out = _run(
        tool.execute_tool(
            "memory",
            {"action": "remove", "old_content": "c"},
            context={
                "memory_store_port": fake_store,
                "memory_search_port": fake_search,
                "user_id": 7,
                "agent_id": 1,
            },
        )
    )
    data = json.loads(out)
    assert data["message"] == "记忆已移除"
    fake_store.delete.assert_awaited_once_with(42)
    fake_search.delete_memory.assert_awaited_once_with(1, 42)


# ==================== 不变式 3：LongTermMemory 经端口工作 ====================


def test_long_term_store_uses_store_and_search_ports():
    from novamind.engines.agent.memory.long_term import LongTermMemory

    entry = LongTermMemoryEntry(
        id=10, agent_id=1, user_id=2, category="fact", content="c",
    )
    fake_store = SimpleNamespace(
        create=AsyncMock(return_value=entry),
    )
    fake_search = SimpleNamespace(
        index_memory=AsyncMock(return_value=None),
    )
    # embedding_factory 返回一个能 generate_embedding 的假客户端
    fake_embedding = SimpleNamespace(generate_embedding=AsyncMock(return_value=[0.1, 0.2]))
    fake_prompt = SimpleNamespace(format=AsyncMock(return_value="prompt"))

    async def embedding_factory():
        return fake_embedding

    lt = LongTermMemory(
        memory_store=fake_store,
        llm_client_factory=lambda: None,
        prompt_provider=fake_prompt,
        memory_search=fake_search,
        embedding_factory=embedding_factory,
    )
    result = _run(lt.store(agent_id=1, user_id=2, category="fact", content="c"))
    assert result.id == 10
    fake_store.create.assert_awaited_once()
    # _index_to_es 应经 embedding_factory 生成向量并调 search.index_memory
    fake_embedding.generate_embedding.assert_awaited_once_with("c")
    fake_search.index_memory.assert_awaited_once()


def test_long_term_replace_uses_find_by_content_contains():
    from novamind.engines.agent.memory.long_term import LongTermMemory

    entry = LongTermMemoryEntry(
        id=11, agent_id=1, user_id=2, category="fact", content="old",
    )
    fake_store = SimpleNamespace(
        find_by_content_contains=AsyncMock(return_value=entry),
        update_content=AsyncMock(return_value=None),
        flush=AsyncMock(return_value=None),
    )
    lt = LongTermMemory(
        memory_store=fake_store,
        llm_client_factory=lambda: None,
        prompt_provider=SimpleNamespace(),
    )
    out = _run(lt.replace(agent_id=1, user_id=2, category="fact", old_content="ol", new_content="new"))
    assert out["message"] == "记忆已更新"
    fake_store.find_by_content_contains.assert_awaited_once_with(1, 2, "ol")
    fake_store.update_content.assert_awaited_once_with(11, "new")


def test_long_term_consolidate_uses_prompt_provider():
    from unittest.mock import Mock

    from novamind.engines.agent.memory.long_term import LongTermMemory
    from novamind.engines.agent.memory.interfaces import MemoryMessage

    entry = LongTermMemoryEntry(
        id=99, agent_id=1, user_id=2, category="fact", content="x",
    )
    # PromptProvider.format 是同步方法（返回 str），用普通 Mock 而非 AsyncMock
    fake_prompt = SimpleNamespace(format=Mock(return_value="prompt-text"))
    fake_store = SimpleNamespace(
        find_similar=AsyncMock(return_value=None),
        create=AsyncMock(return_value=entry),
    )
    # LLM 返回一个合法 JSON 数组
    fake_llm = SimpleNamespace(generate_text=AsyncMock(return_value='[{"category":"fact","content":"x"}]'))

    async def llm_factory():
        return fake_llm

    lt = LongTermMemory(
        memory_store=fake_store,
        llm_client_factory=llm_factory,
        prompt_provider=fake_prompt,
    )

    msgs = [MemoryMessage(role="user", content="hi") for _ in range(6)]
    count = _run(lt.consolidate(agent_id=1, user_id=2, conversation_id=3, messages=msgs))
    # 关键断言：prompt_provider.format 被同步调用（取代 PromptManager.format_prompt），
    # 且 key 为字符串字面量（引擎不 import PromptTemplate 枚举）
    fake_prompt.format.assert_called_once()
    args, kwargs = fake_prompt.format.call_args
    assert args[0] == "agent_long_term_memory"
    # 记忆提取 1 条且去重通过 → store 成功 → 计数 1
    assert count == 1