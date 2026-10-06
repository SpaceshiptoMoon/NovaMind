"""非流式 chat 异常分类：QAError（客户端语义）原样上抛，不得裹成 LLMServiceError(500)。

回归背景：2026-10-07 QA 链路实测发现空消息请求返回 500 LLM_SERVICE_ERROR——
chat() 的 except Exception 兜底把 _prepare_chat 抛出的 InvalidMessageContentError
（注册 400）也包了进去，用户输入错误被伪装成服务器故障。
"""
import pytest

from novamind.features.qa.exceptions import InvalidMessageContentError
from novamind.features.qa.services.ai_chat_service import AIChatService


class _CleanupSpy:
    calls = 0

    async def _cleanup_user_message(self, message):
        type(self).calls += 1


def _make_service() -> AIChatService:
    from novamind.core.middleware.structured_logging import get_logger

    svc = AIChatService.__new__(AIChatService)
    svc.logger = get_logger("test.ai_chat_error_classification")
    return svc


@pytest.mark.asyncio
async def test_chat_invalid_content_raises_qa_error_not_llm_service_error():
    """空消息（QAError 子类）原样上抛：类型与 code 保持 400 语义，不裹 500。"""
    svc = _make_service()

    async def _prepare(*args, **kwargs):
        raise InvalidMessageContentError("消息内容不能为空")

    svc._prepare_chat = _prepare

    with pytest.raises(InvalidMessageContentError) as ei:
        await svc.chat(user_id=1, content="   ")
    assert ei.value.code == "INVALID_MESSAGE_CONTENT"
    # 客户端输入错误不属于 LLM 故障，不应被裹上「LLM 服务错误」前缀
    assert "LLM 服务错误" not in ei.value.message


@pytest.mark.asyncio
async def test_chat_unexpected_error_still_wrapped_as_llm_service_error():
    """相邻正常场景不误伤：真未知异常仍走 LLMServiceError 兜底（500 语义）。"""
    svc = _make_service()

    async def _prepare(*args, **kwargs):
        raise RuntimeError("boom")

    svc._prepare_chat = _prepare

    from novamind.features.qa.exceptions import LLMServiceError

    with pytest.raises(LLMServiceError):
        await svc.chat(user_id=1, content="hi")


@pytest.mark.asyncio
async def test_chat_qa_error_cleans_up_user_message():
    """QAError 分支同样执行用户消息清理安全网（与 LLMServiceError 分支一致）。"""
    svc = _make_service()

    async def _prepare(*args, **kwargs):
        raise InvalidMessageContentError("消息内容不能为空")

    svc._prepare_chat = _prepare
    cleaned = []

    async def _cleanup(m):
        cleaned.append(m)

    svc._cleanup_user_message = _cleanup

    with pytest.raises(InvalidMessageContentError):
        await svc.chat(user_id=1, content="   ")
    assert cleaned == [None]  # user_message 尚未产生（prepare 抛出），清理被调用
