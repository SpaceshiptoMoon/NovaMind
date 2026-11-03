"""Agent 绑定内置工具端到端测试：真实注册表 + 真实执行器 + 真实工具 + 脚本化 LLM。

与单测的区别：executor/registry/engine 全部是生产实现（build_tool_registry +
ToolExecutor + AgentEngine），只有 LLM 与外部端口是桩——验证的是完整 ReAct
回路：模型发工具调用 → 引擎收集 → 执行器校验/路由 → 真实工具执行 → 结果
回喂消息流 → 模型消化后终止。

三个场景：
A. 正路径：todo 写入 → 工具 JSON 结果进入消息流 → 模型终止；
B. 参数自纠：畸形参数被执行器校验拦截 → 带修正指引的错误回喂 → 模型
   第二轮修正后成功（失败方向安全的端到端证明）；
C. 端口绑定工具：knowledge_search 经真实执行器打到 fake 检索端口，
   id 从模型参数流入端口 kwargs。
"""
import json
from types import SimpleNamespace

import pytest
from novamind.engines.agent.agent_engine import AgentEngine
from novamind.engines.agent.memory.todo_store import TodoStore
from novamind.engines.agent.tool.context import ToolContext
from novamind.engines.agent.tool.executor import ToolExecutor
from novamind.engines.agent.tool.ports import KnowledgePipelineConfig
from novamind.features.agent.tool.registry_setup import build_tool_registry
from novamind.shared.ai_models.base_model import BaseLLM, LLMResponseWithTools, ToolCall

pytestmark = pytest.mark.unit

CONVERSATION_ID = 42


# ----------------------- 脚本化桩 LLM -----------------------


class ScriptedLLM(BaseLLM):
    """按脚本逐轮应答；记录每轮收到的完整 messages 供断言回喂契约。"""

    def __init__(self, turns: list):
        self.model = "stub"
        self._turns = list(turns)
        self.received: list[list[dict]] = []

    async def generate_with_tools(self, **kwargs):
        # 引擎把对话消息放在 prompt= kwarg（对齐 BaseLLM 接口）
        messages = kwargs.get("prompt") or []
        self.received.append(json.loads(json.dumps(messages, default=str)))
        return self._turns.pop(0)(messages)

    async def generate_text(self, **kwargs):
        raise NotImplementedError

    async def generate_text_stream(self, **kwargs):
        raise NotImplementedError
        yield  # 不可达；保持 async generator 语义


def _call(id_: str, name: str, args: dict) -> LLMResponseWithTools:
    return LLMResponseWithTools(
        content=None,
        tool_calls=[ToolCall(id=id_, name=name, arguments=json.dumps(args))],
        finish_reason="tool_calls",
        usage={"total_tokens": 10},
    )


def _final(text: str) -> LLMResponseWithTools:
    return LLMResponseWithTools(
        content=text, tool_calls=None, finish_reason="stop", usage={"total_tokens": 5},
    )


def _tool_messages(llm: ScriptedLLM) -> list[dict]:
    """最近一轮收到的消息里 role=tool 的条目。"""
    return [m for m in llm.received[-1] if m.get("role") == "tool"]


def _make_engine(todo_store: TodoStore):
    registry = build_tool_registry(todo_store=todo_store, sandbox=None)
    executor = ToolExecutor(registry, mcp_client_manager=None)
    return AgentEngine(tool_executor=executor), executor


# ----------------------- 场景 A：todo 正路径 -----------------------


@pytest.mark.asyncio
async def test_e2e_todo_write_then_final_answer():
    store = TodoStore()
    engine, executor = _make_engine(store)
    tools = executor.resolve_tools_openai_format(["todo"], [])
    llm = ScriptedLLM([
        lambda msgs: _call("c1", "todo", {
            "items": [{"id": "1", "content": "读文档", "status": "in_progress"}],
        }),
        lambda msgs: _final("任务已登记完成"),
    ])
    ctx = ToolContext(
        db_session=None, user_id=1, agent_id=1,
        session_id=None, conversation_id=CONVERSATION_ID,
    )

    events = []
    async for e in engine.run(
        llm_client=llm,
        messages=[{"role": "user", "content": "帮我建个任务清单"}],
        tools=tools,
        context=ctx,
        stream=False,
    ):
        events.append(e)

    # 模型两轮：第一轮发工具调用，第二轮收到工具结果后终止
    assert len(llm.received) == 2
    tool_msgs = _tool_messages(llm)
    assert tool_msgs, "工具结果必须回喂进消息流（role=tool）"
    payload = json.loads(tool_msgs[0]["content"])
    assert "任务清单已更新" in payload["message"]
    assert payload["total"] == 1

    # 工具真实落了存储
    items = store.read(CONVERSATION_ID)
    assert [t["content"] for t in items] == ["读文档"]
    assert items[0]["status"] == "in_progress"

    # 事件面：工具调用事件 + 终答事件
    assert any(e.event_type == "assistant_tool_calls" for e in events)
    finals = [e for e in events if e.event_type == "content"]
    assert finals and finals[-1].data["content"] == "任务已登记完成"


