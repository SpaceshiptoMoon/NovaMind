"""LLM 响应 JSON 提取工具回归测试：extract_json_value / extract_json_obj 契约。

验证核心不变量：
1. extract_json_value：对象/数组/围栏/前导噪声均可提取，垃圾返回 None；
2. extract_json_obj 契约保持：数组输入返回 None（grade_retrier 等既有调用方
   依赖「只回 dict」语义，数组泄漏会改变其分支行为）；
3. extract_json_str 异常语义不变（空输入抛 ValueError）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.shared.utils.llm_response import (
    extract_json_obj,
    extract_json_str,
    extract_json_value,
)

pytestmark = pytest.mark.unit


class TestExtractJsonValue:
    def test_plain_object(self):
        assert extract_json_value('{"a": 1}') == {"a": 1}

    def test_plain_array(self):
        assert extract_json_value('[1, 2, 3]') == [1, 2, 3]

    def test_fenced_object(self):
        text = '以下是结果：\n```json\n{"chunks": [{"q": "x"}]}\n```\n希望有帮助'
        assert extract_json_value(text) == {"chunks": [{"q": "x"}]}

    def test_fenced_array(self):
        text = '```json\n[{"k": "v"}]\n```'
        assert extract_json_value(text) == [{"k": "v"}]

    def test_leading_text_then_object(self):
        text = 'Sure! Here is the JSON: {"ok": true} — anything else?'
        assert extract_json_value(text) == {"ok": True}

    def test_leading_text_then_array(self):
        """贪婪数组兜底：对象正则先试，失败后数组正则兜住（deep_research 场景）。"""
        text = 'Plan:\n[{"step": "a"}, {"step": "b"}]\nDone.'
        assert extract_json_value(text) == [{"step": "a"}, {"step": "b"}]

    def test_object_with_brace_inside_string(self):
        """value 内嵌 } 的对象（skill_checker 反例形态）：贪婪匹配完整取回。"""
        text = '前置说明 {"reason": "包含右括号 } 的原因", "verdict": true} 后缀'
        assert extract_json_value(text) == {"reason": "包含右括号 } 的原因", "verdict": True}

    def test_empty_and_none(self):
        assert extract_json_value("") is None
        assert extract_json_value(None) is None
        assert extract_json_value("   ") is None

    def test_garbage_returns_none(self):
        assert extract_json_value("这不是 JSON") is None
        assert extract_json_value("{broken json") is None

    def test_scalar_still_parses(self):
        """标量 JSON 值：裸 "42"/"true" 不以 {/[ 开头也走不到兜底——返回 None 是
        可接受语义（调用方都用 dict/list 消费）；但纯对象内的标量不受影响。"""
        assert extract_json_value('{"n": 42}')["n"] == 42


class TestExtractJsonObjContract:
    def test_object_passthrough(self):
        assert extract_json_obj('{"a": 1}') == {"a": 1}

    def test_array_returns_none(self):
        """契约守护：数组不冒充 dict（grade_retrier 依赖此语义）。"""
        assert extract_json_obj('[{"k": "v"}]') is None

    def test_fenced_array_returns_none(self):
        assert extract_json_obj('```json\n[1]\n```') is None

    def test_none_and_garbage(self):
        assert extract_json_obj(None) is None
        assert extract_json_obj("no json here") is None


class TestExtractJsonStrUnchanged:
    def test_empty_raises(self):
        with pytest.raises(ValueError):
            extract_json_str("")

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            extract_json_str("完全没有结构化内容")
