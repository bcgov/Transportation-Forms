"""Tests for FEAT-0012: Form Number Prefix granular permissions.

Test cases TC1.1–TC1.5 verify that the five new prefix permissions
(create, read, update, delete, archive) are properly catalogued,
assigned to the admin role by default, excluded from non-admin roles,
and enforced at the API layer.
"""

import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import (
    DEFAULT_ROLES,
    Permission,
    RESOURCE_ACTION_PERMISSIONS,
)
from backend.database import get_db
from backend.main import app as fastapi_app
from backend.models import User, UserRole


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PREFIX_PERMISSIONS = [
    Permission.FORM_NUMBER_PREFIX_CREATE,
    Permission.FORM_NUMBER_PREFIX_READ,
    Permission.FORM_NUMBER_PREFIX_UPDATE,
    Permission.FORM_NUMBER_PREFIX_DELETE,
    Permission.FORM_NUMBER_PREFIX_ARCHIVE,
]

PREFIX_PERMISSION_VALUES = {p.value for p in PREFIX_PERMISSIONS}

NON_ADMIN_ROLES = ["staff_manager", "reviewer", "staff_viewer"]

ADMIN_PREFIX_BASE = "/api/v1/admin/prefixes"

# A fake UUID used as a path parameter for single-resource endpoints.
_FAKE_ID = "00000000-0000-4000-8000-000000000099"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_permission_client(
    db,
    user: User,
    *,
    roles_label: str = "custom",
) -> TestClient:
    """Return a TestClient whose auth is pinned to *user*.

    The user's actual DB permissions (via UserRole → Role) are what
    ``require_permission`` checks; this helper merely satisfies the
    ``get_current_user`` dependency so that the request is authenticated.
    """

    def _get_user(request: Request) -> TokenData:
        return TokenData(
            sub=str(user.id),
            email=str(user.email),
            name=f"{user.first_name} {user.last_name}",
            roles=[roles_label],
            token_type="access",
        )

    fastapi_app.dependency_overrides[get_db] = lambda: db
    fastapi_app.dependency_overrides[get_current_user] = _get_user
    return TestClient(fastapi_app)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFeat0012PrefixPermissions:
    """TC1.1–TC1.5 for FEAT-0012 Form Number Prefix permissions."""

    # -- TC1.1 ---------------------------------------------------------------

    def test_tc1_1_permission_catalog_includes_prefix_permissions(self):
        """TC1.1: All 5 prefix permissions exist in Permission enum and
        in RESOURCE_ACTION_PERMISSIONS['form_number_prefixes'].
        """
        # Arrange
        expected_actions = {
            "create": Permission.FORM_NUMBER_PREFIX_CREATE,
            "read": Permission.FORM_NUMBER_PREFIX_READ,
            "update": Permission.FORM_NUMBER_PREFIX_UPDATE,
            "delete": Permission.FORM_NUMBER_PREFIX_DELETE,
            "archive": Permission.FORM_NUMBER_PREFIX_ARCHIVE,
        }

        # Act & Assert – enum members exist
        for perm in PREFIX_PERMISSIONS:
            assert perm in Permission, (
                f"{perm!r} missing from Permission enum"
            )

        # Act & Assert – RESOURCE_ACTION_PERMISSIONS mapping
        assert "form_number_prefixes" in RESOURCE_ACTION_PERMISSIONS
        mapping = RESOURCE_ACTION_PERMISSIONS["form_number_prefixes"]
        for action, expected_perm in expected_actions.items():
            assert action in mapping, (
                f"Action '{action}' missing from form_number_prefixes mapping"
            )
            assert mapping[action] == expected_perm

    # -- TC1.2 ---------------------------------------------------------------

    def test_tc1_2_admin_role_receives_prefix_permissions_by_default(self):
        """TC1.2: DEFAULT_ROLES['admin']['permissions'] contains all 5
        prefix permissions.
        """
        # Arrange
        admin_perms = DEFAULT_ROLES["admin"]["permissions"]
        admin_perm_values = {
            p.value if hasattr(p, "value") else str(p)
            for p in admin_perms
        }

        # Act & Assert
        for perm in PREFIX_PERMISSIONS:
            assert perm.value in admin_perm_values, (
                f"{perm.value} not in admin default permissions"
            )

    # -- TC1.3 ---------------------------------------------------------------

    def test_tc1_3_non_admin_roles_lack_prefix_permissions(self):
        """TC1.3: staff_manager, reviewer, and staff_viewer roles do NOT
        have any prefix permission.
        """
        for role_name in NON_ADMIN_ROLES:
            # Arrange
            assert role_name in DEFAULT_ROLES, (
                f"Expected role '{role_name}' in DEFAULT_ROLES"
            )
            role_perms = DEFAULT_ROLES[role_name]["permissions"]
            role_perm_values = {
                p.value if hasattr(p, "value") else str(p)
                for p in role_perms
            }

            # Act & Assert
            overlap = PREFIX_PERMISSION_VALUES & role_perm_values
            assert not overlap, (
                f"Role '{role_name}' unexpectedly has prefix permissions: "
                f"{overlap}"
            )

    # -- TC1.4 ---------------------------------------------------------------

    def test_tc1_4_granular_permission_denies_unassigned_actions(
        self, db, user_factory, role_factory, prefix_factory,
    ):
        """TC1.4: A user with ONLY form_number_prefix:read can list
        prefixes but is denied create, update, delete, and archive.
        """
        # Arrange — create user with a role that has ONLY read permission
        user = user_factory(
            email="readonly-prefix@example.com",
            first_name="ReadOnly",
            last_name="PrefixUser",
        )
        role = role_factory(
            name=f"prefix_reader_{uuid.uuid4().hex[:6]}",
            permissions=[Permission.FORM_NUMBER_PREFIX_READ.value],
        )
        db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
        db.flush()

        # Create a prefix so the list endpoint has data
        pfx = prefix_factory(prefix="Z", created_by=user)

        client = _make_permission_client(db, user)

        try:
            # Act & Assert — READ should succeed
            resp = client.get(ADMIN_PREFIX_BASE)
            assert resp.status_code == 200, (
                f"Expected 200 for list, got {resp.status_code}: {resp.text}"
            )

            # Act & Assert — CREATE should be denied
            resp = client.post(
                ADMIN_PREFIX_BASE,
                json={"prefix": "DENIED", "description": "should fail"},
            )
            assert resp.status_code == 403, (
                f"Expected 403 for create, got {resp.status_code}"
            )

            # Act & Assert — UPDATE should be denied
            resp = client.put(
                f"{ADMIN_PREFIX_BASE}/{pfx.id}",
                json={"description": "should fail"},
            )
            assert resp.status_code == 403, (
                f"Expected 403 for update, got {resp.status_code}"
            )

            # Act & Assert — DELETE should be denied
            resp = client.delete(f"{ADMIN_PREFIX_BASE}/{pfx.id}")
            assert resp.status_code == 403, (
                f"Expected 403 for delete, got {resp.status_code}"
            )

            # Act & Assert — ARCHIVE should be denied
            resp = client.post(f"{ADMIN_PREFIX_BASE}/{pfx.id}/archive")
            assert resp.status_code == 403, (
                f"Expected 403 for archive, got {resp.status_code}"
            )
        finally:
            # Clean up dependency overrides
            fastapi_app.dependency_overrides.pop(get_db, None)
            fastapi_app.dependency_overrides.pop(get_current_user, None)

    # -- TC1.5 ---------------------------------------------------------------

    def test_tc1_5_unpermitted_user_denied_all_endpoints(
        self, db, user_factory, role_factory,
    ):
        """TC1.5: A user with NO prefix permissions is denied (403) on
        every admin prefix endpoint.
        """
        # Arrange — user with a role that has zero prefix permissions
        user = user_factory(
            email="noperm@example.com",
            first_name="NoPerm",
            last_name="User",
        )
        role = role_factory(
            name=f"no_prefix_{uuid.uuid4().hex[:6]}",
            permissions=[Permission.FORM_READ.value],  # unrelated perm
        )
        db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
        db.flush()

        client = _make_permission_client(db, user)

        try:
            endpoints = [
                ("GET", ADMIN_PREFIX_BASE),
                ("GET", f"{ADMIN_PREFIX_BASE}/{_FAKE_ID}"),
                ("POST", ADMIN_PREFIX_BASE),
                ("PUT", f"{ADMIN_PREFIX_BASE}/{_FAKE_ID}"),
                ("DELETE", f"{ADMIN_PREFIX_BASE}/{_FAKE_ID}"),
                ("POST", f"{ADMIN_PREFIX_BASE}/{_FAKE_ID}/archive"),
            ]

            for method, url in endpoints:
                # Act
                kwargs = {}
                if method in ("POST", "PUT"):
                    kwargs["json"] = {"prefix": "X", "description": "test"}
                resp = client.request(method, url, **kwargs)

                # Assert
                assert resp.status_code == 403, (
                    f"Expected 403 for {method} {url}, "
                    f"got {resp.status_code}: {resp.text}"
                )
        finally:
            # Clean up dependency overrides
            fastapi_app.dependency_overrides.pop(get_db, None)
            fastapi_app.dependency_overrides.pop(get_current_user, None)
