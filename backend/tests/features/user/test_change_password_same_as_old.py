"""change_password 新旧密码相同校验测试。

P3-2 回归：新密码与当前密码相同时必须拒绝（PasswordSameAsOldError），
而不是哈希落库静默成功——改密无进展却提示成功会误导用户。
"""
from unittest.mock import AsyncMock, patch

import pytest
from novamind.features.user.exceptions import PasswordSameAsOldError
from novamind.features.user.models.user import User
from novamind.features.user.repository.user_repository import UserRepository
from novamind.features.user.services.user_service import UserService

pytestmark = pytest.mark.unit


def _make_service(user: User | None) -> tuple[UserService, AsyncMock]:
    repo = AsyncMock(spec=UserRepository)
    repo.get_user_by_id = AsyncMock(return_value=user)
    return UserService(repo), repo


def _make_user() -> User:
    return User(id=1, username="alice", email="a@e.com", password_hash="hashed", status=1)


@pytest.mark.asyncio
async def test_change_password_same_as_old_rejected():
    """新密码 == 当前密码 → 抛 PasswordSameAsOldError，且不落库不清 token"""
    service, repo = _make_service(_make_user())

    with (
        patch(
            "novamind.core.auth.hashing.verify_password_async", AsyncMock(return_value=True)
        ) as mock_verify,
        patch(
            "novamind.core.auth.hashing.get_password_hash_async", AsyncMock(return_value="new-hash")
        ) as mock_hash,
    ):
        with pytest.raises(PasswordSameAsOldError):
            await service.change_password(1, "Same@123", "Same@123")

    # 相同性短路在验密之前即拒绝：不查库、不哈希、不动 repository
    repo.get_user_by_id.assert_not_awaited()
    mock_verify.assert_not_awaited()
    mock_hash.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_password_different_old_succeeds():
    """相邻正常场景：新密码 != 当前密码时不误伤，正常走完改密链路"""
    service, repo = _make_service(_make_user())

    with (
        patch(
            "novamind.core.auth.hashing.verify_password_async", AsyncMock(return_value=True)
        ),
        patch(
            "novamind.core.auth.hashing.get_password_hash_async",
            AsyncMock(return_value="new-hash"),
        ),
        patch.object(UserService, "_set_password_hash", AsyncMock()) as mock_set,
        patch.object(UserService, "_set_must_change_password", AsyncMock()),
        patch(
            "novamind.features.user.services.auth_service.AuthService.blacklist_all_user_tokens",
            AsyncMock(),
        ),
    ):
        ok = await service.change_password(1, "Old@123", "New@456")

    assert ok is True
    mock_set.assert_awaited_once_with(1, "new-hash")
