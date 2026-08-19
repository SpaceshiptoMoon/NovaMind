"""LLM usage 归一化 + cost 估算（可观测性 E1）。

不同 provider 返回的 usage 字段形态不一，``normalize_usage`` 统一为
``CanonicalUsage``（input/output/cache_read/cache_write/reasoning），
``estimate_cost`` 按内置默认价格表估算 USD 成本（per-million tokens）。

支持三种形态：
- OpenAI Chat Completions: ``prompt_tokens``/``completion_tokens`` +
  ``prompt_tokens_details.cached_tokens`` + ``completion_tokens_details.reasoning_tokens``
- Anthropic Messages: ``input_tokens``/``output_tokens`` +
  ``cache_read_input_tokens``/``cache_creation_input_tokens``
- 通用简化: 仅 ``total_tokens``
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class CanonicalUsage:
    """归一化后的 token 用量（一次 LLM 调用）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    def __add__(self, other: "CanonicalUsage") -> "CanonicalUsage":
        return CanonicalUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


def _get_nested(d: Dict[str, Any], *keys: str) -> int:
    """取嵌套字段，缺省 0。"""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return 0
        cur = cur.get(k)
        if cur is None:
            return 0
    try:
        return int(cur)
    except (TypeError, ValueError):
        return 0


def normalize_usage(raw: Optional[Dict[str, Any]]) -> CanonicalUsage:
    """归一化 Anthropic/OpenAI/通用 三种 usage 形态为 CanonicalUsage。"""
    if not raw or not isinstance(raw, dict):
        return CanonicalUsage()

    # Anthropic Messages 形态
    if "input_tokens" in raw or "output_tokens" in raw:
        return CanonicalUsage(
            input_tokens=int(raw.get("input_tokens", 0) or 0),
            output_tokens=int(raw.get("output_tokens", 0) or 0),
            cache_read_tokens=int(raw.get("cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(raw.get("cache_creation_input_tokens", 0) or 0),
        )

    # OpenAI Chat Completions 形态
    if "prompt_tokens" in raw or "completion_tokens" in raw:
        prompt = int(raw.get("prompt_tokens", 0) or 0)
        completion = int(raw.get("completion_tokens", 0) or 0)
        cache_read = _get_nested(raw, "prompt_tokens_details", "cached_tokens")
        # OpenAI prompt_tokens 含 cached，扣除得真实 input
        input_tokens = max(0, prompt - cache_read)
        reasoning = _get_nested(raw, "completion_tokens_details", "reasoning_tokens")
        # DeepSeek 兼容：prompt_cache_hit_tokens
        if not cache_read and "prompt_cache_hit_tokens" in raw:
            cache_read = int(raw.get("prompt_cache_hit_tokens", 0) or 0)
            input_tokens = max(0, prompt - cache_read)
        return CanonicalUsage(
            input_tokens=input_tokens,
            output_tokens=completion,
            cache_read_tokens=cache_read,
            reasoning_tokens=reasoning,
        )

    # 通用简化：仅 total_tokens → 计入 output（无法区分 input/output）
    total = int(raw.get("total_tokens", 0) or 0)
    return CanonicalUsage(output_tokens=total)


@dataclass(frozen=True)
class PricingEntry:
    """单模型定价（per 1M tokens，USD）。"""

    input_per_million: Decimal
    output_per_million: Decimal
    cache_read_per_million: Decimal = Decimal("0")
    cache_write_per_million: Decimal = Decimal("0")


# 默认价格表（per 1M tokens, USD）。key=(provider_lower, model_lower)。
# 仅含常见模型；未命中返回 cost=0（status="unknown"），可由 yaml/DB 覆盖扩展。
_DEFAULT_PRICING: Dict[Tuple[str, str], PricingEntry] = {
    ("openai", "gpt-4o"): PricingEntry(Decimal("2.5"), Decimal("10"), Decimal("1.25")),
    ("openai", "gpt-4o-mini"): PricingEntry(Decimal("0.15"), Decimal("0.6"), Decimal("0.075")),
    ("openai", "gpt-4.1"): PricingEntry(Decimal("2"), Decimal("8"), Decimal("0.5")),
    ("anthropic", "claude-3-5-sonnet"): PricingEntry(Decimal("3"), Decimal("15"), Decimal("0.3"), Decimal("3.75")),
    ("anthropic", "claude-3-5-haiku"): PricingEntry(Decimal("0.8"), Decimal("4"), Decimal("0.08"), Decimal("1")),
    ("deepseek", "deepseek-chat"): PricingEntry(Decimal("0.27"), Decimal("1.1"), Decimal("0.07")),
    ("dashscope", "qwen-plus"): PricingEntry(Decimal("0.4"), Decimal("1.2")),
    ("dashscope", "qwen-max"): PricingEntry(Decimal("2.4"), Decimal("9.6")),
    ("dashscope", "qwen-turbo"): PricingEntry(Decimal("0.05"), Decimal("0.2")),
}


def _lookup_pricing(model: str, provider: Optional[str]) -> Optional[PricingEntry]:
    """按 (provider, model) 查价格，model 名做点号→横杠归一化。"""
    if not model:
        return None
    model_norm = model.lower().replace(".", "-")
    # 先精确 (provider, model)
    if provider:
        key = (provider.lower(), model_norm)
        if key in _DEFAULT_PRICING:
            return _DEFAULT_PRICING[key]
    # 再按 model 名模糊匹配（任意 provider）
    for (p, m), entry in _DEFAULT_PRICING.items():
        if m == model_norm or model_norm.startswith(m) or m.startswith(model_norm):
            return entry
    return None


def estimate_cost(usage: CanonicalUsage, model: str, provider: Optional[str] = None) -> Decimal:
    """按内置价格表估算 USD 成本；未命中价格表返回 Decimal('0')。"""
    entry = _lookup_pricing(model, provider)
    if entry is None:
        return Decimal("0")
    cost = (
        Decimal(usage.input_tokens) * entry.input_per_million
        + Decimal(usage.output_tokens) * entry.output_per_million
        + Decimal(usage.cache_read_tokens) * entry.cache_read_per_million
        + Decimal(usage.cache_write_tokens) * entry.cache_write_per_million
    ) / Decimal("1000000")
    return cost


__all__ = [
    "CanonicalUsage",
    "PricingEntry",
    "normalize_usage",
    "estimate_cost",
]