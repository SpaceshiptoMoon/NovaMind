"""单元测试：kb-ops O2——citation_click 服务逻辑 + 事件查询 repository。

覆盖：
- record_citation_click：归属校验（404/仅 assistant/权限）、EventRecorder 旁路调用参数
- KbEventRepository.list_events/count_events：权限域过滤、event_type/时间窗过滤、分页

citation_click 路由是 qa_service 方法的一行薄封装（204），服务层已覆盖其语义；
权限域谓词的双保险由 list_events 空集语义覆盖。
"""
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.unit


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def ops_db():
    """SQLite 内存库（StaticPool 跨会话可见）：kb_events + question_answers。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.qa.models.question_answer import QuestionAnswer

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[KbEvent.__table__, QuestionAnswer.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


# ========== record_citation_click（qa_service） ==========


def _make_service(factory):
    """构造只装 repository.session 的 QAService（跳过完整 init）。"""
    from novamind.features.qa.services.qa_service import QAService

    svc = QAService.__new__(QAService)
    from novamind.core.middleware.structured_logging import get_logger

    svc.logger = get_logger("test.citation_click")
    svc.repository = type("R", (), {"session": None})()
    return svc, svc.repository


def _patch_repo_get(svc, message):
    """桩 repository.get_by_id 返回预设消息。"""

    async def _get(message_id):
        return message if message and message.id == message_id else None

    svc.repository.get_by_id = _get


def _msg(id_=1, user_id=1, role="assistant", session_id="s1", space_id=10, kb_id=20):
    from novamind.shared.utils.time_utils import now_china

    return type(
        "M",
        (),
        {
            "id": id_,
            "user_id": user_id,
            "role": role,
            "session_id": session_id,
            "space_id": space_id,
            "kb_id": kb_id,
            "created_at": now_china(),
        },
    )()


@pytest.mark.asyncio
async def test_citation_click_records_event():
    """正例：assistant 消息归属人点击 → EventRecorder 收到正确参数。"""
    from novamind.features.qa.schemas.qa import CitationClickRequest
    from novamind.features.qa.services.qa_service import QAService

    svc, _repo = _make_service(None)
    _patch_repo_get(svc, _msg(id_=7, user_id=1))

    recorded = []

    class _FakeRecorder:
        async def record(self, **kwargs):
            recorded.append(kwargs)

    with patch(
        "novamind.features.knowledge_ops.services.event_recorder.EventRecorder",
        _FakeRecorder,
    ):
        await svc.record_citation_click(
            message_id=7,
            request=CitationClickRequest(
                source_index=2, chunk_id="ck-1", document_id=5, kb_id=20
            ),
            user_id=1,
        )

    assert len(recorded) == 1
    kwargs = recorded[0]
    assert kwargs["event_type"] == "citation_click"
    assert kwargs["session_id"] == "s1"
    assert kwargs["space_id"] == 10
    assert kwargs["kb_id"] == 20
    assert kwargs["extra"]["message_id"] == 7
    assert kwargs["extra"]["source_index"] == 2
    assert kwargs["extra"]["document_id"] == 5


@pytest.mark.asyncio
async def test_citation_click_message_not_found_or_not_owner():
    """归属校验：消息不存在 / 非归属人 → MessageNotFoundError。"""
    import pytest as _pytest

    from novamind.features.qa.exceptions import MessageNotFoundError
    from novamind.features.qa.schemas.qa import CitationClickRequest
    from novamind.features.qa.services.qa_service import QAService

    svc, _repo = _make_service(None)
    _patch_repo_get(svc, _msg(id_=7, user_id=2))  # 消息属于用户 2

    with _pytest.raises(MessageNotFoundError):
        await svc.record_citation_click(
            message_id=7, request=CitationClickRequest(), user_id=1
        )

    with _pytest.raises(MessageNotFoundError):
        await svc.record_citation_click(
            message_id=999, request=CitationClickRequest(), user_id=1
        )


@pytest.mark.asyncio
async def test_citation_click_rejects_user_message():
    """仅 assistant 消息可上报：user 消息 → UnauthorizedAccessException。"""
    import pytest as _pytest

    from novamind.features.qa.exceptions import UnauthorizedAccessException
    from novamind.features.qa.schemas.qa import CitationClickRequest
    from novamind.features.qa.services.qa_service import QAService

    svc, _repo = _make_service(None)
    _patch_repo_get(svc, _msg(id_=7, user_id=1, role="user"))

    with _pytest.raises(UnauthorizedAccessException):
        await svc.record_citation_click(
            message_id=7, request=CitationClickRequest(), user_id=1
        )


# ========== KbEventRepository 查询 ==========


async def _seed_events(factory, events: list[dict]):
    """按字典列表种入 kb_events。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent

    async with factory() as session:
        for spec in events:
            session.add(KbEvent(**spec))
        await session.commit()


