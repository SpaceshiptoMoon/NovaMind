"""子 agent 客户端工厂（_subagent_client_factory）回归测试。

历史 bug：方法被误叠 ``@staticmethod`` 且签名保留 ``(self, user_id)``，
实例访问 ``self._subagent_client_factory(user_id)`` 时实参 user_id 落到形参
self、真形参 user_id 缺参，Agent 对话在构造 SubAgentRunner 时直接
TypeError（端到端实测暴露，单测此前未覆盖该工厂）。

契约：引擎（SubAgentRunner）只收 ``async factory(model) -> 客户端``；
本工厂由业务侧闭包 user_id，LLM 优先、失败回退 VLM。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.features.agent.services.chat_service import AgentChatService

pytestmark = pytest.mark.unit


def _build_service(llm, vlm) -> AgentChatService:
    """绕过 __init__ 构造最小 ChatService：只注入模型配置服务的双取客户端方法。"""
    svc = AgentChatService.__new__(AgentChatService)
    svc.model_config_service = SimpleNamespace(
        get_llm_client_by_model=AsyncMock(return_value=llm),
        get_vlm_client_by_model=AsyncMock(return_value=vlm),
    )
    return svc


@pytest.mark.asyncio
async def test_factory_binds_user_and_returns_llm_client():
    """实例调用传 user_id 拿到 async 工厂；factory(model) 优先返回 LLM 客户端。"""
    llm, vlm = object(), object()
    svc = _build_service(llm, vlm)

    factory = svc._subagent_client_factory(7)
    assert callable(factory)

    client = await factory("glm-5.3-flash")
    assert client is llm
    svc.model_config_service.get_llm_client_by_model.assert_awaited_once_with(
        7, "glm-5.3-flash"
    )


@pytest.mark.asyncio
async def test_factory_falls_back_to_vlm_on_llm_failure():
    """LLM 取客户端失败时回退 VLM 客户端（业务侧降级策略不进引擎）。"""
    llm, vlm = object(), object()
    svc = _build_service(llm, vlm)
    svc.model_config_service.get_llm_client_by_model = AsyncMock(
        side_effect=RuntimeError("额度不可用")
    )

    client = await svc._subagent_client_factory(7)("qwen3.8-27b")
    assert client is vlm
    svc.model_config_service.get_vlm_client_by_model.assert_awaited_once_with(
        7, "qwen3.8-27b"
    )


def test_factory_signature_is_instance_method_with_user_id():
    """签名守卫：必须为 (self, user_id) 实例方法形态，防再次误叠 @staticmethod。

    误叠后实例访问只收到一个位置实参（user_id 落到 self），运行期以
    "missing user_id" TypeError 暴露；此处用签名静态断言提前拦截。
    """
    import inspect

    params = list(inspect.signature(AgentChatService._subagent_client_factory).parameters)
    assert params == ["self", "user_id"]
    assert not isinstance(
        inspect.getattr_static(AgentChatService, "_subagent_client_factory"),
        staticmethod,
    )
