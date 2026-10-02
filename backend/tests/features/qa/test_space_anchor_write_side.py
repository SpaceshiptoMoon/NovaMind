"""space 锚点写侧收口回归测试。

收口语义：ai_chat_service._prepare_chat 落消息时回填 message.space_id
（user + assistant 均带），qa_service 反馈/citation_click 直接读消息行，
不再从会话 RAG 配置兜底。

- 正例：消息行有锚点 → 运营链路直接用
- 反例：消息行 NULL → 不再查会话配置兜底（锚点缺失如实传递，宁缺勿猜）
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novamind.features.qa.services.qa_service import QAService

pytestmark = pytest.mark.unit


def _make_service(message) -> QAService:
    """最小桩：repository.get_by_id 返回预设消息，cache_service 关闭。"""
    svc = QAService.__new__(QAService)
    from novamind.core.middleware.structured_logging import get_logger

    svc.logger = get_logger("test.space_anchor")
    svc.repository = SimpleNamespace(
        get_by_id=AsyncMock(return_value=message),
        session=None,
    )
    svc.cache_service = None
    return svc


def _msg(space_id: int | None) -> SimpleNamespace:
    from novamind.shared.utils.time_utils import now_china

    return SimpleNamespace(
        id=7, user_id=1, role="assistant", session_id="s-anchor",
        space_id=space_id, kb_id=20, created_at=now_china(),
    )


@pytest.mark.asyncio
async def test_citation_click_uses_message_row_space_directly() -> None:
    """正例：消息行有空间锚点 → 事件锚点直接取消息行。"""
    from novamind.features.qa.schemas.qa import CitationClickRequest

    svc = _make_service(_msg(space_id=10))
    recorded = []

    class _FakeRecorder:
        async def record(self, **kwargs):
            recorded.append(kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "novamind.features.knowledge_ops.services.event_recorder.EventRecorder",
            _FakeRecorder,
        )
        await svc.record_citation_click(
            message_id=7,
            request=CitationClickRequest(
                source_index=1, chunk_id="ck", document_id=5, kb_id=20
            ),
            user_id=1,
        )

    assert recorded[0]["space_id"] == 10


@pytest.mark.asyncio
async def test_citation_click_null_space_not_backfilled() -> None:
    """反例：消息行 NULL → 锚点缺失如实传递（None），不查会话配置兜底。

    会话若真绑定了空间也不取——收口后锚点唯一权威来源是消息行。
    """
    from novamind.features.qa.schemas.qa import CitationClickRequest

    svc = _make_service(_msg(space_id=None))
    # 兜底若还在，会走 _get_session_config_with_cache——桩上该方法不存在，
    # 一旦被调用即 AttributeError 使测试失败（结构性反证）。
    recorded = []

    class _FakeRecorder:
        async def record(self, **kwargs):
            recorded.append(kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "novamind.features.knowledge_ops.services.event_recorder.EventRecorder",
            _FakeRecorder,
        )
        await svc.record_citation_click(
            message_id=7,
            request=CitationClickRequest(
                source_index=1, chunk_id="ck", document_id=5, kb_id=20
            ),
            user_id=1,
        )

    assert len(recorded) == 1
    assert recorded[0]["space_id"] is None


@pytest.mark.asyncio
async def test_feedback_null_space_not_backfilled() -> None:
    """反馈落行：消息行 NULL → space 冗余存 NULL，不查会话配置兜底。"""
    from novamind.features.qa.schemas.qa import MessageFeedbackRequest

    svc = _make_service(_msg(space_id=None))
    upserted = {}

    class _FakeFeedbackRepo:
        def __init__(self, _session):
            pass

        async def upsert(self, **kwargs):
            upserted.update(kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "novamind.features.qa.services.qa_service.MessageFeedbackRepository",
            _FakeFeedbackRepo,
        )
        await svc.set_message_feedback(
            message_id=7,
            request=MessageFeedbackRequest(rating="down", comment=None),
            user_id=1,
        )

    assert upserted["space_id"] is None


@pytest.mark.asyncio
async def test_prepare_chat_request_carries_space_id() -> None:
    """写侧收口源点：user/assistant 消息落库时 QARequest 均带空间锚点。

    端到端桩太重（LLM/ES/模型配置全依赖），此处验证数据流契约：
    ChatPreparation.rag_space 字段存在，user 消息在 _prepare_chat 构造处
    带 space_id=rag_space，assistant 消息四处构造均透传 prep.rag_space——
    防「字段被静默删掉」的契约钉子。
    """
    import inspect

    import novamind.features.qa.services.ai_chat_service as ai_chat_module
    from novamind.features.qa.services.ai_chat_service import ChatPreparation

    assert "rag_space" in ChatPreparation.__dataclass_fields__

    src = inspect.getsource(ai_chat_module)
    # user 消息构造（_prepare_chat 内）
    assert "space_id=rag_space, extra=extra" in src
    # assistant 消息构造：四处 QARequest 均透传 prep.rag_space
    assert src.count("space_id=prep.rag_space") == 4
    # ChatPreparation 返回体携带锚点
    assert "rag_space=rag_space" in src
