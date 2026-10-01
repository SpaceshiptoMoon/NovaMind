"""单元测试：kb-ops A1 归因流水线。

覆盖（计划验收标准：四类正反用例 + 幂等 + 失败安全）：
- 候选筛选谓词：失败问答进、正常回答不进（反例）
- attribute_single_event 四分判定：
  · content_gap（重放零命中，降阈值仍零命中）
  · retrieval_failure（原始零命中、降阈值命中 / 命中但失效占比低）
  · quality_decay（命中且失效文档占比过半）
  · ValueError 路径（消息不存在/非 assistant/无 space/无相邻查询）
- 幂等：已有 attribution 不覆盖、不重放检索
- 写回：attribution + meta 落 extra，SAVEPOINT 保护
- permission_boundary stub 显式断言（A1 阶段不可达，防误用）

重放检索 _replay_search 全部打桩（不依赖 ES），判定逻辑全真跑。
"""
import sys
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
async def attr_db():
    """SQLite 内存库：question_answers + session_configs + qa_message_feedback。"""
    from novamind.core.database.base import Base
    from novamind.features.qa.models.qa_feedback import MessageFeedback
    from novamind.features.qa.models.question_answer import QuestionAnswer
    from novamind.features.qa.models.session_config import SessionConfig

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    QuestionAnswer.__table__,
                    SessionConfig.__table__,
                    MessageFeedback.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


async def _insert_pair(
    factory,
    *,
    answer_id: int,
    session_id: str = "s1",
    space_id: int | None = 10,
    user_id: int = 1,
    extra: dict | None = None,
    role: str = "assistant",
):
    """插入 (user 提问, assistant 回答) 相邻对，user 消息 id = answer_id - 1。"""
    from novamind.features.qa.models.question_answer import QuestionAnswer

    async with factory() as session:
        session.add(QuestionAnswer(
            id=answer_id - 1, session_id=session_id, user_id=user_id,
            role="user", content="知识库检索支持哪些检索模式？",
        ))
        session.add(QuestionAnswer(
            id=answer_id, session_id=session_id, user_id=user_id,
            role=role, content="回答内容", space_id=space_id, extra=extra,
        ))
        await session.commit()


def _replay_patch(orig: list[dict], low: list[dict]):
    """打桩 _replay_search：首次调用返回 orig，后续（降阈值）返回 low。"""
    calls = []

    async def _fake_replay(db, **kwargs):
        calls.append(kwargs)
        return orig if len(calls) == 1 else low

    return _fake_replay, calls


# ========== 四分判定 ==========


@pytest.mark.asyncio
async def test_content_gap_when_replay_always_empty(attr_db):
    """content_gap：重放原始阈值零命中，降阈值仍零命中 → 库内真无内容。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        ATTR_CONTENT_GAP,
        attribute_single_event,
    )

    factory, _ = attr_db
    await _insert_pair(factory, answer_id=2)

    replay, calls = _replay_patch(orig=[], low=[])
    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", replay
    ):
        async with factory() as db:
            attr = await attribute_single_event(db, 2)
    assert attr == ATTR_CONTENT_GAP
    assert len(calls) == 2  # 降阈值重放确实执行了


@pytest.mark.asyncio
async def test_retrieval_failure_when_low_threshold_hits(attr_db):
    """retrieval_failure：原始阈值零命中、降阈值命中 → 内容存在但分数不达阈值。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        ATTR_RETRIEVAL_FAILURE,
        attribute_single_event,
    )

    factory, _ = attr_db
    await _insert_pair(factory, answer_id=2)

    replay, _ = _replay_patch(orig=[], low=[{"score": 0.2, "document_id": 1}])
    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", replay
    ):
        async with factory() as db:
            attr = await attribute_single_event(db, 2)
    assert attr == ATTR_RETRIEVAL_FAILURE


