import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import AuditLog, Role, User, UserRole


def _create_user(db, email: str, *, first_name: str = "Test", last_name: str = "User", keycloak_id: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        first_name=first_name,
        last_name=last_name,
        keycloak_id=keycloak_id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _create_role(db, name: str, *, is_system: bool = False, permissions: list[str] | None = None) -> Role:
    role = Role(
        id=uuid.uuid4(),
        name=name,
        description=f"{name} role",
        permissions=permissions or ["form:read"],
        is_system=is_system,
        is_active=True,
    )
    db.add(role)
    db.flush()
    return role


def _assign_role(db, *, user: User, role: Role, assigned_by: User | None = None) -> UserRole:
    user_role = UserRole(
        id=uuid.uuid4(),
        user_id=user.id,
        role_id=role.id,
        assigned_by_id=assigned_by.id if assigned_by else None,
    )
    db.add(user_role)
    db.flush()
    return user_role


def _client_for(db, *, user: User, roles: list[str]) -> TestClient:
    token = TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name or ''} {user.last_name or ''}".strip(),
        roles=roles,
        token_type="access",
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    return TestClient(app)


@pytest.fixture()
def admin_users_context(db):
    admin_user = _create_user(db, "admin.users@example.com", first_name="Admin", keycloak_id="kc-admin")
    non_admin_user = _create_user(db, "staff.users@example.com", first_name="Staff", keycloak_id="kc-staff")
    target_user = _create_user(db, "target.users@example.com", first_name="Target", last_name="Person", keycloak_id="kc-target")

    admin_role = _create_role(db, "admin", is_system=True, permissions=["admin:all"])
    viewer_role = _create_role(db, "staff_viewer", is_system=True, permissions=["form:read"])
    reviewer_role = _create_role(db, "reviewer", is_system=True, permissions=["form:review"])

    _assign_role(db, user=admin_user, role=admin_role)
    _assign_role(db, user=non_admin_user, role=viewer_role)
    _assign_role(db, user=target_user, role=viewer_role, assigned_by=admin_user)

    yield {
        "admin_user": admin_user,
        "non_admin_user": non_admin_user,
        "target_user": target_user,
        "admin_role": admin_role,
        "viewer_role": viewer_role,
        "reviewer_role": reviewer_role,
    }

    app.dependency_overrides.clear()


class TestAdminUsersApi:
    @pytest.mark.integration
    def test_non_admin_cannot_access_admin_users_endpoints(self, db, admin_users_context):
        client = _client_for(db, user=admin_users_context["non_admin_user"], roles=["staff_viewer"])

        response = client.get("/api/v1/admin/users")

        assert response.status_code == 403
        assert "Admin role required" in response.json()["detail"]

    @pytest.mark.integration
    def test_admin_can_list_users_with_keycloak_and_roles(self, db, admin_users_context):
        client = _client_for(db, user=admin_users_context["admin_user"], roles=["admin"])

        response = client.get("/api/v1/admin/users?q=target")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert len(body["items"]) >= 1
        target = next(item for item in body["items"] if item["email"] == "target.users@example.com")
        assert target["keycloak_id"] == "kc-target"
        assert any(role["name"] == "staff_viewer" for role in target["roles"])

    @pytest.mark.integration
    def test_admin_can_get_user_detail_including_first_sign_in_and_roles(self, db, admin_users_context):
        target_user = admin_users_context["target_user"]
        client = _client_for(db, user=admin_users_context["admin_user"], roles=["admin"])

        response = client.get(f"/api/v1/admin/users/{target_user.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "target.users@example.com"
        assert body["first_name"] == "Target"
        assert body["last_name"] == "Person"
        assert body["first_sign_in_at"]
        assert any(role["name"] == "staff_viewer" for role in body["roles"])

    @pytest.mark.integration
    def test_admin_can_assign_and_unassign_roles_for_user(self, db, admin_users_context):
        target_user = admin_users_context["target_user"]
        reviewer_role = admin_users_context["reviewer_role"]
        client = _client_for(db, user=admin_users_context["admin_user"], roles=["admin"])

        assign_response = client.put(
            f"/api/v1/admin/users/{target_user.id}/roles",
            json={"role_ids": [str(reviewer_role.id)]},
        )

        assert assign_response.status_code == 200
        assigned_roles = {role["name"] for role in assign_response.json()["roles"]}
        assert assigned_roles == {"reviewer"}

        clear_response = client.put(
            f"/api/v1/admin/users/{target_user.id}/roles",
            json={"role_ids": []},
        )

        assert clear_response.status_code == 200
        assert clear_response.json()["roles"] == []

        audit_rows = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "users",
                AuditLog.entity_id == str(target_user.id),
                AuditLog.action == "UPDATE_ROLES",
            )
            .all()
        )
        assert len(audit_rows) >= 2

    @pytest.mark.integration
    def test_update_roles_rejects_invalid_role_id(self, db, admin_users_context):
        target_user = admin_users_context["target_user"]
        client = _client_for(db, user=admin_users_context["admin_user"], roles=["admin"])

        response = client.put(
            f"/api/v1/admin/users/{target_user.id}/roles",
            json={"role_ids": [str(uuid.uuid4())]},
        )

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()
