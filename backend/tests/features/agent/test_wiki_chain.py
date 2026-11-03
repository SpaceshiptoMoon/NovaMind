"""Wiki 写读改依赖链测试：wiki_write_page → wiki_search → wiki_read_page → wiki_replace_text。

验证 DEPENDS ON 声明的两段 id 流动：slug 从 search 输出流入 read/replace 参数，
old_text 从 read 输出的正文流入 replace（描述要求「exact current text from a
fresh wiki_read_page」）。真 SQLite 定向建表，与 test_wiki_tools 同套 fixture。
"""
import json

import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.engines.agent.tool.context import ToolContext
from novamind.features.agent.tool.builtins.wiki_tools import WikiTool
from novamind.features.knowledge_space.models.wiki import (
    WikiPage,
    WikiPageIssue,
    WikiPageRevision,
)
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

pytestmark = pytest.mark.unit

EDITOR_USER = 8


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def db():
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
    from novamind.features.knowledge_space.models.space_member import SpaceMember

    tables = [
        WikiPage.__table__, WikiPageRevision.__table__, WikiPageIssue.__table__,
        KnowledgeBase.__table__, KnowledgeSpace.__table__, SpaceMember.__table__,
    ]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        session.add(KnowledgeSpace(id=1, name="s", owner_id=EDITOR_USER, visibility=0, status=1))
        session.add(KnowledgeBase(id=1, space_id=1, name="kb", creator_id=EDITOR_USER, status=1, config={}))
        from datetime import datetime

        session.add(SpaceMember(
            space_id=1, user_id=EDITOR_USER, role=1, joined_at=datetime.now(),
        ))
        await session.commit()
        yield session
    await engine.dispose()


def _ctx(db) -> ToolContext:
    return ToolContext(db_session=db, user_id=EDITOR_USER, agent_id=1)


@pytest.mark.asyncio
async def test_wiki_write_read_replace_chain(db):
    """写→搜（slug）→读（old_text）→替换→复读验证，链上无手填 id。"""
    tool = WikiTool()
    ctx = _ctx(db)

    # 第 1 跳：创建 synthesis 页
    written = json.loads(await tool.execute_tool(
        "wiki_write_page",
        {
            "kb_id": 1, "slug": "synthesis/rag", "title": "检索增强综述",
            "content": "RAG三阶段流程：索引、检索、生成。", "page_type": "synthesis",
        },
        ctx,
    ))
    assert "error" not in written
    assert written["slug"] == "synthesis/rag"
    assert written["version"] == 1

    # 第 2 跳：search 找到页面，slug 从输出流入下一步（不手填）
    found = json.loads(await tool.execute_tool(
        "wiki_search", {"kb_id": 1, "query": "检索增强"}, ctx,
    ))
    assert found["total"] == 1
    slug = found["items"][0]["slug"]
    assert slug == "synthesis/rag"

    # 第 3 跳：slug 流入 read_page，取正文精确子串作 old_text
    pages = json.loads(await tool.execute_tool(
        "wiki_read_page", {"kb_id": 1, "slugs": [slug]}, ctx,
    ))
    page = pages["pages"][0]
    assert page["slug"] == slug
    content = page["content"]
    old_text = "RAG三阶段流程"
    assert old_text in content

    # 第 4 跳：slug + old_text 流入 replace_text
    replaced = json.loads(await tool.execute_tool(
        "wiki_replace_text",
        {"kb_id": 1, "slug": slug, "old_text": old_text, "new_text": "RAG五阶段流程"},
        ctx,
    ))
    assert "error" not in replaced
    assert replaced["replacements"] >= 1
    assert replaced["version"] == 2

    # 第 5 跳：复读验证替换生效、旧文本消失
    reread = json.loads(await tool.execute_tool(
        "wiki_read_page", {"kb_id": 1, "slugs": [slug]}, ctx,
    ))
    final = reread["pages"][0]["content"]
    assert "RAG五阶段流程" in final
    assert old_text not in final