@pytest.mark.asyncio
async def test_retrieval_failure_when_hits_but_healthy(attr_db):
    """retrieval_failure：重放命中且文档健康（低分候选的保守兜底，不臆断生成问题）。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        ATTR_RETRIEVAL_FAILURE,
        attribute_single_event,
    )

    factory, _ = attr_db
    await _insert_pair(factory, answer_id=2)

    replay, _ = _replay_patch(
        orig=[{"score": 0.3, "document_id": 1, "lifecycle_status": "active"}], low=[]
    )
    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", replay
    ):
        async with factory() as db:
            attr = await attribute_single_event(db, 2)
    assert attr == ATTR_RETRIEVAL_FAILURE


@pytest.mark.asyncio
async def test_quality_decay_when_dead_docs_dominate(attr_db):
    """quality_decay：命中主体是失效文档（占比过半）。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        ATTR_QUALITY_DECAY,
        attribute_single_event,
    )

    factory, _ = attr_db
    await _insert_pair(factory, answer_id=2)

    replay, _ = _replay_patch(
        orig=[
            {"score": 0.4, "document_id": 1, "lifecycle_status": "superseded"},
            {"score": 0.3, "document_id": 2, "lifecycle_status": "archived"},
            {"score": 0.3, "document_id": 3, "lifecycle_status": "active"},
        ],
        low=[],
    )
    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", replay
    ):
        async with factory() as db:
            attr = await attribute_single_event(db, 2)
    assert attr == ATTR_QUALITY_DECAY


@pytest.mark.asyncio
async def test_permission_boundary_stub_not_reachable(attr_db):
    """stub 断言：命中且健康时归 retrieval_failure 而非 permission_boundary
    （B1 检索层权限接线前该分支不可达——防误用提前失败）。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        ATTR_PERMISSION_BOUNDARY,
        ATTR_RETRIEVAL_FAILURE,
        attribute_single_event,
    )

    factory, _ = attr_db
    await _insert_pair(factory, answer_id=2)

    replay, _ = _replay_patch(
        orig=[{"score": 0.5, "document_id": 1, "lifecycle_status": "active"}], low=[]
    )
    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", replay
    ):
        async with factory() as db:
            attr = await attribute_single_event(db, 2)
    assert attr == ATTR_RETRIEVAL_FAILURE
    assert attr != ATTR_PERMISSION_BOUNDARY


# ========== ValueError 路径 ==========


@pytest.mark.asyncio
async def test_space_fallback_from_session_config(attr_db):
    """space 兜底（O2 教训）：消息行 space_id 为 None 时从会话 RAG 绑定解析。

    真实接口验证抓到的场景：点踩消息 space 为空 → 候选可进（谓词已放宽）→
    归因用会话配置的 space_id 重放检索。
    """
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        ATTR_RETRIEVAL_FAILURE,
        attribute_single_event,
    )
    from novamind.features.qa.models.session_config import SessionConfig

    factory, _ = attr_db
    # 消息 space_id=None
    await _insert_pair(factory, answer_id=2, session_id="s-fallback", space_id=None)
    # 会话绑定了 space 10
    async with factory() as session:
        session.add(SessionConfig(session_id="s-fallback", user_id=1,
                                  kb_bindings={"space_id": 10, "kb_ids": [6], "auto_rag": True}))
        await session.commit()

    captured = {}

    async def _fake_replay(db, **kwargs):
        captured.update(kwargs)
        return [{"score": 0.5, "document_id": 1, "lifecycle_status": "active"}]

    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", _fake_replay
    ):
        async with factory() as db:
            attr = await attribute_single_event(db, 2)
    assert attr == ATTR_RETRIEVAL_FAILURE
    assert captured["space_id"] == 10  # 兜底解析生效
    assert captured["kb_ids"] == [6]


@pytest.mark.asyncio
async def test_valueerror_on_missing_or_invalid_message(attr_db):
    """消息不存在 / 非 assistant / 无 space_id / 无相邻查询 → ValueError。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        attribute_single_event,
    )

    factory, _ = attr_db
    await _insert_pair(factory, answer_id=2)
    # 无 space_id 的 assistant 消息
    await _insert_pair(factory, answer_id=4, session_id="s2", space_id=None)
    # 无相邻 user 查询（直接插 assistant，user id=4 不存在——answer=6 的前一条是 5）
    from novamind.features.qa.models.question_answer import QuestionAnswer

    async with factory() as session:
        session.add(QuestionAnswer(
            id=6, session_id="s3", user_id=1, role="assistant",
            content="孤立回答", space_id=10,
        ))
        await session.commit()

    async with factory() as db:
        with pytest.raises(ValueError):
            await attribute_single_event(db, 999)   # 不存在
        with pytest.raises(ValueError):
            await attribute_single_event(db, 1)     # 是 user 消息
        with pytest.raises(ValueError):
            await attribute_single_event(db, 4)     # 无 space_id
        with pytest.raises(ValueError):
            await attribute_single_event(db, 6)     # 无相邻 user 查询