# ----------------------- 场景 B：畸形参数自纠 -----------------------


@pytest.mark.asyncio
async def test_e2e_malformed_args_self_correction():
    store = TodoStore()
    engine, executor = _make_engine(store)
    tools = executor.resolve_tools_openai_format(["todo"], [])
    llm = ScriptedLLM([
        lambda msgs: _call("c1", "todo", {"items": "oops"}),  # 畸形：数组写成字符串
        lambda msgs: _call("c2", "todo", {
            "items": [{"id": "1", "content": "修正后任务", "status": "pending"}],
        }),
        lambda msgs: _final("已修正并登记"),
    ])
    ctx = ToolContext(
        db_session=None, user_id=1, agent_id=1, conversation_id=CONVERSATION_ID,
    )

    events = []
    async for e in engine.run(
        llm_client=llm,
        messages=[{"role": "user", "content": "建清单"}],
        tools=tools,
        context=ctx,
        stream=False,
    ):
        events.append(e)

    assert len(llm.received) == 3, "畸形 → 错误回喂 → 修正 → 终止，共三轮"
    # 第一轮工具结果是校验错误，带修正指引
    err_msgs = [m for m in llm.received[1] if m.get("role") == "tool"]
    assert err_msgs, "校验错误必须回喂"
    assert "参数校验失败" in err_msgs[0]["content"]
    assert "修正" in err_msgs[0]["content"], "必须带修正指引（失败安全方向）"
    # 第二轮修正后真实写入（第 3 轮消息流含两条 tool 消息：错误 + 成功，取末条）
    assert "error" not in json.loads(_tool_messages(llm)[-1]["content"])
    assert [t["content"] for t in store.read(CONVERSATION_ID)] == ["修正后任务"]
    assert any(e.event_type == "content" for e in events)


def _tool_messages_after(llm: ScriptedLLM, index: int) -> list[dict]:
    return [m for m in llm.received[index] if m.get("role") == "tool"]


# ----------------------- 场景 C：端口绑定工具（knowledge_search） -----------------------


class _FakeSearchPort:
    """记录 pipeline_search 收到的 id；返回单条命中。"""

    def __init__(self):
        self.kwargs: dict | None = None

    async def pipeline_search(self, **kwargs):
        self.kwargs = kwargs
        return {
            "items": [SimpleNamespace(
                content="RAG 是检索增强生成的缩写", score=0.9,
                document_id=11, chunk_id=2,
                file_info={"filename": "report.pdf"}, narrative_chapter=None,
            )],
            "insufficient_evidence": False,
            "rewritten_query": kwargs.get("query", ""),
            "rewrite_degraded": False,
            "grade_traces": [],
        }


@pytest.mark.asyncio
async def test_e2e_knowledge_search_through_executor():
    engine, executor = _make_engine(TodoStore())
    tools = executor.resolve_tools_openai_format(["knowledge_search"], [])
    port = _FakeSearchPort()
    llm = ScriptedLLM([
        lambda msgs: _call("c1", "knowledge_search",
                           {"space_id": 3, "kb_id": 7, "query": "RAG 是什么"}),
        lambda msgs: _final("RAG 是检索增强生成"),
    ])
    ctx = ToolContext(
        db_session=None, user_id=8, agent_id=1,
        knowledge_search_port=port,
        knowledge_pipeline=KnowledgePipelineConfig(),
    )

    events = []
    async for e in engine.run(
        llm_client=llm,
        messages=[{"role": "user", "content": "RAG 是什么"}],
        tools=tools,
        context=ctx,
        stream=False,
    ):
        events.append(e)

    # 模型参数 → 执行器 → 工具 → 端口，id 原样流入
    assert port.kwargs["space_id"] == 3
    assert port.kwargs["kb_ids"] == [7]
    # 命中行（含 filename）回喂进消息流
    tool_msgs = _tool_messages(llm)
    assert "report.pdf" in tool_msgs[0]["content"]
    assert "RAG 是检索增强生成的缩写" in tool_msgs[0]["content"]
    finals = [e for e in events if e.event_type == "content"]
    assert finals[-1].data["content"] == "RAG 是检索增强生成"
