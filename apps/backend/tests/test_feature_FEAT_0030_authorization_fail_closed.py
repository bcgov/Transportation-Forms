"""Fail-closed authorization tests for FEAT-0030 US-007."""

from datetime import datetime, timezone
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import Form, Role, UserRole


def _assign_role(db, user, name: str, permissions) -> Role:
    role = Role(
        id=uuid.uuid4(),
        name=name,
        permissions=permissions,
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()
    return role


def _client(db, user, *, token_roles=None, token_permissions=None) -> TestClient:
    token = TokenData(
        sub=str(user.id),
        email=str(user.email),
        name="FEAT-0030 Authorization Test",
        roles=token_roles if token_roles is not None else [],
        token_type="access",
        permissions=token_permissions if token_permissions is not None else [],
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_live_staff_viewer_role_overrides_stale_admin_claims(db, user_factory) -> None:
    user = user_factory(email="stale-claims-feat0030@example.com")
    _assign_role(db, user, "Staff_Viewer", ["form:read"])
    published = Form(
        id=uuid.uuid4(),
        title="Published from live role",
        description="Visible",
        status="published",
        is_public=True,
        keywords=[],
        created_by_id=user.id,
        collects_personal_info="No",
    )
    draft = Form(
        id=uuid.uuid4(),
        title="Draft hidden despite stale claim",
        description="Hidden",
        status="draft",
        is_public=False,
        keywords=[],
        created_by_id=user.id,
        collects_personal_info="No",
    )
    db.add_all([published, draft])
    db.flush()
    client = _client(
        db,
        user,
        token_roles=["admin"],
        token_permissions=["form:read", "portal:navigation", "reservation:read"],
    )

    forms_response = client.get("/api/v1/forms", params={"limit": 24})
    reservations_response = client.get("/api/v1/reservations/my")

    assert forms_response.status_code == 200
    assert [item["id"] for item in forms_response.json()["items"]] == [
        str(published.id)
    ]
    assert reservations_response.status_code == 403
    assert reservations_response.json() == {
        "detail": "Insufficient permissions for this action"
    }


def test_duplicate_normalized_roles_deny_protected_forms(db, user_factory) -> None:
    user = user_factory(email="duplicate-roles-feat0030@example.com")
    _assign_role(db, user, "staff_viewer", ["form:read"])
    _assign_role(db, user, " Staff_Viewer ", ["form:read"])
    client = _client(db, user, token_roles=["staff_viewer"])

    response = client.get("/api/v1/forms", params={"limit": 24})

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions for this action"}


@pytest.mark.parametrize(
    "permissions",
    (
        ["form:read", "form:read"],
        ["form:read", {"reservation:read": True}],
        "form:read",
    ),
)
def test_malformed_permission_payload_denies_access(
    db, user_factory, permissions
) -> None:
    user = user_factory(email=f"malformed-{uuid.uuid4().hex}@example.com")
    _assign_role(db, user, f"malformed_{uuid.uuid4().hex}", permissions)
    client = _client(db, user, token_permissions=["form:read"])

    response = client.get("/api/v1/forms", params={"limit": 24})

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions for this action"}


@pytest.mark.parametrize("principal_state", ("inactive", "deleted"))
def test_inactive_or_deleted_user_denied(
    db, user_factory, principal_state: str
) -> None:
    user = user_factory(email=f"{principal_state}-feat0030@example.com")
    _assign_role(db, user, f"{principal_state}_{uuid.uuid4().hex}", ["form:read"])
    if principal_state == "inactive":
        user.is_active = False
    else:
        user.deleted_at = datetime.now(timezone.utc)
    db.flush()
    client = _client(db, user, token_permissions=["form:read"])

    response = client.get("/api/v1/forms", params={"limit": 24})

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions for this action"}


def test_malformed_token_subject_denied_without_database_error(db) -> None:
    token = TokenData(
        sub="not-a-uuid",
        email="malformed-subject@example.com",
        name="Malformed Subject",
        roles=["staff_viewer"],
        token_type="access",
        permissions=["form:read"],
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/forms", params={"limit": 24})

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permissions for this action"}