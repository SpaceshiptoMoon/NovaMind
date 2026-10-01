"""单元测试：知识运营批次 O1 补充覆盖。

与 test_knowledge_ops_event_ledger.py 互补，覆盖前者留白的路径：
- QueryReformulateDetector._get_previous_user_query 真实 DB 查询
  （user_id 过滤 / role 过滤 / id 排除 / 取最新——此前测试全部 Mock 掉该查询）
- 埋点接线门控（ai_chat_service 仅 do_rag 时调用检测——提取的接线点级测试）
- 端到端真实链路（真 DB 查询 + 真实 EventRecorder 落 kb_events）
- 边界：纯标点查询、created_at 为 None

DB 交互经 SQLite 内存库定向建表（kb_events + question_answers，StaticPool
使 :memory: 跨会话可见；BigInteger PK 经 @compiles 降级 INTEGER 解决自增）。
"""
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

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


# SQLite 中 BIGINT PRIMARY KEY 不别名 rowid，BigInteger 自增主键在内存库不生成
# id（NOT NULL constraint failed）。编译期降为 INTEGER 仅影响 SQLite 建表，不改模型。
# 同款先例：tests/features/knowledge_space/test_document_enqueue_batch_atomic.py
@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def ops_full_db():
    """SQLite 内存库：kb_events + question_answers 定向建表，StaticPool 共享连接。

    返回 (factory, engine)；各测试自管会话生命周期。
    """
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.qa.models.question_answer import QuestionAnswer

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
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


async def _insert_user_message(
    factory, *, id_: int, session_id: str, user_id: int, content: str,
    role: str = "user", created_at=None,
):
    """插入一条 question_answers 测试消息（直接 ORM，created_at 可控）。"""
    from novamind.features.qa.models.question_answer import QuestionAnswer

    async with factory() as session:
        msg = QuestionAnswer(
            id=id_,
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
        )
        if created_at is not None:
            msg.created_at = created_at
        session.add(msg)
        await session.commit()
    return msg


# ========== _get_previous_user_query：真实 DB 查询路径 ==========


@pytest.mark.asyncio
async def test_get_previous_returns_latest_user_message(ops_full_db):
    """取会话内该用户最新一条 user 消息：多条时取 id 最大者。"""
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )

    factory, _ = ops_full_db
    await _insert_user_message(factory, id_=1, session_id="s1", user_id=1, content="第一条")
    await _insert_user_message(factory, id_=2, session_id="s1", user_id=1, content="第二条")
    await _insert_user_message(factory, id_=3, session_id="s1", user_id=1, content="第三条")

    detector = QueryReformulateDetector()
    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        prev = await detector._get_previous_user_query("s1", 1, exclude_message_id=4)
    assert prev is not None
    assert prev.id == 3
    assert prev.content == "第三条"


@pytest.mark.asyncio
async def test_get_previous_filters_by_user(ops_full_db):
    """user_id 过滤：会话内其他用户的提问不作为改写比对目标。"""
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )

    factory, _ = ops_full_db
    # 用户 2 的消息 id 更大（更新），但检测的是用户 1
    await _insert_user_message(factory, id_=1, session_id="s1", user_id=1, content="退货政策是什么")
    await _insert_user_message(factory, id_=2, session_id="s1", user_id=2, content="别人问的完全不同")

    detector = QueryReformulateDetector()
    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        prev = await detector._get_previous_user_query("s1", 1, exclude_message_id=3)
    assert prev is not None
    assert prev.user_id == 1
    assert prev.id == 1