# ========== 幂等与写回 ==========


@pytest.mark.asyncio
async def test_idempotent_existing_attribution_skips_replay(attr_db):
    """幂等：已有 attribution 直接返回且不跑重放检索。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        ATTR_CONTENT_GAP,
        attribute_single_event,
    )

    factory, _ = attr_db
    await _insert_pair(
        factory, answer_id=2,
        extra={"attribution": "content_gap", "other": 1},
    )

    calls = []

    async def _no_replay(db, **kwargs):
        calls.append(kwargs)
        return []

    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", _no_replay
    ):
        async with factory() as db:
            attr = await attribute_single_event(db, 2)
    assert attr == "content_gap"
    assert calls == []  # 未重放


@pytest.mark.asyncio
async def test_write_back_extra_fields(attr_db):
    """写回：extra.attribution + attribution_meta 落库且保留原有 extra 键。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        attribute_single_event,
    )
    from novamind.features.qa.models.question_answer import QuestionAnswer

    factory, _ = attr_db
    await _insert_pair(factory, answer_id=2, extra={"sources": []})

    replay, _ = _replay_patch(orig=[], low=[])
    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", replay
    ):
        async with factory() as db:
            await attribute_single_event(db, 2)
            await db.commit()

    async with factory() as session:
        row = (await session.execute(
            select(QuestionAnswer).where(QuestionAnswer.id == 2)
        )).scalar_one()
    assert row.extra["attribution"] == "content_gap"
    meta = row.extra["attribution_meta"]
    assert meta["replay_orig_count"] == 0
    assert meta["replay_low_count"] == 0
    assert "attributed_at" in meta
    assert row.extra["sources"] == []  # 原 extra 键保留


@pytest.mark.asyncio
async def test_replay_total_failure_raises_not_content_gap(attr_db):
    """失败方向安全：重放检索全部 KB 失败（基建故障）→ 抛错留空，绝不归因 content_gap。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        attribute_single_event,
    )
    from novamind.features.qa.models.question_answer import QuestionAnswer

    factory, _ = attr_db
    await _insert_pair(factory, answer_id=2)

    async def _all_fail(db, **kwargs):
        raise RuntimeError("ES down")

    with patch(
        "novamind.features.knowledge_ops.tasks.attribution_worker._replay_search", _all_fail
    ):
        async with factory() as db:
            with pytest.raises(RuntimeError):
                await attribute_single_event(db, 2)

    async with factory() as session:
        row = (await session.execute(
            select(QuestionAnswer).where(QuestionAnswer.id == 2)
        )).scalar_one()
    assert (row.extra or {}).get("attribution") is None  # 留空下轮重试


# ========== 候选筛选（反例：正常回答不进归因） ==========


@pytest.mark.asyncio
async def test_batch_skips_healthy_answers(attr_db):
    """候选谓词：零命中/低分/点踩进候选；正常成功回答（result_count>0 且高分无点踩）不进。"""
    from novamind.features.knowledge_ops.tasks.attribution_worker import (
        attribute_pending_events,
    )
    from novamind.features.qa.models.question_answer import QuestionAnswer

    factory, _ = attr_db
    # 失败候选：零命中
    await _insert_pair(
        factory, answer_id=2, session_id="s-gap",
        extra={"retrieval": {"result_count": 0, "max_score": None}, "answer_status": "answered"},
    )
    # 正常回答（反例）：命中 5 条、高分
    await _insert_pair(
        factory, answer_id=4, session_id="s-ok",
        extra={"retrieval": {"result_count": 5, "max_score": 0.88}, "answer_status": "answered"},
    )

    executed = []

    async def _fake_single(db, message_id):
        executed.append(message_id)
        return "content_gap"

    with (
        patch(
            "novamind.features.knowledge_ops.tasks.attribution_worker.attribute_single_event",
            _fake_single,
        ),
        patch(
            "novamind.core.database.database.get_db_session"
        ) as mock_session,
    ):
        # get_db_session 是 worker 函数内 import——patch 源模块属性；
        # 用真实 factory 顶替其上下文管理器语义
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_session_ctx():
            async with factory() as session:
                yield session

        mock_session.side_effect = _fake_session_ctx
        counts = await attribute_pending_events()

    assert executed == [2]  # 只有失败候选被处理；正常回答（id=4）不进
    assert counts == {"content_gap": 1}
