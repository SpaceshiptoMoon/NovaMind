"""member 邀请/直加通知接线回归测试。

纯桩验证：_notify_space_invite 组装的通知参数（user_id/type/link 含完整
token/space_name 降级）与异常静默语义。不碰真实 DB。
"""
from types import SimpleNamespace

import novamind.features.knowledge_space.api.member_routes as routes
import pytest

pytestmark = pytest.mark.unit


class _RecordingPort:
    def __init__(self):
        self.calls = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)


class _FakeSpaceRepo:
    def __init__(self, space):
        self._space = space

    async def get_by_id(self, space_id):
        return self._space


@pytest.fixture
def capture(monkeypatch):
    """捕获 as_notification_port 与 SpaceRepository 构造"""
    port = _RecordingPort()
    monkeypatch.setattr(routes, "as_notification_port", lambda db: port)
    return port


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invite_notification_carries_full_token(monkeypatch, capture):
    """邀请通知 link 含完整 invite_token（截断曾是真实 bug）"""
    space = SimpleNamespace(id=5, name="研发空间")
    monkeypatch.setattr(routes, "SpaceRepository", lambda db: _FakeSpaceRepo(space))
    fake_db = SimpleNamespace()

    await routes._notify_space_invite(
        fake_db, user_id=9, space_id=5, role_value="viewer",
        invite_token="tok-full-value",
    )

    assert len(capture.calls) == 1
    call = capture.calls[0]
    assert call["user_id"] == 9
    assert call["type"] == "space_invite"
    assert call["link"] == "/home/spaces/5/join?token=tok-full-value"
    assert call["extra_data"]["space_name"] == "研发空间"
    assert call["extra_data"]["invite_token"] == "tok-full-value"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invite_notification_space_missing_falls_back(monkeypatch, capture):
    """空间查不到时 space_name 降级为「空间 {id}」"""
    monkeypatch.setattr(routes, "SpaceRepository", lambda db: _FakeSpaceRepo(None))

    await routes._notify_space_invite(
        SimpleNamespace(), user_id=9, space_id=77, role_value="editor",
        invite_token="tok",
    )

    call = capture.calls[0]
    assert "空间 77" in call["title"]
    assert call["extra_data"]["space_name"] == "空间 77"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_add_notification(monkeypatch, capture):
    """直加成员通知：link 指向空间主页，不带 token"""
    space = SimpleNamespace(id=5, name="研发空间")
    monkeypatch.setattr(routes, "SpaceRepository", lambda db: _FakeSpaceRepo(space))

    await routes._notify_space_invite(
        SimpleNamespace(), user_id=9, space_id=5, role_value="editor", direct=True,
    )

    call = capture.calls[0]
    assert call["link"] == "/home/spaces/5"
    assert "invite_token" not in call["extra_data"]
    assert "已加入" in call["title"] or "加入" in call["title"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_failure_swallowed(monkeypatch):
    """SpaceRepository 抛异常时静默（不打断邀请主流程）"""
    class _BoomRepo:
        def __init__(self, db):
            pass

        async def get_by_id(self, space_id):
            raise RuntimeError("db down")

    monkeypatch.setattr(routes, "SpaceRepository", _BoomRepo)

    await routes._notify_space_invite(
        SimpleNamespace(), user_id=9, space_id=5, role_value="viewer",
        invite_token="tok",
    )  # 不抛
