"""单元测试：generate_text 对服务商强制 enable_thinking 约束的自适应重试。

背景：DashScope qwen3.8 系列部分模型强制 enable_thinking=True，客户端默认
False 会被 400 拒绝（InternalError.Algo.InvalidParameter: restricted to True）。
修复：捕获该特征错误后按提示值自适应重试一次，与 VideoInputNotSupportedError
的「服务商约束自适应」模式同构。

覆盖：
- 解析函数：True/False 提示、非约束错误、缺失提示值 → None
- generate_text：首次 400（强制 True）→ 以 True 重试成功
- 重试后仍失败 → 异常照常上抛（不无限重试）
- 请求值已等于强制值 → 不重试直接上抛
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.ai_models.llm.openai_compatible import (
    OpenAICompatibleLLM,
    _restricted_thinking_value,
)

pytestmark = pytest.mark.unit


def _err(forced: str) -> Exception:
    return Exception(
        "Error code: 400 - {'error': {'message': "
        f"'<400> InternalError.Algo.InvalidParameter: The value of the "
        f"enable_thinking parameter is restricted to {forced}.'}}"
    )


# ==================== _restricted_thinking_value ====================


def test_parse_forced_true():
    assert _restricted_thinking_value(_err("True")) is True


def test_parse_forced_false():
    assert _restricted_thinking_value(_err("False")) is False


def test_parse_non_restricted_error_returns_none():
    assert _restricted_thinking_value(Exception("Error code: 400 - quota exceeded")) is None
    assert _restricted_thinking_value(Exception("timeout")) is None


def test_parse_missing_value_returns_none():
    assert _restricted_thinking_value(Exception("enable_thinking is invalid")) is None


# ==================== generate_text 自适应重试 ====================


class _FakeCompletions:
    """按脚本序列返回：先抛指定异常，后续成功。"""

    def __init__(self, script):
        self.script = script
        self.calls = []

    async def create(self, **kwargs):
        import copy

        self.calls.append(copy.deepcopy(kwargs))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _make_client(script):
    client = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
    client.model = "test-model"
    client.default_system_prompt = "sys"
    client._prompt_cache_key = None
    client._semaphore = None
    client._max_concurrent = 1
    client.timeout = 120
    client.client = type("C", (), {"chat": type("Chat", (), {"completions": _FakeCompletions(script)})()})()
    return client


def _ok_response(text="ok"):
    from types import SimpleNamespace

    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
    )


@pytest.mark.asyncio
async def test_generate_text_retries_with_forced_thinking_true():
    """正例：默认 False 被 400（强制 True）拒绝 → 以 True 重试成功。"""
    completions = _FakeCompletions([_err("True"), _ok_response("desc")])
    client = _make_client([])
    client.client.chat.completions = completions

    out = await client.generate_text(prompt="hi", max_tokens=100)
    assert out == "desc"
    assert len(completions.calls) == 2
    assert completions.calls[0]["extra_body"]["enable_thinking"] is False
    assert completions.calls[1]["extra_body"]["enable_thinking"] is True


@pytest.mark.asyncio
async def test_generate_text_retry_failure_raises():
    """反例：自适应重试仍失败 → 异常上抛，不无限重试。"""
    completions = _FakeCompletions([_err("True"), _err("True")])
    client = _make_client([])
    client.client.chat.completions = completions

    with pytest.raises(Exception, match="restricted"):
        await client.generate_text(prompt="hi", max_tokens=100)
    assert len(completions.calls) == 2


@pytest.mark.asyncio
async def test_generate_text_same_value_no_retry():
    """反例：请求值已等于强制值 → 不重试，直接上抛。"""
    completions = _FakeCompletions([_err("True")])
    client = _make_client([])
    client.client.chat.completions = completions

    with pytest.raises(Exception, match="restricted"):
        await client.generate_text(prompt="hi", max_tokens=100, enable_thinking=True)
    assert len(completions.calls) == 1


@pytest.mark.asyncio
async def test_generate_text_unrelated_400_no_retry():
    """反例：非 enable_thinking 约束的 400 → 不触发自适应重试。"""
    completions = _FakeCompletions([Exception("Error code: 400 - invalid model")])
    client = _make_client([])
    client.client.chat.completions = completions

    with pytest.raises(Exception, match="invalid model"):
        await client.generate_text(prompt="hi", max_tokens=100)
    assert len(completions.calls) == 1
