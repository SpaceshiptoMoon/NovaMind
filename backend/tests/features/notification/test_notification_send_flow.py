"""send_notification 落库 + WS 推送流程回归测试。

批次 3 核心链路：偏好过滤 → 落库 → ConnectionManager 推送 notification.new
完整对象；推送异常不影响落库结果。
"""
from typing import Any

import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


# SQLite 内存库 BigInteger 主键不自动生成 id，编译期降为 INTEGER（仅影响本测试建表）
@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"

from novamind.features.notification.models.notification import Notification
from novamind.features.notification.models.notification_preference import (
    NotificationPreference,
)
from novamind.features.notification.services.notification_service import NotificationService
from novamind.features.user.models.role import Role
from novamind.features.user.models.user import User

pytestmark = pytest.mark.unit

_TEST_TABLES = [
    Role.__table__,
    User.__table__,
    Notification.__table__,
    NotificationPreference.__table__,
]


class _RecordingManager:
    """记录 send_to_user 调用的桩 ConnectionManager"""

    def __init__(self):
        self.calls: list[tuple] = []
        self.fail = False

    async def send_to_user(self, user_id: int, event: dict[str, Any]) -> bool:
        if self.fail:
            raise RuntimeError("ws down")
        self.calls.append((user_id, event))
        return True


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TEST_TABLES))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def recording_manager(monkeypatch):
    mgr = _RecordingManager()
    import novamind.features.notification.services.notification_service as mod
    monkeypatch.setattr(mod, "ws_manager", mgr)
    return mgr


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_persists_and_pushes_full_object(db, recording_manager):
    """send_notification 落库后经 WS 推 notification.new 完整对象"""
    svc = NotificationService(db)
    notification = await svc.send_notification(
        user_id=1, type="skill_review", title="技能审核通过",
        content="可以发布了", link="/home/workspace/skills/1",
        extra_data={"skill_id": 1},
    )

    assert notification is not None and notification.id is not None
    # 落库
    assert notification.type == "skill_review"
    assert notification.is_read is False
    # WS 推送：完整对象（前端直接 prepend 不回源）
    assert len(recording_manager.calls) == 1
    user_id, event = recording_manager.calls[0]
    assert user_id == 1
    assert event["type"] == "notification.new"
    data = event["data"]
    assert data["id"] == notification.id
    assert data["title"] == "技能审核通过"
    assert data["link"] == "/home/workspace/skills/1"
    assert data["extra_data"] == {"skill_id": 1}
    assert data["is_read"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_pushes_datetime_created_at(db, recording_manager):
    """created_at datetime 字段 isoformat 后推送（不经 default=str 也能序列化）"""
    svc = NotificationService(db)
    notification = await svc.send_notification(
        user_id=1, type="system", title="t", content="c",
    )
    _, event = recording_manager.calls[0]
    assert event["data"]["id"] == notification.id
    # created_at 已转 isoformat 字符串
    created = event["data"]["created_at"]
    assert created is None or isinstance(created, str)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_respects_in_app_disabled(db, recording_manager):
    """in_app_enabled=False：不落库不推送"""
    svc = NotificationService(db)
    await svc.update_preferences(1, {"in_app_enabled": False})

    notification = await svc.send_notification(
        user_id=1, type="system", title="t", content="c",
    )

    assert notification is None
    assert recording_manager.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_respects_type_filter(db, recording_manager):
    """types_enabled 白名单过滤：类型不在名单内不落库不推送"""
    svc = NotificationService(db)
    await svc.update_preferences(1, {"types_enabled": ["skill_review"]})

    # 白名单外：不发
    notification = await svc.send_notification(
        user_id=1, type="system", title="t", content="c",
    )
    assert notification is None
    assert recording_manager.calls == []

    # 白名单内：发
    notification = await svc.send_notification(
        user_id=1, type="skill_review", title="t", content="c",
    )
    assert notification is not None
    assert len(recording_manager.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_ws_failure_does_not_break_persist(db, recording_manager):
    """WS 推送抛异常被吞，落库结果不受影响"""
    recording_manager.fail = True
    svc = NotificationService(db)

    notification = await svc.send_notification(
        user_id=1, type="system", title="t", content="c",
    )

    assert notification is not None, "推送失败不得影响落库"
    assert notification.id is not None
