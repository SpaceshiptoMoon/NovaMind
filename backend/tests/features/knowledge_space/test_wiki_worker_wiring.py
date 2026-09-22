"""Wiki retract worker 接线测试：注册名一致性 + 接线不回退 + ES 清理分支

背景：retract 任务（删除文档的异步兜底）曾完整实现但未注册进嵌入式
arq worker——job 入队后 worker 找不到函数，其中唯一的 ES 页向量清理
从不执行。这组测试钉死接线，防回退。
"""
import inspect

import pytest

from novamind.core.middleware import startup_manager
from novamind.features.knowledge_space.tasks.wiki_tasks import (
    enqueue_wiki_retract,
    process_wiki_retract_task,
)

pytestmark = pytest.mark.unit


@pytest.mark.unit
def test_retract_task_function_name_matches_enqueue_string():
    """worker 注册名（函数 __qualname__）必须与 enqueue_job 字符串逐字一致"""
    from arq.worker import func

    assert func(process_wiki_retract_task).name == "process_wiki_retract_task"
    # 入队侧字符串同步核对（grep 不到调用关系，只能靠字面量对齐）
    src = inspect.getsource(enqueue_wiki_retract)
    assert '"process_wiki_retract_task"' in src


@pytest.mark.unit
def test_worker_functions_include_wiki_retract():
    """嵌入式 worker functions 列表必须包含 retract 任务（接线门禁）"""
    src = inspect.getsource(startup_manager)
    assert "process_wiki_retract_task" in src


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retract_task_cleans_es_for_deleted_pages(monkeypatch):
    """retract 任务只对「被整页软删」的页面清 ES 向量；剥引用的页面不动"""
    calls: list[str] = []

    class FakeES:
        async def delete_chunk(self, space_id, chunk_id):
            calls.append(chunk_id)
            return True

    class FakePage:
        def __init__(self, page_id: str):
            self.id = page_id

    class FakePageRepo:
        async def get_by_slug(self, kb_id, slug, include_deleted=False):
            assert include_deleted is True  # 软删页需 include_deleted 才查得到
            mapping = {"entity/solo": FakePage("page-1")}
            return mapping.get(slug)

    class FakeRetractSvc:
        def __init__(self, session, *, kb_id, space_id):
            self.page_repo = FakePageRepo()

        async def reconcile_document_removal(self, document_id):
            return {"deleted": ["entity/solo"], "stripped": ["entity/multi"]}

    class FakeSessionFactory:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        async def commit(self):
            return None

    import novamind.features.knowledge_space.tasks.wiki_tasks as wiki_tasks

    # wiki_tasks 内是函数内懒 import，patch 真实来源模块
    import novamind.core.database.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_session", FakeSessionFactory)
    import novamind.features.knowledge_space.services.wiki_retract_service as retract_mod

    monkeypatch.setattr(retract_mod, "WikiRetractService", FakeRetractSvc)

    import novamind.shared.storage.client_factory as cf_mod

    class FakeClientFactory:
        @staticmethod
        async def get_elasticsearch_client():
            return FakeES()

    monkeypatch.setattr(cf_mod, "ClientFactory", FakeClientFactory)

    result = await wiki_tasks.process_wiki_retract_task(
        {}, kb_id=1, space_id=1, document_id=100
    )

    assert result == {"deleted": ["entity/solo"], "stripped": ["entity/multi"]}
    # wp- 前缀 = wiki_es_sync.WIKI_CHUNK_ID_PREFIX；只清 deleted 页
    assert calls == ["wp-page-1"]
