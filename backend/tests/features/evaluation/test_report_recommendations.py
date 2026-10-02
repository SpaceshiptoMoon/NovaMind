"""
报告级诊断建议聚合（批次 4 闭环行动腿）回归测试

覆盖 _build_recommendations 三路来源与阈值行为：
- 检索失败归因按类别分组计数、targets 去重收集
- 切分健康超过保守提示线才提示（阈值边界两侧）
- 生成质量低于及格线提示
- 按 count 降序、空输入返回空表
"""

from novamind.features.evaluation.services.evaluation_service import _build_recommendations


def _detail_with_diagnosis(category: str, sources: list[str]) -> dict:
    return {
        "failure_diagnosis": {"category": category, "evidence": "e", "suggestion": "s"},
        "retrieval": {"expected_sources": sources},
    }


def test_group_failure_diagnoses_with_dedup_targets():
    """同类别归因分组计数，期望来源文档去重收集。"""
    details = [
        _detail_with_diagnosis("index_missing", ["99999"]),
        _detail_with_diagnosis("index_missing", ["99999", "88888"]),
        _detail_with_diagnosis("ranking_issue", ["576"]),
    ]
    recs = _build_recommendations(details, None, {})
    by_cat = {r["category"]: r for r in recs}
    assert by_cat["index_missing"]["count"] == 2
    assert by_cat["index_missing"]["targets"] == ["99999", "88888"]
    assert by_cat["ranking_issue"]["count"] == 1
    # 按计数降序：index_missing(2) 在 ranking_issue(1) 前
    assert recs[0]["category"] == "index_missing"


def test_chunk_health_thresholds():
    """碎片/边界信号超保守提示线才进建议，低于线不提示。"""
    # 8 chunk 中 3 碎片（37.5% ≥ 30%）+ 4 边界（50% ≥ 50%）→ 两条都提示
    health = {"total_chunks": 8, "short_chunks": 3, "unterminated_chunks": 4}
    recs = _build_recommendations([], health, {})
    cats = {r["category"] for r in recs}
    assert cats == {"fragmentation", "boundary_cut"}

    # 低于线：10 chunk 中 2 碎片（20%）+ 4 边界（40%）→ 均不提示
    health_low = {"total_chunks": 10, "short_chunks": 2, "unterminated_chunks": 4}
    assert _build_recommendations([], health_low, {}) == []


def test_low_generation_recommendation():
    """生成综合分低于及格线（5 分）提示，达到线不提示。"""
    recs = _build_recommendations([], None, {"overall": 4.2})
    assert [r["category"] for r in recs] == ["low_generation"]
    assert _build_recommendations([], None, {"overall": 5.0}) == []
    assert _build_recommendations([], None, {}) == []


def test_empty_details_returns_empty():
    """无任何信号时返回空表（无需行动）。"""
    assert _build_recommendations([], None, {"overall": 8.0}) == []
