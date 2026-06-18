"""Tests for FEAT-0025 Business Areas Admin list endpoint.

The runtime permission check (``require_permission``) reads role
permissions from the database — not from the JWT — so the shared
``admin_user`` fixture (which creates an ``admin`` role with an empty
permission set) is insufficient. We seed the admin role with the
``business_area:*`` permissions explicitly, mirroring the pattern used
by ``test_feature_FEAT_0025_business_areas_admin_delete.py``.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import Permission
from backend.database import get_db
from backend.main import app as fastapi_app
from backend.models import Role, User, UserRole


def _token_for(user: User) -> TokenData:
    return TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        roles=["admin"],
        token_type="access",
    )


@pytest.fixture()
def _ba_admin_user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"ba-admin-{uuid.uuid4().hex[:8]}@example.com",
        first_name="BA",
        last_name="Admin",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def admin_api_client(db, _ba_admin_user):
    """TestClient whose user holds the BA permissions in the DB role
    (the runtime permission check uses DB roles, not the JWT)."""
    role = Role(
        id=uuid.uuid4(),
        name="admin",
        description="admin role for FEAT-0025 list test",
        permissions=[
            Permission.BUSINESS_AREA_READ.value,
            Permission.BUSINESS_AREA_MANAGE.value,
        ],
        is_system=True,
        is_active=True,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(id=uuid.uuid4(), user_id=_ba_admin_user.id, role_id=role.id))
    db.flush()

    fastapi_app.dependency_overrides[get_db] = lambda: db
    fastapi_app.dependency_overrides[get_current_user] = lambda: _token_for(
        _ba_admin_user
    )
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_list_business_areas_admin_returns_200_and_list(admin_api_client):
    """A user with ``business_area:manage`` MUST get 200 + a JSON list.

    Permitting 403 here would mask permission-wiring regressions.
    """
    response = admin_api_client.get("/api/v1/admin/business-areas")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)

