"""子 agent 客户端工厂（context_assembly.build_llm_vlm_client_factory）回归测试。

历史 bug：旧私有方法 ``AgentChatService._subagent_client_factory`` 被误叠
``@staticmethod`` 且签名保留 ``(self, user_id)``，实例访问时实参 user_id 落到
形参 self、真形参 user_id 缺参，Agent 对话在构造 SubAgentRunner 时直接
TypeError（端到端实测暴露，单测此前未覆盖该工厂）。重构后工厂收口到
``context_assembly.build_llm_vlm_client_factory``。

契约：引擎（SubAgentRunner）只收 ``async factory(model) -> 客户端``；
user_id 由业务侧闭包绑定，LLM 优先、失败回退 VLM。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from novamind.features.agent.services.context_assembly import (
    build_llm_vlm_client_factory,
)

pytestmark = pytest.mark.unit


def _build_factory(llm, vlm, user_id: int = 7):
    """构造被测工厂：ModelConfigService 桩只注入双取客户端方法，user_id 绑定 7。"""
    mcs = SimpleNamespace(
        get_llm_client_by_model=AsyncMock(return_value=llm),
        get_vlm_client_by_model=AsyncMock(return_value=vlm),
    )
    return build_llm_vlm_client_factory(mcs, user_id), mcs


@pytest.mark.asyncio
async def test_factory_binds_user_and_returns_llm_client():
    """factory(model) 优先返回 LLM 客户端，且以绑定的 user_id 调模型配置服务。"""
    llm, vlm = object(), object()
    factory, mcs = _build_factory(llm, vlm)
    assert callable(factory)

    client = await factory("glm-5.3-flash")
    assert client is llm
    mcs.get_llm_client_by_model.assert_awaited_once_with(7, "glm-5.3-flash")


@pytest.mark.asyncio
async def test_factory_falls_back_to_vlm_on_llm_failure():
    """LLM 取客户端失败时回退 VLM 客户端（业务侧降级策略不进引擎）。"""
    llm, vlm = object(), object()
    factory, mcs = _build_factory(llm, vlm)
    mcs.get_llm_client_by_model = AsyncMock(side_effect=RuntimeError("额度不可用"))

    client = await factory("qwen3.8-27b")
    assert client is vlm
    mcs.get_vlm_client_by_model.assert_awaited_once_with(7, "qwen3.8-27b")


def test_factory_signature_takes_model_and_binds_user_id():
    """签名守卫：工厂构造收 (model_config_service, user_id)，产物闭包只暴露 (model)。

    历史回归：旧实现误叠 @staticmethod 时实参错位（user_id 落 self）以
    TypeError 暴露；新契约下对构造签名与产物工厂形参做静态断言提前拦截。
    """
    import inspect

    params = list(inspect.signature(build_llm_vlm_client_factory).parameters)
    assert params == ["model_config_service", "user_id"]
    factory, _ = _build_factory(object(), object())
    assert list(inspect.signature(factory).parameters) == ["model"]
    assert not inspect.ismethod(factory)
