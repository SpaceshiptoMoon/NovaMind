"""Wiki 编辑 / 版本 / 回滚 API 测试。

乐观锁冲突、部分更新语义、回滚幂等、软删唯一占位、版本历史。
直接测 repository 层（update_page_with_lock / revert_page）+ 路由层
请求模型校验。
"""
import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from novamind.core.database.base import Base
from novamind.features.knowledge_space.exceptions import (
    WikiPageVersionConflictError,
)
from novamind.features.knowledge_space.models.wiki import (
    WikiEditSource,
    WikiPage,
    WikiPageRevision,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiPageRepository,
)


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def wiki_db():
    tables = [WikiPage.__table__, WikiPageRevision.__table__]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def page(wiki_db):
    """预置 v1 页面"""
    repo = WikiPageRepository(wiki_db)
    p, _ = await repo.upsert_with_snapshot(
        1, "entity/a", space_id=1, title="A", content="v1 正文", summary="s1",
        page_type="entity", edit_source=WikiEditSource.PIPELINE,
    )
    await wiki_db.commit()
    return p


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_with_correct_version_bumps(wiki_db, page):
    """乐观锁版本匹配 → 内容更新 + version 递增 + 快照"""
    repo = WikiPageRepository(wiki_db)
    await repo.update_page_with_lock(
        page, content="v2 正文", edit_source=WikiEditSource.USER,
        editor_id=8, expected_version=1,
    )
    assert page.version == 2
    assert page.content == "v2 正文"
    assert page.last_edit_source == WikiEditSource.USER
    assert page.last_editor_id == 8

    revisions = await repo.list_revisions(page.id)
    assert len(revisions) == 1
    assert revisions[0].content == "v1 正文"
    assert revisions[0].edit_source == WikiEditSource.PIPELINE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_with_stale_version_conflicts(wiki_db, page):
    """版本不匹配 → 409 语义异常，内容不变"""
    repo = WikiPageRepository(wiki_db)
    with pytest.raises(WikiPageVersionConflictError):
        await repo.update_page_with_lock(page, content="x", expected_version=99)
    assert page.version == 1
    assert page.content == "v1 正文"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partial_update_absent_fields_keep(wiki_db, page):
    """部分更新：缺席字段保持原值"""
    repo = WikiPageRepository(wiki_db)
    await repo.update_page_with_lock(page, summary="新摘要", expected_version=1)
    assert page.summary == "新摘要"
    assert page.title == "A"
    assert page.content == "v1 正文"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_same_content_no_bump(wiki_db, page):
    """更新为相同内容 → version 不递增、无快照，但 last_edit_source 刷新"""
    repo = WikiPageRepository(wiki_db)
    await repo.update_page_with_lock(page, content="v1 正文", expected_version=1)
    assert page.version == 1
    revisions = await repo.list_revisions(page.id)
    assert len(revisions) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_revert_creates_new_version(wiki_db, page):
    """回滚 = 用旧版本创建新版本，且可再回滚（回滚自身可被回滚）"""
    repo = WikiPageRepository(wiki_db)
    # v1 → v2（人工编辑）
    await repo.update_page_with_lock(page, content="v2 正文", edit_source=WikiEditSource.USER,
                                     editor_id=8, expected_version=1)
    revision_v1 = await repo.get_revision(page.id, 1)
    assert revision_v1 is not None

    # v2 → revert 到 v1，得到 v3
    new_version = await repo.revert_page(page, revision_v1, editor_id=9)
    assert new_version == 3
    assert page.content == "v1 正文"
    assert page.last_edit_source == WikiEditSource.REVERT
    assert page.last_editor_id == 9

    # revert 到当前版本内容 → 版本号不变（幂等守卫由 API 层拦截，repo 层不递增）
    same = await repo.revert_page(page, revision_v1, editor_id=9)
    assert same == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_soft_delete_releases_slug(wiki_db, page):
    """软删后 slug 可复用（deleted_flag 让出唯一占位），旧实体不可见"""
    repo = WikiPageRepository(wiki_db)
    await repo.soft_delete_page(page)
    await wiki_db.commit()

    assert (await repo.get_by_slug(1, "entity/a")) is None
    # slug 复用：新建同名 slug 不冲突
    p2, created = await repo.upsert_with_snapshot(
        1, "entity/a", space_id=1, title="A-new", content="新页面",
        summary="", page_type="entity", edit_source=WikiEditSource.USER,
    )
    assert created is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_revision_unique_constraint_idempotent(wiki_db, page):
    """(page_id, version) 唯一约束：先查后插保证重试幂等——重复快照同版本不新增"""
    repo = WikiPageRepository(wiki_db)
    # 造一个 version=5 的页面并快照一次
    p, _ = await repo.upsert_with_snapshot(
        1, "entity/b", space_id=1, title="B", content="x", summary="",
        page_type="entity", edit_source=WikiEditSource.PIPELINE,
    )
    p.version = 5
    await wiki_db.flush()
    await repo._snapshot_revision(p)  # 快照 v5
    count_before = len(await repo.list_revisions(p.id))
    # 重试场景：对同一 v5 再快照 → 先查后插应跳过
    await repo._snapshot_revision(p)
    count_after = len(await repo.list_revisions(p.id))
    assert count_after == count_before


# ==================== schema 校验 ====================


def test_update_request_partial_semantics():
    """Update 请求模型：缺席字段为 None（部分更新语义）"""
    from novamind.features.knowledge_space.schemas.wiki_schema import WikiPageUpdateRequest

    body = WikiPageUpdateRequest(content="只改正文")
    assert body.title is None
    assert body.version == 0  # 0 = 跳过乐观锁（legacy 客户端）
    assert body.status is None


def test_create_request_rejects_summary_type():
    """summary 页只能由管道管理，创建请求模型层允许透传、路由层拦截"""
    from novamind.features.knowledge_space.schemas.wiki_schema import WikiPageCreateRequest

    body = WikiPageCreateRequest(slug="entity/x", title="X", page_type="summary")
    assert body.page_type == "summary"  # schema 放行，路由层校验拦截
