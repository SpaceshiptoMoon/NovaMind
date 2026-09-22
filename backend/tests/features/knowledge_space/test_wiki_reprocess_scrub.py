"""reparse 清洗 pending wiki ingest 测试：scrub/purge/worker 兜底/管道中止

对齐 WeKnora scrubWikiPendingIngest 语义：文档重新解析时取消其
pending/running 的 wiki 生成（履历置 CANCELLED + arq 层 job 键手术），
防旧分块触发的生成烧 LLM。
"""
import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.wiki import (
    WikiIngestRecord,
    WikiIngestStatus,
    WikiPage,
    WikiPageRevision,
)
from novamind.features.knowledge_space.repository.wiki_repository import (
    WikiIngestRecordRepository,
)
from novamind.features.knowledge_space.tasks.wiki_tasks import scrub_pending_wiki_ingest
from novamind.features.knowledge_space.services.wiki_query_service import status_name
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bi(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def db():
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


async def _make_record(session, document_id: int, status: WikiIngestStatus, job_id=None):
    repo = WikiIngestRecordRepository(session)
    record = await repo.create({
        "space_id": 1, "kb_id": 1, "document_id": document_id, "job_id": job_id,
    })
    if status == WikiIngestStatus.RUNNING:
        record.mark_running()
    elif status == WikiIngestStatus.DONE:
        record.mark_done(1, 0)
    elif status == WikiIngestStatus.FAILED:
        record.mark_failed("x")
    await session.flush()
    return record


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scrub_marks_pending_and_running_cancelled(db):
    """scrub 只取消 PENDING/RUNNING；DONE/FAILED 终态不动"""
    await _make_record(db, 100, WikiIngestStatus.PENDING, job_id="job-a")
    await _make_record(db, 100, WikiIngestStatus.RUNNING, job_id="job-b")
    await _make_record(db, 100, WikiIngestStatus.DONE)
    await _make_record(db, 100, WikiIngestStatus.FAILED)
    await _make_record(db, 200, WikiIngestStatus.PENDING, job_id="job-other-doc")

    cancelled = await scrub_pending_wiki_ingest(db, 100, "文档重新解析，取消本轮 wiki 生成")
    await db.commit()

    assert cancelled == 2
    repo = WikiIngestRecordRepository(db)
    records = await repo.list_by_document(100)
    by_status = {r.status for r in records}
    assert by_status == {
        WikiIngestStatus.CANCELLED, WikiIngestStatus.DONE, WikiIngestStatus.FAILED,
    }
    for r in records:
        if r.status == WikiIngestStatus.CANCELLED:
            assert "重新解析" in r.error_message
            assert r.completed_at is not None
    # 其它文档不受影响
    other = await repo.list_by_document(200)
    assert other[0].status == WikiIngestStatus.PENDING


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scrub_idempotent(db):
    """scrub 幂等：已 CANCELLED 的行二次 scrub 不再计数"""
    await _make_record(db, 100, WikiIngestStatus.RUNNING, job_id="job-a")
    assert await scrub_pending_wiki_ingest(db, 100, "r1") == 1
    await db.commit()
    assert await scrub_pending_wiki_ingest(db, 100, "r2") == 0


@pytest.mark.unit
def test_status_name_maps_cancelled():
    assert status_name(WikiIngestStatus.CANCELLED) == "cancelled"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_worker_skips_job_cancelled_by_reprocess(monkeypatch, db):
    """purge 没赶上、job 已被 worker pop：CANCELLED 且 job_id 匹配 → 放弃"""
    from novamind.features.knowledge_space.tasks import wiki_tasks

    record = await _make_record(db, 100, WikiIngestStatus.PENDING, job_id="job-live")
    record.mark_cancelled("文档重新解析，取消本轮 wiki 生成")
    await db.commit()

    class FakeRecordRepo:
        def __init__(self, session):
            pass

        async def list_by_document(self, document_id, limit=10):
            return [record]

        async def list_by_kb(self, kb_id, limit=20):
            return [record]

        async def create(self, data):
            raise AssertionError("被清洗的 job 不得创建新履历行")

    class FakeKB:
        id = 1
        creator_id = 1
        status = "active"

        def get_config(self):
            return {"wiki": {"enabled": True}}

    class FakeKBRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, kb_id):
            return FakeKB()

    class FakeSessionFactory:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False

    import novamind.core.database.database as db_mod
    import novamind.features.knowledge_space.repository.knowledge_base_repository as kb_repo_mod
    import novamind.features.knowledge_space.repository.wiki_repository as wiki_repo_mod

    monkeypatch.setattr(db_mod, "get_db_session", FakeSessionFactory)
    monkeypatch.setattr(kb_repo_mod, "KnowledgeBaseRepository", FakeKBRepo)
    monkeypatch.setattr(wiki_repo_mod, "WikiIngestRecordRepository", FakeRecordRepo)

    result = await wiki_tasks.process_wiki_ingest_task(
        {"job_id": "job-live"}, kb_id=1, space_id=1, document_id=100,
    )
    assert result == {"skipped": "cancelled_by_reprocess"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_worker_creates_new_record_when_no_cancelled_match(monkeypatch, db):
    """正常路径回归：无 CANCELLED 匹配 → 建新 PENDING 行继续跑"""
    from novamind.features.knowledge_space.tasks import wiki_tasks

    created_rows: list[dict] = []

    class FakeRecord:
        id = 999
        status = WikiIngestStatus.PENDING
        job_id = None

        def mark_running(self):
            self.status = WikiIngestStatus.RUNNING

        def mark_failed(self, error_message):
            self.status = WikiIngestStatus.FAILED
            self.error_message = error_message

    class FakeRecordRepo:
        def __init__(self, session):
            pass

        async def list_by_document(self, document_id, limit=10):
            return []

        async def list_by_kb(self, kb_id, limit=20):
            return []

        async def create(self, data):
            created_rows.append(data)
            return FakeRecord()

    class FakeKB:
        id = 1
        creator_id = 1
        status = "active"

        def get_config(self):
            return {"wiki": {"enabled": True}}

    class FakeKBRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, kb_id):
            return FakeKB()

    class FakeSessionFactory:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False

    import novamind.core.database.database as db_mod
    import novamind.features.knowledge_space.repository.knowledge_base_repository as kb_repo_mod
    import novamind.features.knowledge_space.repository.wiki_repository as wiki_repo_mod

    monkeypatch.setattr(db_mod, "get_db_session", FakeSessionFactory)
    monkeypatch.setattr(kb_repo_mod, "KnowledgeBaseRepository", FakeKBRepo)
    monkeypatch.setattr(wiki_repo_mod, "WikiIngestRecordRepository", FakeRecordRepo)

    # KB 校验通过后走文档读取；文档不存在 → skipped（足以证明走到了建新行之后）
    class FakeDocRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, document_id):
            return None

    import novamind.features.knowledge_space.repository.document_repository as doc_repo_mod

    monkeypatch.setattr(doc_repo_mod, "DocumentRepository", FakeDocRepo)

    result = await wiki_tasks.process_wiki_ingest_task(
        {"job_id": "fresh-job"}, kb_id=1, space_id=1, document_id=100,
    )
    # 后续 Redis/ES 依赖未装配会以 error 收场，但关键断言是：
    # 没被 cancelled 语义拦截，且建了新 PENDING 行（走了正常路径）
    assert result.get("skipped") != "cancelled_by_reprocess"
    assert len(created_rows) == 1  # 建了新 PENDING 行
