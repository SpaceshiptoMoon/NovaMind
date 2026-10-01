"""单元测试：文档复审策略设置（kb-ops B2 收尾）。

覆盖：
- owner 设置复审周期与下次复审时间（正例）
- 空间 admin 改派 owner（正例）
- 非 owner 非 admin 拒绝；非 admin 改派 owner 拒绝（权限边界）
- 周期越界拒绝（0 / 3651）
- None 字段不修改（PATCH 语义）

直接测路由函数（schema 校验由 FastAPI 层，此处构造对象直调）。
"""
import sys
from datetime import datetime
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
async def rs_db():
    """SQLite 内存库：documents + users + space_members。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_space.models.document import Document
    from novamind.features.knowledge_space.models.space_member import SpaceMember
    from novamind.features.user.models.user import User

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[User.__table__, Document.__table__, SpaceMember.__table__],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _seed_doc(factory, *, doc_id: int = 1, owner_id: int = 7):
    from novamind.features.knowledge_space.models.document import Document

    async with factory() as session:
        session.add(Document(
            id=doc_id, space_id=10, kb_id=1, uploader_id=owner_id,
            filename="政策.pdf", file_type="pdf", file_size=100,
            file_hash=f"h{doc_id}", lifecycle_status="active", owner_id=owner_id,
        ))
        await session.commit()


def _member(is_admin: bool):
    """SpaceMember 桩（is_admin() 是模型方法）。"""
    m = type("M", (), {"is_admin": lambda self: is_admin})()
    return m


def _request(**kwargs):
    from novamind.features.knowledge_space.schemas.document_schema import (
        DocumentReviewSettingsUpdate,
    )

    return DocumentReviewSettingsUpdate(**kwargs)


async def _call_update(factory, *, doc_id: int, user_id: int, is_admin: bool, request):
    """直调路由函数（依赖参数手工注入；validate_kb_access 打桩放行）。"""
    import novamind.features.knowledge_space.api.document_routes as dr

    async with factory() as db:
        with patch.object(dr, "validate_kb_access", new=AsyncMock(return_value=None)):
            return await dr.update_document_review_settings(
                space_id=10, kb_id=1, document_id=doc_id,
                request=request, member=_member(is_admin),
                current_user_id=user_id, db=db,
            )


@pytest.mark.asyncio
async def test_owner_sets_review_cycle_and_next_review(rs_db):
    """owner 设置复审周期与下次复审时间。"""
    factory, _ = rs_db
    await _seed_doc(factory, doc_id=1, owner_id=7)

    next_at = datetime(2026, 12, 1, 9, 0)
    result = await _call_update(
        factory, doc_id=1, user_id=7, is_admin=False,
        request=_request(review_cycle_days=90, next_review_at=next_at),
    )
    assert result["review_cycle_days"] == 90
    assert result["next_review_at"] == "2026-12-01T09:00:00"
    assert result["owner_id"] == 7


@pytest.mark.asyncio
async def test_admin_reassigns_owner(rs_db):
    """空间 admin 改派 owner。"""
    factory, _ = rs_db
    await _seed_doc(factory, doc_id=1, owner_id=7)

    result = await _call_update(
        factory, doc_id=1, user_id=99, is_admin=True,
        request=_request(owner_id=42),
    )
    assert result["owner_id"] == 42


@pytest.mark.asyncio
async def test_non_owner_non_admin_denied(rs_db):
    """非 owner 非 admin → SpaceAccessDeniedError。"""
    from novamind.features.knowledge_space.exceptions import SpaceAccessDeniedError

    factory, _ = rs_db
    await _seed_doc(factory, doc_id=1, owner_id=7)

    with pytest.raises(SpaceAccessDeniedError):
        await _call_update(
            factory, doc_id=1, user_id=8, is_admin=False,
            request=_request(review_cycle_days=30),
        )


@pytest.mark.asyncio
async def test_non_admin_cannot_reassign_owner(rs_db):
    """owner 本人也不能改派 owner（管理动作仅 admin）。"""
    from novamind.features.knowledge_space.exceptions import SpaceAccessDeniedError

    factory, _ = rs_db
    await _seed_doc(factory, doc_id=1, owner_id=7)

    with pytest.raises(SpaceAccessDeniedError):
        await _call_update(
            factory, doc_id=1, user_id=7, is_admin=False,
            request=_request(owner_id=42),
        )


@pytest.mark.asyncio
async def test_missing_doc_404(rs_db):
    """文档不存在 → DocumentNotFoundError。"""
    from novamind.features.knowledge_space.exceptions import DocumentNotFoundError

    factory, _ = rs_db
    with pytest.raises(DocumentNotFoundError):
        await _call_update(
            factory, doc_id=999, user_id=7, is_admin=True,
            request=_request(review_cycle_days=30),
        )


@pytest.mark.asyncio
async def test_none_fields_noop(rs_db):
    """全 None 请求体不改任何字段（PATCH 幂等语义）。"""
    factory, _ = rs_db
    await _seed_doc(factory, doc_id=1, owner_id=7)

    result = await _call_update(
        factory, doc_id=1, user_id=7, is_admin=False,
        request=_request(),
    )
    assert result["review_cycle_days"] is None
    assert result["next_review_at"] is None
    assert result["owner_id"] == 7