@pytest.mark.asyncio
async def test_list_events_filters_by_space_and_type(ops_db):
    """权限域过滤：只返回指定空间；event_type 精确过滤。"""
    from novamind.features.knowledge_ops.repository.kb_event_repository import (
        KbEventRepository,
    )

    factory, _ = ops_db
    await _seed_events(
        factory,
        [
            {"event_type": "citation_click", "user_id": 1, "space_id": 10},
            {"event_type": "query_reformulate", "user_id": 1, "space_id": 10},
            {"event_type": "citation_click", "user_id": 1, "space_id": 99},  # 别的空间
        ],
    )

    async with factory() as session:
        repo = KbEventRepository(session)
        all_space10 = await repo.list_events(space_ids=[10])
        assert len(all_space10) == 2
        assert all(e.space_id == 10 for e in all_space10)

        only_clicks = await repo.list_events(space_ids=[10], event_type="citation_click")
        assert len(only_clicks) == 1
        assert only_clicks[0].event_type == "citation_click"

        # 空权限域恒空（跨空间不可见）
        assert await repo.list_events(space_ids=[]) == []


@pytest.mark.asyncio
async def test_list_events_time_window_and_pagination(ops_db):
    """时间窗过滤 + 分页 + 倒序。"""
    from novamind.features.knowledge_ops.repository.kb_event_repository import (
        KbEventRepository,
    )
    from novamind.shared.utils.time_utils import now_china

    factory, _ = ops_db
    now = now_china()
    await _seed_events(
        factory,
        [
            {"event_type": "citation_click", "user_id": 1, "space_id": 10},
            {"event_type": "citation_click", "user_id": 1, "space_id": 10},
            {
                "event_type": "citation_click",
                "user_id": 1,
                "space_id": 10,
                "created_at": now - timedelta(days=5),  # 窗外
            },
        ],
    )

    async with factory() as session:
        repo = KbEventRepository(session)
        recent = await repo.list_events(
            space_ids=[10], start=now - timedelta(days=1), end=now + timedelta(hours=1)
        )
        assert len(recent) == 2
        # created_at 倒序（新在前）：按 id 倒序验证
        assert [e.id for e in recent] == sorted([e.id for e in recent], reverse=True)

        paged = await repo.list_events(space_ids=[10], limit=1, offset=0)
        assert len(paged) == 1

        total = await repo.count_events(space_ids=[10])
        assert total == 3
        total_recent = await repo.count_events(
            space_ids=[10], start=now - timedelta(days=1)
        )
        assert total_recent == 2


@pytest.mark.asyncio
async def test_citation_click_end_to_end_persists(ops_db):
    """端到端：service 校验 → 真实 EventRecorder → kb_events 落行。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.qa.schemas.qa import CitationClickRequest
    from novamind.features.qa.services.qa_service import QAService

    factory, _ = ops_db

    svc, _repo = _make_service(None)
    _patch_repo_get(svc, _msg(id_=7, user_id=1, session_id="s-e2e", space_id=10))

    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        await svc.record_citation_click(
            message_id=7,
            request=CitationClickRequest(
                source_index=1, chunk_id="ck-e2e", document_id=5, kb_id=20
            ),
            user_id=1,
        )

    async with factory() as session:
        rows = (await session.execute(select(KbEvent))).scalars().all()
    assert len(rows) == 1
    ev = rows[0]
    assert ev.event_type == "citation_click"
    assert ev.session_id == "s-e2e"
    assert ev.space_id == 10
    assert ev.kb_id == 20
    assert ev.extra["chunk_id"] == "ck-e2e"
