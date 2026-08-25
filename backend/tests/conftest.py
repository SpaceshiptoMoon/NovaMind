from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from novamind.core.database.base import Base

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
    from novamind.features.user.models.role import Role, Permission, RolePermission
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
