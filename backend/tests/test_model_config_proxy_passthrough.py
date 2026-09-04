"""模型配置 proxy 透传测试。

验证 extra_config.proxy 三态语义在所有客户端工厂路径的透传：
  - get_rerank_client_by_model → create_rerank_client（本次补齐）
  - _test_rerank → create_rerank_client（本次补齐）
  - _detect_embedding_dimension → create_embedding_client（本次补齐）
  - get_embedding_client_by_model → create_embedding_client（已有，回归保护）
"""

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _make_service() -> "ModelConfigService":
    """构造绕过 DB 依赖的 ModelConfigService。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    with patch.object(ModelConfigService, "__init__", lambda self: None):
        return ModelConfigService()


def _config_row(extra_config):
    """模拟 ORM 行（_get_client_by_model 只需这几个字段）。"""
    return SimpleNamespace(
        protocol="openai",
        api_key="enc-key",
        base_url="https://example.com/v1",
        model="test-model",
        extra_config=extra_config,
    )


def _patch_crypto_and_client_factory(target_create: str, captured: dict):
    """打补丁：解密返回明文 key；工厂函数捕获 proxy 参数。"""
    from novamind.features.user.services import model_config_service as mcs

    async def fake_decrypt(key):
        return "plain-key"

    fake_client = MagicMock()

    def fake_create(**kwargs):
        captured.update(kwargs)
        return fake_client

    return (
        patch.object(mcs, "decrypt_api_key_async", fake_decrypt),
        patch.object(mcs, target_create, fake_create),
    )


# ---- get_rerank_client_by_model 透传 proxy ----

def test_get_rerank_client_passes_extra_proxy():
    """extra_config.proxy=null → get_rerank_client_by_model 应向工厂传 proxy=None。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    captured = {}
    svc = _make_service()

    # _get_client_by_model 内部走 repository 查询，直接 mock 掉
    async def fake_get_client_by_model(_self, user_id, model, model_type, create_from_credentials):
        return create_from_credentials(_config_row({"proxy": None}))

    with patch.object(ModelConfigService, "_get_client_by_model", fake_get_client_by_model):
        with patch(
            "novamind.features.user.services.model_config_service.create_rerank_client"
        ) as mock_create:
            mock_create.return_value = MagicMock()  # 工厂同步返回客户端实例
            asyncio.run(svc.get_rerank_client_by_model(user_id=1, model="test-rerank"))
            captured = mock_create.call_args.kwargs

    assert "proxy" in captured, "get_rerank_client_by_model 应向工厂传 proxy"
    assert captured["proxy"] is None


def test_get_rerank_client_default_inherits():
    """extra_config 无 proxy 键 → 传 PROXY_INHERIT 哨兵（继承环境默认）。"""
    from novamind.shared.ai_models.base_model import PROXY_INHERIT
    from novamind.features.user.services.model_config_service import ModelConfigService

    svc = _make_service()

    async def fake_get_client_by_model(_self, user_id, model, model_type, create_from_credentials):
        return create_from_credentials(_config_row({"dimension": 1024}))

    with patch.object(ModelConfigService, "_get_client_by_model", fake_get_client_by_model):
        with patch(
            "novamind.features.user.services.model_config_service.create_rerank_client"
        ) as mock_create:
            mock_create.return_value = MagicMock()  # 工厂同步返回客户端实例
            asyncio.run(svc.get_rerank_client_by_model(user_id=1, model="test-rerank"))
            captured = mock_create.call_args.kwargs

    assert captured.get("proxy") is PROXY_INHERIT


# ---- get_embedding_client_by_model 透传（回归保护）----

def test_get_embedding_client_passes_extra_proxy():
    """extra_config.proxy=null → get_embedding_client_by_model 应向工厂传 proxy=None。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    svc = _make_service()

    async def fake_get_client_by_model(_self, user_id, model, model_type, create_from_credentials):
        return create_from_credentials(_config_row({"proxy": None, "dimension": 1024}))

    with patch.object(ModelConfigService, "_get_client_by_model", fake_get_client_by_model):
        with patch(
            "novamind.features.user.services.model_config_service.create_embedding_client"
        ) as mock_create:
            mock_create.return_value = MagicMock()  # 工厂同步返回客户端实例
            asyncio.run(svc.get_embedding_client_by_model(user_id=1, model="test-emb"))
            captured = mock_create.call_args.kwargs

    assert captured["proxy"] is None


# ---- _detect_embedding_dimension 透传 proxy ----

def test_detect_embedding_dimension_accepts_and_passes_proxy():
    """_detect_embedding_dimension 签名含 proxy 参数且透传给工厂。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    params = inspect.signature(ModelConfigService._detect_embedding_dimension).parameters
    assert "proxy" in params, "_detect_embedding_dimension 缺少 proxy 参数"

    svc = _make_service()

    fake_client = MagicMock()
    fake_client.generate_embedding = AsyncMock(return_value=[0.1] * 1024)

    with patch(
        "novamind.features.user.services.model_config_service.create_embedding_client"
    ) as mock_create:
        mock_create.return_value = fake_client
        dim = asyncio.run(
            svc._detect_embedding_dimension(
                protocol="openai",
                api_key="k",
                base_url="https://example.com",
                model_name="m",
                proxy=None,
            )
        )

    assert dim == 1024
    assert mock_create.call_args.kwargs.get("proxy") is None


# ---- _test_rerank 透传 proxy ----

def test_test_rerank_passes_request_proxy():
    """_test_rerank 应把 request.proxy 传给工厂。"""
    from novamind.features.user.services.model_config_service import ModelConfigService
    from novamind.shared.ai_models.base_model import PROXY_INHERIT

    svc = _make_service()

    fake_client = MagicMock()
    fake_client.rerank = AsyncMock(return_value=[])

    request = SimpleNamespace(
        protocol="openai",
        api_key="k",
        base_url="https://example.com",
        model="m",
        proxy=None,  # 显式禁用代理
    )

    with patch(
        "novamind.features.user.services.model_config_service.create_rerank_client"
    ) as mock_create:
        mock_create.return_value = fake_client
        asyncio.run(svc._test_rerank(request))

    assert mock_create.call_args.kwargs.get("proxy") is None


def test_test_rerank_default_proxy_inherit():
    """request.proxy 缺省（PROXY_INHERIT）时照常透传哨兵。"""
    from novamind.features.user.services.model_config_service import ModelConfigService
    from novamind.shared.ai_models.base_model import PROXY_INHERIT

    svc = _make_service()

    fake_client = MagicMock()
    fake_client.rerank = AsyncMock(return_value=[])

    request = SimpleNamespace(
        protocol="openai",
        api_key="k",
        base_url="https://example.com",
        model="m",
        proxy=PROXY_INHERIT,
    )

    with patch(
        "novamind.features.user.services.model_config_service.create_rerank_client"
    ) as mock_create:
        mock_create.return_value = fake_client
        asyncio.run(svc._test_rerank(request))

    assert mock_create.call_args.kwargs.get("proxy") is PROXY_INHERIT
