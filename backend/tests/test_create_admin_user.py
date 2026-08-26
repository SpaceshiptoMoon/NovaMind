"""create_admin_user 启动初始化测试。"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from novamind.features.user.models.user import User, UserStatus
from novamind.features.user.schemas.user_schema import UserUpdate


@pytest.fixture
def admin_config():
    """模拟默认管理员配置（外层 config.admin 指向该对象）。"""
    from types import SimpleNamespace

    inner = SimpleNamespace(
        create_on_startup=True,
        reset_password_if_exists=True,
        username="admin",
        email="admin@e.com",
        password="Admin@123",
        phone=None,
    )
    cfg = SimpleNamespace(admin=inner)
    return cfg


@pytest.mark.asyncio
async def test_create_admin_user_when_existing_admin_resets_password_without_role_code(
    admin_config,
):
    """默认管理员已存在且 reset_password_if_exists=true 时，仅重置密码，不传 role_code。"""
    from novamind.features.user.api.startup import create_admin_user

    admin = admin_config.admin

    existing_admin = User(
        id=1,
        username=admin.username,
        email=admin.email,
        password_hash="oldhash",
        role_id=1,
        status=UserStatus.ACTIVE,
    )

    user_service = AsyncMock()
    user_service.get_user_by_username.return_value = existing_admin
    user_service.update_user.return_value = existing_admin

    user_repo = AsyncMock()

    with (
        patch(
            "novamind.features.user.api.startup.get_config", return_value=admin_config
        ),
        patch(
            "novamind.features.user.api.startup.get_db_session"
        ) as mock_db_session_ctx,
        patch(
            "novamind.features.user.api.startup.UserRepository", return_value=user_repo
        ) as mock_repo_cls,
        patch(
            "novamind.features.user.api.startup.UserService", return_value=user_service
        ) as mock_svc_cls,
        patch(
            "novamind.features.user.api.startup.AuthService.blacklist_all_user_tokens",
            new_callable=AsyncMock,
        ) as mock_blacklist,
    ):
        mock_db_session_ctx.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await create_admin_user()

        # 已存在时不会调用 create_user
        user_service.create_user.assert_not_called()
        # update_user 被调用一次，且 UserUpdate 中不包含 role_code
        user_service.update_user.assert_awaited_once()
        call_args = user_service.update_user.call_args[1]
        user_update: UserUpdate = call_args["user_update"]
        update_data = user_update.model_dump(exclude_unset=True)
        assert "role_code" not in update_data
        assert "role_id" not in update_data
        assert update_data.get("password") == admin.password
        # 重置密码后清除了旧会话
        mock_blacklist.assert_awaited_once_with(existing_admin.id)


@pytest.mark.asyncio
async def test_create_admin_user_creates_new_admin_with_role_code(admin_config):
    """默认管理员不存在时，使用 create_user(role_code='admin') 创建。"""
    from novamind.features.user.api.startup import create_admin_user

    admin = admin_config.admin

    user_service = AsyncMock()
    user_service.get_user_by_username.return_value = None
    new_admin = User(
        id=1,
        username=admin.username,
        email=admin.email,
        password_hash="hashed",
        role_id=1,
        status=UserStatus.ACTIVE,
    )
    user_service.create_user.return_value = new_admin

    user_repo = AsyncMock()

    with (
        patch(
            "novamind.features.user.api.startup.get_config", return_value=admin_config
        ),
        patch(
            "novamind.features.user.api.startup.get_db_session"
        ) as mock_db_session_ctx,
        patch(
            "novamind.features.user.api.startup.UserRepository", return_value=user_repo
        ) as mock_repo_cls,
        patch(
            "novamind.features.user.api.startup.UserService", return_value=user_service
        ) as mock_svc_cls,
    ):
        mock_db_session_ctx.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock()
        )
        mock_db_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await create_admin_user()

        user_service.create_user.assert_awaited_once_with(
            username=admin.username,
            email=admin.email,
            password=admin.password,
            phone=admin.phone,
            role_code="admin",
        )
        user_service.update_user.assert_not_called()
