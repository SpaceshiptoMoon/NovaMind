"""黑名单合并查询 check_auth_blacklists 回归测试。

验证不变量：
1. 等价性：对任意存储状态与入参组合，结果与依次调用 is_token_revoked +
   is_user_blacklisted 完全一致（安全路径不允许语义漂移）；
2. 有效性：一次认证只发生一次 Redis 往返（原为两次串行）；
3. 故障方向：带 jti 时 Redis 异常向上透传；无 jti 时 fail-close 拒绝。
"""
import pytest

from novamind.core.auth import blacklist as bl

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _FakePipeline:
    def __init__(self, owner):
        self._owner = owner
        self._ops: list[tuple[str, str]] = []

    def exists(self, key):
        self._ops.append(("exists", key))
        return self

    def get(self, key):
        self._ops.append(("get", key))
        return self

    async def execute(self):
        self._owner.round_trips += 1
        self._owner.last_pipeline_ops = list(self._ops)
        if self._owner.fail:
            raise ConnectionError("redis down")
        store = self._owner.store
        return [
            (1 if key in store else 0) if op == "exists" else store.get(key)
            for op, key in self._ops
        ]


class _FakeRawRedis:
    """裸 redis-py 客户端替身：记录往返次数，可注入故障。"""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.fail = False
        self.round_trips = 0
        self.last_pipeline_ops: list[tuple[str, str]] = []

    def pipeline(self, transaction=True):
        assert transaction is False, "黑名单查询不需要事务语义，应使用非事务 pipeline"
        return _FakePipeline(self)

    async def exists(self, key):
        self.round_trips += 1
        if self.fail:
            raise ConnectionError("redis down")
        return 1 if key in self.store else 0

    async def get(self, key):
        self.round_trips += 1
        if self.fail:
            raise ConnectionError("redis down")
        return self.store.get(key)


@pytest.fixture
def raw_redis(monkeypatch):
    fake = _FakeRawRedis()

    async def _get():
        return fake

    monkeypatch.setattr(bl, "_raw_redis", _get)
    return fake


JTI = "jti-abc12345"
UID = 7


@pytest.mark.parametrize(
    ("revoked", "blacklist_at", "token_iat", "jti"),
    [
        (False, None, 1000, JTI),   # 全未命中
        (True, None, 1000, JTI),    # token 已撤销
        (False, 2000, 1000, JTI),   # 黑名单设置晚于签发：拒绝
        (False, 2000, 3000, JTI),   # 黑名单设置早于签发（重新登录后的新 token）：放行
        (False, 2000, 2000, JTI),   # 边界：同一秒签发不算早于
        (False, 2000, None, JTI),   # 无 iat：命中即拒绝
        (True, 2000, 1000, JTI),    # 两者同时命中
        (False, None, 1000, None),  # 无 jti
        (False, 2000, 1000, None),  # 无 jti + 用户黑名单
        (False, 2000, 1000, ""),    # 空串 jti 视同无 jti
    ],
)
async def test_equivalent_to_sequential_checks(
    raw_redis, revoked, blacklist_at, token_iat, jti
):
    """合并查询与依次调用两个原函数结果一致。"""
    if revoked:
        raw_redis.store[f"{bl.TOKEN_BLACKLIST_PREFIX}{JTI}"] = "1"
    if blacklist_at is not None:
        raw_redis.store[f"{bl.USER_BLACKLIST_PREFIX}{UID}"] = str(blacklist_at)

    expected = (
        bool(jti) and await bl.is_token_revoked(jti),
        await bl.is_user_blacklisted(UID, token_iat=token_iat),
    )
    actual = await bl.check_auth_blacklists(jti, UID, token_iat=token_iat)
    assert actual == expected


async def test_single_round_trip(raw_redis):
    """一次认证只发生一次 Redis 往返，两条命令在同一 pipeline。"""
    await bl.check_auth_blacklists(JTI, UID, token_iat=1000)
    assert raw_redis.round_trips == 1
    assert [op for op, _ in raw_redis.last_pipeline_ops] == ["exists", "get"]


async def test_no_jti_skips_token_check(raw_redis):
    """无 jti 时不发 EXISTS，结果按用户级黑名单解析（不错位）。"""
    raw_redis.store[f"{bl.USER_BLACKLIST_PREFIX}{UID}"] = "2000"
    result = await bl.check_auth_blacklists(None, UID, token_iat=1000)
    assert result == (False, True)
    assert [op for op, _ in raw_redis.last_pipeline_ops] == ["get"]


async def test_redis_failure_with_jti_raises(raw_redis):
    """带 jti 时 Redis 异常向上透传（与 is_token_revoked 一致）。"""
    raw_redis.fail = True
    with pytest.raises(bl.AuthBlacklistError):
        await bl.check_auth_blacklists(JTI, UID, token_iat=1000)


async def test_redis_failure_without_jti_fails_closed(raw_redis):
    """无 jti 时 Redis 异常按 fail-close 处理：视为在黑名单中，拒绝访问。"""
    raw_redis.fail = True
    assert await bl.check_auth_blacklists(None, UID, token_iat=1000) == (False, True)
