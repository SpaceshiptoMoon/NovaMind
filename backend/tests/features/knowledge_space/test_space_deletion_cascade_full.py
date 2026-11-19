"""空间删除级联全量覆盖回归测试（2026-11 红队确认缺陷修复）。

缺陷背景：删除级联曾用 ``get_by_space``（默认 limit=100、created_at desc）
当全量遍历——超过 100 个 KB 的空间删除时**最旧的 KB** 漏软删，而 ES/MinIO
清理是空间级全量，形成「DB 活跃行 + 底层资源已毁」的空壳不一致；同款缺陷
存在于 delete_space 与 leave_space（最后管理员离开级联）两条路径。修复：
级联统一改用无分页的 ``get_all_by_space``，leave_space 并补齐 delete_space
已有的检索缓存失效。

不变量：
1. 全量性：101 个 KB 的空间删除后全部软删——含 created_at 最旧的
   （desc+limit 截断恰好漏它），且其文档级联软删；
2. 不误伤：恰 100 个 KB（旧上限内）的删除行为与修复前一致；
3. leave_space 同语义：最后管理员离开 101 KB 空间 → 全部软删 + 审计 +
   缓存失效覆盖全量 KB。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from novamind.features.knowledge_space.models.knowledge_space import (
    KnowledgeSpace,
    SpaceStatus,
    SpaceVisibility,
)
from novamind.features.knowledge_space.models.space_audit_log import SpaceAuditLog
from novamind.features.knowledge_space.models.space_member import (
    MemberStatus,
    SpaceMember,
    SpaceRole,
)
from novamind.features.knowledge_space.services.member_service import MemberService
from novamind.features.knowledge_space.services.space_service import SpaceService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

# 只建两条级联路径实际触达的表（全量 create_all 在 SQLite 有元数据陷阱，见 tests/README）
_TABLES = [
    KnowledgeSpace.__table__,
    KnowledgeBase.__table__,
    Document.__table__,
    SpaceMember.__table__,
    SpaceAuditLog.__table__,
]

SPACE_ID = 1


def _kb(kb_id: int, created_at: datetime) -> KnowledgeBase:
    return KnowledgeBase(
        id=kb_id, space_id=SPACE_ID, name=f"kb-{kb_id}", creator_id=1,
        config={"embedding": {}}, status=KnowledgeBaseStatus.ACTIVE,
        created_at=created_at,
    )


def _doc(doc_id: int, kb_id: int) -> Document:
    return Document(
        id=doc_id, space_id=SPACE_ID, kb_id=kb_id, uploader_id=1,
        filename=f"doc-of-kb-{kb_id}.pdf", file_type="pdf", file_size=1,
        file_hash=f"hash-{kb_id}",
    )


async def _make_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_TABLES)
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return maker()


async def _seed_space(session: AsyncSession, kb_count: int) -> None:
    """建空间 + kb_count 个 KB（created_at 递增，id=1 最旧）+ 最旧 KB 挂 1 个文档。"""
    session.add(KnowledgeSpace(
        id=SPACE_ID, name="级联测试空间", owner_id=10,
        visibility=SpaceVisibility.PRIVATE, status=SpaceStatus.ACTIVE,
    ))
    base = datetime(2024, 1, 1)
    for i in range(1, kb_count + 1):
        session.add(_kb(i, base + timedelta(minutes=i)))
    # created_at 最旧的 KB（id=1）挂一个文档——desc+limit=100 截断时恰好它是漏网者
    session.add(_doc(1, kb_id=1))
    await session.commit()


def _patch_audit_create_with_manual_id(db: AsyncSession):
    """SQLite 下 space_audit_logs 的 BigInteger 主键不自动分配：包装 create 手动赋 id
    （同 test_space_invite_join 的 SpaceMember 手动 id 惯例）。返回原实现供恢复。"""
    from novamind.features.knowledge_space.repository.audit_repository import AuditRepository

    async def _create_wrapped(self, data: dict):
        log = SpaceAuditLog(**data)
        max_id = (await db.execute(select(func.max(SpaceAuditLog.id)))).scalar() or 0
        log.id = max_id + 1
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log

    orig = AuditRepository.create
    AuditRepository.create = _create_wrapped  # type: ignore[assignment]
    return orig


async def _all_kbs(session: AsyncSession) -> list[KnowledgeBase]:
    rows = (await session.execute(select(KnowledgeBase))).scalars().all()
    return list(rows)


async def test_delete_space_cascades_all_kbs_beyond_legacy_limit(fake_redis):
    """缺陷场景：101 个 KB 删除后必须全部软删（含最旧的），文档级联不漏。

    fake_redis 隔离缓存失效（单测不得触真实 Redis）；顺带断言失效覆盖全量。
    """
    session = await _make_session()
    await _seed_space(session, kb_count=101)
    await fake_redis.set("search:1:content_hybrid:h", {"r": 1}, expire=60)

    service = SpaceService(session)
    await service.delete_space(space_id=SPACE_ID, user_id=1)

    kbs = await _all_kbs(session)
    assert len(kbs) == 101
    not_deleted = [kb.id for kb in kbs if kb.deleted_at is None]
    assert not not_deleted, f"全部 KB 必须软删，漏网：{not_deleted}"
    oldest = next(kb for kb in kbs if kb.id == 1)
    assert oldest.deleted_at is not None, "created_at 最旧的 KB（desc+limit 截断的漏网者）必须软删"
    assert "search:1:content_hybrid:h" not in fake_redis.store, "最旧 KB 的检索缓存必须失效"

    docs = (await session.execute(select(Document))).scalars().all()
    assert len(docs) == 1 and docs[0].deleted_at is not None, "最旧 KB 的文档必须级联软删"

    space = await session.get(KnowledgeSpace, SPACE_ID)
    assert space.deleted_at is not None, "空间本身必须软删"
    members = (await session.execute(select(SpaceMember))).scalars().all()
    assert members == [], "空间成员记录必须清空"


async def test_delete_space_within_legacy_limit_still_fully_cascades(fake_redis):
    """不误伤：恰 100 个 KB（旧上限内）的删除行为与修复前一致。"""
    session = await _make_session()
    await _seed_space(session, kb_count=100)

    service = SpaceService(session)
    await service.delete_space(space_id=SPACE_ID, user_id=1)

    kbs = await _all_kbs(session)
    assert len(kbs) == 100
    assert all(kb.deleted_at is not None for kb in kbs), "100 KB 空间必须全部软删"


async def test_last_admin_leave_cascades_all_kbs_writes_audit_and_invalidates_cache(fake_redis):
    """leave_space 同语义：101 KB 全软删 + kb_delete/space_delete 审计 + 缓存失效覆盖全量。"""
    session = await _make_session()
    await _seed_space(session, kb_count=101)
    # 最后一名管理员（owner_id=10 不在成员表中，user 20 是唯一 ADMIN）
    session.add(SpaceMember(
        id=1, space_id=SPACE_ID, user_id=20, role=SpaceRole.ADMIN,
        status=MemberStatus.ACTIVE, invited_by=10,
    ))
    await session.commit()

    # 预置检索缓存键：首/中/尾三个 KB + 一个非本空间键
    for kb_id in (1, 50, 101):
        await fake_redis.set(f"search:{kb_id}:content_hybrid:h", {"r": 1}, expire=60)
    await fake_redis.set("search:999:content_hybrid:h", {"r": 2}, expire=60)

    service = MemberService(session)
    orig_audit_create = _patch_audit_create_with_manual_id(session)
    try:
        result = await service.leave_space(space_id=SPACE_ID, user_id=20, confirm=True)
    finally:
        from novamind.features.knowledge_space.repository.audit_repository import AuditRepository

        AuditRepository.create = orig_audit_create  # type: ignore[assignment]
    assert result is True

    kbs = await _all_kbs(session)
    assert len(kbs) == 101
    assert all(kb.deleted_at is not None for kb in kbs), "leave_space 级联必须软删全部 KB"

    space = await session.get(KnowledgeSpace, SPACE_ID)
    assert space.deleted_at is not None

    audits = (await session.execute(select(SpaceAuditLog))).scalars().all()
    actions = [a.action for a in audits]
    assert actions.count("kb_delete") == 101, "每个 KB 一条 kb_delete 审计"
    assert "space_delete" in actions

    for kb_id in (1, 50, 101):
        assert f"search:{kb_id}:content_hybrid:h" not in fake_redis.store, f"KB {kb_id} 的检索缓存必须失效"
    assert "search:999:content_hybrid:h" in fake_redis.store, "非本空间的缓存键必须存活"
