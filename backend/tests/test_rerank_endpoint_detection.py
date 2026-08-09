"""回归测试：CompatibleRerankClient 端点与请求体按 base_url 自动适配 DashScope。

DashScope 有两套 rerank 入口，按 base_url 自动区分：
- 原生：base_url 含 dashscope.aliyuncs.com 且不含 compatible-api，
  端点 /rerank/text-rerank/text-rerank，请求体嵌套
  {model, input:{query,documents}, parameters:{top_n}}（qwen3-vl-rerank 实测 200）。
- 兼容：base_url 含 compatible-api，端点 /reranks，请求体扁平。
其它兼容服务商（硅基流动、智谱）端点 /rerank、扁平 body。
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


def _client(base_url: str, endpoint: str = ""):
    from novamind.shared.ai_models.rerank.openai_rerank import CompatibleRerankClient

    return CompatibleRerankClient(
        api_key="sk-test",
        base_url=base_url,
        model_name="qwen3-vl-rerank",
        endpoint=endpoint,
    )


# ---- 端点自动选择 ----

def test_dashscope_native_uses_text_rerank_endpoint():
    """原生 DashScope（base_url 不含 compatible-api）端点为 /rerank/text-rerank/text-rerank。"""
    c = _client("https://dashscope.aliyuncs.com/api/v1/services")
    assert c._is_dashscope_native is True
    assert c.endpoint == "/rerank/text-rerank/text-rerank"


def test_dashscope_native_url_matches_verified_curl():
    """base_url=.../api/v1/services + 自动端点 = 已实测 200 的完整 URL。"""
    c = _client("https://dashscope.aliyuncs.com/api/v1/services")
    assert f"{c.base_url}{c.endpoint}" == (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )


def test_dashscope_compatible_uses_reranks_endpoint():
    """兼容 DashScope（base_url 含 compatible-api）端点为 /reranks，非原生模式。"""
    c = _client("https://dashscope.aliyuncs.com/compatible-api/v1")
    assert c._is_dashscope_native is False
    assert c.endpoint == "/reranks"


def test_non_dashscope_uses_default_rerank_endpoint():
    """其它兼容服务商仍用默认 /rerank。"""
    c = _client("https://api.siliconflow.cn/v1")
    assert c._is_dashscope_native is False
    assert c.endpoint == "/rerank"


def test_explicit_endpoint_overrides_autodetect():
    """显式传 endpoint 时优先使用，不被自动识别覆盖。"""
    c = _client("https://dashscope.aliyuncs.com/api/v1/services", endpoint="/custom/rerank")
    assert c.endpoint == "/custom/rerank"


# ---- 请求体格式（桩捕获 payload，不走网络）----

class _FakeResp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"output": {"results": [
            {"index": 0, "relevance_score": 0.93, "document": {"text": "a"}},
            {"index": 2, "relevance_score": 0.82, "document": {"text": "c"}},
        ]}}


class _FakeClient:
    def __init__(self):
        self.captured = None

    async def post(self, url, headers=None, json=None):
        self.captured = {"url": url, "headers": headers, "json": json}
        return _FakeResp()


class _FakeSem:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _patch_transport(client):
    fake_client = _FakeClient()
    client._get_semaphore = lambda: _FakeSem()
    client._get_http_client = _make_async_return(fake_client)
    return fake_client


def _make_async_return(value):
    async def _ret():
        return value
    return _ret


@pytest.mark.asyncio
async def test_native_body_is_nested_input_parameters():
    """原生 DashScope 发嵌套 {model, input:{query,documents}, parameters:{top_n}}。"""
    c = _client("https://dashscope.aliyuncs.com/api/v1/services")
    fake = _patch_transport(c)

    await c.rerank(query="什么是文本排序模型", documents=["a", "b", "c"], top_k=2)

    payload = fake.captured["json"]
    assert payload["model"] == "qwen3-vl-rerank"
    assert payload["input"] == {"query": "什么是文本排序模型", "documents": ["a", "b", "c"]}
    assert payload["parameters"]["top_n"] == 2
    # 不应出现扁平字段
    assert "query" not in payload
    assert "documents" not in payload
    assert "top_n" not in payload


@pytest.mark.asyncio
async def test_compatible_body_is_flat():
    """兼容 API 与其它服务商发扁平 {model, query, documents, top_n}。"""
    c = _client("https://dashscope.aliyuncs.com/compatible-api/v1")
    fake = _patch_transport(c)

    await c.rerank(query="q", documents=["a", "b"], top_k=2)

    payload = fake.captured["json"]
    assert payload == {"model": "qwen3-vl-rerank", "query": "q", "documents": ["a", "b"], "top_n": 2}


@pytest.mark.asyncio
async def test_native_response_parsed_from_output_results():
    """原生响应 {output:{results:[...]}} 能被正确解析为 index+relevance_score。"""
    c = _client("https://dashscope.aliyuncs.com/api/v1/services")
    _patch_transport(c)

    results = await c.rerank(query="q", documents=["a", "b", "c"], top_k=3)

    assert results == [
        {"index": 0, "relevance_score": 0.93},
        {"index": 2, "relevance_score": 0.82},
    ]