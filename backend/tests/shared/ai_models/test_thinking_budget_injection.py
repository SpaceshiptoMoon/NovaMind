"""thinking_budget 注入回归测试：thinking 模型 content 空响应修复。

背景（2026-10-05 实测）：qwen3.8 系列强制 enable_thinking=True，thinking 的
reasoning token 计入输出预算且无界——密集文档 reasoning 可达 8600+ 字符，
把 max_tokens 吃满后 content 为空（completion_tokens 恰好撞满上限）。
修复：enable_thinking=True 时自动注入 thinking_budget = max_tokens * 0.5，
reasoning 有界、正文永远有预算；显式配置 thinking_budget 不覆盖。

验证不变量：
1. thinking=False：不注入 thinking_budget（非思考模型无此概念）；
2. thinking=True：注入预算 = max(max_tokens * 0.5, 16)；
3. extra_body 已有 thinking_budget（用户显式配置）：不覆盖；
4. 强制 thinking 重试路径（服务商 400 → forced=True）：同样注入；
5. 预算下限 16：max_tokens 极小时不为 0/负数。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.ai_models.llm.openai_compatible import OpenAICompatibleLLM

pytestmark = pytest.mark.unit


def _make_client() -> OpenAICompatibleLLM:
    """构造不触网的客户端实例（AsyncOpenAI 用 mock 替换）。"""
    with patch("novamind.shared.ai_models.llm.openai_compatible.AsyncOpenAI"):
        return OpenAICompatibleLLM(
            api_key="test-key", base_url="http://test", model_name="test-model",
        )


def _fake_response(content: str = '{"chunks": []}', completion: int = 100) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.completion_tokens = completion
    return resp


class TestThinkingBudgetInjection:
    @pytest.mark.asyncio
    async def test_no_budget_when_thinking_disabled(self):
        """thinking=False：extra_body 不含 thinking_budget。"""
        client = _make_client()
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return _fake_response()

        client.client.chat.completions.create = AsyncMock(side_effect=fake_create)

        await client.generate_text("hi", max_tokens=2048, enable_thinking=False)

        extra = captured["extra_body"]
        assert extra.get("enable_thinking") is False
        assert "thinking_budget" not in extra

    @pytest.mark.asyncio
    async def test_budget_injected_when_thinking_enabled(self):
        """thinking=True：注入 max_tokens * 0.5。"""
        client = _make_client()
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return _fake_response()

        client.client.chat.completions.create = AsyncMock(side_effect=fake_create)

        await client.generate_text("hi", max_tokens=2048, enable_thinking=True)

        extra = captured["extra_body"]
        assert extra.get("enable_thinking") is True
        assert extra.get("thinking_budget") == 1024

    @pytest.mark.asyncio
    async def test_explicit_budget_not_overridden(self):
        """用户显式配置 thinking_budget：不覆盖。"""
        client = _make_client()

        class PatchedClient(OpenAICompatibleLLM):
            def _apply_thinking_budget(self, extra_body: dict, max_tokens: int) -> None:
                extra_body.setdefault("thinking_budget", 999)  # 模拟已配置

        with patch("novamind.shared.ai_models.llm.openai_compatible.AsyncOpenAI"):
            patched = PatchedClient(
                api_key="k", base_url="http://t", model_name="m",
            )
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return _fake_response()

        patched.client.chat.completions.create = AsyncMock(side_effect=fake_create)

        await patched.generate_text("hi", max_tokens=2048, enable_thinking=True)

        assert captured["extra_body"]["thinking_budget"] == 999

    @pytest.mark.asyncio
    async def test_forced_thinking_retry_also_gets_budget(self):
        """服务商强制 thinking 的自适应重试路径：同样注入预算。"""
        client = _make_client()
        calls = []

        def make_resp(content: str, comp: int) -> MagicMock:
            r = MagicMock()
            r.choices = [MagicMock()]
            r.choices[0].message.content = content
            r.usage.completion_tokens = comp
            return r

        async def fake_create(**kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                # 第一次：400 报 enable_thinking 被强制为 True
                #（消息格式须命中 _restricted_thinking_value 解析："restricted to True"）
                err = Exception(
                    "400 <400> InternalError.Algo.InvalidParameter: The value of "
                    "enable_thinking is restricted to True"
                )
                raise err
            return make_resp('{"chunks": []}', 50)

        client.client.chat.completions.create = AsyncMock(side_effect=fake_create)

        result = await client.generate_text("hi", max_tokens=2048, enable_thinking=False)

        assert len(calls) == 2
        assert calls[1]["extra_body"]["enable_thinking"] is True
        assert calls[1]["extra_body"]["thinking_budget"] == 1024

    def test_budget_floor_16(self):
        """max_tokens 极小时预算下限 16（不为 0/负）。"""
        client = _make_client()
        extra: dict = {"enable_thinking": True}
        client._apply_thinking_budget(extra, max_tokens=8)
        assert extra["thinking_budget"] == 16

    @pytest.mark.asyncio
    async def test_stream_path_also_gets_budget(self):
        """流式路径：thinking=True 同样注入预算。"""
        client = _make_client()
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            # 构造空流
            stream = MagicMock()
            stream.__aenter__ = AsyncMock(return_value=async_iter([]))
            stream.__aexit__ = AsyncMock(return_value=False)
            return stream

        async def async_iter(items):
            for i in items:
                yield i

        client.client.chat.completions.create = AsyncMock(side_effect=fake_create)

        chunks = [c async for c in client.generate_text_stream("hi", max_tokens=2048, enable_thinking=True)]
        assert chunks == []
        assert captured["extra_body"]["thinking_budget"] == 1024