@pytest.mark.asyncio
async def test_get_previous_filters_role_and_excludes_current(ops_full_db):
    """role=user 过滤 + 排除当前消息：assistant 消息与当前消息本身都不作数。"""
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )

    factory, _ = ops_full_db
    await _insert_user_message(factory, id_=1, session_id="s1", user_id=1, content="真正上一条")
    # 当前消息（id=2）与一条 assistant 消息（id=3，id 更大更新）都不应被选中
    await _insert_user_message(factory, id_=2, session_id="s1", user_id=1, content="当前消息", role="user")
    await _insert_user_message(factory, id_=3, session_id="s1", user_id=1, content="AI 回答", role="assistant")

    detector = QueryReformulateDetector()
    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        prev = await detector._get_previous_user_query("s1", 1, exclude_message_id=2)
    assert prev is not None
    assert prev.id == 1
    assert prev.role == "user"


@pytest.mark.asyncio
async def test_get_previous_isolates_sessions(ops_full_db):
    """会话隔离：s2 的消息不能成为 s1 检测的比对目标。"""
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )

    factory, _ = ops_full_db
    await _insert_user_message(factory, id_=1, session_id="s2", user_id=1, content="别的会话的问题")
    await _insert_user_message(factory, id_=2, session_id="s1", user_id=1, content="本会话的问题")

    detector = QueryReformulateDetector()
    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        prev = await detector._get_previous_user_query("s1", 1, exclude_message_id=3)
    assert prev is not None
    assert prev.session_id == "s1"


@pytest.mark.asyncio
async def test_get_previous_empty_session_returns_none(ops_full_db):
    """空会话（无其他 user 消息）返回 None，检测静默退出。"""
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )

    factory, _ = ops_full_db
    detector = QueryReformulateDetector()
    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        prev = await detector._get_previous_user_query("s-empty", 1, exclude_message_id=1)
    assert prev is None


# ========== 端到端真实链路：真 DB 查询 + 真实 EventRecorder 落账本 ==========


@pytest.mark.asyncio
async def test_end_to_end_reformulate_recorded(ops_full_db):
    """端到端：真查上一条消息 → 判定改写 → EventRecorder 独立会话落 kb_events。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )
    from novamind.shared.utils.time_utils import now_china

    factory, _ = ops_full_db
    # 上一条 user 消息：时间窗内
    await _insert_user_message(
        factory, id_=1, session_id="s1", user_id=1,
        content="退货政策是什么", created_at=now_china(),
    )

    detector = QueryReformulateDetector()
    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        await detector.check_after_new_query(
            session_id="s1",
            user_id=1,
            space_id=10,
            current_message_id=2,  # 当前消息尚未入库（或 id=2 排除自身）
            current_query="退货政策是什么呀",  # 实测相似度 0.833 ≥ 0.5
        )

    async with factory() as session:
        events = (await session.execute(select(KbEvent))).scalars().all()
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "query_reformulate"
    assert ev.user_id == 1
    assert ev.space_id == 10
    assert ev.extra["previous_message_id"] == 1
    assert ev.extra["similarity"] >= 0.5
    assert ev.query_text == "退货政策是什么呀"


@pytest.mark.asyncio
async def test_end_to_end_no_event_when_gap_too_big(ops_full_db):
    """端到端反例：上一条消息超时间窗 → 不落事件（回到旧会话重问不是改写）。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )
    from novamind.shared.utils.time_utils import now_china

    factory, _ = ops_full_db
    await _insert_user_message(
        factory, id_=1, session_id="s1", user_id=1,
        content="退货政策是什么",
        created_at=now_china() - timedelta(seconds=3600),  # 远超 120s 窗口
    )

    detector = QueryReformulateDetector()
    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        await detector.check_after_new_query(
            session_id="s1", user_id=1, space_id=10,
            current_message_id=2, current_query="退货政策是什么呀",
        )

    async with factory() as session:
        events = (await session.execute(select(KbEvent))).scalars().all()
    assert events == []


# ========== 边界：归一化为空 / created_at 为 None ==========


@pytest.mark.asyncio
async def test_punctuation_only_query_skips_detection(ops_full_db):
    """纯标点查询归一化后为空 → 直接退出，不查库不落事件。"""
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )

    factory, _ = ops_full_db
    detector = QueryReformulateDetector()

    called = False

    async def _spy_prev(session_id, user_id, exclude_message_id):
        nonlocal called
        called = True
        return None

    detector._get_previous_user_query = _spy_prev
    await detector.check_after_new_query(
        session_id="s1", user_id=1, space_id=10,
        current_message_id=2, current_query="？？？！！！",
    )
    assert called is False  # 归一化短路：根本不该走到查库


