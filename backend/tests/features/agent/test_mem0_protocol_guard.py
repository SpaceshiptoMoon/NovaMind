"""Mem0 装配协议守卫：非 openai 兼容协议的默认模型必须在装配期拒绝（降级 builtin）。

背景：mem0 只有 openai provider，anthropic 协议端点用 OpenAI SDK 调用会得到
包着错误的 200（choices=null）→ reconcile 全空转后才在提取期报错。守卫把
失败左移到装配期，由 _create_memory_manager 的 except 降级 builtin。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from novamind.features.user.exceptions import ModelConfigNotFoundError
from novamind.features.user.services.model_config_service import ModelConfigService

pytestmark = pytest.mark.unit


def _service_with(params_by_type: dict[str, dict]) -> ModelConfigService:
    svc = ModelConfigService.__new__(ModelConfigService)
    svc.model_config = None  # 不触碰 DB：get_model_connection_params 被替换
    async def fake_get(user_id: int, model_type: str) -> dict:
        return params_by_type[model_type]
    svc.get_model_connection_params = AsyncMock(side_effect=fake_get)
    return svc


def _params(protocol: str) -> dict:
    return {
        "base_url": "http://gw.example/v1",
        "api_key": "k" * 10,
        "model": "some-model",
        "protocol": protocol,
    }


# ==================== get_model_connection_params 透出 protocol ====================

@pytest.mark.asyncio
async def test_get_model_connection_params_includes_protocol():
    """返回值必须含 protocol 键（Mem0 守卫依赖）。"""
    svc = ModelConfigService.__new__(ModelConfigService)
    svc.get_user_default_model_name = AsyncMock(return_value="m-1")
    cred = __import__("types").SimpleNamespace(
        protocol="openai", model="m-1", api_key="cipher", base_url="http://x/v1",
        extra_config=None,
    )
    svc.get_credentials_by_model = AsyncMock(return_value=cred)

    from novamind.shared.utils.crypto import decrypt_api_key_async

    params = await svc.get_model_connection_params(1, "llm")

    assert params["protocol"] == "openai"
    assert set(params) == {"base_url", "api_key", "model", "protocol"}


# ==================== 协议守卫（经 _create_memory_manager 同款分派逻辑） ====================

@pytest.mark.asyncio
async def test_anthropic_default_model_rejected_at_assembly():
    """llm 默认模型为 anthropic 协议 → 装配期抛 ModelConfigNotFoundError。"""
    from novamind.features.agent.services.chat_service import AgentChatService as ChatService

    svc = _service_with({"llm": _params("anthropic"), "embedding": _params("openai")})
    chat = ChatService.__new__(ChatService)
    chat.model_config_service = svc

    with pytest.raises(ModelConfigNotFoundError, match="anthropic"):
        await chat._build_memory_reconciler(
            user_id=1, agent_id=11, memory_store=None, memory_search=None,
        )


@pytest.mark.asyncio
async def test_embedding_protocol_mismatch_also_rejected():
    """embedding 协议非 openai 同样拒绝（embedder 也走 mem0 openai provider）。"""
    from novamind.features.agent.services.chat_service import AgentChatService as ChatService

    svc = _service_with({"llm": _params("openai"), "embedding": _params("ollama")})
    chat = ChatService.__new__(ChatService)
    chat.model_config_service = svc

    with pytest.raises(ModelConfigNotFoundError, match="embedding"):
        await chat._build_memory_reconciler(
            user_id=1, agent_id=11, memory_store=None, memory_search=None,
        )


@pytest.mark.asyncio
async def test_openai_compatible_passes_guard_and_builds():
    """双 openai 协议 → 守卫放行，reconciler 正常构造（不实际建 AsyncMemory）。"""
    from novamind.features.agent.services.chat_service import AgentChatService as ChatService

    svc = _service_with({"llm": _params("openai"), "embedding": _params("openai")})
    chat = ChatService.__new__(ChatService)
    chat.model_config_service = svc

    store = __import__("types").SimpleNamespace()
    reconciler = await chat._build_memory_reconciler(
        user_id=1, agent_id=11, memory_store=store, memory_search=None,
    )

    assert reconciler._store is store
    assert reconciler._llm_params["openai_base_url"] == "http://gw.example/v1"
