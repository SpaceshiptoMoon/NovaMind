"""单元测试：kb-ops A2——gap 聚合仓库 + 周报渲染。

覆盖：
- GapRepository：gap 清单聚类（同问合并/频次排序）、待归因计数、归因分布、
  空间双通道过滤（消息行 space_id + 反馈表冗余）、正常回答不进（反例）
- _render_digest_content：空窗不渲染条目、top 截断、归因分布行
- _last_week_window：自然周边界

DB 交互 SQLite 内存库定向建表（question_answers + qa_message_feedback）。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

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


@pytest_asyncio.fixture
async def gap_db():
    """SQLite 内存库：question_answers + qa_message_feedback（StaticPool）。"""
    from novamind.core.database.base import Base
    from novamind.features.qa.models.qa_feedback import MessageFeedback
    from novamind.features.qa.models.question_answer import QuestionAnswer

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[QuestionAnswer.__table__, MessageFeedback.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_failure(
    factory,
    *,
    answer_id: int,
    session_id: str = "s1",
    space_id: int | None = 10,
    query: str = "退货流程是什么",
    extra: dict | None = None,
    user_id: int = 1,
):
    """插入 (user 提问, assistant 失败回答) 对，answer extra 可注入 attribution。"""
    from novamind.features.qa.models.question_answer import QuestionAnswer

    base_extra = {"retrieval": {"result_count": 0, "max_score": None}, "answer_status": "answered"}
    if extra:
        base_extra.update(extra)
    async with factory() as session:
        session.add(QuestionAnswer(
            id=answer_id - 1, session_id=session_id, user_id=user_id,
            role="user", content=query,
        ))
        session.add(QuestionAnswer(
            id=answer_id, session_id=session_id, user_id=user_id,
            role="assistant", content="回答", space_id=space_id, extra=base_extra,
        ))
        await session.commit()


def _repo(factory):
    from novamind.features.knowledge_ops.repository.gap_repository import GapRepository

    return GapRepository


# ========== gap 清单聚类 ==========


@pytest.mark.asyncio
async def test_gap_items_cluster_same_query(gap_db):
    """同问多次失败聚成一簇（归一化合并），频次正确、按频次降序。"""
    from novamind.features.knowledge_ops.repository.gap_repository import GapRepository

    factory, _ = gap_db
    # 同一问题的两种措辞（归一化后不同——精确聚类 v1 只合并完全同文）
    await _seed_failure(factory, answer_id=2, query="量子计算入门学什么", extra={"attribution": "content_gap"})
    await _seed_failure(factory, answer_id=4, session_id="s2", query="量子计算入门学什么", extra={"attribution": "content_gap"})
    await _seed_failure(factory, answer_id=6, session_id="s3", query="如何部署集群", extra={"attribution": "content_gap"})

    now = datetime.now()
    async with factory() as session:
        repo = GapRepository(session)
        items = await repo.list_gap_items(10, now - timedelta(days=1), now + timedelta(hours=1))

    assert len(items) == 2
    assert items[0]["hit_count"] == 2  # 同问两簇中频次高的在前
    assert items[0]["query"] == "量子计算入门学什么"
    assert len(items[0]["message_ids"]) == 2
    assert items[1]["hit_count"] == 1


@pytest.mark.asyncio
async def test_gap_items_excludes_other_attributions(gap_db):
    """gap 清单只含 content_gap；retrieval_failure/未归因不进清单（但进分布）。"""
    from novamind.features.knowledge_ops.repository.gap_repository import GapRepository

    factory, _ = gap_db
    await _seed_failure(factory, answer_id=2, query="缺内容的问题", extra={"attribution": "content_gap"})
    await _seed_failure(factory, answer_id=4, session_id="s2", query="检索失败的问题", extra={"attribution": "retrieval_failure"})
    await _seed_failure(factory, answer_id=6, session_id="s3", query="还没归因的问题")

    now = datetime.now()
    async with factory() as session:
        repo = GapRepository(session)
        items = await repo.list_gap_items(10, now - timedelta(days=1), now + timedelta(hours=1))
        dist = await repo.attribution_distribution(10, now - timedelta(days=1), now + timedelta(hours=1))
        pending = await repo.count_pending_attribution(10, now - timedelta(days=1), now + timedelta(hours=1))

    assert len(items) == 1
    assert items[0]["query"] == "缺内容的问题"
    assert dist == {"content_gap": 1, "retrieval_failure": 1, "pending": 1}
    assert pending == 1


@pytest.mark.asyncio
async def test_space_isolation_and_feedback_channel(gap_db):
    """空间隔离（他空间数据不可见）+ 反馈表通道（消息行 space 为空靠点踩命中）。"""
    from novamind.features.knowledge_ops.repository.gap_repository import GapRepository
    from novamind.features.qa.models.qa_feedback import MessageFeedback

    factory, _ = gap_db
    # 空间 10 的 content_gap
    await _seed_failure(factory, answer_id=2, space_id=10, query="空间10的缺口", extra={"attribution": "content_gap"})
    # 空间 99 的 content_gap（不可见）
    await _seed_failure(factory, answer_id=4, session_id="s99", space_id=99, query="空间99的缺口", extra={"attribution": "content_gap"})
    # 空间 10 的点踩消息：消息行 space=None（O2 教训），靠反馈表 space_id=10 命中
    await _seed_failure(
        factory, answer_id=6, session_id="s-fb", space_id=None, query="点踩的问题",
        extra={"attribution": "retrieval_failure",
               "retrieval": {"result_count": 5, "max_score": 0.9}},
    )
    async with factory() as session:
        session.add(MessageFeedback(
            message_id=6, user_id=1, session_id="s-fb", space_id=10, rating="down",
        ))
        await session.commit()

    now = datetime.now()
    async with factory() as session:
        repo = GapRepository(session)
        dist = await repo.attribution_distribution(10, now - timedelta(days=1), now + timedelta(hours=1))

    assert dist == {"content_gap": 1, "retrieval_failure": 1}  # 空间99 不可见；点踩通道命中


@pytest.mark.asyncio
async def test_healthy_answers_excluded(gap_db):
    """反例：正常高分回答不进任何统计。"""
    from novamind.features.knowledge_ops.repository.gap_repository import GapRepository

    factory, _ = gap_db
    await _seed_failure(
        factory, answer_id=2, query="正常问题",
        extra={"attribution": "",
               "retrieval": {"result_count": 5, "max_score": 0.9}},
    )

    now = datetime.now()
    async with factory() as session:
        repo = GapRepository(session)
        dist = await repo.attribution_distribution(10, now - timedelta(days=1), now + timedelta(hours=1))
        items = await repo.list_gap_items(10, now - timedelta(days=1), now + timedelta(hours=1))
        pending = await repo.count_pending_attribution(10, now - timedelta(days=1), now + timedelta(hours=1))

    assert dist == {}
    assert items == []
    assert pending == 0


# ========== service 组装 ==========


@pytest.mark.asyncio
async def test_gap_report_service_assembles_kpi(gap_db):
    """service 层组装：KPI 汇总（failure_total/pending/gap 计数）与窗口回填。"""
    from novamind.features.knowledge_ops.services.gap_report_service import GapReportService

    factory, _ = gap_db
    await _seed_failure(factory, answer_id=2, query="缺口A", extra={"attribution": "content_gap"})
    await _seed_failure(factory, answer_id=4, session_id="s2", query="缺口A", extra={"attribution": "content_gap"})
    await _seed_failure(factory, answer_id=6, session_id="s3", query="检索失败B", extra={"attribution": "retrieval_failure"})

    now = datetime.now()
    async with factory() as session:
        service = GapReportService(session)
        report = await service.get_gap_report(10, start=now - timedelta(days=1), end=now + timedelta(hours=1))

    assert report["kpi"]["failure_total"] == 3
    assert report["kpi"]["pending_attribution"] == 0
    assert report["kpi"]["gap_cluster_count"] == 1
    assert report["kpi"]["gap_query_count"] == 2
    assert report["attribution_distribution"]["content_gap"] == 2
    assert report["attribution_distribution"]["retrieval_failure"] == 1
    assert report["gap_items"][0]["hit_count"] == 2
    assert "start" in report["window"] and "end" in report["window"]


# ========== 周报渲染与窗口 ==========


def test_last_week_window_boundaries():
    """自然周窗口：上周一 00:00 ~ 本周一 00:00。"""
    from novamind.features.knowledge_ops.tasks.weekly_digest import _last_week_window

    ws, we = _last_week_window(datetime(2026, 10, 1, 15, 30))  # 周四
    assert ws == datetime(2026, 9, 21, 0, 0)   # 上上周一？不——9-28 是周一，9-21 是上上周一
    # 2026-10-01 是周四：本周一 = 09-28；上周一 = 09-21 ✓
    assert we == datetime(2026, 9, 28, 0, 0)
    assert ws.weekday() == 0 and we.weekday() == 0


def test_render_digest_content():
    """周报正文：含统计行 + top 条目 + 归因分布；空窗清单不渲染条目行。"""
    from novamind.features.knowledge_ops.tasks.weekly_digest import _render_digest_content

    report = {
        "kpi": {"failure_total": 5, "pending_attribution": 1,
                "gap_cluster_count": 2, "gap_query_count": 3},
        "attribution_distribution": {"content_gap": 3, "retrieval_failure": 1, "pending": 1},
        "gap_items": [
            {"query": "量子计算入门", "hit_count": 2, "message_ids": [1, 2]},
            {"query": "集群部署", "hit_count": 1, "message_ids": [3]},
        ],
        "window": {"start": "2026-09-21T00:00:00", "end": "2026-09-28T00:00:00"},
    }
    content = _render_digest_content(report)
    assert "5 次提问未获理想回答" in content
    assert "量子计算入门" in content
    assert "提问 2 次" in content
    assert "content_gap:3" in content

    # 空窗：无条目时不渲染编号行
    empty = _render_digest_content({
        "kpi": {"failure_total": 2, "pending_attribution": 2,
                "gap_cluster_count": 0, "gap_query_count": 0},
        "attribution_distribution": {"pending": 2},
        "gap_items": [],
        "window": {"start": "", "end": ""},
    })
    assert "Top" in empty and "1." not in empty
