"""单元测试：kb-ops B2——复审建议（新版识别/幂等/处置）+ 复审提醒。

覆盖：
- normalize_filename：版本号/日期后缀归一（正反例）
- detect_new_version_suggestions：同 KB 同归一化名建议生成；异名/已退役/
  跨 KB 不建议（反例）；幂等（重复判定不重复建）
- SuggestionRepository：upsert 幂等 / resolve 状态机 / 非法动作拒绝
- review_reminder：next_review_at 窗口扫描 / 无 next_review_at 不提醒 /
  compute_next_review_at 周期顺延
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

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
async def b2_db():
    """SQLite 内存库：documents + kb_review_suggestions。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_review_suggestion import (
        KbReviewSuggestion,
    )
    from novamind.features.knowledge_space.models.document import Document

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[Document.__table__, KbReviewSuggestion.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_doc(factory, *, doc_id: int, kb_id: int = 1, space_id: int = 10,
                    filename: str = "退货政策.pdf", status: str = "active", **kw):
    from novamind.features.knowledge_space.models.document import Document

    async with factory() as session:
        session.add(Document(
            id=doc_id, space_id=space_id, kb_id=kb_id, uploader_id=1,
            filename=filename, file_type="pdf", file_size=100, file_hash=f"h{doc_id}",
            lifecycle_status=status,
            owner_id=kw.get("owner_id", 1),
            next_review_at=kw.get("next_review_at"),
            review_cycle_days=kw.get("review_cycle_days"),
            deleted_at=kw.get("deleted_at"),
        ))
        await session.commit()


# ========== 文件名归一化 ==========


def test_normalize_filename_variants():
    """版本号/日期/标记后缀归一到同一键；不同主题不合并（反例）。"""
    from novamind.features.knowledge_ops.services.new_version_detector import (
        normalize_filename,
    )

    assert normalize_filename("退货政策v2.pdf") == normalize_filename("退货政策.PDF")
    assert normalize_filename("退货政策_final.docx") == normalize_filename("退货政策.pdf")
    assert normalize_filename("政策-20240101.md") == normalize_filename("政策.pdf")
    assert normalize_filename("报告_v2_final.pdf") == normalize_filename("报告.PDF")
    # 反例：不同主题不合并
    assert normalize_filename("报销政策.pdf") != normalize_filename("退货政策.pdf")


# ========== 新版识别 ==========


@pytest.mark.asyncio
async def test_detect_suggests_for_same_normalized_name(b2_db):
    """正例：同 KB 同归一化名（退货政策v2 vs 退货政策）→ 建议。"""
    from novamind.features.knowledge_ops.services.new_version_detector import (
        detect_new_version_suggestions,
    )

    factory, _ = b2_db
    await _seed_doc(factory, doc_id=1, filename="退货政策.pdf", status="active")
    await _seed_doc(factory, doc_id=2, filename="退货政策v2.pdf", status="active")

    with patch(
        "novamind.core.database.database.get_db_session"
    ) as mock_session:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
            async with factory() as session:
                yield session

        mock_session.side_effect = _ctx
        created = await detect_new_version_suggestions(
            space_id=10, kb_id=1, new_doc_id=2,
        )
    assert len(created) == 1


@pytest.mark.asyncio
async def test_detect_ignores_different_names_and_retired(b2_db):
    """反例：异名不建；旧版已 superseded 不建；跨 KB 不建。"""
    from novamind.features.knowledge_ops.services.new_version_detector import (
        detect_new_version_suggestions,
    )

    factory, _ = b2_db
    await _seed_doc(factory, doc_id=1, filename="完全不同.pdf", status="active")
    await _seed_doc(factory, doc_id=3, filename="退货政策.pdf", status="superseded")
    await _seed_doc(factory, doc_id=5, kb_id=99, filename="退货政策.pdf", status="active")
    await _seed_doc(factory, doc_id=6, filename="退货政策v3.pdf", status="active")

    with patch(
        "novamind.core.database.database.get_db_session"
    ) as mock_session:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
            async with factory() as session:
                yield session

        mock_session.side_effect = _ctx
        created = await detect_new_version_suggestions(
            space_id=10, kb_id=1, new_doc_id=6,
        )
    assert created == []


@pytest.mark.asyncio
async def test_detect_idempotent(b2_db):
    """幂等：同一对文档重复判定只建一条建议。"""
    from novamind.features.knowledge_ops.services.new_version_detector import (
        detect_new_version_suggestions,
    )

    factory, _ = b2_db
    await _seed_doc(factory, doc_id=1, filename="退货政策.pdf", status="active")
    await _seed_doc(factory, doc_id=2, filename="退货政策v2.pdf", status="active")

    async def _run():
        with patch(
            "novamind.core.database.database.get_db_session"
        ) as mock_session:
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def _ctx():
                async with factory() as session:
                    yield session

            mock_session.side_effect = _ctx
            return await detect_new_version_suggestions(
                space_id=10, kb_id=1, new_doc_id=2,
            )

    first = await _run()
    second = await _run()
    assert len(first) == 1
    assert second == []  # 幂等跳过


# ========== 建议 repository 处置 ==========


@pytest.mark.asyncio
async def test_resolve_suggestion_states(b2_db):
    """处置：accept/dismiss 落状态与处置人；非法动作拒绝；不存在返回 None。"""
    from novamind.features.knowledge_ops.repository.suggestion_repository import (
        SUGGESTION_NEW_VERSION,
        SuggestionRepository,
    )

    factory, _ = b2_db
    async with factory() as session:
        repo = SuggestionRepository(session)
        s1 = await repo.upsert_open_suggestion(
            space_id=10, kb_id=1, suggestion_type=SUGGESTION_NEW_VERSION,
            old_doc_id=1, new_doc_id=2, score=10000,
        )
        resolved = await repo.resolve(s1.id, "accepted", user_id=9)
        assert resolved.status == "accepted"
        assert resolved.resolved_by == 9
        with pytest.raises(ValueError):
            await repo.resolve(s1.id, "hijack", user_id=9)
        assert await repo.resolve(999, "accepted", user_id=9) is None


# ========== 复审提醒 ==========


@pytest.mark.asyncio
async def test_review_reminder_window(b2_db):
    """提醒窗口：临期/过期 active 文档提醒；无 next_review_at / 已退役不提醒。"""
    from contextlib import asynccontextmanager

    from novamind.features.knowledge_ops.tasks.review_reminder import (
        send_review_reminders,
    )

    factory, _ = b2_db
    now = datetime.now()
    await _seed_doc(factory, doc_id=1, filename="临期.pdf", next_review_at=now + timedelta(days=3))
    await _seed_doc(factory, doc_id=2, filename="过期.pdf", next_review_at=now - timedelta(days=10))
    await _seed_doc(factory, doc_id=3, filename="远期.pdf", next_review_at=now + timedelta(days=60))
    await _seed_doc(factory, doc_id=4, filename="无期限.pdf", next_review_at=None)
    await _seed_doc(factory, doc_id=5, filename="已退役.pdf",
                    next_review_at=now - timedelta(days=1), status="archived")

    # get_db_session 是函数内 import——patch 源模块属性（A1 同款手法）
    with patch("novamind.core.database.database.get_db_session") as mock_session:

        @asynccontextmanager
        async def _ctx():
            async with factory() as session:
                yield session

        mock_session.side_effect = _ctx
        # 通知发送同样旁路（不验证通知表，只验证扫描窗口语义）
        with patch(
            "novamind.features.notification.services.notification_service."
            "NotificationService.send_notification",
            new=_async_noop,
        ):
            notified = await send_review_reminders()
    assert sorted(notified.keys()) == ["1", "2"]  # 仅临期+过期
    assert notified["1"] == 1 and notified["2"] == 1


async def _async_noop(*args, **kwargs):
    return None


def test_compute_next_review_at_fallback():
    """周期顺延：有周期用周期，无周期回退默认 90 天。"""
    from novamind.features.knowledge_ops.tasks.review_reminder import (
        compute_next_review_at,
    )

    base = datetime(2026, 10, 1)
    assert compute_next_review_at(30, 90, base=base) == datetime(2026, 10, 31)
    assert compute_next_review_at(None, 90, base=base) == datetime(2026, 12, 30)
