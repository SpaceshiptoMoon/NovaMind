"""Embedding / LLM 客户端容错测试。

验证（2026-09-04 DashScope ReadTimeout 故障的回归测试）：
  - openai SDK 包装的异常（APITimeoutError / APIConnectionError / RateLimitError）
    会命中 tenacity 重试名单——修复前 tenacity 名单只有 httpx 异常，
    openai 包装类型直接穿透，超时后外层重试从不触发。
  - generate_embeddings_batch 的双层 batch_size 语义：不传 batch_size 时
    使用构造器的 self.batch_size（而非方法硬编码默认值）。
  - BaseRerank._get_http_client 复用 build_openai_http_client 三态代理语义。
"""

import asyncio
import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _make_client(**kwargs) -> "OpenAICompatibleEmbedding":
    """构造绕过真实 AsyncOpenAI 初始化的客户端实例。"""
    from novamind.shared.ai_models.embedding.openai_compatible import (
        OpenAICompatibleEmbedding,
    )

    with patch("novamind.shared.ai_models.embedding.openai_compatible.AsyncOpenAI"):
        client = OpenAICompatibleEmbedding(
            api_key="test-key",
            base_url="https://example.com/v1",
            model_name="test-embedding",
            **kwargs,
        )
    return client


# ---- openai 包装异常命中 tenacity 重试 ----

def test_retry_list_contains_openai_wrapped_exceptions():
    """tenacity 重试名单必须包含 openai SDK 包装异常类型。"""
    from novamind.shared.ai_models.embedding import openai_compatible as emb_mod
    from novamind.shared.ai_models.llm import openai_compatible as llm_mod

    openai_exc = emb_mod.OPENAI_RETRY_EXCEPTIONS
    assert openai_exc, "OPENAI_RETRY_EXCEPTIONS 不应为空（openai 已安装）"

    from openai import APIConnectionError, APITimeoutError, RateLimitError

    assert APIConnectionError in openai_exc
    assert APITimeoutError in openai_exc
    assert RateLimitError in openai_exc

    # LLM 客户端复用同一异常元组（同 bug 类，同修复）
    assert llm_mod.OPENAI_RETRY_EXCEPTIONS is openai_exc or llm_mod.OPENAI_RETRY_EXCEPTIONS == openai_exc


def test_embedding_batch_timeout_is_retried():
    """模拟 DashScope ReadTimeout：_generate_batch 抛 APITimeoutError 两次后成功，
    tenacity 应重试并最终返回结果（修复前直接穿透抛出）。"""
    from openai import APITimeoutError
    import httpx

    # 构造真实的 APITimeoutError（需要 message 参数和 request 属性）
    request = httpx.Request("POST", "https://example.com/v1/embeddings")
    exc = APITimeoutError(request=request)

    client = _make_client(batch_size=32)

    calls = {"n": 0}
    fake_response = MagicMock()
    fake_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    async def flaky_create(**kwargs):
        if calls["n"] < 2:
            calls["n"] += 1
            raise exc
        return fake_response

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=flaky_create)

    result = asyncio.run(client._generate_batch(["文本1", "文本2"]))

    assert calls["n"] == 2, "应重试 2 次后成功"
    assert result == [[0.1, 0.2, 0.3]]


def test_embedding_batch_timeout_exhausts_retries_and_reraises():
    """连续超时 3 次后，tenacity 应停止重试并原样抛出（reraise=True 不包 RetryError）。"""
    from openai import APITimeoutError
    import httpx

    request = httpx.Request("POST", "https://example.com/v1/embeddings")
    exc = APITimeoutError(request=request)

    client = _make_client()
    calls = {"n": 0}

    async def always_timeout(**kwargs):
        calls["n"] += 1
        raise exc

    client.client = MagicMock()
    client.client.embeddings.create = AsyncMock(side_effect=always_timeout)

    with pytest.raises(APITimeoutError):
        asyncio.run(client._generate_batch(["文本"]))

    assert calls["n"] == 3, "stop_after_attempt(3) 应恰好尝试 3 次"


# ---- 双层 batch_size 语义 ----

def test_generate_embeddings_batch_uses_constructor_batch_size_by_default():
    """不传 batch_size 时使用构造器的 self.batch_size，而非方法硬编码默认值。"""
    client = _make_client(batch_size=32)

    inner_batches = []

    async def fake_generate_batch(batch_texts):
        inner_batches.append(len(batch_texts))
        return [[0.0]] * len(batch_texts)

    client._generate_batch = fake_generate_batch

    texts = [f"文本{i}" for i in range(35)]
    result = asyncio.run(client.generate_embeddings_batch(texts))

    assert inner_batches == [32, 3], (
        f"35 条文本应按构造器 batch_size=32 切成 [32, 3]，实际: {inner_batches}"
    )
    assert len(result) == 35


def test_generate_embeddings_batch_explicit_batch_size_wins():
    """显式传 batch_size 时优先于构造器配置（调用方显式覆盖语义保留）。"""
    client = _make_client(batch_size=32)

    inner_batches = []

    async def fake_generate_batch(batch_texts):
        inner_batches.append(len(batch_texts))
        return [[0.0]] * len(batch_texts)

    client._generate_batch = fake_generate_batch

    texts = [f"文本{i}" for i in range(15)]
    asyncio.run(client.generate_embeddings_batch(texts, batch_size=10))

    assert inner_batches == [10, 5], f"显式 batch_size=10 应切成 [10, 5]，实际: {inner_batches}"


def test_base_embedding_abstract_signature_allows_none_batch_size():
    """BaseEmbedding 抽象签名 batch_size 默认值应为 None（None → 客户端自配批次）。"""
    from novamind.shared.ai_models.base_model import BaseEmbedding

    params = inspect.signature(BaseEmbedding.generate_embeddings_batch).parameters
    assert params["batch_size"].default is None


# ---- BaseRerank proxy 透传 ----

def test_base_rerank_http_client_uses_proxy_semantics():
    """BaseRerank._get_http_client 复用 build_openai_http_client：
    proxy=None 时 httpx 客户端应关闭 trust_env（不读环境代理）。"""
    import httpx

    from novamind.shared.ai_models.rerank.openai_rerank import CompatibleRerankClient

    client = CompatibleRerankClient(
        api_key="k",
        base_url="https://example.com",
        model_name="m",
        proxy=None,
    )

    http = asyncio.run(client._get_http_client())
    try:
        # trust_env=False 时 httpx 不从环境变量构建代理 mounts（无代理 mounts）
        assert http.trust_env is False
    finally:
        asyncio.run(http.aclose())
        client._http_client = None


def test_base_rerank_default_proxy_inherit():
    """默认 PROXY_INHERIT：不设置 trust_env=False，保持 httpx 默认（继承环境）。"""
    from novamind.shared.ai_models.rerank.openai_rerank import CompatibleRerankClient

    client = CompatibleRerankClient(
        api_key="k",
        base_url="https://example.com",
        model_name="m",
    )
    assert client.proxy is not None
    # PROXY_INHERIT 哨兵语义：_get_http_client 生成的客户端保持默认 trust_env=True
    http = asyncio.run(client._get_http_client())
    try:
        assert http.trust_env is True
    finally:
        asyncio.run(http.aclose())


def test_create_rerank_client_passes_proxy():
    """rerank 工厂把 proxy 透传给 openai 协议客户端。"""
    from novamind.shared.ai_models.rerank import create_rerank_client

    client = create_rerank_client(
        protocol="openai",
        api_key="k",
        base_url="https://example.com",
        model_name="m",
        proxy=None,
    )
    assert client.proxy is None
