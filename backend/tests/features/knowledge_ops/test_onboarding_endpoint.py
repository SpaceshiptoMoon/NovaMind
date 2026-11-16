"""运营冷启动引导回归（运营平台批次 1）。

覆盖：三态阶段判定（empty/collecting/ready）、embedding 生效语义
（显式配置 or 用户默认回退——与检索侧同判据，正反两用例：
显式配置与默认回退都判可检索，两者皆无才判未配置）。
"""
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

pytest.importorskip("aiosqlite")

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 16, 12, 0, 0)
EMBEDDING_CONFIG = {"embedding": {"model": "text-embedding-v3", "dimension": 1024}}


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def onb_db():
    """五表内存库（users/spaces/kbs/documents/kb_events）。"""
    from novamind.core.database.base import Base
    from novamind.features.knowledge_ops.models.kb_event import KbEvent
    from novamind.features.knowledge_space.models.document import Document
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
    from novamind.features.user.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    async def setup():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        tables = [
            User.__table__, KnowledgeSpace.__table__, KnowledgeBase.__table__,
            Document.__table__, KbEvent.__table__,
        ]
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine

    factory, engine = asyncio.run(setup())

    async def seed():
        from novamind.features.user.models.user import User

        async with factory() as session:
            session.add(User(id=1, username="owner", email="o@x.com", password_hash="h", role_id=1))
            await session.commit()

    asyncio.run(seed())
    yield factory
    asyncio.run(engine.dispose())


def _no_user_default(monkeypatch):
    """屏蔽用户默认 embedding 回退（显式未配置路径的反向前提）。"""
    from novamind.features.user.services.model_config_service import ModelConfigService

    monkeypatch.setattr(
        ModelConfigService, "get_user_default_model_name", AsyncMock(return_value=None)
    )


def _user_default(monkeypatch, model: str):
    from novamind.features.user.services.model_config_service import ModelConfigService

    monkeypatch.setattr(
        ModelConfigService, "get_user_default_model_name", AsyncMock(return_value=model)
    )


def _add_space(factory, config: dict | None) -> None:
    async def body():
        from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace

        async with factory() as session:
            session.add(KnowledgeSpace(id=1, name="s1", owner_id=1, config=config))
            await session.commit()

    asyncio.run(body())


def _add_documents(factory, count: int) -> None:
    async def body():
        from novamind.features.knowledge_space.models.document import Document
        from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase

        async with factory() as session:
            session.add(KnowledgeBase(id=3, space_id=1, name="kb1", creator_id=1, config={}))
            for i in range(count):
                session.add(Document(
                    id=100 + i, space_id=1, kb_id=3, uploader_id=1,
                    filename=f"doc{i}.pdf", file_type="pdf", file_size=10,
                    file_hash=f"h{i}", storage={},
                ))
            await session.commit()

    asyncio.run(body())


def _add_queries(factory, count: int) -> None:
    async def body():
        from novamind.features.knowledge_ops.models.kb_event import KbEvent

        async with factory() as session:
            for i in range(count):
                session.add(KbEvent(
                    id=i + 1, event_type="query", user_id=1, space_id=1,
                    extra={"results_count": 5}, created_at=NOW - timedelta(hours=i),
                ))
            await session.commit()

    asyncio.run(body())


def _onboarding(factory):
    from novamind.features.knowledge_ops.services.ops_onboarding_service import OpsOnboardingService

    async def body():
        async with factory() as session:
            return await OpsOnboardingService(session).get_onboarding(1)

    return asyncio.run(body())


def test_missing_space_returns_empty(onb_db):
    """空间不存在：empty + 明确文案（不硬造检查项）。"""
    data = _onboarding(onb_db)
    assert data["stage"] == "empty"
    assert data["checks"] == []
    assert "不存在" in data["next_step"]


def test_empty_stage(onb_db, monkeypatch):
    """无 embedding 且无文档：empty，两项检查未过且带行动建议。"""
    _no_user_default(monkeypatch)
    _add_space(onb_db, config=None)
    data = _onboarding(onb_db)
    assert data["stage"] == "empty"
    by_key = {c["key"]: c for c in data["checks"]}
    assert by_key["embedding"]["ok"] is False
    assert by_key["embedding"]["action_hint"] is not None
    assert by_key["documents"]["ok"] is False
    assert by_key["documents"]["detail"].startswith("0 篇")


def test_collecting_stage(onb_db, monkeypatch):
    """显式 embedding + 足量文档 + 无行为数据：collecting（采集期）。"""
    _add_space(onb_db, config=EMBEDDING_CONFIG)
    _add_documents(onb_db, 12)
    data = _onboarding(onb_db)
    assert data["stage"] == "collecting"
    by_key = {c["key"]: c for c in data["checks"]}
    assert by_key["embedding"]["ok"] is True
    assert "text-embedding-v3" in by_key["embedding"]["detail"]
    assert by_key["documents"]["ok"] is True
    assert by_key["query_volume"]["ok"] is False
    assert "采集期" in by_key["query_volume"]["detail"]


def test_ready_stage(onb_db, monkeypatch):
    """全检查通过：ready，行为数据带真实计数。"""
    _add_space(onb_db, config=EMBEDDING_CONFIG)
    _add_documents(onb_db, 12)
    _add_queries(onb_db, 31)
    data = _onboarding(onb_db)
    assert data["stage"] == "ready"
    by_key = {c["key"]: c for c in data["checks"]}
    assert all(c["ok"] for c in data["checks"])
    assert "31 次" in by_key["query_volume"]["detail"]


def test_embedding_user_default_fallback(onb_db, monkeypatch):
    """生效语义：无显式配置但用户默认模型存在 → 判可检索，标注「用户默认」。"""
    _user_default(monkeypatch, "default-emb")
    _add_space(onb_db, config=None)
    _add_documents(onb_db, 12)
    data = _onboarding(onb_db)
    by_key = {c["key"]: c for c in data["checks"]}
    assert by_key["embedding"]["ok"] is True
    assert "default-emb" in by_key["embedding"]["detail"]
    assert "用户默认" in by_key["embedding"]["detail"]
    # 采集期而非 empty：可检索 + 有内容
    assert data["stage"] == "collecting"


def test_query_volume_window_counts_recent_only(onb_db, monkeypatch):
    """窗口语义：30 天前的事件不计入近 7 天判定（采集期不误判 ready）。"""
    _add_space(onb_db, config=EMBEDDING_CONFIG)
    _add_documents(onb_db, 12)
    from novamind.features.knowledge_ops.models.kb_event import KbEvent

    async def seed_old():
        async with onb_db() as session:
            session.add(KbEvent(
                id=1, event_type="query", user_id=1, space_id=1,
                extra={"results_count": 5}, created_at=NOW - timedelta(days=30),
            ))
            await session.commit()

    asyncio.run(seed_old())
    data = _onboarding(onb_db)
    assert data["stage"] == "collecting"  # 旧事件不计，仍在采集期
