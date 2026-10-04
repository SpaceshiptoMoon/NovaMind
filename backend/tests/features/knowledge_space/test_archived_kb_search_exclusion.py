"""归档知识库退出检索召回的回归测试。

覆盖两道闸门：
1. 服务层拦截：SearchService.search 对归档 KB（status=2）抛
   KnowledgeBaseArchivedError——这是所有检索消费方（路由/QA RAG/归因
   worker/MCP）的公共必经点，显式指定归档 kb_id 的检索在此拒绝。
2. 默认库列表过滤：QA RAG 与归因 worker 的「kb_ids 缺省回退空间前 3 个」
   只取 ACTIVE 库——归档库不占回退名额（相邻正常场景不误伤：活跃库照常回填）。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytest.importorskip("aiosqlite")

from novamind.core.database.base import Base
from novamind.features.knowledge_space.exceptions import KnowledgeBaseArchivedError
from novamind.features.knowledge_space.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.schemas.search_schema import SearchRequest
from novamind.features.knowledge_space.services.search_service import SearchService

pytestmark = pytest.mark.unit


def _kb(kb_id: int, name: str, status: KnowledgeBaseStatus) -> KnowledgeBase:
    return KnowledgeBase(
        id=kb_id, space_id=1, name=name, creator_id=1,
        config={"embedding": {}}, status=status,
    )


async def _make_session(seed: list[KnowledgeBase]):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # 只建本测试涉及的表（全量 create_all 有既存元数据问题，见 tests README）
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[KnowledgeBase.__table__]
            )
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(seed)
        await session.commit()
        yield session
    await engine.dispose()


def _make_search_service(session) -> SearchService:
    """构造不触达 ES/引擎的 SearchService：拦截发生在引擎调用之前。"""
    svc = SearchService.__new__(SearchService)
    svc.session = session
    svc.kb_repo = KnowledgeBaseRepository(session)
    svc.member_repo = SimpleNamespace(is_member=AsyncMock(return_value=True))
    svc.space_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    svc.es_client = SimpleNamespace()
    svc.model_config_service = None
    svc.logger = SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    # 引擎若被调用即失败：归档拦截必须发生在委托引擎之前
    svc._retrieval_engine = SimpleNamespace(
        retrieve_raw=AsyncMock(side_effect=AssertionError("归档库不应进入引擎"))
    )
    return svc


def _request() -> SearchRequest:
    return SearchRequest(query="测试查询", search_mode="content_bm25", top_k=5)


@pytest.mark.parametrize("kb_status", [
    pytest.param(KnowledgeBaseStatus.ARCHIVED, id="archived"),
    pytest.param(KnowledgeBaseStatus.ACTIVE, id="active-对照"),
])
def test_search_service_blocks_archived_kb(kb_status):
    """归档 KB 检索抛 KnowledgeBaseArchivedError；活跃 KB 正常放行（对照）。"""
    if kb_status == KnowledgeBaseStatus.ACTIVE:
        # 活跃对照路径：放行到引擎层，用最小引擎桩返回空结果
        async def run_active():
            async for session in _make_session([_kb(1, "kb1", kb_status)]):
                svc = _make_search_service(session)
                svc._retrieval_engine = SimpleNamespace(
                    retrieve_raw=AsyncMock(return_value=SimpleNamespace(
                        results=[], cached=False,
                    ))
                )
                return await svc.search(
                    space_id=1, kb_id=1, user_id=1, request=_request()
                )
        result = asyncio.run(run_active())
        assert result["results"] == []
    else:
        async def run_archived():
            async for session in _make_session([_kb(1, "kb1", kb_status)]):
                svc = _make_search_service(session)
                return await svc.search(
                    space_id=1, kb_id=1, user_id=1, request=_request()
                )
        with pytest.raises(KnowledgeBaseArchivedError) as exc_info:
            asyncio.run(run_archived())
        assert exc_info.value.kb_id == 1


@pytest.mark.parametrize("with_archived", [False, True], ids=["纯活跃", "活跃+归档"])
def test_default_kb_fallback_excludes_archived(with_archived):
    """QA RAG / 归因 worker 的默认回退（get_by_space + status=ACTIVE）不含归档库。"""
    seed = [
        _kb(1, "active-1", KnowledgeBaseStatus.ACTIVE),
        _kb(2, "archived-1", KnowledgeBaseStatus.ARCHIVED),
    ]
    if with_archived:
        seed.append(_kb(3, "active-2", KnowledgeBaseStatus.ACTIVE))

    async def run():
        async for session in _make_session(seed):
            repo = KnowledgeBaseRepository(session)
            kbs = await repo.get_by_space(1, status=KnowledgeBaseStatus.ACTIVE)
            return [kb.id for kb in kbs]

    ids = asyncio.run(run())
    assert 2 not in ids, "归档库不得进入默认回退列表"
    assert 1 in ids
    if with_archived:
        assert 3 in ids, "归档库占位不得挤掉后面的活跃库"