@pytest.mark.asyncio
async def test_none_created_at_skips_gracefully(ops_full_db):
    """created_at 为 None 的历史脏数据 → 判空退出（修复前此处 TypeError 靠 except 吞）。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        QueryReformulateDetector,
    )

    factory, _ = ops_full_db
    detector = QueryReformulateDetector()

    prev = type("P", (), {"id": 1, "content": "退货政策是什么", "created_at": None})()

    async def _fake_prev(session_id, user_id, exclude_message_id):
        return prev

    detector._get_previous_user_query = _fake_prev
    # 不抛即通过（修复前 now_china() - None 抛 TypeError 被旁路 except 吞掉，
    # 行为上碰巧不落事件；修复后显式判空，语义清晰）
    await detector.check_after_new_query(
        session_id="s1", user_id=1, space_id=10,
        current_message_id=2, current_query="退货政策是什么呀",
    )

    async with factory() as session:
        events = (await session.execute(select(KbEvent))).scalars().all()
    assert events == []


# ========== 埋点接线门控：仅 do_rag 时调用检测 ==========


@pytest.mark.asyncio
async def test_wiring_invokes_detector_only_when_rag_on():
    """_maybe_detect_query_reformulate 接线门控（真实方法，桩检测器）：

    - do_rag=True → 调检测器且参数逐项正确
    - do_rag=False → 不调
    - 检测器抛错 → 接线层兜底吞掉，不传播
    """
    from novamind.features.qa.services.ai_chat_service import AIChatService

    svc = AIChatService.__new__(AIChatService)
    from novamind.core.middleware.structured_logging import get_logger

    svc.logger = get_logger("test.ai_chat_gate")

    calls = []

    class _SpyDetector:
        async def check_after_new_query(self, **kwargs):
            calls.append(kwargs)

    import novamind.features.knowledge_ops.services.query_reformulate_detector as det_mod

    with patch.object(det_mod, "QueryReformulateDetector", _SpyDetector):
        # 开：RAG 会话触发检测，参数透传完整
        await svc._maybe_detect_query_reformulate(
            do_rag=True, session_id="s1", user_id=1,
            space_id=10, user_message_id=2, content="退货政策是什么呀",
        )
        assert len(calls) == 1
        assert calls[0] == {
            "session_id": "s1",
            "user_id": 1,
            "space_id": 10,
            "current_message_id": 2,
            "current_query": "退货政策是什么呀",
        }

        # 关：非 RAG 会话完全不调
        await svc._maybe_detect_query_reformulate(
            do_rag=False, session_id="s1", user_id=1,
            space_id=10, user_message_id=2, content="任意",
        )
        assert len(calls) == 1  # 计数不变


@pytest.mark.asyncio
async def test_wiring_swallows_detector_error():
    """接线层兜底：检测器构造/调用抛错不向 _prepare_chat 传播。"""
    from novamind.features.qa.services.ai_chat_service import AIChatService

    svc = AIChatService.__new__(AIChatService)
    from novamind.core.middleware.structured_logging import get_logger

    svc.logger = get_logger("test.ai_chat_gate")

    class _BoomDetector:
        def __init__(self):
            raise RuntimeError("detector init failed")

    import novamind.features.knowledge_ops.services.query_reformulate_detector as det_mod

    with patch.object(det_mod, "QueryReformulateDetector", _BoomDetector):
        # 不抛即通过
        await svc._maybe_detect_query_reformulate(
            do_rag=True, session_id="s1", user_id=1,
            space_id=10, user_message_id=2, content="任意",
        )


# ========== 辅助 ==========


def now_china_helper():
    from novamind.shared.utils.time_utils import now_china

    return now_china()
