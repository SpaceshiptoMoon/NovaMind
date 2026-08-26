"""用户注册/创建角色绑定测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from novamind.features.user.services.user_service import UserService
from novamind.features.user.repository.user_repository import UserRepository
from novamind.features.user.models.role import Role
from novamind.features.user.models.user import User


@pytest.mark.asyncio
async def test_create_user_binds_role_id_by_role_code():
    """create_user 接受 role_code='viewer'，内部查 role 并写入 role_id。"""
    viewer_role = Role(id=1, code="viewer", name="浏览者")

    repo = AsyncMock(spec=UserRepository)
    repo.get_role_by_code.return_value = viewer_role
    repo.get_user_by_username = AsyncMock(return_value=None)
    repo.get_user_by_email = AsyncMock(return_value=None)
    repo.get_user_by_phone = AsyncMock(return_value=None)
    repo.create_user = AsyncMock(
        return_value=User(
            id=1,
            username="newuser",
            email="new@e.com",
            password_hash="hashed",
            role_id=viewer_role.id,
            status=1,
        )
    )

    service = UserService(repo)
    await service.create_user(
        username="newuser",
        email="new@e.com",
        password="Secure@123",
        phone=None,
        role_code="viewer",
    )

    create_payload = repo.create_user.call_args[0][0]
    assert "is_admin" not in create_payload
    assert create_payload["role_id"] == viewer_role.id


@pytest.mark.asyncio
async def test_register_user_forces_viewer_role():
    """register_user 强制 role_code='viewer'，不允许外部指定角色。"""
    viewer_role = Role(id=2, code="viewer", name="浏览者")

    repo = AsyncMock(spec=UserRepository)
    repo.get_role_by_code.return_value = viewer_role
    repo.get_user_by_username = AsyncMock(return_value=None)
    repo.get_user_by_email = AsyncMock(return_value=None)
    repo.get_user_by_phone = AsyncMock(return_value=None)
    repo.create_user = AsyncMock(
        return_value=User(
            id=1,
            username="reguser",
            email="reg@e.com",
            password_hash="hashed",
            role_id=viewer_role.id,
            status=1,
        )
    )

    service = UserService(repo)
    await service.register_user(
        username="reguser",
        email="reg@e.com",
        password="Secure@123",
    )

    # 无论外部是否尝试传入角色，register_user 内部都写 viewer
    role_code_used = repo.get_role_by_code.call_args[0][0]
    assert role_code_used == "viewer"
