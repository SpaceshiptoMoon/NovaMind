"""pytest 全局夹具：SQLite 异步引擎定向建表、DB 会话与客户端工厂桩。"""
from __future__ import annotations

import sys
from pathlib import Path

# 路径设置必须先于任何 novamind import：venv 的 editable 安装
# （__editable__.novamind-0.1.0.pth）会把主仓库 backend/src 注入 sys.path，
# 若 conftest 先 import 后插路径，novamind 包已被绑定到主仓库（worktree 的
# 新 feature 找不到）。先插路径再 import，保证 novamind 解析到当前工作树。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Make `novamind` importable via the src-side namespace package
# (backend/src/novamind/) without relying on the legacy backend/novamind
# dev-bridge shim, which has been removed. The real code lives under
# backend/src/{core,features,setting,shared}; the inner novamind package
# re-export them as novamind.<name>.
SOURCE_ROOT = BACKEND_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import pytest
import pytest_asyncio
from novamind.core.database.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(scope="session", autouse=True)
def _register_prompt_templates() -> None:
    """注册全部 feature 提示词模板，供绕过 lifespan 的单元测试使用。

    生产环境由 `startup_manager._register_prompt_templates` 在 lifespan 注册；
    但许多单元测试直接调用内部服务函数（如 `_generate_image_description`），
    这些函数内部 `PromptManager.get_template(...)` 需要模板已注册。本 fixture
    在 session 开始时调用与启动期相同的集中注册函数，保证单测路径不抛 KeyError。
    """
    from novamind.core.middleware.prompt_registration import (
        register_all_prompt_templates,
    )

    register_all_prompt_templates()


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="运行需 :8100 服务的集成测试（默认跳过，避免噪声掩盖真回归）",
    )


def pytest_collection_modifyitems(config, items):
    """默认跳过 integration 标记的测试（依赖运行中的 :8100 服务）。

    集成测试常驻 ConnectionError 会掩盖真回归信号。显式 ``--run-integration``
    才运行；普通 ``pytest`` / ``pytest -m unit`` 一律跳过。
    """
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(
        reason="集成测试需运行中的 :8100 服务，加 --run-integration 启用"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest_asyncio.fixture
async def tmp_db():
    """SQLite 内存库，定向建表，每测试独立。"""
    from novamind.features.user.models.role import Permission, Role, RolePermission
    from novamind.features.user.models.user import User

    rbac_tables = [
        Role.__table__,
        Permission.__table__,
        RolePermission.__table__,
        User.__table__,
    ]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=rbac_tables))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


class JsonFakeRedis:
    """RedisCache 替身：与真实客户端一样以 JSON 存取，记录 TTL，可注入故障。"""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self.fail = False

    def _check(self):
        if self.fail:
            raise ConnectionError("redis down")

    async def get(self, key):
        import json

        self._check()
        raw = self.store.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key, value, expire=None):
        import json

        self._check()
        self.store[key] = json.dumps(value, ensure_ascii=False)
        self.ttls[key] = expire
        return True

    async def delete(self, *keys):
        self._check()
        for key in keys:
            self.store.pop(key, None)
            self.ttls.pop(key, None)
        return len(keys)


@pytest.fixture
def fake_redis():
    """假 Redis，塞进 ClientFactory 单例缓存口。

    业务代码经 get_redis_client() 取客户端；塞进单例口后，无论是注入到被测
    对象的，还是业务代码里临时新建的 repository，拿到的都是同一个假客户端，
    测到的是与生产相同的读写与失效路径。
    """
    from novamind.shared.cache.helpers import reset_cache_stats
    from novamind.shared.storage.client_factory import ClientFactory

    fake = JsonFakeRedis()
    previous = ClientFactory._instances.get("redis")
    ClientFactory._instances["redis"] = fake
    reset_cache_stats()
    yield fake
    if previous is None:
        ClientFactory._instances.pop("redis", None)
    else:
        ClientFactory._instances["redis"] = previous
