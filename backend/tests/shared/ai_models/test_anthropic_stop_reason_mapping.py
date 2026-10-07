"""AnthropicLLM stop_reason → finish_reason 映射回归测试。

背景（2026-10-07 审计）：generate_text_structured 非流式路径把
response.stop_reason 原生词汇（end_turn/max_tokens/refusal 等）直通
finish_reason，经 OpenAI 网关透传后 OpenAI 方言客户端收到非法值；
且 _map_stop_reason 原映射表只有 tool_use/stop_sequence 两项，
max_tokens 截断会落默认 stop（length 语义丢失）。

验证不变量：
1. 全部 Anthropic 官方 stop_reason 词汇都映射为 OpenAI 四值之一
   （stop/length/tool_calls/content_filter），无原生词汇泄漏；
2. 截断类（max_tokens/model_context_window_exceeded）→ length；
3. 拒绝类（refusal）→ content_filter；
4. 未知/缺失词兜底 stop（向前兼容上游新增词汇）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.ai_models.llm.anthropic_llm import AnthropicLLM

pytestmark = pytest.mark.unit

_OPENAI_FINISH_REASONS = {"stop", "length", "tool_calls", "content_filter"}


def _make_client() -> AnthropicLLM:
    """构造不触网的客户端实例（AsyncAnthropic 用 mock 替换）。"""
    with patch("anthropic.AsyncAnthropic"):
        return AnthropicLLM(
            api_key="test-key", base_url="https://test", model_name="test-model",
        )


class TestMapStopReason:
    """_map_stop_reason 全词条映射：OpenAI 方言四值闭合。"""

    def test_all_anthropic_stop_reasons_map_into_openai_vocabulary(self):
        """Anthropic 官方词汇全表：映射结果不泄漏原生词汇。"""
        anthropic_vocabulary = [
            "end_turn", "max_tokens", "stop_sequence", "tool_use",
            "refusal", "pause_turn", "model_context_window_exceeded",
        ]
        for raw in anthropic_vocabulary:
            assert AnthropicLLM._map_stop_reason(raw) in _OPENAI_FINISH_REASONS, (
                f"stop_reason={raw!r} 映射结果不在 OpenAI finish_reason 词表内"
            )

    def test_truncation_family_maps_to_length(self):
        """截断类：max_tokens 与上下文窗口溢出都归 length（原表缺失会落 stop）。"""
        assert AnthropicLLM._map_stop_reason("max_tokens") == "length"
        assert AnthropicLLM._map_stop_reason("model_context_window_exceeded") == "length"

    def test_refusal_maps_to_content_filter(self):
        """拒绝类：refusal → content_filter（原表缺失会落 stop）。"""
        assert AnthropicLLM._map_stop_reason("refusal") == "content_filter"

    def test_normal_end_family_maps_to_stop(self):
        """正常结束类：end_turn/stop_sequence/pause_turn 归 stop。"""
        assert AnthropicLLM._map_stop_reason("end_turn") == "stop"
        assert AnthropicLLM._map_stop_reason("stop_sequence") == "stop"
        assert AnthropicLLM._map_stop_reason("pause_turn") == "stop"

    def test_tool_use_maps_to_tool_calls(self):
        """工具调用：tool_use → tool_calls（原表既有行为不回归）。"""
        assert AnthropicLLM._map_stop_reason("tool_use") == "tool_calls"

    def test_unknown_and_none_fall_back_to_stop(self):
        """未知词/None 兜底 stop：上游新增词汇不炸、缺失不猜值。"""
        assert AnthropicLLM._map_stop_reason("some_future_reason") == "stop"
        assert AnthropicLLM._map_stop_reason(None) == "stop"


class TestNonStreamFinishReasonNoLeak:
    """非流式结构化路径端到端：LLMResponse.finish_reason 不再透传原生词汇。"""

    @pytest.mark.asyncio
    async def test_generate_text_structured_maps_max_tokens_to_length(self):
        """stop_reason=max_tokens → finish_reason=length（原实现泄漏 'max_tokens'）。"""
        from unittest.mock import AsyncMock, MagicMock

        client = _make_client()
        resp = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "截断前的部分回答"
        resp.content = [text_block]
        resp.usage = None
        resp.stop_reason = "max_tokens"
        client.client.messages.create = AsyncMock(return_value=resp)

        result = await client.generate_text_structured(prompt="hi")
        assert result.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_generate_text_structured_maps_end_turn_to_stop(self):
        """stop_reason=end_turn → finish_reason=stop（原实现泄漏 'end_turn'）。"""
        from unittest.mock import AsyncMock, MagicMock

        client = _make_client()
        resp = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "正常回答"
        resp.content = [text_block]
        resp.usage = None
        resp.stop_reason = "end_turn"
        client.client.messages.create = AsyncMock(return_value=resp)

        result = await client.generate_text_structured(prompt="hi")
        assert result.finish_reason == "stop"
