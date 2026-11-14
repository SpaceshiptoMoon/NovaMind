"""认证状态快照缓存回归测试（2026-11-14 认证链缓存批次）。

验证不变量：
1. 有效性：快照 miss 回填后命中路径零 SQL；快照字段派生正确；
2. 一致性（失效时序）：写入口失效 + 提交后二次失效双保险——「失效早于
   提交」窗口内被并发请求回填的脏值，会在 commit 后被二次失效清掉；
3. 一致性（角色变更）：assign_user_role 后快照失效，is_admin 不残留
   （角色变更无 token 黑名单兜底，快照是唯一防线）；
4. 一致性（强制改密标记）：_set_must_change_password 写库后快照失效；
5. 降级：Redis 故障时认证链降级直查，不阻断；
6. 语义：软删除用户返回 None 且不缓存。

假 Redis 模拟 RedisCache 的 JSON 序列化往返（IntEnum 快照 status 读回
变 int，与真实行为一致），可注入故障。
"""
import asyncio
import json

import pytest
from sqlalchemy import event, update

from novamind.features.user.models.role import Role
from novamind.features.user.models.user import User, UserStatus
from novamind.features.user.repository.user_repository import (
    UserRepository,
    _post_commit_tasks,
)
from novamind.features.user.services.user_service import UserService

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

AUTH_KEY = "auth:status:{}"


