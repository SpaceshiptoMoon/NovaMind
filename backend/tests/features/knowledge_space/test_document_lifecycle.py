"""单元测试：kb-ops B1 文档生命周期状态机。

覆盖：
- 状态机转换表（合法/非法路径穷举）
- supersede/archive/reactivate 的 DB 落状态 + 版本链锚点
- 非法转换抛 DocumentLifecycleError；不存在/软删除抛 ValueError
- ES 同步失败回滚 DB 状态（失败方向安全的核心断言）
- SCHEMA_MIGRATIONS 注册完整性（六列齐全）

ES 交互全部打桩（_sync_es_chunks），DB 交互走 SQLite 内存库定向建表。
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


@pytest_asyncio.fixture
async def lc_db():
    """SQLite 内存库：documents + users（FK 目标）。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_space.models.document import Document
    from novamind.features.user.models.user import User

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[User.__table__, Document.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_doc(factory, *, doc_id: int, status: str = "active", **kwargs) -> None:
    from novamind.features.knowledge_space.models.document import Document

    async with factory() as session:
        session.add(Document(
            id=doc_id, space_id=kwargs.get("space_id", 10), kb_id=1,
            uploader_id=1, filename=f"doc{doc_id}.pdf", file_type="pdf",
            file_size=100, file_hash=f"h{doc_id}",
            lifecycle_status=status,
            superseded_by_doc_id=kwargs.get("superseded_by_doc_id"),
            deleted_at=kwargs.get("deleted_at"),
        ))
        await session.commit()


async def _get_doc(factory, doc_id: int):
    from novamind.features.knowledge_space.models.document import Document

    async with factory() as session:
        row = (await session.execute(
            select(Document).where(Document.id == doc_id)
        )).scalar_one_or_none()
        if row is None:
            return None
        session.expunge(row)
        return row


# ========== 状态机转换表 ==========


def test_transition_table():
    """转换表：合法路径齐全、非法路径封闭。"""
    from novamind.features.knowledge_space.models.document import DocumentLifecycleStatus as L

    assert L.ALLOWED_TRANSITIONS[L.DRAFT] == {L.ACTIVE}
    assert L.ALLOWED_TRANSITIONS[L.ACTIVE] == {L.SUPERSEDED, L.ARCHIVED}
    assert L.ALLOWED_TRANSITIONS[L.SUPERSEDED] == {L.ARCHIVED, L.ACTIVE}
    assert L.ALLOWED_TRANSITIONS[L.ARCHIVED] == {L.ACTIVE}
    # 退役状态白名单 = 检索排除面
    assert L.RETIREMENT_STATES == {L.SUPERSEDED, L.ARCHIVED}


# ========== DB 转换 ==========


@pytest.mark.asyncio
async def test_supersede_sets_status_and_version_link(lc_db):
    """supersede：旧文档 → superseded + superseded_by_doc_id 锚点 + ES 同步。"""
    from novamind.features.knowledge_space.services.lifecycle_service import LifecycleService

    factory, _ = lc_db
    await _seed_doc(factory, doc_id=1, status="active")
    await _seed_doc(factory, doc_id=2, status="active")

    with patch(
        "novamind.features.knowledge_space.services.lifecycle_service.LifecycleService._sync_es_chunks",
        new=AsyncMock(return_value=5),
    ):
        async with factory() as session:
            svc = LifecycleService(session)
            doc = await svc.supersede(old_doc_id=1, new_doc_id=2)
    assert doc.lifecycle_status == "superseded"
    assert doc.superseded_by_doc_id == 2


@pytest.mark.asyncio
async def test_archive_and_reactivate_roundtrip(lc_db):
    """archive：active → archived；reactivate：archived → active（唯一回退）。"""
    from novamind.features.knowledge_space.services.lifecycle_service import LifecycleService

    factory, _ = lc_db
    await _seed_doc(factory, doc_id=1, status="active")

    with patch(
        "novamind.features.knowledge_space.services.lifecycle_service.LifecycleService._sync_es_chunks",
        new=AsyncMock(return_value=3),
    ):
        async with factory() as session:
            doc = await LifecycleService(session).archive(1)
        assert doc.lifecycle_status == "archived"

        async with factory() as session:
            doc = await LifecycleService(session).reactivate(1)
    assert doc.lifecycle_status == "active"
    # 回退不残留版本链
    assert doc.superseded_by_doc_id is None or doc.superseded_by_doc_id == 1 * 0  # 未设置


@pytest.mark.asyncio
async def test_illegal_transition_raises(lc_db):
    """非法转换：draft → archived / draft → superseded 直接拒绝。"""
    from novamind.features.knowledge_space.services.lifecycle_service import (
        DocumentLifecycleError,
        LifecycleService,
    )

    factory, _ = lc_db
    await _seed_doc(factory, doc_id=1, status="draft")

    async with factory() as session:
        svc = LifecycleService(session)
        with pytest.raises(DocumentLifecycleError):
            await svc.archive(1)
        with pytest.raises(DocumentLifecycleError):
            await svc.supersede(1, 2)


@pytest.mark.asyncio
async def test_missing_or_deleted_doc_raises(lc_db):
    """不存在 / 软删除文档 → ValueError。"""
    from novamind.features.knowledge_space.services.lifecycle_service import LifecycleService
    from datetime import datetime

    factory, _ = lc_db
    await _seed_doc(factory, doc_id=1, status="active", deleted_at=datetime.now())

    async with factory() as session:
        svc = LifecycleService(session)
        with pytest.raises(ValueError):
            await svc.archive(999)
        with pytest.raises(ValueError):
            await svc.archive(1)


# ========== ES 同步失败回滚（失败方向安全核心） ==========


@pytest.mark.asyncio
async def test_es_sync_failure_rolls_back_db(lc_db):
    """ES 同步失败 → DB 状态回滚到 active（不留「DB 下线检索照出」的错误状态）。"""
    from novamind.features.knowledge_space.services.lifecycle_service import LifecycleService

    factory, _ = lc_db
    await _seed_doc(factory, doc_id=1, status="active")

    async def _es_fail(space_id, doc_id, status):
        raise RuntimeError("ES down")

    with patch(
        "novamind.features.knowledge_space.services.lifecycle_service.LifecycleService._sync_es_chunks",
        new=_es_fail,
    ):
        async with factory() as session:
            with pytest.raises(RuntimeError):
                await LifecycleService(session).archive(1)

    doc = await _get_doc(factory, 1)
    assert doc.lifecycle_status == "active"  # 已回滚


# ========== 迁移注册完整性 ==========


def test_schema_migrations_registered():
    """SCHEMA_MIGRATIONS 含 documents 六列（模型字段与迁移同步的守卫）。"""
    from novamind.core.database.schema_migrations import SCHEMA_MIGRATIONS

    doc_columns = {c for t, c, _ in SCHEMA_MIGRATIONS if t == "documents"}
    expected = {
        "lifecycle_status", "owner_id", "effective_date",
        "review_cycle_days", "next_review_at", "superseded_by_doc_id",
    }
    assert expected <= doc_columns
