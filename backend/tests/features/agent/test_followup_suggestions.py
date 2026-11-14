"""追问建议生成回归测试（DeerFlow suggestions 同构：每轮回答后生成 follow-up pills）。

覆盖：
1. _parse_followup_suggestions 纯解析：裸数组 / markdown 围栏包裹 / 前后杂质 /
   非法输出返回空 / 超长条目丢弃 / max_items 截断
2. generate_followup_suggestions：
   - 会话不存在 / 他人会话 → SessionNotFoundError（归属防线与消息读取同口径，HTTP 404）
   - 空会话（message_count=0）→ [] 且不触发 LLM
   - 尾部窗口全是 tool 等过程行 → [] 且不触发 LLM
   - 正常路径：prompt 只含 user/assistant 行且限 6 条窗口、解析出 3 条建议
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.features.agent.exceptions import AgentError, SessionNotFoundError
from novamind.features.agent.services.chat_service import AgentChatService

pytestmark = pytest.mark.unit


def _msg(id_, role, content):
    """构造 agent_messages 行桩（追问只读 role/content）"""
    return SimpleNamespace(id=id_, role=role, content=content)


def _conv(user_id=7, message_count=5, agent_id=3):
    return SimpleNamespace(id=1, user_id=user_id, message_count=message_count, agent_id=agent_id)


def _build_service(conv, messages, llm_content='["追问一", "追问二", "追问三"]'):
    """绕过 __init__ 手动注入追问链路依赖（其余属性本测试不触达）"""
    svc = AgentChatService.__new__(AgentChatService)
    svc.session_repo = SimpleNamespace(get_by_session_id=AsyncMock(return_value=conv))
    svc.msg_repo = SimpleNamespace(
        list_recent_by_conversation=AsyncMock(return_value=messages)
    )
    svc.agent_service = SimpleNamespace(
        agent_repo=SimpleNamespace(
            get_by_id=AsyncMock(
                return_value=SimpleNamespace(llm_model="cfg-model", name="知识库问答助手")
            )
        )
    )
    llm_client = SimpleNamespace(
        generate_with_tools=AsyncMock(return_value=SimpleNamespace(content=llm_content))
    )
    svc.model_config_service = SimpleNamespace(
        get_llm_client_by_model=AsyncMock(return_value=llm_client),
        get_vlm_client_by_model=AsyncMock(),
        get_user_default_model_name=AsyncMock(return_value="default-model"),
    )
    return svc


# ==================== 解析纯函数 ====================


def test_parse_bare_json_array() -> None:
    out = AgentChatService._parse_followup_suggestions('["a", "b", "c"]', 3)
    assert out == ["a", "b", "c"]


def test_parse_strips_markdown_fence_and_prose() -> None:
    text = '好的，以下是建议：\n```json\n["问题1？", "问题2？", "问题3？"]\n```\n以上。'
    out = AgentChatService._parse_followup_suggestions(text, 3)
    assert out == ["问题1？", "问题2？", "问题3？"]


def test_parse_invalid_output_returns_empty() -> None:
    assert AgentChatService._parse_followup_suggestions("抱歉我无法生成", 3) == []
    assert AgentChatService._parse_followup_suggestions("", 3) == []
    assert AgentChatService._parse_followup_suggestions("[ Broken json", 3) == []


def test_parse_drops_overlong_and_caps_items() -> None:
    long = "x" * 200
    text = json.dumps(["短问题？", long, "短问题2？", "短问题3？", "多余？"], ensure_ascii=False)
    out = AgentChatService._parse_followup_suggestions(text, 3)
    assert long not in out
    assert len(out) == 3


# ==================== 生成主链路 ====================


@pytest.mark.asyncio
async def test_generate_rejects_missing_or_foreign_session() -> None:
    """会话不存在 / 他人会话 → SessionNotFoundError（AgentError 子类，HTTP 404 与消息读取同口径）"""
    svc = _build_service(conv=None, messages=[])
    with pytest.raises(SessionNotFoundError):
        await svc.generate_followup_suggestions(7, "sess-x")

    svc = _build_service(conv=_conv(user_id=99), messages=[_msg(1, "user", "hi")])
    with pytest.raises(SessionNotFoundError):
        await svc.generate_followup_suggestions(7, "sess-1")

    # SessionNotFoundError 必须仍是 AgentError 子类：兜底 except AgentError 的调用方不被破坏
    svc = _build_service(conv=None, messages=[])
    with pytest.raises(AgentError):
        await svc.generate_followup_suggestions(7, "sess-y")


@pytest.mark.asyncio
async def test_generate_empty_session_skips_llm() -> None:
    """空会话直接返回空数组，不触发 LLM 调用"""
    svc = _build_service(conv=_conv(message_count=0), messages=[])
    out = await svc.generate_followup_suggestions(7, "sess-1")
    assert out == []
    svc.model_config_service.get_llm_client_by_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_all_tool_rows_skips_llm() -> None:
    """尾部窗口全是 tool 过程行（无 user/assistant 文本）→ 空数组且不调 LLM"""
    msgs = [_msg(i, "tool", '{"result": 1}') for i in range(5)]
    svc = _build_service(conv=_conv(), messages=msgs)
    out = await svc.generate_followup_suggestions(7, "sess-1")
    assert out == []
    svc.model_config_service.get_llm_client_by_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_builds_prompt_and_parses(monkeypatch) -> None:
    """正常路径：prompt 只含 user/assistant 行（tool 行过滤）、窗口限 6 条、解析 3 条"""
    msgs = [
        _msg(1, "user", "旧问题（应被 6 条窗口挤掉）"),
        _msg(2, "user", "问题A"),
        _msg(3, "assistant", "回答A"),
        _msg(4, "tool", '{"result": 1}'),
        _msg(5, "user", "问题B"),
        _msg(6, "assistant", "回答B"),
        _msg(7, "user", "问题C"),
        _msg(8, "assistant", "回答C"),
    ]
    svc = _build_service(conv=_conv(), messages=msgs)

    captured: dict = {}

    class _FakePromptManager:
        @staticmethod
        def format_prompt(template: str, **kw) -> str:
            captured["template"] = template
            captured["conversation_text"] = kw["conversation_text"]
            return f"PROMPT<{kw['conversation_text']}>"

    import novamind.features.agent.services.chat_service as cs

    monkeypatch.setattr(cs, "PromptManager", _FakePromptManager)

    out = await svc.generate_followup_suggestions(7, "sess-1")

    assert captured["template"] == "agent_followup_suggestions"
    text = captured["conversation_text"]
    assert "旧问题" not in text  # 过滤 tool 行后剩 7 条，6 条窗口挤掉最旧的「旧问题」
    assert "问题A" in text
    assert "回答B" in text and "问题C" in text
    assert "tool" not in text  # 过程行不进 prompt
    assert text.count("\n") == 5  # 6 条消息 5 个换行
    assert out == ["追问一", "追问二", "追问三"]

    # 模型解析走 agent.llm_model（cfg-model），未传 llm_model
    svc.model_config_service.get_llm_client_by_model.assert_awaited_once_with(7, "cfg-model")


@pytest.mark.asyncio
async def test_generate_llm_model_override_passthrough() -> None:
    """显式 llm_model 透传模型解析（覆盖 agent 配置）"""
    svc = _build_service(
        conv=_conv(),
        messages=[_msg(1, "user", "你好"), _msg(2, "assistant", "你好！")],
        llm_content='["q"]',
    )
    await svc.generate_followup_suggestions(7, "sess-1", llm_model="custom-model")
    svc.model_config_service.get_llm_client_by_model.assert_awaited_once_with(7, "custom-model")


@pytest.mark.asyncio
async def test_generate_unparseable_llm_output_returns_empty() -> None:
    """模型输出不可解析 → 空数组（增强能力静默降级，不抛错）"""
    svc = _build_service(
        conv=_conv(),
        messages=[_msg(1, "user", "你好"), _msg(2, "assistant", "你好！")],
        llm_content="抱歉，我无法按要求输出",
    )
    out = await svc.generate_followup_suggestions(7, "sess-1")
    assert out == []
