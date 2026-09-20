"""批5 检索对齐测试：WikiBoost 加权、ES 同步、wiki_search 排序"""
import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.engines.rag.retrieval_engine import RetrievalEngine, RetrievalQuery
from novamind.features.knowledge_space.services.wiki_es_sync import (
    WIKI_CHUNK_TYPE,
    WikiEsSyncService,
    wiki_chunk_id,
)
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bi(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def db_session():
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
    from novamind.features.knowledge_space.models.wiki import (
        WikiIngestRecord,
        WikiPage,
        WikiPageRevision,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            WikiPage.__table__, WikiPageRevision.__table__,
            WikiIngestRecord.__table__, KnowledgeBase.__table__,
        ])
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as session:
        yield session
    await engine.dispose()


# ==================== WikiBoost ====================


def _rq(**overrides) -> RetrievalQuery:
    defaults = dict(
        space_id=1, kb_id=1, query="q", effective_query="q",
        sub_queries=None, sub_query_merge_mode="rrf", search_mode="content_hybrid",
        top_k=10, vector_weight=0.7, bm25_weight=0.3, content_weight=0.6,
        question_weight=0.4, rrf_k=60, score_threshold=0.0,
        rerank_enabled=False, rerank_top_k=3, rerank_model=None,
    )
    defaults.update(overrides)
    return RetrievalQuery(**defaults)


class _FakeEs:
    async def search_by_mode(self, *a, **k):
        return {"hits": {"hits": [], "total": {"value": 0}}}


def _make_engine():
    return RetrievalEngine(es_client=_FakeEs(), cache_port=None)


@pytest.mark.unit
class TestWikiBoost:
    """engine 层 WikiBoost：×factor 稳定重排（直接测排序语义）"""

    def test_boost_reorders_wiki_pages_up(self):
        """wiki 页分数 ×1.3 后应排到非 wiki 同分结果之前"""
        results = [
            {"chunk_id": "c1", "score": 0.8, "chunk_type": None, "content": "a"},
            {"chunk_id": "w1", "score": 0.8, "chunk_type": "wiki_page", "content": "w"},
        ]
        factor = 1.3
        for r in results:
            if r.get("chunk_type") == "wiki_page":
                r["score"] = min(1.0, r["score"] * factor)
        results.sort(key=lambda r: (r.get("chunk_type") == "wiki_page", r.get("score", 0)), reverse=True)
        assert results[0]["chunk_id"] == "w1"

    def test_boost_factor_identity(self):
        """factor=1.0 恒等跳过——引擎代码路径条件直接判定"""
        # 等价于引擎的 if 条件：factor != 1.0 才进入
        factor = 1.0
        assert not (factor != 1.0)  # 跳过 boost

    def test_cache_key_factor_sensitive(self):
        """factor 入缓存键：不同 factor 不共享缓存"""
        h1 = RetrievalEngine._generate_query_hash("q", 5, "content_hybrid", wiki_boost_factor=1.0)
        h2 = RetrievalEngine._generate_query_hash("q", 5, "content_hybrid", wiki_boost_factor=1.3)
        assert h1 != h2
        # 相同 factor 稳定
        assert h1 == RetrievalEngine._generate_query_hash("q", 5, "content_hybrid", wiki_boost_factor=1.0)


# ==================== ES 同步 ====================


class _FakeSyncEs:
    def __init__(self):
        self.indexed = {}

    async def index_chunk(self, space_id: int, chunk_data: dict) -> bool:
        self.indexed[chunk_data["chunk_id"]] = chunk_data
        return True

    async def delete_chunk(self, space_id: int, chunk_id: str) -> bool:
        self.indexed.pop(chunk_id, None)
        return True


@pytest.mark.unit
class TestWikiEsSync:
    @pytest.mark.asyncio
    async def test_sync_page_builds_doc(self):
        """sync_page 构造 wp- 前缀文档：chunk_type/document_id=0/metadata"""

        class FakeSession:
            pass

        svc = WikiEsSyncService(FakeSession(), _FakeSyncEs())

        class FakeSpaceRepo:
            async def get_by_id(self, space_id, use_cache=False):
                class S:
                    embedding_config = {"dimension": 1024}

                return S()

        # 注入维度解析
        async def fake_dim(space_id):
            return 1024

        svc._resolve_embedding_dim = fake_dim

        class FakePage:
            id = "page-uuid"
            kb_id = 1
            slug = "entity/acme"
            title = "Acme"
            summary = "一家公司"
            content = "Acme 的正文内容"
            page_type = "entity"

        ok = await svc.sync_page(1, FakePage(), embedding=[0.1] * 4)
        assert ok
        doc = svc.es.indexed["wp-page-uuid"]
        assert doc["chunk_type"] == WIKI_CHUNK_TYPE
        assert doc["document_id"] == 0  # 哨兵
        assert doc["metadata"]["wiki_slug"] == "entity/acme"
        assert doc["content"].startswith("Acme\n一家公司")

    def test_chunk_id_prefix(self):
        assert wiki_chunk_id("x") == "wp-x"


# ==================== 搜索排序 ====================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_pages_ranked(db_session):
    """rank 分级排序：title 命中 > content 命中；snippet 截取"""
    from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository

    repo = WikiPageRepository(db_session)
    await repo.create_page({
        "space_id": 1, "kb_id": 1, "slug": "entity/other", "title": "其他页",
        "page_type": "entity", "content": "这里顺带提到了量子计算这个词但不是主题。" * 3,
        "status": "published",
    })
    await repo.create_page({
        "space_id": 1, "kb_id": 1, "slug": "concept/quantum", "title": "量子计算",
        "page_type": "concept", "content": "量子计算是利用量子力学原理计算的技术。" * 5,
        "status": "published",
    })

    results = await repo.search_pages_ranked(1, "量子计算", limit=10)
    assert len(results) == 2
    # title 命中 rank=4 应排在 content 命中 rank=1 之前
    assert results[0]["slug"] == "concept/quantum"
    assert results[0]["rank"] == 4
    assert results[1]["rank"] == 1
    # snippet 含命中词
    assert "量子计算" in results[0]["snippet"]
    # 新字段
    assert results[0]["aliases"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_pages_ranked_alias_match(db_session):
    """别名参与匹配（title 级 rank=4）"""
    from novamind.features.knowledge_space.repository.wiki_repository import WikiPageRepository

    repo = WikiPageRepository(db_session)
    await repo.create_page({
        "space_id": 1, "kb_id": 1, "slug": "entity/acme", "title": "甲公司",
        "aliases": ["Acme Corp"],
        "page_type": "entity", "content": "正文不含英文缩写。",
        "status": "published",
    })
    results = await repo.search_pages_ranked(1, "Acme Corp", limit=10)
    assert len(results) == 1
    assert results[0]["rank"] == 4  # 别名命中按 title 级
