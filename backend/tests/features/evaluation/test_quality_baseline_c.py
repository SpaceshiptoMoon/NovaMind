"""单元测试：kb-ops C——配置指纹稳定性 + 合成测试集解析。

覆盖：
- compute_config_fingerprint：同配置恒同值（显式默认值=不传）、键序无关、
  非指纹字段变更不影响、中文值跨编码稳定
- parse_generation_response：正常解析 / ```json 围栏 / 坏 JSON / 缺字段跳过 / 配额截断
- build_generation_prompt：片段数与截断
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


# ========== 合成测试集解析 ==========


def test_parse_generation_response_normal():
    """正常 JSON 解析：question/expected_answer 齐全的用例提取。"""
    from novamind.features.evaluation.services.testset_generation import (
        parse_generation_response,
    )

    resp = '{"cases": [{"chunk_index": 1, "question": "什么是RAG", "expected_answer": "检索增强生成"}, {"chunk_index": 2, "question": "", "expected_answer": "空问题应跳过"}]}'
    cases = parse_generation_response(resp, expected_count=10)
    assert len(cases) == 1
    assert cases[0]["question"] == "什么是RAG"


def test_parse_generation_response_markdown_fence():
    """```json 围栏容忍。"""
    from novamind.features.evaluation.services.testset_generation import (
        parse_generation_response,
    )

    resp = '```json\n{"cases": [{"question": "Q", "expected_answer": "A"}]}\n```'
    cases = parse_generation_response(resp, expected_count=10)
    assert len(cases) == 1


def test_parse_generation_response_bad_json_returns_empty():
    """坏 JSON 返回空列表（容错不抛）。"""
    from novamind.features.evaluation.services.testset_generation import (
        parse_generation_response,
    )

    assert parse_generation_response("不是JSON", expected_count=5) == []
    assert parse_generation_response("", expected_count=5) == []


def test_parse_generation_response_quota_truncates():
    """配额截断：超出 expected_count 的用例丢弃。"""
    from novamind.features.evaluation.services.testset_generation import (
        parse_generation_response,
    )

    resp = '{"cases": [{"question": "q1", "expected_answer": "a1"}, {"question": "q2", "expected_answer": "a2"}, {"question": "q3", "expected_answer": "a3"}]}'
    cases = parse_generation_response(resp, expected_count=2)
    assert len(cases) == 2


def test_build_generation_prompt_sections():
    """prompt 构造：片段编号齐全、超长截断到 CHUNK_TEXT_LIMIT。"""
    from novamind.features.evaluation.services.testset_generation import (
        CHUNK_TEXT_LIMIT,
        build_generation_prompt,
    )

    texts = ["短片段", "长" * (CHUNK_TEXT_LIMIT + 500)]
    prompt = build_generation_prompt(texts)
    assert "### 片段 1" in prompt and "### 片段 2" in prompt
    # 超长片段被截断（片段 2 的内容长度 ≤ CHUNK_TEXT_LIMIT）
    assert (CHUNK_TEXT_LIMIT + 500) not in [len(prompt)]  # 冒烟：prompt 总长受控
    assert prompt.count("长") <= CHUNK_TEXT_LIMIT + 20  # 截断生效（含格式字符余量）
