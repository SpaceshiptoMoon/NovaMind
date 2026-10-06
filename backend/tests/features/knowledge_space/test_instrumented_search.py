"""InstrumentedSearchService 埋点测试：query 事件进账本、失败旁路不拖垮检索。

埋点语义：用户触发的检索每次产生一条 query 事件（含 results_count/max_score
载荷）；EventRecorder 挂掉时检索结果原样返回（旁路语义，项目失败方向安全
硬规则）。系统重放（归因 worker/evaluation）不走本类，直接用父类。
"""
from unittest.mock import AsyncMock, patch

import pytest
from novamind.features.knowledge_space.schemas.search_schema import SearchMode, SearchRequest
from novamind.features.knowledge_space.services.instrumented_search_service import (
    InstrumentedSearchService,
)
from novamind.features.knowledge_space.services.search_service import SearchService

pytestmark = pytest.mark.unit


def _make_service() -> InstrumentedSearchService:
    """最小构造：只测 search 包装逻辑，检索引擎不触真（super().search 被 patch）。"""
    svc = InstrumentedSearchService.__new__(InstrumentedSearchService)
    import logging

    svc.logger = logging.getLogger("test")
    return svc


def _make_request(query: str = "测试查询") -> SearchRequest:
    return SearchRequest(query=query, search_mode=SearchMode.CONTENT_HYBRID, top_k=5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_records_query_event_with_payload():
    """检索成功 → 记录 query 事件，载荷含结果数与最高分"""
    svc = _make_service()
    fake_result = {"results": [{"score": 0.92}, {"score": 0.71}], "total": 2}
    recorded = {}

    class _FakeRecorder:
        async def record(self, **kw):
            recorded.update(kw)

    with (
        patch.object(
            SearchService, "search", AsyncMock(return_value=fake_result)
        ) as mock_search,
        patch(
            "novamind.features.knowledge_ops.services.event_recorder.EventRecorder",
            _FakeRecorder,
        ),
    ):
        result = await svc.search(
            space_id=6, kb_id=11, user_id=1, request=_make_request()
        )

    assert result == fake_result  # 检索结果原样透传
    mock_search.assert_awaited_once()
    assert recorded["event_type"] == "query"
    assert recorded["space_id"] == 6
    assert recorded["kb_id"] == 11
    assert recorded["user_id"] == 1
    assert recorded["query_text"] == "测试查询"
    assert recorded["extra"]["results_count"] == 2
    assert recorded["extra"]["max_score"] == 0.92
    assert recorded["extra"]["bypass_document_permission"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_zero_results_still_records():
    """零命中也记录：results_count=0 + max_score=0 是归因的核心信号"""
    svc = _make_service()
    recorded = {}

    class _FakeRecorder:
        async def record(self, **kw):
            recorded.update(kw)

    with (
        patch.object(
            SearchService, "search", AsyncMock(return_value={"results": []})
        ),
        patch(
            "novamind.features.knowledge_ops.services.event_recorder.EventRecorder",
            _FakeRecorder,
        ),
    ):
        await svc.search(space_id=6, kb_id=11, user_id=1, request=_make_request())

    assert recorded["extra"]["results_count"] == 0
    assert recorded["extra"]["max_score"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recorder_failure_does_not_break_search():
    """账本挂掉 → 检索结果照常返回（旁路语义，失败方向安全）"""
    svc = _make_service()
    fake_result = {"results": [{"score": 0.5}]}

    class _BrokenRecorder:
        async def record(self, **kw):
            raise RuntimeError("账本 DB 挂了")

    with (
        patch.object(
            SearchService, "search", AsyncMock(return_value=fake_result)
        ),
        patch(
            "novamind.features.knowledge_ops.services.event_recorder.EventRecorder",
            _BrokenRecorder,
        ),
    ):
        result = await svc.search(
            space_id=6, kb_id=11, user_id=1, request=_make_request()
        )

    assert result == fake_result
