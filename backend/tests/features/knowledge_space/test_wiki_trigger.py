"""wiki 触发接线测试。

验证文档任务成功分支：wiki.enabled 才入队、未启用不入队、入队异常被吞
（不影响文档任务终态）、触发函数读 KB 配置的分支逻辑。
"""
import novamind.features.knowledge_space.tasks.document_tasks as doc_tasks
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_enqueues_when_enabled(monkeypatch):
    """wiki.enabled=true → 调用 enqueue_wiki_ingest"""
    enqueued = []

    class _FakeKB:
        id = 2
        status = 1
        config = {"wiki": {"enabled": True}}

        def get_config(self):
            return self.config

    class _FakeRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, kb_id):
            return _FakeKB()

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        "novamind.core.database.database.get_db_session",
        lambda: _FakeSession(),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.repository.knowledge_base_repository.KnowledgeBaseRepository",
        _FakeRepo,
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.tasks.wiki_tasks.enqueue_wiki_ingest",
        lambda **kw: _async_return("job-123"),
    )
    # 捕获入队参数
    captured = {}

    async def fake_enqueue(**kw):
        captured.update(kw)
        return "job-123"

    monkeypatch.setattr(
        "novamind.features.knowledge_space.tasks.wiki_tasks.enqueue_wiki_ingest",
        fake_enqueue,
    )

    await doc_tasks._trigger_wiki_ingest_if_enabled(kb_id=2, space_id=3, document_id=42)
    assert captured == {"kb_id": 2, "space_id": 3, "document_id": 42}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_skips_when_disabled(monkeypatch):
    """wiki.enabled=false → 不入队"""
    called = []

    class _FakeKB:
        id = 2
        status = 1
        config = {"wiki": {"enabled": False}}

        def get_config(self):
            return self.config

    class _FakeRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, kb_id):
            return _FakeKB()

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        "novamind.core.database.database.get_db_session",
        lambda: _FakeSession(),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.repository.knowledge_base_repository.KnowledgeBaseRepository",
        _FakeRepo,
    )

    async def fake_enqueue(**kw):
        called.append(kw)
        return "job-123"

    monkeypatch.setattr(
        "novamind.features.knowledge_space.tasks.wiki_tasks.enqueue_wiki_ingest",
        fake_enqueue,
    )

    await doc_tasks._trigger_wiki_ingest_if_enabled(kb_id=2, space_id=3, document_id=42)
    assert called == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_skips_when_kb_missing(monkeypatch):
    """KB 不存在 → 不入队不抛"""
    class _FakeRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, kb_id):
            return None

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        "novamind.core.database.database.get_db_session",
        lambda: _FakeSession(),
    )
    monkeypatch.setattr(
        "novamind.features.knowledge_space.repository.knowledge_base_repository.KnowledgeBaseRepository",
        _FakeRepo,
    )

    # 不应抛异常
    await doc_tasks._trigger_wiki_ingest_if_enabled(kb_id=2, space_id=3, document_id=42)


def _async_return(value):
    import asyncio

    future = asyncio.get_event_loop().create_future()
    future.set_result(value)
    return future
