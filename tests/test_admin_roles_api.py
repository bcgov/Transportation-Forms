import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import AuditLog, Role, User, UserRole


def _create_user(db, email: str, first_name: str, last_name: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _create_role(
    db,
    *,
    name: str,
    permissions: list[str] | None = None,
    is_system: bool = False,
) -> Role:
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
def admin_role_api_context(db):
    admin_user = _create_user(db, "admin.roles@example.com", "Admin", "User")
    non_admin_user = _create_user(db, "staff.roles@example.com", "Staff", "User")

    admin_role = _create_role(db, name="admin", permissions=["role:create", "role:edit", "role:delete"], is_system=True)
    staff_role = _create_role(db, name="staff_viewer", permissions=["form:read"], is_system=True)

    _assign_role(db, user=admin_user, role=admin_role)
    _assign_role(db, user=non_admin_user, role=staff_role)

    yield {
        "admin_user": admin_user,
        "non_admin_user": non_admin_user,
    }

    app.dependency_overrides.clear()


class TestAdminRoleManagementApi:
    @pytest.mark.integration
    def test_non_admin_cannot_access_admin_role_endpoints(self, db, admin_role_api_context):
        client = _client_for(
            db,
            user=admin_role_api_context["non_admin_user"],
            roles=["staff_viewer"],
        )

        response = client.get("/api/v1/admin/roles")

        assert response.status_code == 403
        assert "Admin role required" in response.json()["detail"]

    @pytest.mark.integration
    def test_admin_can_create_custom_role_and_audit_is_written(self, db, admin_role_api_context):
        client = _client_for(
            db,
            user=admin_role_api_context["admin_user"],
            roles=["admin"],
        )

        response = client.post(
            "/api/v1/admin/roles",
            json={
                "name": "content_editor",
                "description": "Can edit and publish forms",
                "permissions": ["form:read", "form:edit", "form:publish"],
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "content_editor"
        assert body["is_system"] is False
        assert sorted(body["permissions"]) == ["form:edit", "form:publish", "form:read"]

        role = db.query(Role).filter(Role.name == "content_editor", Role.deleted_at.is_(None)).first()
        assert role is not None

        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "roles",
                AuditLog.entity_id == str(role.id),
                AuditLog.action == "CREATE",
            )
            .first()
        )
        assert audit is not None

    @pytest.mark.integration
    def test_duplicate_custom_role_returns_409(self, db, admin_role_api_context):
        client = _client_for(
            db,
            user=admin_role_api_context["admin_user"],
            roles=["admin"],
        )

        first = client.post(
            "/api/v1/admin/roles",
            json={"name": "analyst", "description": "Analyst", "permissions": ["form:read"]},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/v1/admin/roles",
            json={"name": "analyst", "description": "Duplicate", "permissions": ["form:read"]},
        )

        assert second.status_code == 409

    @pytest.mark.integration
    def test_role_detail_returns_assigned_users(self, db, admin_role_api_context):
        admin_user = admin_role_api_context["admin_user"]
        member = _create_user(db, "member@example.com", "Member", "User")
        custom_role = _create_role(db, name="workflow_owner", permissions=["form:read", "form:edit"])
        _assign_role(db, user=member, role=custom_role, assigned_by=admin_user)

        client = _client_for(db, user=admin_user, roles=["admin"])
        response = client.get(f"/api/v1/admin/roles/{custom_role.id}")

        assert response.status_code == 200
        users = response.json()["users"]
        assert len(users) == 1
        assert users[0]["email"] == "member@example.com"

    @pytest.mark.integration
    def test_system_role_editable_but_not_deletable(self, db, admin_role_api_context):
        admin_user = admin_role_api_context["admin_user"]
        system_role = _create_role(
            db,
            name="reviewer",
            permissions=["form:read", "form:review"],
            is_system=True,
        )

        client = _client_for(db, user=admin_user, roles=["admin"])

        update_resp = client.put(
            f"/api/v1/admin/roles/{system_role.id}",
            json={
                "name": "reviewer",
                "description": "Updated reviewer role",
                "permissions": ["form:read", "form:review", "form:approve"],
            },
        )
        assert update_resp.status_code == 200
        assert "form:approve" in update_resp.json()["permissions"]

        delete_resp = client.delete(f"/api/v1/admin/roles/{system_role.id}")
        assert delete_resp.status_code == 409
        assert "cannot be deleted" in delete_resp.json()["detail"].lower()

        permission_audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "roles",
                AuditLog.entity_id == str(system_role.id),
                AuditLog.action == "UPDATE_PERMISSIONS",
            )
            .first()
        )
        assert permission_audit is not None

    @pytest.mark.integration
    def test_custom_role_can_be_deleted(self, db, admin_role_api_context):
        admin_user = admin_role_api_context["admin_user"]
        custom_role = _create_role(db, name="temporary_role", permissions=["form:read"])
        member = _create_user(db, "temp.member@example.com", "Temp", "Member")
        membership = _assign_role(db, user=member, role=custom_role)

        client = _client_for(db, user=admin_user, roles=["admin"])

        response = client.delete(f"/api/v1/admin/roles/{custom_role.id}")

        assert response.status_code == 200
        assert response.json()["id"] == str(custom_role.id)

        deleted_role = db.query(Role).filter(Role.id == custom_role.id).first()
        deleted_membership = db.query(UserRole).filter(UserRole.id == membership.id).first()
        assert deleted_role is not None
        assert deleted_role.deleted_at is not None
        assert deleted_membership is not None
        assert deleted_membership.deleted_at is not None

    @pytest.mark.integration
    def test_get_missing_role_returns_404(self, db, admin_role_api_context):
        client = _client_for(
            db,
            user=admin_role_api_context["admin_user"],
            roles=["admin"],
        )

        response = client.get(f"/api/v1/admin/roles/{uuid.uuid4()}")

        assert response.status_code == 404
