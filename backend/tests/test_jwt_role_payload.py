"""JWT payload 含 role_code 且 is_admin 派生。"""
import pytest
from novamind.core.auth.token import decode_access_token
from novamind.features.user.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_create_token_pair_payload_has_role_code():
    access, refresh = await AuthService.create_token_pair(
        user_id=1, username="u", email="u@e.com", role_code="admin",
    )
    claims = decode_access_token(access)
    assert claims.role_code == "admin"
    assert claims.is_admin is True


@pytest.mark.asyncio
async def test_create_token_pair_viewer_is_admin_false():
    access, _ = await AuthService.create_token_pair(
        user_id=2, username="v", email="v@e.com", role_code="viewer",
    )
    claims = decode_access_token(access)
    assert claims.is_admin is False
