"""paged_read 共享协议测试：参数钳制与响应装配的口径收口。

背景：read_tool_result/plan_output 历史实现无 clamp（负 limit 静默截尾且
has_more=True 诱导无限翻页），read_tool_result 切片与否返回类型分裂——
本组测试钉住统一口径，防新增分页读工具再复制第三份漂移实现。
"""
import json

import pytest
from novamind.engines.agent.tool.paged_read import (
    clamp_page,
    paged_payload,
    paged_response,
)

pytestmark = pytest.mark.unit


# ==================== clamp_page ====================


def test_clamp_defaults_when_missing():
    assert clamp_page({}, default_limit=10_000, max_limit=20_000) == (0, 10_000)


def test_clamp_negative_offset_floored_to_zero():
    """负 offset 钳到 0（历史：直接进切片返回尾部片段）。"""
    assert clamp_page({"offset": -50}, default_limit=10_000, max_limit=20_000) == (0, 10_000)


def test_clamp_negative_and_zero_limit_bounded():
    """负/零 limit 钳到 1（历史：负 limit 静默截尾且 has_more=True 诱导无限翻页）。"""
    assert clamp_page({"limit": -5}, default_limit=10_000, max_limit=20_000) == (0, 1)
    assert clamp_page({"limit": 0}, default_limit=10_000, max_limit=20_000) == (0, 1)


def test_clamp_oversized_limit_capped():
    assert clamp_page({"limit": 999_999}, default_limit=10_000, max_limit=20_000) == (0, 20_000)


def test_clamp_malformed_values_fall_back():
    """畸形值（字符串非数字/None）回落默认，不抛错（能力缺失优于报错栈）。"""
    assert clamp_page({"offset": "abc", "limit": None}, default_limit=8_000, max_limit=20_000) == (0, 8_000)


def test_clamp_valid_values_pass_through():
    assert clamp_page({"offset": 100, "limit": 500}, default_limit=10_000, max_limit=20_000) == (100, 500)


# ==================== paged_payload / paged_response ====================


CONTENT = "x" * 100


def test_payload_identity_keys_first_and_has_more():
    payload = paged_payload(CONTENT, offset=0, limit=40, total_length=100, step=2)
    assert payload["step"] == 2
    assert payload["content"] == "x" * 40
    assert payload["offset"] == 0
    assert payload["limit"] == 40
    assert payload["total_length"] == 100
    assert payload["has_more"] is True


def test_payload_tail_slice_has_more_false():
    payload = paged_payload(CONTENT, offset=80, limit=40, total_length=100)
    assert payload["content"] == "x" * 20
    assert payload["has_more"] is False


def test_payload_offset_beyond_total_returns_empty_not_error():
    """offset 越界：content 为空、has_more=False（不再诱导翻页）。"""
    payload = paged_payload(CONTENT, offset=500, limit=40, total_length=100)
    assert payload["content"] == ""
    assert payload["has_more"] is False


def test_response_is_valid_json_with_identity():
    out = json.loads(paged_response(CONTENT, 0, 40, 100, tool_call_id=7))
    assert out["tool_call_id"] == 7
    assert out["has_more"] is True
    assert out["total_length"] == 100
