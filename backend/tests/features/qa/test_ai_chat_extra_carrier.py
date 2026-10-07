"""非流式 chat 结果 ai_message 携带 extra 回归测试。

背景（2026-10-07 审计）：chat() 组装 result 时曾漏掉 extra 键——AI 消息
落库时已写入 sources/answer_status/confidence（经 _build_ai_extra），但
非流式响应的 ai_message dict 不含 extra，前端 MessageList 统一读
msg.extra.sources 时拿不到数据，非流式会话的来源角标/置信度恒不渲染。
修复（0879e8b）后 extra 与落库形状对齐。

验证不变量：
1. 正例：chat() 返回的 ai_message["extra"] 与落库消息对象的 extra 一致
   （sources/answer_status/confidence 齐全）；
2. 反例（相邻场景）：extra 为 None（历史数据/无 RAG）时键仍存在——
   前端 getExtra 读 msg.extra ?? {} 安全，键缺失与 None 值是两回事。
"""
import pytest

from novamind.features.qa.services.ai_chat_service import AIChatService, ChatPreparation

pytestmark = pytest.mark.unit


class _FakeQaService:
    """最小 QAService 替身：记录 add_message 收到的 extra 并原样回传。"""

    def __init__(self, stored_extra):
        self.stored_extra = stored_extra
        self.saved_extra = None

    async def commit(self):
        pass

    async def add_message(self, request, user_id):
        self.saved_extra = request.extra
        return _FakeMessage(extra=self.stored_extra)


class _FakeMessage:
    def __init__(self, extra):
        self.id = 42
        self.content = "回答内容"
        self.role = "assistant"
        self.created_at = "2026-10-07T00:00:00"
        self.extra = extra


class _FakeDb:
    """begin_nested savepoint 替身（async context manager，退出即视为提交）。"""

    def begin_nested(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeLlm:
    async def generate_text(self, **kwargs):
        return "回答内容"


def _make_service(qa_service: _FakeQaService) -> AIChatService:
    from novamind.core.middleware.structured_logging import get_logger

    svc = AIChatService.__new__(AIChatService)
    svc.logger = get_logger("test.ai_chat_extra_carrier")
    svc.qa_service = qa_service
    svc.db = _FakeDb()
    return svc


def _make_prep() -> ChatPreparation:
    return ChatPreparation(
        session_id="s-1",
        user_message=_FakeMessage(extra=None),
        conversation_history=[{"role": "user", "content": "hi"}],
        llm_client=_FakeLlm(),
        context=[],
        sources=[{"chunk_id": "c1", "content": "片段"}],
        answer_status="answered",
        confidence=0.86,
    )


@pytest.mark.asyncio
async def test_chat_nonstream_ai_message_carries_extra_with_sources():
    """正例：ai_message.extra 与落库形状一致（sources/answer_status/confidence 在场）。"""
    stored_extra = {
        "sources": [{"chunk_id": "c1", "content": "片段"}],
        "answer_status": "answered",
        "confidence": 0.86,
    }
    qa = _FakeQaService(stored_extra)
    svc = _make_service(qa)

    async def _prepare(*args, **kwargs):
        return _make_prep()

    svc._prepare_chat = _prepare
    result = await svc.chat(user_id=1, content="hi")

    assert "extra" in result["ai_message"]
    assert result["ai_message"]["extra"] == stored_extra
    assert result["ai_message"]["extra"]["sources"] == [{"chunk_id": "c1", "content": "片段"}]
    # 落库侧收到的也是 _build_ai_extra 的产物（同一来源，不二次加工）
    assert qa.saved_extra == stored_extra


@pytest.mark.asyncio
async def test_chat_nonstream_ai_message_extra_key_present_when_none():
    """反例：extra=None 时键仍存在（前端 msg.extra ?? {} 安全依赖键在场或可空）。"""
    qa = _FakeQaService(None)
    svc = _make_service(qa)

    async def _prepare(*args, **kwargs):
        return _make_prep()

    svc._prepare_chat = _prepare
    result = await svc.chat(user_id=1, content="hi")

    assert "extra" in result["ai_message"]
    assert result["ai_message"]["extra"] is None
