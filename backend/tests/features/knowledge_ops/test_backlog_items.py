"""单元测试：kb-ops backlog 三项——检索权限过滤 / 第四分归因 / 质量基线回归判定。

覆盖：
- document_permission_filter：清单提取容错/过滤正确性/空清单零成本
- SpaceAccessChecker：hidden_doc_ids 校验保留（bool-only 归一不再丢清单）
- attribution_worker：permission_boundary 判定分支（用户零命中+绕权限命中）
- quality_baseline.judge_regression：关键指标降幅告警/非关键忽略/基线零除保护
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


# ========== document_permission_filter ==========


def test_extract_hidden_doc_ids_tolerant():
    """坏类型剔除、非正数剔除、None/缺键空表。"""
    from novamind.features.knowledge_space.services.document_permission_filter import (
        extract_hidden_doc_ids,
    )

    assert extract_hidden_doc_ids({"documents": {"hidden_doc_ids": [1, 2.0, "x", -3, True]}}) == [1, 2]
    assert extract_hidden_doc_ids(None) == []
    assert extract_hidden_doc_ids({"documents": {}}) == []
    assert extract_hidden_doc_ids({"knowledge_bases": {"manage": True}}) == []


def test_filter_results_by_permission():
    """剔除命中文档；空清单原样返回（同一对象，零成本路径）。"""
    from novamind.features.knowledge_space.services.document_permission_filter import (
        filter_results_by_permission,
    )

    results = [{"document_id": 1}, {"document_id": 2}, {"document_id": None}]
    assert len(filter_results_by_permission(results, [1])) == 2
    assert filter_results_by_permission(results, []) is results


@pytest.mark.asyncio
async def test_apply_filter_query_fails_open():
    """清单查询异常 → 不过滤（宽松方向）+ 告警。"""
    from novamind.features.knowledge_space.services.document_permission_filter import (
        apply_document_permission_filter,
    )

    results = [{"document_id": 1}]

    with patch(
        "novamind.features.knowledge_space.services.document_permission_filter."
        "get_hidden_doc_ids_for_member",
        new=AsyncMock(side_effect=RuntimeError("db gone")),
    ):
        out = await apply_document_permission_filter(None, space_id=1, user_id=1, results=results)
    assert out == results


# ========== SpaceAccessChecker 校验器 ==========


def test_validator_keeps_hidden_doc_ids():
    """hidden_doc_ids 校验通过且归一保留（此前 bool-only 归一会丢清单）。"""
    from novamind.features.knowledge_space.services.permission_service import SpaceAccessChecker

    ok = SpaceAccessChecker.validate_custom_permissions({
        "documents": {"hidden_doc_ids": [3, 4.0], "upload": True},
        "knowledge_bases": {"manage": False},
    })
    assert ok["documents"]["hidden_doc_ids"] == [3, 4]
    assert ok["documents"]["upload"] is True
    assert ok["knowledge_bases"]["manage"] is False


def test_validator_rejects_bad_doc_ids():
    """非正整数清单 / bool 混入拒绝。"""
    from novamind.features.knowledge_space.services.permission_service import SpaceAccessChecker

    for bad in (["x"], [-1], [True], "3"):
        try:
            SpaceAccessChecker.validate_custom_permissions({"documents": {"hidden_doc_ids": bad}})
            raise SystemExit(f"should raise for {bad}")
        except ValueError:
            pass


# ========== attribution permission_boundary ==========


@pytest.mark.asyncio
async def test_attribution_permission_boundary_branch():
    """四分判定第四支：用户视角（含降阈值）零命中 + 绕权限命中 → permission_boundary。

    _replay_search 全桩（记录 bypass 参数），判定逻辑真跑（SQLite 造消息对）。
    """
    from datetime import datetime

    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        ATTR_PERMISSION_BOUNDARY,
        attribute_single_event,
    )
    from novamind.features.knowledge_space.models.document import Document
    from novamind.features.qa.models.question_answer import QuestionAnswer
    from novamind.features.qa.models.session_config import SessionConfig

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    from novamind.core.database.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(
            c, tables=[QuestionAnswer.__table__, Document.__table__, SessionConfig.__table__],
        ))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        session.add(QuestionAnswer(id=1, session_id="s1", user_id=1, role="user", content="绩效评分标准"))
        session.add(QuestionAnswer(id=2, session_id="s1", user_id=1, role="assistant",
                                  content="答", space_id=10))
        await session.commit()

    calls = []

    async def _fake_replay(db, **kwargs):
        calls.append(kwargs)
        # 第 1/2 次（用户视角原始+降阈值）零命中；第 3 次（绕权限）命中
        return [{"document_id": 9}] if kwargs.get("bypass_document_permission") else []

    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", _fake_replay,
    ):
        async with factory() as db:
            attr = await attribute_single_event(db, 2)

    assert attr == ATTR_PERMISSION_BOUNDARY
    assert len(calls) == 3
    assert calls[2]["bypass_document_permission"] is True
    await engine.dispose()


# ========== quality_baseline 回归判定 ==========


def test_judge_regression_alerts_on_key_metric_drop():
    """关键指标降幅超阈值 → 告警；非关键指标忽略。"""
    from novamind.features.knowledge_ops.tasks.quality_baseline import judge_regression

    baseline = {"retrieval": {"mrr": 0.9, "noise": 0.1}, "generation": {"overall": 8.0}}
    current = {"retrieval": {"mrr": 0.8, "noise": 0.5}, "generation": {"overall": 7.9}}
    regressions = judge_regression(baseline, current, delta_threshold=0.05)
    keys = [r["key"] for r in regressions]
    assert "retrieval.mrr" in keys            # 降幅 11% 超阈值
    assert "generation.overall" not in keys   # 降幅 1.25% 容忍
    assert all("noise" not in k for k in keys)  # 非关键指标不参与


def test_judge_regression_zero_baseline_safe():
    """基线为零不除零（跳过该指标）。"""
    from novamind.features.knowledge_ops.tasks.quality_baseline import judge_regression

    assert judge_regression(
        {"retrieval": {"mrr": 0}}, {"retrieval": {"mrr": 0.5}},
    ) == []


def test_judge_regression_improvement_no_alert():
    """指标提升不告警。"""
    from novamind.features.knowledge_ops.tasks.quality_baseline import judge_regression

    assert judge_regression(
        {"retrieval": {"mrr": 0.8}}, {"retrieval": {"mrr": 0.95}},
    ) == []
