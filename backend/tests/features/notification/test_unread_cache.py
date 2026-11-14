"""通知未读数缓存与失效回归测试。

验证不变量：
1. 有效性：未读数 30s 缓存内不再 COUNT；
2. 一致性：发送通知 / 单条已读 / 全部已读之后，未读数缓存立即失效，
   下次读取拿到数据库新值（「全部已读」后红点必须立即消失）；
3. 列表端点的 unread_count 与角标共用同一缓存键，两处数字一致。
"""
from types import SimpleNamespace

import pytest
from novamind.features.notification.services.notification_service import (
    NotificationService,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


UNREAD_KEY = "notif:unread:7"


def _make_service(unread: int):
    svc = NotificationService.__new__(NotificationService)
    svc.db = None
    svc._pref_repo = None
    calls = {"count": 0}

    class _Repo:
        async def get_unread_count(self, user_id):
            calls["count"] += 1
            return unread

        async def list_by_user(self, user_id, limit, offset, unread_only):
            return [], 0

        async def mark_read(self, notification_id, user_id):
            return True

        async def mark_all_read(self, user_id):
            return unread

        async def create(self, data):
            from types import SimpleNamespace

            return SimpleNamespace(id=1)

    svc._repo = _Repo()

    async def _push_ws(user_id, notification):
        return None

    svc._push_ws = _push_ws

    async def _get_user_email(user_id):
        return None

    svc._get_user_email = _get_user_email

    async def _pref_get_or_create(user_id):
        from types import SimpleNamespace

        return SimpleNamespace(in_app_enabled=True, email_enabled=False, types_enabled=None)

    svc._pref_repo = SimpleNamespace(get_or_create=_pref_get_or_create)
    return svc, calls


async def test_unread_count_cached(fake_redis):
    svc, calls = _make_service(3)

    assert (await svc.get_unread_count(7)).unread_count == 3
    assert (await svc.get_unread_count(7)).unread_count == 3
    assert calls["count"] == 1


async def test_mark_all_read_invalidates(fake_redis):
    """全部已读后红点必须立即消失（本用例 TTL 内失效生效）。"""
    svc, calls = _make_service(3)
    await svc.get_unread_count(7)
    assert UNREAD_KEY in fake_redis.store

    await svc.mark_all_read(7)
    assert UNREAD_KEY not in fake_redis.store, "全部已读必须失效未读数缓存"

    # 失效后重新 COUNT（call=2），证明确实回源而不是读到缓存旧值
    await svc.get_unread_count(7)
    assert calls["count"] == 2


async def test_mark_read_invalidates(fake_redis):
    svc, calls = _make_service(2)
    await svc.get_unread_count(7)

    await svc.mark_read(1, 7)
    assert UNREAD_KEY not in fake_redis.store


async def test_send_notification_invalidates(fake_redis):
    svc, calls = _make_service(1)
    await svc.get_unread_count(7)

    await svc.send_notification(7, "kb_ops", "标题", "内容")
    assert UNREAD_KEY not in fake_redis.store


async def test_list_endpoint_shares_same_cache(fake_redis):
    """列表端点与角标共用缓存键：两处数字一致，COUNT 只发生一次。"""
    svc, calls = _make_service(5)

    listed = await svc.get_notifications(7)
    badge = await svc.get_unread_count(7)

    assert listed.unread_count == badge.unread_count == 5
    assert calls["count"] == 1
