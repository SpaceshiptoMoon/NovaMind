"""单元测试：kb-ops C——配置指纹稳定性。

覆盖：
- compute_config_fingerprint：同配置恒同值（显式默认值=不传）、键序无关、
  非指纹字段变更不影响、中文值跨编码稳定
（合成测试集解析部分已随 testset_generation 下线删除，2026-11-15 工作台剥离）
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


# ========== 配置指纹 ==========


def test_fingerprint_stable_across_calls():
    """同配置多次计算恒同值。"""
    from novamind.features.evaluation.services.config_fingerprint import (
        compute_config_fingerprint,
    )

    cfg = {"search_mode": "content_hybrid", "llm_model": "qwen3.8-flash"}
    assert compute_config_fingerprint(cfg) == compute_config_fingerprint(cfg)


def test_fingerprint_explicit_defaults_equal_none():
    """显式传默认值与不传（None=全默认）同指纹——经 schema 归一的语义。"""
    from novamind.features.evaluation.schemas.evaluation_schema import EvaluationConfig
    from novamind.features.evaluation.services.config_fingerprint import (
        compute_config_fingerprint,
    )

    defaults = EvaluationConfig().model_dump()
    assert compute_config_fingerprint(None) == compute_config_fingerprint(defaults)


def test_fingerprint_key_order_irrelevant():
    """键序不影响指纹（sort_keys 归一）。"""
    from novamind.features.evaluation.services.config_fingerprint import (
        compute_config_fingerprint,
    )

    a = compute_config_fingerprint({"llm_model": "m1", "search_mode": "content_hybrid"})
    b = compute_config_fingerprint({"search_mode": "content_hybrid", "llm_model": "m1"})
    assert a == b


def test_fingerprint_ignores_non_quality_fields():
    """非指纹字段（评估器开关等）变更不影响指纹。"""
    from novamind.features.evaluation.services.config_fingerprint import (
        compute_config_fingerprint,
    )

    base = {"search_mode": "content_hybrid"}
    with_evaluator_toggles = {**base, "enable_mrr": False, "enable_recall_at_k": True}
    assert compute_config_fingerprint(base) == compute_config_fingerprint(with_evaluator_toggles)


def test_fingerprint_changes_with_quality_fields():
    """指纹字段变更必变指纹（回归判定有效性的前提）。"""
    from novamind.features.evaluation.services.config_fingerprint import (
        compute_config_fingerprint,
    )

    a = compute_config_fingerprint({"llm_model": "m1"})
    b = compute_config_fingerprint({"llm_model": "m2"})
    c = compute_config_fingerprint({"search_mode": "content_bm25"})
    assert a != b
    assert a != c


def test_fingerprint_chinese_model_name_stable():
    """中文模型名跨调用稳定（ensure_ascii=False + utf-8 编码）。"""
    from novamind.features.evaluation.services.config_fingerprint import (
        compute_config_fingerprint,
    )

    cfg = {"llm_model": "通义千问-测试版"}
    assert compute_config_fingerprint(cfg) == compute_config_fingerprint(dict(cfg))