class JsonFakeRedis:
    """模拟 RedisCache：JSON 序列化往返 + 可注入故障。"""

    def __init__(self):
        self.store = {}
        self.fail = False

    async def get(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        raw = self.store.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key, value, expire=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.store[key] = json.dumps(value, ensure_ascii=False, default=int)
        return True

    async def delete(self, *keys):
        if self.fail:
            raise ConnectionError("redis down")
        for k in keys:
            self.store.pop(k, None)
        return len(keys)


@pytest.fixture
def fake_redis():
    """假 Redis，同时塞进 ClientFactory 单例缓存。

    业务代码里新建的 repository 实例（如 role_service 内的
    UserRepository(self.db)）经 get_redis_client() 取客户端；塞进单例口后
    它们拿到的是同一个假客户端，测到的就是生产同款失效路径。
    """
    from novamind.shared.storage.client_factory import ClientFactory

    fake = JsonFakeRedis()
    previous = ClientFactory._instances.get("redis")
    ClientFactory._instances["redis"] = fake
    yield fake
    if previous is None:
        ClientFactory._instances.pop("redis", None)
    else:
        ClientFactory._instances["redis"] = previous


@pytest.fixture
def user_repo(tmp_db, fake_redis):
    repo = UserRepository(tmp_db)
    repo._cache = fake_redis  # 绕过懒加载直接注入
    return repo


@pytest.fixture
def sql_counter(tmp_db):
    """统计 session 发出的 SQL 条数（验证命中路径零查询）。"""
    engine = tmp_db.bind.sync_engine
    counter = {"n": 0}

    def _before_cursor(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _before_cursor)
    yield counter
    event.remove(engine, "before_cursor_execute", _before_cursor)


async def _drain_post_commit_tasks():
    """等全部提交后二次失效任务执行完毕。"""
    while _post_commit_tasks:
        await asyncio.gather(*list(_post_commit_tasks))


async def _seed(session, role_code="user", username="alice") -> tuple[User, Role]:
    # SQLite 下 BigInteger 主键不自增（仓库测试惯例显式给 id，见 test_rbac_models）
    role = Role(id=1, code=role_code, name=role_code)
    session.add(role)
    await session.flush()
    user = User(
        id=1,
        username=username,
        email=f"{username}@test.local",
        password_hash="h",
        role_id=role.id,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()
    return user, role


async def test_snapshot_fields_and_hit_skips_sql(user_repo, tmp_db, sql_counter):
    """快照字段派生正确；第二次读取零 SQL（有效性）。"""
    user, role = await _seed(tmp_db)
    await tmp_db.commit()

    snap = await user_repo.get_auth_status_cached(user.id)
    assert snap["id"] == user.id
    assert snap["role_code"] == role.code
    assert snap["is_admin"] is False
    assert snap["is_active"] is True
    assert snap["is_deleted"] is False
    assert snap["must_change_password"] is False

    sql_counter["n"] = 0
    again = await user_repo.get_auth_status_cached(user.id)
    assert again == snap
    assert sql_counter["n"] == 0, f"命中路径不应发 SQL，实际 {sql_counter['n']} 条"


async def test_post_commit_invalidation_clears_dirty_refill(
    user_repo, tmp_db, fake_redis
):
    """「失效早于提交」窗口内的脏回填在 commit 后被二次失效清掉（一致性核心）。

    时序：回填 active 快照 → update_user 改 INACTIVE（内部立即失效 + 注册
    提交后失效）→ 模拟并发认证请求在提交前 miss 并回填旧 active 快照 →
    commit → 二次失效执行 → 脏快照被清，重读拿到 is_active=False。
    """
    user, _ = await _seed(tmp_db)
    await tmp_db.commit()

    stale = await user_repo.get_auth_status_cached(user.id)
    assert stale["is_active"] is True

    # 写入口：置为停用（repository 不提交，commit 由调用方统一管理）
    user.status = UserStatus.INACTIVE
    await user_repo._invalidate_user_cache(user.id, user.username)
    assert AUTH_KEY.format(user.id) not in fake_redis.store  # 立即失效生效

    # 模拟并发请求在失效之后、提交之前 miss 并回填旧值
    fake_redis.store[AUTH_KEY.format(user.id)] = json.dumps(stale, default=int)

    await tmp_db.commit()  # 提交触发 after_commit 二次失效
    await _drain_post_commit_tasks()

    assert (
        AUTH_KEY.format(user.id) not in fake_redis.store
    ), "提交后二次失效必须清掉窗口内的脏回填"

    fresh = await user_repo.get_auth_status_cached(user.id)
    assert fresh["is_active"] is False


async def test_assign_user_role_invalidates_snapshot(user_repo, tmp_db, fake_redis):
    """角色分配后快照失效：降级管理员的 is_admin 不残留（无黑名单兜底的字段）。"""
    user, _ = await _seed(tmp_db, role_code="user")
    admin_role = Role(id=2, code="admin", name="管理员")
    tmp_db.add(admin_role)
    await tmp_db.flush()
    await tmp_db.commit()

    before = await user_repo.get_auth_status_cached(user.id)
    assert before["is_admin"] is False

    from novamind.features.user.services.role_service import RoleService

    svc = RoleService(tmp_db, permission_checker=None)
    await svc.assign_user_role(user.id, admin_role.id)
    await tmp_db.commit()
    await _drain_post_commit_tasks()

    assert (
        AUTH_KEY.format(user.id) not in fake_redis.store
    ), "角色分配必须失效认证快照"

    # 同 session 的 identity map 命中旧对象且 selectin 关系不重载；
    # 生产认证链每请求新会话无此语义，测试侧清空模拟新会话
    tmp_db.expunge_all()
    after = await user_repo.get_auth_status_cached(user.id)
    assert after["role_code"] == "admin"
    assert after["is_admin"] is True


async def test_must_change_password_write_invalidates_snapshot(
    user_repo, tmp_db, fake_redis
):
    """_set_must_change_password 写库后快照失效，改密标记不残留旧值。"""
    user, _ = await _seed(tmp_db)
    user.must_change_password = False
    await tmp_db.commit()

    svc = UserService.__new__(UserService)
    svc.user_repository = user_repo

    snap = await user_repo.get_auth_status_cached(user.id)
    assert snap["must_change_password"] is False

    await svc._set_must_change_password(user.id, True)
    await tmp_db.commit()
    await _drain_post_commit_tasks()

    assert (
        AUTH_KEY.format(user.id) not in fake_redis.store
    ), "改密标记写入必须失效认证快照"

    refreshed = await user_repo.get_auth_status_cached(user.id)
    assert refreshed["must_change_password"] is True


async def test_redis_down_degrades_to_db(user_repo, tmp_db, fake_redis):
    """Redis 故障时降级直查：认证链不因缓存层不可用而阻断。"""
    user, _ = await _seed(tmp_db)
    await tmp_db.commit()

    fake_redis.fail = True
    snap = await user_repo.get_auth_status_cached(user.id)
    assert snap is not None and snap["is_active"] is True

    fake_redis.fail = False
    assert AUTH_KEY.format(user.id) not in fake_redis.store, "故障期间不应留下半成品缓存"


async def test_soft_deleted_user_returns_none_and_not_cached(
    user_repo, tmp_db, fake_redis
):
    """软删除用户返回 None 且不缓存（与直查语义一致）。"""
    user, _ = await _seed(tmp_db)
    await tmp_db.commit()

    assert (await user_repo.get_auth_status_cached(user.id)) is not None

    assert await user_repo.soft_delete(user.id) is True
    await tmp_db.commit()
    await _drain_post_commit_tasks()

    assert await user_repo.get_auth_status_cached(user.id) is None
    assert AUTH_KEY.format(user.id) not in fake_redis.store


async def test_rollback_leaves_listener_dormant_but_harmless(
    user_repo, tmp_db, fake_redis
):
    """回滚后未触发的监听器在下一次 commit 时兜底清理，且不会误伤。

    回滚意味着写未生效，此时缓存里的旧快照本来就是「正确值」；监听器
    一旦在后续 commit 触发，删除是幂等安全的（下次读 miss 回填新值）。
    """
    user, _ = await _seed(tmp_db)
    await tmp_db.commit()
    # rollback 会 expire ORM 属性，之后再访问会触发同步懒加载；提前求值
    user_id, username = user.id, user.username
    await user_repo.get_auth_status_cached(user_id)

    user.status = UserStatus.INACTIVE
    await user_repo._invalidate_user_cache(user_id, username)
    await tmp_db.rollback()  # 写未生效，监听器未触发

    snap = await user_repo.get_auth_status_cached(user_id)
    assert snap["is_active"] is True, "回滚后重读应仍是未变更的状态"

    await tmp_db.execute(
        update(User).where(User.id == user_id).values(status=UserStatus.INACTIVE)
    )
    await tmp_db.commit()  # 残留监听器在此触发
    await _drain_post_commit_tasks()

    assert AUTH_KEY.format(user_id) not in fake_redis.store
    again = await user_repo.get_auth_status_cached(user_id)
    assert again["is_active"] is False
