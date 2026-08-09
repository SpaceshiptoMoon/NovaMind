"""回归测试：CompatibleRerankClient 端点按 base_url 自动识别 DashScope。

DashScope 的 OpenAI 兼容 rerank 端点是 ``/reranks``（非 ``/rerank``），
base_url 需配成 ``https://dashscope.aliyuncs.com/compatible-api/v1``。
此前端点默认 ``/rerank`` 且测试流程不传 endpoint，导致 DashScope rerank
打到错误端点 + 400。修复后按 base_url 自动选择端点。
"""

import sys
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
        model_name="qwen3-rerank",
        endpoint=endpoint,
    )


def test_dashscope_auto_uses_reranks_endpoint():
    """base_url 指向 DashScope 兼容 API 时端点自动为 /reranks。"""
    c = _client("https://dashscope.aliyuncs.com/compatible-api/v1")
    assert c.endpoint == "/reranks"
    # base_url 末尾斜杠被规整，不影响识别
    c2 = _client("https://dashscope.aliyuncs.com/compatible-api/v1/")
    assert c2.endpoint == "/reranks"


def test_non_dashscope_uses_default_rerank_endpoint():
    """其它兼容服务商（硅基流动等）仍用默认 /rerank。"""
    c = _client("https://api.siliconflow.cn/v1")
    assert c.endpoint == "/rerank"


def test_explicit_endpoint_overrides_autodetect():
    """显式传 endpoint 时优先使用，不被自动识别覆盖。"""
    c = _client("https://dashscope.aliyuncs.com/compatible-api/v1", endpoint="/custom/rerank")
    assert c.endpoint == "/custom/rerank"


def test_rerank_url_construction_dashscope():
    """DashScope 下 base_url + endpoint 拼出正确的 /compatible-api/v1/reranks。"""
    c = _client("https://dashscope.aliyuncs.com/compatible-api/v1")
    # rerank() 内部用 f"{self.base_url}{self.endpoint}"
    assert f"{c.base_url}{c.endpoint}" == (
        "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
    )