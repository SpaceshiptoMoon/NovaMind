"""skill_repository.list_marketplace 搜索路径回归测试。

P2 修复背景：原实现用 try/except 包 FULLTEXT 表达式构建，但兼容性错误在
execute 阶段才抛，ILIKE 降级是永不触发的 dead code。现按连接方言判定：
MySQL 走 FULLTEXT（ngram），其余（SQLite 测试环境）走 ILIKE。
"""
import pytest
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from novamind.core.database.base import BaseModel
from novamind.features.skill.models.skill import (
    SkillDefinition, SkillSource, SkillStatus, SkillVisibility, ReviewStatus,
)
from novamind.features.skill.repository.skill_repository import SkillRepository

# 模型的 BigInteger 自增主键在 SQLite 内存库不会自动生成 id（NOT NULL constraint failed）。
# 编译期把 BigInteger 降为 INTEGER，仅影响本测试的 SQLite 建表，不改模型。
@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


def _published_skill(**overrides) -> dict:
    base = dict(
        user_id=1,
        name="code-reviewer",
        display_name="代码审查",
        description="审查 Python 代码质量",
        body_markdown="## 指令\n审查代码",
        skill_source=SkillSource.CUSTOM,
        visibility=SkillVisibility.PUBLIC,
        status=SkillStatus.PUBLISHED,
        review_status=ReviewStatus.APPROVED,
    )
    base.update(overrides)
    return base


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_search_ilike_path_executes_on_sqlite():
    """非 MySQL 方言走 ILIKE 降级且真实可执行（原 dead code 路径）"""
    engine = create_async_engine("sqlite+aiosqlite://")
    # 定向建表，避免 create_all 全量建表的 SQLite 陷阱
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn, tables=[SkillDefinition.__table__]: tables[0].create(sync_conn, checkfirst=True)
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(SkillDefinition(**_published_skill()))
        session.add(SkillDefinition(**_published_skill(
            name="pdf-export", display_name="PDF 导出", description="导出 PDF 文档",
        )))
        await session.commit()

        repo = SkillRepository(session)
        assert session.bind.dialect.name == "sqlite"

        # 关键词命中 name/display_name
        skills, total = await repo.list_marketplace(keyword="code")
        assert total == 1
        assert skills[0].name == "code-reviewer"

        # 关键词命中 description
        skills, total = await repo.list_marketplace(keyword="PDF")
        assert total == 1
        assert skills[0].name == "pdf-export"

        # 无命中
        skills, total = await repo.list_marketplace(keyword="不存在的词")
        assert total == 0

    await engine.dispose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_marketplace_search_respects_marketplace_filter():
    """ILIKE 路径同样只返回已发布+已过审+公开的技能"""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn, tables=[SkillDefinition.__table__]: tables[0].create(sync_conn, checkfirst=True)
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(SkillDefinition(**_published_skill()))
        # 未过审：不应出现在结果里
        session.add(SkillDefinition(**_published_skill(
            name="draft-one", display_name="草稿", review_status=ReviewStatus.PENDING,
        )))
        # 私有：不应出现在结果里
        session.add(SkillDefinition(**_published_skill(
            name="private-one", display_name="私有", visibility=SkillVisibility.PRIVATE,
        )))
        await session.commit()

        repo = SkillRepository(session)
        skills, total = await repo.list_marketplace()
        assert total == 1
        assert skills[0].name == "code-reviewer"

    await engine.dispose()
