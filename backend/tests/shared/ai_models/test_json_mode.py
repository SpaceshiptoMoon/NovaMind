"""request_json 统一入口回归测试：三层防护（prompt 约束/response_format/提取容错）。

验证核心不变量：
1. ② 层：默认带 response_format={"type":"json_object"}；显式 None 时不带该键；
2. ① 层：str/list prompt 均追加 JSON_ONLY_RULE（list 不改动方原列表）；
3. ③ 层：围栏/前导噪声可解析；空响应缩短 max_tokens 重试；类型不符重试；
   轮次耗尽返回 None；
4. transport 异常原样上抛（不在组合层吞掉）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.ai_models.base_model import BaseLLM
from novamind.shared.ai_models.llm.json_mode import (
    request_json,
)
from novamind.shared.prompts.json_contract import JSON_ONLY_RULE

pytestmark = pytest.mark.unit


class FakeLLM(BaseLLM):
    """最小桩：记录 generate_text 调用参数，按脚本返回。"""

    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate_text(self, prompt, max_tokens=2048, temperature=0.7,
                            top_p=0.8, response_format=None, enable_thinking=False,
                            **_):
        self.calls.append({
            "prompt": prompt,
            "max_tokens": max_tokens,
            "response_format": response_format,
        })
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate_text_stream(self, prompt, **_):
        yield ""


def _run(coro):
    return asyncio.run(coro)


class TestResponseFormatLayer:
    def test_default_json_object_sent(self):
        llm = FakeLLM(['{"ok": true}'])
        result = _run(request_json(llm, "hi"))
        assert result == {"ok": True}
        assert llm.calls[0]["response_format"] == {"type": "json_object"}

    def test_none_format_omits_key_value(self):
        llm = FakeLLM(['{"ok": true}'])
        _run(request_json(llm, "hi", response_format=None))
        assert llm.calls[0]["response_format"] is None


class TestPromptInstructionLayer:
    def test_str_prompt_appends_rule(self):
        llm = FakeLLM(['{"ok": 1}'])
        _run(request_json(llm, "原始指令"))
        assert JSON_ONLY_RULE in llm.calls[0]["prompt"]
        assert llm.calls[0]["prompt"].startswith("原始指令")

    def test_schema_hint_appended(self):
        llm = FakeLLM(['{"claims": []}'])
        _run(request_json(llm, "hi", schema_hint='{"claims": ["..."]}'))
        assert '{"claims": ["..."]}' in llm.calls[0]["prompt"]

    def test_list_prompt_appends_to_last_user_message(self):
        llm = FakeLLM(['{"ok": 1}'])
        original = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "用户问题"},
        ]
        _run(request_json(llm, original))
        sent = llm.calls[0]["prompt"]
        # 原列表不被改动
        assert original[1]["content"] == "用户问题"
        # 发送侧末条 user 已追加
        assert JSON_ONLY_RULE in sent[1]["content"]
        assert sent[0]["content"] == "sys"

    def test_append_disabled(self):
        llm = FakeLLM(['{"ok": 1}'])
        _run(request_json(llm, "hi", append_json_rule=False))
        assert JSON_ONLY_RULE not in llm.calls[0]["prompt"]


class TestExtractionRetryLayer:
    def test_fenced_output_parses(self):
        llm = FakeLLM(['```json\n{"ok": true}\n```'])
        assert _run(request_json(llm, "hi")) == {"ok": True}

    def test_empty_response_shrinks_tokens_and_recovers(self):
        llm = FakeLLM(["", '{"ok": true}'])
        result = _run(request_json(llm, "hi", max_tokens=2048))
        assert result == {"ok": True}
        # 第二轮 max_tokens 缩短为一半
        assert llm.calls[0]["max_tokens"] == 2048
        assert llm.calls[1]["max_tokens"] == 1024

    def test_type_mismatch_retries_then_none(self):
        """期望 dict 收到数组：类型不符进入重试，耗尽返回 None。"""
        llm = FakeLLM(["[1,2]", "[3]"])
        result = _run(request_json(llm, "hi", max_parse_retries=1))
        assert result is None
        assert len(llm.calls) == 2

    def test_expect_list_returns_array(self):
        llm = FakeLLM(['[{"step": "a"}]'])
        result = _run(request_json(llm, "hi", expect_list=True))
        assert result == [{"step": "a"}]

    def test_garbage_exhausts_to_none(self):
        llm = FakeLLM(["垃圾1", "垃圾2"])
        assert _run(request_json(llm, "hi", max_parse_retries=1)) is None
        assert len(llm.calls) == 2

    def test_transport_exception_propagates(self):
        llm = FakeLLM([ConnectionError("网络断")])
        with pytest.raises(ConnectionError):
            _run(request_json(llm, "hi"))

    def test_timeout_applied(self):
        """timeout 传 asyncio.wait_for：超时抛 TimeoutError（不吞）。"""

        class SlowLLM(FakeLLM):
            async def generate_text(self, prompt, **kw):
                await asyncio.sleep(10)
                return "{}"

        with pytest.raises(asyncio.TimeoutError):
            _run(request_json(SlowLLM([]), "hi", timeout=0.05))
