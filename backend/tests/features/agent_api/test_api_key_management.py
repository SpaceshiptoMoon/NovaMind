"""单元测试：agent_api 批次 1——API key 生成/鉴权/吊销/用户状态联动。

覆盖：
- generate_api_key：前缀/长度/熵唯一性/hash 稳定
- ApiKeyService：create→authenticate 命中、吊销后 401、用户禁用后 401、
  他人 key 404、上限 409、last_used 失败不阻断鉴权
- get_api_key_user 依赖：缺 header 401、成功返回兼容 dict

DB 交互 SQLite 内存库定向建表（agent_api_keys + users），StaticPool；
get_auth_status 与 _touch_last_used_safe 打桩（隔离 user 表结构与全局工厂）。
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


@pytest.fixture(autouse=True)
def _crypto_key():
    """encrypt_api_key_async 需要启动期注入的加密密钥（lifespan 装配，单测补）。"""
    from novamind.shared.utils.crypto import configure_encryption_key

    configure_encryption_key("unit-test-encryption-key-not-a-secret")
    yield


@compiles(BigInteger, "sqlite")
def _bigint_to_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def key_db():
    """SQLite 内存库：agent_api_keys（users 表供 FK 目标；get_auth_status 打桩不查它）。"""
    from novamind.core.database.base import Base
    from novamind.features.agent_api.models.api_key import AgentApiKey
    from novamind.features.user.models.user import User

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[User.__table__, AgentApiKey.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory, engine
    await engine.dispose()


# ========== key 生成 ==========


def test_generate_api_key_format():
    """前缀 nvm_、总长 47、前 12 字符即展示前缀、hash 稳定。"""
    import hashlib

    from novamind.features.agent_api.services.api_key_service import generate_api_key

    plain, key_hash, prefix = generate_api_key()
    assert plain.startswith("nvm_")
    assert len(plain) == 47
    assert prefix == plain[:12]
    assert key_hash == hashlib.sha256(plain.encode()).hexdigest()

    # 熵唯一性（连续生成不撞）
    plain2, _, _ = generate_api_key()
    assert plain2 != plain


# ========== ApiKeyService ==========


def _patch_user_status(active: bool):
    """打桩 UserService.get_auth_status（隔离 user 表结构与查询链）。"""

    async def _fake(self, user_id):
        if not active:
            return None  # 禁用/删除用户按「查无可用状态」处理
        return {
            "id": user_id, "username": "tester", "email": "t@x.com",
            "role_code": "member", "is_admin": False, "status": 1,
            "is_active": active, "is_deleted": False, "must_change_password": False,
        }

    return patch(
        "novamind.features.user.services.user_service.UserService.get_auth_status",
        new=_fake,
    )


def _patch_touch():
    """打桩 last_used_at 更新（隔离全局会话工厂）。"""
    return patch(
        "novamind.features.agent_api.services.api_key_service.ApiKeyService._touch_last_used_safe",
        new=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_create_and_authenticate_roundtrip(key_db):
    """正例：create → authenticate 命中，返回正确 user_id/key_id。"""
    from novamind.features.agent_api.services.api_key_service import ApiKeyService

    factory, _ = key_db
    async with factory() as db:
        svc = ApiKeyService(db)
        with _patch_user_status(True), _patch_touch():
            record, plain = await svc.create_key(user_id=1, name="test-key")
            await db.commit()

        with _patch_user_status(True), _patch_touch():
            ctx = await svc.authenticate(plain)

    assert ctx.user_id == 1
    assert ctx.key_id == record.id
    assert ctx.key_name == "test-key"
    assert ctx.user["username"] == "tester"


@pytest.mark.asyncio
async def test_revoked_key_rejected(key_db):
    """吊销后 authenticate 401（即时失效语义）。"""
    from novamind.features.agent_api.exceptions import InvalidApiKeyError
    from novamind.features.agent_api.services.api_key_service import ApiKeyService

    factory, _ = key_db
    async with factory() as db:
        svc = ApiKeyService(db)
        with _patch_user_status(True), _patch_touch():
            record, plain = await svc.create_key(user_id=1, name="k")
            await db.commit()
        await svc.revoke_key(user_id=1, key_id=record.id)
        await db.commit()

    with _patch_user_status(True):
        with pytest.raises(InvalidApiKeyError):
            await svc.authenticate(plain)


@pytest.mark.asyncio
async def test_disabled_user_key_rejected(key_db):
    """用户禁用后 key 一并失效（与 JWT 用户状态语义一致）。"""
    from novamind.features.agent_api.exceptions import InvalidApiKeyError
    from novamind.features.agent_api.services.api_key_service import ApiKeyService

    factory, _ = key_db
    async with factory() as db:
        svc = ApiKeyService(db)
        with _patch_user_status(True), _patch_touch():
            _, plain = await svc.create_key(user_id=1, name="k")
            await db.commit()

    with _patch_user_status(False):
        with pytest.raises(InvalidApiKeyError):
            await svc.authenticate(plain)


@pytest.mark.asyncio
async def test_revoke_other_users_key_404(key_db):
    """防横探：吊销他人 key 返回 404（不泄露存在性）。"""
    from novamind.features.agent_api.exceptions import ApiKeyNotFoundError
    from novamind.features.agent_api.services.api_key_service import ApiKeyService

    factory, _ = key_db
    async with factory() as db:
        svc = ApiKeyService(db)
        with _patch_user_status(True), _patch_touch():
            record, _ = await svc.create_key(user_id=1, name="k")
            await db.commit()

    with pytest.raises(ApiKeyNotFoundError):
        await svc.revoke_key(user_id=2, key_id=record.id)


@pytest.mark.asyncio
async def test_key_limit_409(key_db):
    """有效 key 达上限 → 409；吊销后额度释放。"""
    from novamind.features.agent_api.exceptions import ApiKeyLimitExceededError
    from novamind.features.agent_api.services.api_key_service import (
        MAX_ACTIVE_KEYS_PER_USER,
        ApiKeyService,
    )

    factory, _ = key_db
    async with factory() as db:
        svc = ApiKeyService(db)
        with _patch_user_status(True), _patch_touch():
            for _ in range(MAX_ACTIVE_KEYS_PER_USER):
                await svc.create_key(user_id=1, name="k")
            await db.commit()

            with pytest.raises(ApiKeyLimitExceededError):
                await svc.create_key(user_id=1, name="over")

            # 吊销一个后额度释放
            keys = await svc.list_keys(user_id=1)
            await svc.revoke_key(user_id=1, key_id=keys[0].id)
            await db.commit()
            _, plain = await svc.create_key(user_id=1, name="after-revoke")
            assert plain.startswith("nvm_")


@pytest.mark.asyncio
async def test_last_used_failure_does_not_block_auth(key_db):
    """last_used_at 更新失败不影响鉴权（fire-and-forget 语义）。"""
    from novamind.features.agent_api.services.api_key_service import ApiKeyService

    factory, _ = key_db
    async with factory() as db:
        svc = ApiKeyService(db)
        with _patch_user_status(True), _patch_touch():
            _, plain = await svc.create_key(user_id=1, name="k")
            await db.commit()

    # 不 patch _touch_last_used_safe 本身（会连内部容错一起替换）——
    # patch 其内部的 get_db_session 让更新真实失败，验证容错层
    with _patch_user_status(True), patch(
        "novamind.core.database.database.get_db_session",
        side_effect=RuntimeError("db gone"),
    ):
        ctx = await svc.authenticate(plain)
    assert ctx.user_id == 1


@pytest.mark.asyncio
async def test_get_api_key_user_dependency(key_db):
    """get_api_key_user 依赖：缺 header 401；成功返回兼容 dict + request.state.user_id。"""
    from fastapi import Request

    from novamind.features.agent_api.api.dependencies import get_api_key_user
    from novamind.features.agent_api.services.api_key_service import ApiKeyService

    factory, _ = key_db
    async with factory() as db:
        svc = ApiKeyService(db)
        with _patch_user_status(True), _patch_touch():
            _, plain = await svc.create_key(user_id=1, name="k")
            await db.commit()

    request = Request({"type": "http", "headers": [], "method": "GET", "url": "", "query_string": b""})

    # 缺 header → 401
    with pytest.raises(Exception) as exc_info:
        await get_api_key_user(request=request, x_api_key=None, service=svc)
    assert getattr(exc_info.value, "code", "") == "INVALID_API_KEY"

    # 成功 → 兼容 dict
    with _patch_user_status(True), _patch_touch():
        user = await get_api_key_user(request=request, x_api_key=plain, service=svc)
    assert user["id"] == 1
    assert user["is_admin"] is False
    assert user["jti"] is None
    assert request.state.user_id == 1
