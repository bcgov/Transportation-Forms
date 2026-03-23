import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import AccessRequest, AuditLog, Role, User, UserRole


def _create_user(db, email: str, *, first_name: str = "Test", last_name: str = "User") -> User:
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


def _create_role(db, name: str, *, is_system: bool = True) -> Role:
    role = Role(
        id=uuid.uuid4(),
        name=name,
        permissions=["form:read"],
        is_system=is_system,
        is_active=True,
    )
    db.add(role)
    db.flush()
    return role


def _assign_role(db, *, user: User, role: Role) -> UserRole:
    user_role = UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id)
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
def context(db):
    admin_user = _create_user(db, "admin.access@example.com", first_name="Admin")
    staff_user = _create_user(db, "staff.access@example.com", first_name="Staff")
    norole_user = _create_user(db, "norole.access@example.com", first_name="NoRole")

    admin_role = _create_role(db, "admin")
    staff_role = _create_role(db, "staff_viewer")
    _assign_role(db, user=admin_user, role=admin_role)
    _assign_role(db, user=staff_user, role=staff_role)

    yield {
        "admin_user": admin_user,
        "staff_user": staff_user,
        "norole_user": norole_user,
    }

    app.dependency_overrides.clear()


class TestAccessRequestsApi:
    @pytest.mark.integration
    def test_norole_user_can_submit_request(self, db, context):
        client = _client_for(db, user=context["norole_user"], roles=[])

        response = client.post("/api/v1/access-requests")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["user_id"] == str(context["norole_user"].id)

    @pytest.mark.integration
    def test_duplicate_pending_request_returns_409(self, db, context):
        client = _client_for(db, user=context["norole_user"], roles=[])

        first = client.post("/api/v1/access-requests")
        assert first.status_code == 201

        second = client.post("/api/v1/access-requests")
        assert second.status_code == 409

    @pytest.mark.integration
    def test_user_with_existing_roles_cannot_submit(self, db, context):
        client = _client_for(db, user=context["staff_user"], roles=["staff_viewer"])

        response = client.post("/api/v1/access-requests")

        assert response.status_code == 400
        assert "already has portal role" in response.json()["detail"].lower()

    @pytest.mark.integration
    def test_non_admin_blocked_from_admin_endpoints(self, db, context):
        client = _client_for(db, user=context["staff_user"], roles=["staff_viewer"])

        response = client.get("/api/v1/admin/access-requests")

        assert response.status_code == 403

    @pytest.mark.integration
    def test_admin_can_list_and_approve_request(self, db, context):
        submitter_client = _client_for(db, user=context["norole_user"], roles=[])
        create = submitter_client.post("/api/v1/access-requests")
        request_id = create.json()["id"]

        admin_client = _client_for(db, user=context["admin_user"], roles=["admin"])

        list_resp = admin_client.get("/api/v1/admin/access-requests?status=pending")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] >= 1

        approve_resp = admin_client.post(
            f"/api/v1/admin/access-requests/{request_id}/approve",
            json={"review_notes": "Approved by admin"},
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        db_request = db.query(AccessRequest).filter(AccessRequest.id == uuid.UUID(request_id)).first()
        assert db_request is not None
        assert db_request.status == "approved"
        assert db_request.processed_by_id == context["admin_user"].id

    @pytest.mark.integration
    def test_admin_can_reject_request(self, db, context):
        submitter_client = _client_for(db, user=context["norole_user"], roles=[])
        create = submitter_client.post("/api/v1/access-requests")
        request_id = create.json()["id"]

        admin_client = _client_for(db, user=context["admin_user"], roles=["admin"])
        reject_resp = admin_client.post(
            f"/api/v1/admin/access-requests/{request_id}/reject",
            json={"review_notes": "Insufficient justification"},
        )

        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "rejected"

    @pytest.mark.integration
    def test_me_returns_latest_request_status(self, db, context):
        client = _client_for(db, user=context["norole_user"], roles=[])
        create = client.post("/api/v1/access-requests")
        assert create.status_code == 201

        me_resp = client.get("/api/v1/access-requests/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["status"] == "pending"

    @pytest.mark.integration
    def test_audit_logs_written_for_submit_approve_reject(self, db, context):
        user_a = _create_user(db, "audit-a@example.com")
        user_b = _create_user(db, "audit-b@example.com")

        submit_a = _client_for(db, user=user_a, roles=[]).post("/api/v1/access-requests").json()["id"]
        submit_b = _client_for(db, user=user_b, roles=[]).post("/api/v1/access-requests").json()["id"]

        _client_for(db, user=context["admin_user"], roles=["admin"]).post(
            f"/api/v1/admin/access-requests/{submit_a}/approve",
            json={"review_notes": "ok"},
        )
        _client_for(db, user=context["admin_user"], roles=["admin"]).post(
            f"/api/v1/admin/access-requests/{submit_b}/reject",
            json={"review_notes": "no"},
        )

        actions = {
            row.action
            for row in db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "access_requests",
                AuditLog.entity_id.in_([submit_a, submit_b]),
            )
            .all()
        }
        assert "SUBMIT" in actions
        assert "APPROVE" in actions
        assert "REJECT" in actions
