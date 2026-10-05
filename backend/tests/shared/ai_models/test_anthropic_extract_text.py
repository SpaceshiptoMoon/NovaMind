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
