"""refresh token family（轮换链追踪）回归测试。

背景：刷新轮换只拉黑当前旧 jti——被盗用的旧 token 再现时仅拒绝该次请求，
盗贼手里更新的那枚 token 仍可继续换新。family（fam claim + Redis 登记链）
补上「复用连坐」：已轮换 token 复用/家族 jti 不一致 → 整条链作废。

验证核心不变量：
1. 登录/轮换写入 fam claim 且轮换透传同一 fam、family 当前 jti 随轮换推进；
2. 已轮换旧 token 复用 → 连坐（family 作废 + 最新 jti 拉黑），且连坐后
   盗贼手里的最新 token 也被拒；
3. 连坐幂等（重复触发无害）；
4. 显式 logout（带 refresh token）杀整条链；
5. 存量无 fam 旧 token 平滑过渡（走现状逻辑不误拒）。
"""

import pytest
from novamind.features.user.services.auth_service import AuthService

pytestmark = pytest.mark.unit


class _FakeFamilyStore:
    """auth_service 命名空间内四个黑名单原语的内存假实现（含 jti 黑名单）。"""

    def __init__(self):
        self.family_current: dict[str, str] = {}
        self.family_revoked: set[str] = set()
        self.revoked_jtis: set[str] = set()

    async def get_current(self, fam):
        return self.family_current.get(fam)

    async def set_current(self, fam, jti, ttl):
        self.family_current[fam] = jti

    async def is_family_revoked(self, fam):
        return fam in self.family_revoked

    async def mark_family_revoked(self, fam, ttl):
        self.family_revoked.add(fam)

    async def is_jti_revoked(self, jti):
        return jti in self.revoked_jtis

    async def revoke_jti(self, jti, expires_seconds=None):
        if jti:
            self.revoked_jtis.add(jti)


def _install(monkeypatch) -> _FakeFamilyStore:
    """把 auth_service 命名空间内的黑名单原语替换为内存假库。"""
    import novamind.core.auth.blacklist as blacklist_mod
    import novamind.features.user.services.auth_service as auth_mod

    store = _FakeFamilyStore()

    monkeypatch.setattr(auth_mod, "_core_family_current_jti", store.get_current)
    monkeypatch.setattr(auth_mod, "_core_is_family_revoked", store.is_family_revoked)
    monkeypatch.setattr(auth_mod, "_core_mark_family_revoked", store.mark_family_revoked)
    monkeypatch.setattr(auth_mod, "_core_is_token_revoked", store.is_jti_revoked)
    # create_refresh_token 函数体内懒 import（调用时读 blacklist 模块属性）
    monkeypatch.setattr(blacklist_mod, "set_token_family_current_jti", store.set_current)
    # revoke_token/_add_user_token 直连 Redis → 打桩为内存记录
    monkeypatch.setattr(AuthService, "revoke_token", store.revoke_jti)

    async def _noop_add_user_token(user_id, jti, ttl):
        return None

    monkeypatch.setattr(AuthService, "_add_user_token", _noop_add_user_token)
    return store


async def _active_user(user_id=1):
    return {
        "id": user_id,
        "username": "u",
        "email": "u@t.com",
        "role_code": "viewer",
        "is_admin": False,
        "status": 1,
    }


async def _login_pair() -> tuple[str, str]:
    return await AuthService.create_token_pair(
        user_id=1, username="u", email="u@t.com", role_code="viewer"
    )


def _jti_of(refresh_token: str) -> str:
    return AuthService._decode_token(refresh_token)["jti"]


def _fam_of(refresh_token: str) -> str:
    return AuthService._decode_token(refresh_token)["fam"]


@pytest.mark.asyncio
async def test_login_and_rotation_share_family(monkeypatch):
    """登录写入 fam；轮换透传同一 fam 且 family 当前 jti 推进到新 token。"""
    store = _install(monkeypatch)
    access, refresh = await _login_pair()

    fam = _fam_of(refresh)
    assert fam and store.family_current[fam] == _jti_of(refresh)

    result = await AuthService.refresh_access_token(refresh, get_user_func=_active_user)
    assert result is not None
    _, new_refresh, _ = result
    assert _fam_of(new_refresh) == fam, "轮换必须透传同一 family"
    assert store.family_current[fam] == _jti_of(new_refresh)
    assert _jti_of(refresh) in store.revoked_jtis, "旧 jti 轮换时拉黑"


@pytest.mark.asyncio
async def test_rotated_token_reuse_revokes_whole_family(monkeypatch):
    """已轮换旧 token 复用 → 连坐：family 作废 + 最新 jti 拉黑，最新 token 也被拒。"""
    store = _install(monkeypatch)
    _, refresh = await _login_pair()
    old_refresh = refresh

    result = await AuthService.refresh_access_token(old_refresh, get_user_func=_active_user)
    _, newest_refresh, _ = result

    # 盗贼用旧 token 复用
    reused = await AuthService.refresh_access_token(old_refresh, get_user_func=_active_user)
    assert reused is None, "复用已轮换 token 必须被拒"
    fam = _fam_of(newest_refresh)
    assert fam in store.family_revoked, "连坐必须标记 family 作废"
    newest_jti = _jti_of(newest_refresh)
    assert newest_jti in store.revoked_jtis, "连坐必须拉黑盗贼手里的最新 jti"

    # 连坐后盗贼手里的最新 token 再刷新也被拒（幂等：再次触发连坐不报错）
    assert await AuthService.refresh_access_token(newest_refresh, get_user_func=_active_user) is None
    assert await AuthService.refresh_access_token(newest_refresh, get_user_func=_active_user) is None


@pytest.mark.asyncio
async def test_family_jti_mismatch_denied(monkeypatch):
    """黑名单条目缺失时的兜底：family 当前 jti 与请求 jti 不一致 → 连坐拒绝。"""
    store = _install(monkeypatch)
    _, refresh = await _login_pair()
    fam = _fam_of(refresh)

    # 伪造：family 登记指向另一枚 jti（模拟黑名单 7 天 TTL 过期后旧 token 复用）
    store.family_current[fam] = "some-other-jti"

    result = await AuthService.refresh_access_token(refresh, get_user_func=_active_user)
    assert result is None
    assert fam in store.family_revoked


@pytest.mark.asyncio
async def test_logout_kills_family_chain(monkeypatch):
    """显式登出（带 refresh token）连坐杀链：同 family 再刷新被拒。"""
    store = _install(monkeypatch)
    _, refresh = await _login_pair()
    fam = _fam_of(refresh)

    await AuthService.logout(refresh)

    assert fam in store.family_revoked
    assert await AuthService.refresh_access_token(refresh, get_user_func=_active_user) is None


@pytest.mark.asyncio
async def test_legacy_token_without_fam_passes_through(monkeypatch):
    """存量无 fam 旧 token 平滑过渡：走现状逻辑不误拒、不写 family。"""
    store = _install(monkeypatch)

    # 直接签发（走当前代码会带 fam）→ 手工构造无 fam 的 payload 模拟存量 token
    access, refresh = await _login_pair()
    payload = AuthService._decode_token(refresh)
    payload.pop("fam")
    real_encode = AuthService._decode_token

    def _fake_decode(token):
        if token == refresh:
            return payload
        return real_encode(token)

    monkeypatch.setattr(AuthService, "_decode_token", staticmethod(_fake_decode))

    result = await AuthService.refresh_access_token(refresh, get_user_func=_active_user)
    assert result is not None, "存量无 fam token 必须平滑通过"
    _, new_refresh, _ = result
    # 新签发的 token 带新 fam（新 family），不影响旧链语义
    assert _fam_of(new_refresh)
