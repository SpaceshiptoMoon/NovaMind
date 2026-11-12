"""批量触发解析「空 ids = 全部未处理文档」语义回归测试。

回归背景：空 ids 分支原本 ``get_by_kb(kb_id)`` 不滤 status 且受默认 limit=100
截断——最新任务 COMPLETED 的文档会被卷入并静默触发 REPROCESS（最多 100 个），
FAILED/CANCELLED 也被重入队。修复后空 ids 只取未处理文档（status=PENDING，
覆盖「从无任务」），并分页取全量。

验证核心不变量：
1. 空 ids：get_by_kb 必须带 status=PENDING 过滤（防 REPROCESS 误触发）；
2. 分页循环：页满继续、页短终止，全部未处理文档被收集（防静默截断）；
3. 显式 ids：不触碰 get_by_kb（全量语义只在未指定 ids 时生效，不误伤显式路径）。
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from novamind.features.knowledge_space.services.document_task_service import (
    DocumentTaskService,
)

pytestmark = pytest.mark.unit


def _doc(doc_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=doc_id, kb_id=1, space_id=1)


def _make_service(get_by_kb_pages: list[list]) -> tuple[DocumentTaskService, AsyncMock]:
    """__new__ 绕过 init；repo 全桩，task_repo 类在调用处模块级替换。"""
    service = DocumentTaskService.__new__(DocumentTaskService)
    service.session = object()
    service.logger = SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None
    )
    get_by_kb = AsyncMock(side_effect=get_by_kb_pages)
    service.doc_repo = SimpleNamespace(
        get_by_kb=get_by_kb,
        get_by_ids=AsyncMock(return_value=[]),
        lock_active_documents_by_ids=AsyncMock(return_value=[]),
    )
    service.kb_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                id=1, is_active=lambda: True, get_config=lambda: {}
            )
        )
    )
    return service, get_by_kb


def _patch_task_repo(monkeypatch) -> None:
    """替换模块内 DocumentTaskRepository：查询桩返回空映射（无活跃/历史任务）。"""
    import novamind.features.knowledge_space.services.document_task_service as svc_module

    class _FakeTaskRepo:
        def __init__(self, session):
            self.session = session

        async def lock_active_by_document_ids(self, ids):
            return {}

        async def get_latest_by_document_ids(self, ids):
            return {}

    monkeypatch.setattr(svc_module, "DocumentTaskRepository", _FakeTaskRepo)


@pytest.mark.asyncio
async def test_empty_ids_filters_pending_and_paginates(monkeypatch):
    """空 ids：带 status=PENDING 过滤 + 分页取全量（页满继续、页短终止）。"""
    _patch_task_repo(monkeypatch)
    page1 = [_doc(i) for i in range(1, 201)]
    page2 = [_doc(i) for i in range(201, 251)]
    service, get_by_kb = _make_service([page1, page2])

    result = await DocumentTaskService.process_kb_documents(service, kb_id=1, user_id=7)

    assert get_by_kb.await_count == 2
    first_kwargs = get_by_kb.await_args_list[0].kwargs
    second_kwargs = get_by_kb.await_args_list[1].kwargs
    assert first_kwargs["status"] == 0 and second_kwargs["status"] == 0
    assert (first_kwargs["skip"], first_kwargs["limit"]) == (0, 200)
    assert (second_kwargs["skip"], second_kwargs["limit"]) == (200, 200)
    # 全部 250 个收集后才进入后续流程（此处锁桩返回空 → 全部 failed，不触碰入队）
    assert result["total"] == 250
    assert result["success"] == 0


@pytest.mark.asyncio
async def test_empty_ids_no_pending_returns_empty_summary(monkeypatch):
    """空 ids 且无未处理文档：短路返回空汇总，不触碰知识库后续流程。"""
    service, get_by_kb = _make_service([[]])

    result = await DocumentTaskService.process_kb_documents(service, kb_id=1, user_id=7)

    assert get_by_kb.await_count == 1
    assert result == {
        "task_id": None, "total": 0, "success": 0, "failed": 0, "skipped": 0,
        "results": [],
    }


@pytest.mark.asyncio
async def test_explicit_ids_do_not_touch_full_scan(monkeypatch):
    """显式 ids：走 get_by_ids，不触发全量分页扫描（空 ids 语义不外溢）。"""
    _patch_task_repo(monkeypatch)
    service, get_by_kb = _make_service([])
    service.doc_repo.get_by_ids = AsyncMock(return_value=[_doc(11)])

    result = await DocumentTaskService.process_kb_documents(
        service, kb_id=1, user_id=7, document_ids=[11]
    )

    assert get_by_kb.await_count == 0
    service.doc_repo.get_by_ids.assert_awaited_once_with([11])
    assert result["total"] == 1
