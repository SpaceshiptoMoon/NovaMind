"""单元测试：知识运营事件账本（O1）。

覆盖：
- EventRecorder.record 写入成功 / 异常吞掉 / 脱敏与截断
- char_trigram_similarity / normalize_query 正反用例

历史：QueryReformulateDetector 改写判定测试随 QA 对话链清退一并删除
（检测类已删，工具函数保留）。

DB 交互经 SQLite 内存库定向建表（kb_events），复用 conftest 的 tmp_db 思路。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import BigInteger
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
async def ops_db():
    """SQLite 内存库，定向建 kb_events 表，每测试独立。

    StaticPool 必须加：``:memory:`` 每个连接是独立库，EventRecorder 内部
    自开新会话，不加则 INSERT 落在无表的另一连接上（异常被旁路吞掉，
    表现为"永远记不进"）。
    """
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_event import KbEvent

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[KbEvent.__table__])
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


# ========== EventRecorder ==========


@pytest.mark.asyncio
async def test_record_inserts_event(ops_db):
    """正常路径：record 落一行，字段正确、文本已脱敏。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.services.event_recorder import EventRecorder

    _, factory = ops_db
    recorder = EventRecorder()

    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        await recorder.record(
            event_type="query_reformulate",
            user_id=1,
            session_id="sess-1",
            space_id=10,
            kb_id=20,
            query_text="我的手机号 13812345678",
            extra={"similarity": 0.8},
        )

    async with factory() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(KbEvent))).scalars().all()
        assert len(rows) == 1
        ev = rows[0]
        assert ev.event_type == "query_reformulate"
        assert ev.user_id == 1
        assert ev.space_id == 10
        assert ev.kb_id == 20
        # PII 已脱敏（redact 将手机号替换为 [REDACTED_PHONE]）
        assert "13812345678" not in ev.query_text
        assert "[REDACTED_PHONE]" in ev.query_text


@pytest.mark.asyncio
async def test_record_swallows_exception(ops_db):
    """旁路语义：session factory 抛错时 record 静默返回，不向调用方传播。"""
    from novamind.features.knowledge_ops.services.event_recorder import EventRecorder

    recorder = EventRecorder()

    def _boom():
        raise RuntimeError("db unavailable")

    with patch(
        "novamind.core.database.database.get_session_factory", side_effect=_boom
    ):
        # 不抛即通过
        await recorder.record(
            event_type="query_reformulate", user_id=1, query_text="hello"
        )


@pytest.mark.asyncio
async def test_record_truncates_long_query(ops_db):
    """超长查询截断到 512 字符，不落库失败。"""
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_ops.services.event_recorder import EventRecorder

    _, factory = ops_db
    recorder = EventRecorder()

    with patch(
        "novamind.core.database.database.get_session_factory", return_value=factory
    ):
        await recorder.record(
            event_type="query_reformulate",
            user_id=1,
            query_text="长" * 2000,
        )

    async with factory() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(KbEvent))).scalars().all()
        assert len(rows) == 1
        assert len(rows[0].query_text) == 512


# ========== 相似度 ==========


def test_similarity_identical_and_unrelated():
    """正例：同义改写高相似；反例：无关问题低相似。"""
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        char_trigram_similarity,
        normalize_query,
    )

    a = normalize_query("退货政策是什么？")
    b = normalize_query("退货政策是啥")
    assert char_trigram_similarity(a, b) >= 0.5

    c = normalize_query("今天天气怎么样")
    assert char_trigram_similarity(a, c) < 0.5


def test_similarity_short_strings():
    """短串退化路径：相同返回 1，不同返回 0。"""
    from novamind.features.knowledge_ops.services.query_reformulate_detector import (
        char_trigram_similarity,
    )

    assert char_trigram_similarity("ab", "ab") == 1.0
    assert char_trigram_similarity("ab", "cd") == 0.0
    assert char_trigram_similarity("", "abc") == 0.0


# ========== 改写检测 ==========


class _FakePrevious:
    """上一条 user 消息桩（QuestionAnswer 的最小形态）。"""

    def __init__(self, id_, content, created_at):
        self.id = id_
        self.content = content
        self.created_at = created_at
