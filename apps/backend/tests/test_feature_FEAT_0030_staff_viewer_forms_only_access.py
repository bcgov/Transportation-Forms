"""Focused RBAC tests for FEAT-0030 US-007."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import DEFAULT_ROLES, Permission
from backend.database import get_db
from backend.main import app
from backend.models import Form, Role, UserRole


def _permission_values(role_name: str) -> set[str]:
    return {str(permission.value) for permission in DEFAULT_ROLES[role_name]["permissions"]}


def test_seeded_portal_navigation_assignments() -> None:
    """AC2: all seeded portal roles except Staff Viewer receive navigation."""
    permission = Permission.PORTAL_NAVIGATION.value

    for role_name in ("admin", "staff_manager", "reviewer", "content_editor"):
        assert permission in _permission_values(role_name)

    assert permission not in _permission_values("staff_viewer")


def test_staff_viewer_has_no_reservation_permissions() -> None:
    """AC13: Staff Viewer retains no reservation capability."""
    permissions = _permission_values("staff_viewer")

    assert not {permission for permission in permissions if permission.startswith("reservation:")}
    assert permissions == {"form:read", "business_area:read", "category:read"}


def test_permission_migration_backfills_only_existing_active_custom_roles(
    db, monkeypatch
) -> None:
    """AC2 and AC13: rollout updates persisted roles once and is reversible."""
    original_permissions = {
        "admin": [],
        "staff_manager": [],
        "reviewer": [],
        "content_editor": [],
        "staff_viewer": [
            "form:read",
            "reservation:create",
            "reservation:admin",
        ],
        " Staff_Viewer ": {
            "form:read": True,
            "portal:navigation": True,
            "reservation:approve": True,
        },
        "existing_custom": {"form:read": True},
        "inactive_custom": ["form:read"],
    }
    roles = {
        name: Role(
            id=uuid.uuid4(),
            name=name,
            permissions=permissions,
            is_system=is_system,
            is_active=is_active,
        )
        for name, permissions, is_system, is_active in (
            ("admin", original_permissions["admin"], True, True),
            ("staff_manager", original_permissions["staff_manager"], True, True),
            ("reviewer", original_permissions["reviewer"], True, True),
            ("content_editor", original_permissions["content_editor"], True, True),
            ("staff_viewer", original_permissions["staff_viewer"], True, True),
            (" Staff_Viewer ", original_permissions[" Staff_Viewer "], False, True),
            ("existing_custom", original_permissions["existing_custom"], False, True),
            ("inactive_custom", original_permissions["inactive_custom"], False, False),
        )
    }
    db.add_all(roles.values())
    db.flush()

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "022_feat_0030_staff_viewer_forms_only_access.py"
    )
    spec = importlib.util.spec_from_file_location("feat_0030_us_007_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration.op, "execute", lambda sql: db.execute(text(sql)))

    migration.upgrade()
    migration.upgrade()
    db.flush()
    for role in roles.values():
        db.refresh(role)

    for role_name in ("admin", "staff_manager", "reviewer", "content_editor"):
        assert roles[role_name].permissions == ["portal:navigation"]
    assert roles["existing_custom"].permissions == ["form:read", "portal:navigation"]
    assert roles["inactive_custom"].permissions == ["form:read"]
    assert roles["staff_viewer"].permissions == ["form:read"]
    assert roles[" Staff_Viewer "].permissions == ["form:read"]

    future_custom = Role(
        id=uuid.uuid4(),
        name="future_custom",
        permissions=["form:read"],
        is_system=False,
        is_active=True,
    )
    db.add(future_custom)
    db.flush()
    assert future_custom.permissions == ["form:read"]

    migration.downgrade()
    db.flush()
    for role in roles.values():
        db.refresh(role)

    for role_name, permissions in original_permissions.items():
        assert roles[role_name].permissions == permissions


def _client_with_permissions(
    db, user_factory, permissions: list[str], role_name: str | None = None
) -> TestClient:
    user = user_factory()
    role = Role(
        id=uuid.uuid4(),
        name=role_name or f"custom_{uuid.uuid4().hex}",
        permissions=permissions,
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()

    token = TokenData(
        sub=str(user.id),
        email=str(user.email),
        name="US-007 Test User",
        roles=[str(role.name)],
        token_type="access",
        permissions=permissions,
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


_RESERVATION_ID = "11111111-1111-4111-8111-111111111111"

_DENIED_REQUESTS = (
    ("post", "/api/v1/reservations/generate", {"prefix_id": _RESERVATION_ID}),
    (
        "post",
        "/api/v1/reservations/custom",
        {"prefix_id": _RESERVATION_ID, "form_number": "1", "reason": "test"},
    ),
    ("post", f"/api/v1/reservations/{_RESERVATION_ID}/submit", None),
    ("get", "/api/v1/reservations/pending", None),
    ("post", f"/api/v1/reservations/{_RESERVATION_ID}/approve", None),
    (
        "post",
        f"/api/v1/reservations/{_RESERVATION_ID}/reject",
        {"reason": "test"},
    ),
    (
        "post",
        f"/api/v1/reservations/{_RESERVATION_ID}/request-changes",
        {"comments": "test"},
    ),
    ("post", f"/api/v1/reservations/{_RESERVATION_ID}/resubmit", None),
    ("post", f"/api/v1/reservations/{_RESERVATION_ID}/release", None),
    ("get", "/api/v1/reservations/expiring", None),
    ("post", "/api/v1/reservations/expire", None),
    ("get", "/api/v1/reservations/my", None),
    ("get", "/api/v1/reservations", None),
    ("get", "/api/v1/reservations/approved-unused", None),
    ("get", f"/api/v1/reservations/{_RESERVATION_ID}", None),
)


@pytest.mark.parametrize(("method", "path", "json_body"), _DENIED_REQUESTS)
def test_reservation_endpoints_deny_without_matching_permission(
    db, user_factory, method: str, path: str, json_body: dict | None
) -> None:
    """AC14-AC15: authentication alone cannot reach reservation data or actions."""
    client = _client_with_permissions(db, user_factory, [])

    response = client.request(method, path, json=json_body)

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions for this action"}


_ALLOWED_ACTION_REQUESTS = (
    ("reservation:create", "post", "/api/v1/reservations/generate", {"prefix_id": _RESERVATION_ID}),
    ("reservation:submit", "post", f"/api/v1/reservations/{_RESERVATION_ID}/submit", None),
    ("reservation:approve", "post", f"/api/v1/reservations/{_RESERVATION_ID}/approve", None),
    (
        "reservation:reject",
        "post",
        f"/api/v1/reservations/{_RESERVATION_ID}/reject",
        {"reason": "test"},
    ),
    (
        "reservation:request_changes",
        "post",
        f"/api/v1/reservations/{_RESERVATION_ID}/request-changes",
        {"comments": "test"},
    ),
    ("reservation:release", "post", f"/api/v1/reservations/{_RESERVATION_ID}/release", None),
    ("reservation:admin", "get", "/api/v1/reservations/expiring", None),
    ("reservation:read", "get", "/api/v1/reservations/my", None),
)


@pytest.mark.parametrize(
    ("permission", "method", "path", "json_body"), _ALLOWED_ACTION_REQUESTS
)
def test_custom_role_reaches_only_matching_reservation_action(
    db,
    user_factory,
    permission: str,
    method: str,
    path: str,
    json_body: dict | None,
) -> None:
    """AC15: a custom role is authorized by permission rather than role name."""
    client = _client_with_permissions(db, user_factory, [permission])

    allowed_response = client.request(method, path, json=json_body)
    unrelated_response = client.get("/api/v1/reservations/my")

    assert allowed_response.status_code != 403
    if permission != "reservation:read":
        assert unrelated_response.status_code == 403


@pytest.mark.parametrize("role_name", ("staff_viewer", "STAFF_VIEWER", "Staff_Viewer"))
def test_staff_viewer_only_receives_published_forms(
    db, user_factory, role_name: str
) -> None:
    """AC1 and AC8: role-name case does not weaken Published-only visibility."""
    client = _client_with_permissions(
        db, user_factory, ["form:read"], role_name=role_name
    )
    user_id = uuid.UUID(app.dependency_overrides[get_current_user]().sub)
    published = Form(
        id=uuid.uuid4(),
        title="Published Needle",
        description="Visible",
        status="published",
        is_public=True,
        keywords=[],
        created_by_id=user_id,
        collects_personal_info="No",
    )
    draft = Form(
        id=uuid.uuid4(),
        title="Draft Needle",
        description="Hidden",
        status="draft",
        is_public=False,
        keywords=[],
        created_by_id=user_id,
        form_source="Download",
        form_attachment_url="uploads/draft.pdf",
        form_attachment_filename="draft.pdf",
        file_type="pdf",
        collects_personal_info="No",
    )
    db.add_all([published, draft])
    db.flush()

    list_response = client.get(
        "/api/v1/forms", params=[("status", "draft"), ("limit", "24")]
    )
    autocomplete_response = client.get(
        "/api/v1/forms/autocomplete", params={"q": "Needle"}
    )
    published_response = client.get(f"/api/v1/forms/{published.id}")
    draft_response = client.get(f"/api/v1/forms/{draft.id}")
    draft_download_response = client.get(f"/api/v1/forms/{draft.id}/file")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [str(published.id)]
    assert autocomplete_response.status_code == 200
    assert autocomplete_response.json()["suggestions"] == ["Published Needle"]
    assert published_response.status_code == 200
    assert draft_response.status_code == 404
    assert draft_download_response.status_code == 404