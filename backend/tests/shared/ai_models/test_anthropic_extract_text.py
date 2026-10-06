"""AnthropicLLM 文本提取回归测试：思考型模型 thinking 块兼容。

背景（2026-10-06 实测智谱 Anthropic 兼容端点）：glm-5.3-flash 的
content 首块恒为 thinking 块（无 .text 属性）且思考不可关闭，取
content[0].text 会抛 AttributeError 或返回空。修复：只拼接 type=="text" 的块。

验证不变量：
1. thinking 块在前、text 块在后：返回 text 块内容，不崩不混入思考文本；
2. 纯 text 块（传统 Claude 行为）：行为不变；
3. thinking 吃满预算、无 text 块：返回空串（由上层探针判空报错）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.ai_models.llm.anthropic_llm import AnthropicLLM

pytestmark = pytest.mark.unit


def _make_client() -> AnthropicLLM:
    """构造不触网的客户端实例（AsyncAnthropic 用 mock 替换，延迟 import 须 patch 源包）。"""
    with patch("anthropic.AsyncAnthropic"):
        return AnthropicLLM(
            api_key="test-key", base_url="https://test", model_name="test-model",
        )


def _fake_response(*blocks: dict) -> MagicMock:
    """按块类型构造 Messages API 响应（thinking 块无 .text，text 块有）。"""
    resp = MagicMock()
    content = []
    for kind, text in blocks:
        block = MagicMock()
        block.type = kind
        if kind == "text":
            block.text = text
        else:
            del block.text  # ThinkingBlock 没有 .text，访问即 AttributeError
        content.append(block)
    resp.content = content
    resp.usage = None
    return resp


class TestExtractTextBlocks:
    @pytest.mark.asyncio
    async def test_thinking_first_text_after(self):
        """thinking 首块 + text 后块：返回 text 内容，不崩。"""
        client = _make_client()
        client.client.messages.create = AsyncMock(
            return_value=_fake_response(("thinking", "思考过程"), ("text", "正文回答"))
        )
        result = await client.generate_text(prompt="hi")
        assert result == "正文回答"

    @pytest.mark.asyncio
    async def test_pure_text_block_unchanged(self):
        """纯 text 块（传统 Claude 响应形状）：行为不变。"""
        client = _make_client()
        client.client.messages.create = AsyncMock(
            return_value=_fake_response(("text", "plain answer"))
        )
        assert await client.generate_text(prompt="hi") == "plain answer"

    @pytest.mark.asyncio
    async def test_thinking_exhausted_budget_returns_empty(self):
        """thinking 吃满预算、无 text 块：返回空串而非抛 AttributeError。"""
        client = _make_client()
        client.client.messages.create = AsyncMock(
            return_value=_fake_response(("thinking", "只有思考"))
        )
        assert await client.generate_text(prompt="hi") == ""

    @pytest.mark.asyncio
    async def test_multiple_text_blocks_joined(self):
        """多个 text 块：按序拼接。"""
        client = _make_client()
        client.client.messages.create = AsyncMock(
            return_value=_fake_response(
                ("thinking", "思考"), ("text", "第一段"), ("text", "第二段")
            )
        )
        assert await client.generate_text(prompt="hi") == "第一段第二段"


class TestHostEnvInsulation:
    """宿主环境 ANTHROPIC_* 绝缘：凭据与端点只认显式配置。

    背景（2026-10-06 用户实测 401）：宿主 shell 设有 ANTHROPIC_AUTH_TOKEN
    （本地代理工具注入）时，SDK 构造不传 auth_token 会自动读环境拼
    Authorization 头，与显式 api_key 的 x-api-key 双头并发；智谱优先校验
    Authorization，用环境里的无关 token 鉴权而 401「令牌已过期或验证不正确」。
    """

    def test_env_auth_token_not_leaked_into_headers(self):
        """污染环境下构造：实发请求只带 x-api-key，无 Authorization 头。"""
        import asyncio

        import httpx

        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_AUTH_TOKEN": "PROXY_MATIC_JUNK",
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:99999",
            },
        ):
            client = AnthropicLLM(
                api_key="zhipu-token", base_url="", model_name="test-model",
            )
            captured: dict = {}

            def handler(request: httpx.Request) -> httpx.Response:
                captured.update({k.lower(): v for k, v in request.headers.items()})
                return httpx.Response(
                    200,
                    json={
                        "id": "x", "type": "message", "role": "assistant",
                        "model": "m", "content": [{"type": "text", "text": "ok"}],
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                )

            client.client._client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url=client.client.base_url,
            )
            asyncio.run(client.generate_text(prompt="hi", max_tokens=10))

            assert captured.get("x-api-key") == "zhipu-token"
            assert "authorization" not in captured

    def test_empty_base_url_falls_to_official_not_env(self):
        """base_url 空串：落官方默认，不读宿主环境 ANTHROPIC_BASE_URL。"""
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_BASE_URL": "http://127.0.0.1:99999"},
        ):
            client = AnthropicLLM(
                api_key="k", base_url="", model_name="m",
            )
            assert str(client.client.base_url) == "https://api.anthropic.com"


class TestAuthTypeHeaderSelection:
    """auth_type 决定凭据头语义：api_key→x-api-key，bearer→Authorization。

    背景（2026-10-06 用户指出）：智谱 coding plan 发的是 token（官方指定
    ANTHROPIC_AUTH_TOKEN/Bearer 语义），不能与 API Key（x-api-key）混为一谈。
    """

    def _capture_headers(self, client) -> dict:
        import httpx

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update({k.lower(): v for k, v in request.headers.items()})
            return httpx.Response(
                200,
                json={
                    "id": "x", "type": "message", "role": "assistant",
                    "model": "m", "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )

        client.client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=client.client.base_url,
        )
        import asyncio

        asyncio.run(client.generate_text(prompt="hi", max_tokens=10))
        return captured

    def test_default_sends_x_api_key(self):
        """默认（官方语义）：凭据走 x-api-key，无 Authorization 头。"""
        with patch.dict("os.environ", {"ANTHROPIC_AUTH_TOKEN": "ENV_JUNK"}):
            client = AnthropicLLM(api_key="cred-1", base_url="", model_name="m")
            headers = self._capture_headers(client)
            assert headers.get("x-api-key") == "cred-1"
            assert "authorization" not in headers

    def test_bearer_sends_authorization(self):
        """bearer 语义（智谱等网关）：凭据走 Authorization，无 x-api-key 头。"""
        from novamind.shared.ai_models.llm.quirks import LLMQuirks

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "ENV_JUNK"}):
            client = AnthropicLLM(
                api_key="cred-2", base_url="", model_name="m",
                quirks=LLMQuirks(auth_type="bearer"),
            )
            headers = self._capture_headers(client)
            assert headers.get("authorization") == "Bearer cred-2"
            assert "x-api-key" not in headers
