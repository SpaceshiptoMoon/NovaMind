"""usage 归一化 + cost 估算单测（E1 可观测性）。"""
from decimal import Decimal

import pytest

from novamind.shared.ai_models.usage import CanonicalUsage, estimate_cost, normalize_usage

pytestmark = pytest.mark.unit


def test_normalize_total_only():
    u = normalize_usage({"total_tokens": 100})
    assert u.output_tokens == 100
    assert u.total_tokens == 100


def test_normalize_anthropic():
    u = normalize_usage(
        {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 5}
    )
    assert u.input_tokens == 10
    assert u.output_tokens == 20
    assert u.cache_read_tokens == 5


def test_normalize_openai():
    u = normalize_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 30},
        }
    )
    assert u.input_tokens == 70  # 100 - 30 cached
    assert u.output_tokens == 50
    assert u.cache_read_tokens == 30


def test_normalize_none():
    assert normalize_usage(None).total_tokens == 0
    assert normalize_usage({}).total_tokens == 0


def test_estimate_cost_known():
    u = CanonicalUsage(input_tokens=1_000_000, output_tokens=500_000)
    cost = estimate_cost(u, "qwen-max", "dashscope")
    # qwen-max: 2.4 in + 9.6 out per M → 2.4 + 9.6*0.5 = 7.2
    assert cost == Decimal("7.2")


def test_estimate_cost_unknown_model():
    u = CanonicalUsage(input_tokens=1000, output_tokens=500)
    assert estimate_cost(u, "unknown-model") == Decimal("0")


def test_usage_add():
    a = CanonicalUsage(input_tokens=10, output_tokens=5)
    b = CanonicalUsage(input_tokens=20, output_tokens=10)
    c = a + b
    assert c.input_tokens == 30
    assert c.output_tokens == 15
    assert c.total_tokens == 45