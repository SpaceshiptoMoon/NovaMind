"""流式 chat reasoning 落库回归测试（B3，2026-10-07 审计修复）。

背景：流式链路的 reasoning 块只转发前端，从不落库——刷新/归档后思考过程
丢失（agent_messages.reasoning 同构链路在 agent 侧早已落库，qa 掉队）。

修复链路：chat_stream 累积 full_reasoning → add_message(reasoning=...) 列直存
→ done 帧透传终稿 → chat-history 回读。

验证不变量：
1. 正例：LLM 混合流（reasoning+content）→ 落库 reasoning 与流内累积一致，
   done 帧带同一终稿；
2. 反例（相邻场景）：纯 content 流 → 落库 reasoning 为 None，done 帧 reasoning
   也是 None（无思考模式不写空串脏值）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.qa.services.ai_chat_service import AIChatService, ChatPreparation
from novamind.shared.ai_models.base_model import StreamChunk

pytestmark = pytest.mark.unit


class _FakeQaService:
    """最小 QAService 替身：捕获 add_message 收到的 QARequest。"""

    def __init__(self):
        self.saved_request = None
        self.saved_message = None

    async def commit(self):
        pass

    async def add_message(self, request, user_id):
        self.saved_request = request
        # 落库返回值模拟列回读：reasoning 列存的就是请求透传值
        self.saved_message = SimpleNamespace(
            id=99,
            content=request.content,
            role="assistant",
            created_at=None,
            reasoning=request.reasoning,
        )
        return self.saved_message


class _FakeDb:
    def begin_nested(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeLlm:
    """LLM 替身：generate_text_stream_structured 产出预设混合流。"""

    def __init__(self, chunks):
        self._chunks = chunks

    async def generate_text_stream_structured(self, **kwargs):
        for c in self._chunks:
            yield c


def _make_service(llm_chunks) -> AIChatService:
    from novamind.core.middleware.structured_logging import get_logger

    svc = AIChatService.__new__(AIChatService)
    svc.logger = get_logger("test.ai_chat_reasoning_persist")
    qa = _FakeQaService()
    svc.qa_service = qa
    svc.db = _FakeDb()

    async def _prepare(*args, **kwargs):
        return ChatPreparation(
            session_id="s-b3",
            user_message=SimpleNamespace(
                id=1, content="hi", role="user", created_at=None,
            ),
            conversation_history=[{"role": "user", "content": "hi"}],
            llm_client=_FakeLlm(llm_chunks),
            context=[],
            sources=[],
        )

    svc._prepare_chat = _prepare
    return svc, qa


async def _collect(gen):
    events = []
    async for ev in gen:
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_chat_stream_persists_reasoning_and_emits_done():
    """正例：reasoning+content 混合流 → 落库 reasoning 与 done 帧终稿一致。"""
    svc, qa = _make_service([
        StreamChunk(type="reasoning", text="先想一下"),
        StreamChunk(type="reasoning", text="再核对"),
        StreamChunk(type="content", text="答案"),
    ])

    events = await _collect(svc.chat_stream(user_id=1, session_id="s-b3", content="hi"))

    done = next(e for e in events if e["type"] == "done")
    assert done["data"]["reasoning"] == "先想一下再核对"
    # 列直存：落库请求透传同一终稿（None 兜底不写空串）
    assert qa.saved_request.reasoning == "先想一下再核对"
    assert qa.saved_message.reasoning == "先想一下再核对"


@pytest.mark.asyncio
async def test_chat_stream_pure_content_keeps_reasoning_none():
    """反例：纯 content 流 → 落库与 done 帧的 reasoning 均为 None（不写空串）。"""
    svc, qa = _make_service([StreamChunk(type="content", text="普通回答")])

    events = await _collect(svc.chat_stream(user_id=1, session_id="s-b3", content="hi"))

    done = next(e for e in events if e["type"] == "done")
    assert done["data"]["reasoning"] is None
    assert qa.saved_request.reasoning is None
