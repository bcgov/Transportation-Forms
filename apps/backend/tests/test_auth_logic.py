import pytest
from unittest.mock import MagicMock
from backend.auth.authorization import (
    is_admin,
    require_permission,
    require_any_permission,
    require_all_permissions,
    get_user_permissions,
    has_permission,
    has_any_permission,
    has_all_permissions,
    check_resource_permission,
    log_permission_check,
)
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import Permission


def _token(roles):
    return TokenData(
        sub="123e4567-e89b-12d3-a456-426614174000",
        email="test@example.com",
        name="Test User",
        roles=roles,
        token_type="access",
    )


def _empty_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.all.return_value = []
    return db


def _db_with_permission(perm: str):
    db = MagicMock()
    mock_user = MagicMock()
    mock_role = MagicMock()
    mock_role.is_active = True
    mock_role.deleted_at = None
    mock_role.permissions = [perm]
    mock_ur = MagicMock()
    mock_ur.role = mock_role
    db.query.return_value.filter.return_value.first.return_value = mock_user
    db.query.return_value.filter.return_value.all.return_value = [mock_ur]
    return db


class TestAuthLogic:
    @pytest.mark.asyncio
    async def test_is_admin_fast_path(self):
        db = _empty_db()
        assert await is_admin(_token(["admin"]), db) is True

    @pytest.mark.asyncio
    async def test_is_admin_no_admin_role(self):
        db = _empty_db()
        assert await is_admin(_token(["staff"]), db) is False

    @pytest.mark.asyncio
    async def test_is_admin_db_fallback_finds_admin_role(self):
        db = MagicMock()
        mock_ur = MagicMock()
        mock_ur.role = MagicMock()
        mock_ur.role.name = "admin"
        mock_ur.role.is_active = True
        db.query.return_value.filter.return_value.all.return_value = [mock_ur]
        assert await is_admin(_token(["reviewer"]), db) is True

    def test_require_permission_returns_callable(self):
        assert callable(require_permission("forms", "read"))

    def test_require_permission_unknown_resource_returns_callable(self):
        assert callable(require_permission("unknown_resource", "unknown_action"))

    def test_require_any_permission_returns_callable(self):
        assert callable(require_any_permission("form:read", "form:create"))

    def test_require_all_permissions_returns_callable(self):
        assert callable(require_all_permissions("form:read", "form:create"))

    @pytest.mark.asyncio
    async def test_get_user_permissions_no_user(self):
        db = _empty_db()
        perms = await get_user_permissions("nonexistent-id", db)
        assert perms == set()

    @pytest.mark.asyncio
    async def test_get_user_permissions_list(self):
        db = _db_with_permission("form:read")
        perms = await get_user_permissions("some-id", db)
        assert "form:read" in perms

    @pytest.mark.asyncio
    async def test_get_user_permissions_dict(self):
        db = MagicMock()
        mock_user = MagicMock()
        mock_role = MagicMock()
        mock_role.is_active = True
        mock_role.deleted_at = None
        mock_role.permissions = {"form:read": True}
        mock_ur = MagicMock()
        mock_ur.role = mock_role
        db.query.return_value.filter.return_value.first.return_value = mock_user
        db.query.return_value.filter.return_value.all.return_value = [mock_ur]
        perms = await get_user_permissions("some-id", db)
        assert "form:read" in perms

    @pytest.mark.asyncio
    async def test_has_permission_true(self):
        db = _db_with_permission("form:read")
        assert await has_permission("some-id", "form:read", db) is True

    @pytest.mark.asyncio
    async def test_has_permission_false_no_user(self):
        db = _empty_db()
        assert await has_permission("nonexistent", "form:read", db) is False

    @pytest.mark.asyncio
    async def test_has_any_permission_true(self):
        db = _db_with_permission("form:read")
        assert await has_any_permission("id", ["form:read", "form:create"], db) is True

    @pytest.mark.asyncio
    async def test_has_any_permission_false(self):
        db = _empty_db()
        assert await has_any_permission("id", ["form:read", "form:create"], db) is False

    @pytest.mark.asyncio
    async def test_has_all_permissions_true(self):
        db = _db_with_permission("form:read")
        assert await has_all_permissions("id", ["form:read"], db) is True

    @pytest.mark.asyncio
    async def test_has_all_permissions_false(self):
        db = _empty_db()
        assert await has_all_permissions("id", ["form:read"], db) is False

    @pytest.mark.asyncio
    async def test_check_resource_permission_known(self):
        db = _db_with_permission("form:read")
        result = await check_resource_permission("id", "forms", "read", db)
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_check_resource_permission_unknown_returns_false(self):
        db = _empty_db()
        result = await check_resource_permission("id", "unknown_res", "unknown_act", db)
        assert result is False

    @pytest.mark.asyncio
    async def test_log_permission_check_no_db(self):
        await log_permission_check("user-id", "form:read", allowed=True, db=None)

    @pytest.mark.asyncio
    async def test_log_permission_check_allowed_non_sensitive_skips_log(self):
        db = _empty_db()
        await log_permission_check("user-id", "form:read", allowed=True, db=db)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_log_permission_check_denied_writes_audit(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()
        await log_permission_check(
            "user-id", "form:read", allowed=False,
            resource="forms", action="read", db=db,
        )
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_permission_check_sensitive_writes_audit_when_allowed(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()
        await log_permission_check(
            "user-id", Permission.ROLE_CREATE, allowed=True, db=db,
        )
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_permission_check_no_user_skips(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        await log_permission_check("bad-user", "form:read", allowed=False, db=db)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_log_permission_check_db_exception_swallowed(self):
        db = MagicMock()
        db.query.side_effect = Exception("db error")
        await log_permission_check("user-id", "form:read", allowed=False, db=db)

