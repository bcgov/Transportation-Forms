"""TASK-412 — API endpoint integration tests for reservation routes.

Tests the FastAPI routes with a real TestClient against PostgreSQL,
overriding auth dependencies to simulate different user roles.

Covers:
  - POST /generate, /custom
  - POST /submit, /approve, /reject, /request-changes, /resubmit
  - POST /release
  - GET /my, /, /{id}, /pending, /expiring
  - POST /expire
  - Role-based authorization enforcement (staff, approver, admin)
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session

from backend.database import Base, get_db
from backend.main import app
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.models import (
    FormNumberPrefix,
    FormNumberReservation,
    FormReservationApprover,
    Role,
    User,
    UserRole,
)
from .conftest import TEST_DATABASE_URL, _PG_ADMIN_URL, _TEST_DB_NAME

# ---------------------------------------------------------------------------
# Test DB setup – reuses the same PostgreSQL test database as conftest
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api_engine():
    # Ensure the test database exists (same logic as conftest._test_engine).
    admin_engine = create_engine(_PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": _TEST_DB_NAME},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_TEST_DB_NAME}"'))
    admin_engine.dispose()

    engine = create_engine(TEST_DATABASE_URL, echo=False)
    # Drop views that depend on tables before dropping the tables themselves.
    with engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS public_forms_v CASCADE"))
        conn.commit()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def api_session_factory(api_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=api_engine)


@pytest.fixture()
def api_db(api_session_factory, api_engine):
    connection = api_engine.connect()
    transaction = connection.begin()
    session = api_session_factory(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Users & prefix seed data
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_users(api_db: Session):
    """Create staff, approver, and admin users for API tests."""
    staff = User(
        id=uuid.uuid4(), email="api_staff@example.com",
        first_name="Staff", last_name="API", is_active=True,
    )
    approver = User(
        id=uuid.uuid4(), email="api_approver@example.com",
        first_name="Approver", last_name="API", is_active=True,
    )
    admin = User(
        id=uuid.uuid4(), email="api_admin@example.com",
        first_name="Admin", last_name="API", is_active=True,
    )
    api_db.add_all([staff, approver, admin])

    # Roles
    staff_role = Role(
        id=uuid.uuid4(),
        name="staff",
        permissions=[
            "reservation:create",
            "reservation:read",
            "reservation:submit",
            "reservation:release",
        ],
        is_active=True,
    )
    reviewer_role = Role(
        id=uuid.uuid4(),
        name="reviewer",
        permissions=[
            "reservation:read",
            "reservation:approve",
            "reservation:reject",
            "reservation:request_changes",
            "reservation:release",
        ],
        is_active=True,
    )
    admin_role = Role(
        id=uuid.uuid4(),
        name="admin",
        permissions=[
            "reservation:create",
            "reservation:read",
            "reservation:submit",
            "reservation:approve",
            "reservation:reject",
            "reservation:request_changes",
            "reservation:release",
            "reservation:admin",
        ],
        is_active=True,
    )
    api_db.add_all([staff_role, reviewer_role, admin_role])
    api_db.flush()

    api_db.add(UserRole(id=uuid.uuid4(), user_id=staff.id, role_id=staff_role.id))
    api_db.add(UserRole(id=uuid.uuid4(), user_id=approver.id, role_id=reviewer_role.id))
    api_db.add(UserRole(id=uuid.uuid4(), user_id=admin.id, role_id=admin_role.id))
    api_db.flush()

    return {"staff": staff, "approver": approver, "admin": admin}


@pytest.fixture()
def api_prefix(api_db: Session):
    pfx = FormNumberPrefix(
        id=uuid.uuid4(), prefix="API", current_sequence=0,
        padding_length=4, max_number_length=10,
        is_active=True,
    )
    api_db.add(pfx)
    api_db.flush()
    return pfx


# ---------------------------------------------------------------------------
# TestClient with dependency overrides
# ---------------------------------------------------------------------------

def _make_client(api_db: Session, user: User, roles: list[str]) -> TestClient:
    """Create a TestClient with DB and auth overrides."""
    token = TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        roles=roles,
        token_type="access",
    )
    app.dependency_overrides[get_db] = lambda: api_db
    app.dependency_overrides[get_current_user] = lambda: token
    client = TestClient(app)
    return client


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def staff_client(api_db, api_users) -> TestClient:
    return _make_client(api_db, api_users["staff"], ["staff"])


@pytest.fixture()
def approver_client(api_db, api_users) -> TestClient:
    return _make_client(api_db, api_users["approver"], ["reviewer"])


@pytest.fixture()
def admin_client(api_db, api_users) -> TestClient:
    return _make_client(api_db, api_users["admin"], ["admin"])


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------

class TestAutoGenerateEndpoint:

    @pytest.mark.integration
    def test_generate_success(self, staff_client, api_prefix):
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(api_prefix.id)},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "reserved"
        assert data["full_form_number"] == "API0001"
        assert data["numbering_method"] == "auto_generated"

    @pytest.mark.integration
    def test_generate_invalid_prefix(self, staff_client):
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": "not-a-uuid"},
        )
        assert resp.status_code == 400

    @pytest.mark.integration
    def test_generate_nonexistent_prefix(self, staff_client):
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /custom
# ---------------------------------------------------------------------------

class TestCustomEndpoint:

    @pytest.mark.integration
    def test_custom_success(self, staff_client, api_prefix):
        resp = staff_client.post(
            "/api/v1/reservations/custom",
            json={
                "prefix_id": str(api_prefix.id),
                "form_number": "SPEC1",
                "reason": "Needed for special allocation",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["full_form_number"] == "APISPEC1"
        assert data["numbering_method"] == "custom"

    @pytest.mark.integration
    def test_custom_duplicate_returns_409(self, staff_client, api_prefix):
        staff_client.post(
            "/api/v1/reservations/custom",
            json={"prefix_id": str(api_prefix.id), "form_number": "DUP", "reason": "r"},
        )
        resp = staff_client.post(
            "/api/v1/reservations/custom",
            json={"prefix_id": str(api_prefix.id), "form_number": "DUP", "reason": "r2"},
        )
        assert resp.status_code == 409

    @pytest.mark.integration
    def test_custom_missing_reason(self, staff_client, api_prefix):
        resp = staff_client.post(
            "/api/v1/reservations/custom",
            json={"prefix_id": str(api_prefix.id), "form_number": "X", "reason": ""},
        )
        # Pydantic validation should fail (min_length=1)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Approval Workflow Endpoints
# ---------------------------------------------------------------------------

class TestApprovalWorkflowEndpoints:

    @pytest.mark.integration
    def test_submit_approve_flow(
        self, staff_client, approver_client, api_users, api_prefix
    ):
        staff = api_users["staff"]
        staff_token = TokenData(
            sub=str(staff.id),
            email=staff.email,
            name=f"{staff.first_name} {staff.last_name}",
            roles=["staff"],
            token_type="access",
        )
        app.dependency_overrides[get_current_user] = lambda: staff_token

        # Generate
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(api_prefix.id)},
        )
        assert resp.status_code == 201, resp.text
        res_id = resp.json()["id"]

        # Submit
        resp = staff_client.post(f"/api/v1/reservations/{res_id}/submit")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_approval"

        # Approve
        approver = api_users["approver"]
        approver_token = TokenData(
            sub=str(approver.id),
            email=approver.email,
            name=f"{approver.first_name} {approver.last_name}",
            roles=["reviewer"],
            token_type="access",
        )
        app.dependency_overrides[get_current_user] = lambda: approver_token
        resp = approver_client.post(f"/api/v1/reservations/{res_id}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    @pytest.mark.integration
    def test_reject_requires_approver_role(self, staff_client, api_prefix):
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(api_prefix.id)},
        )
        res_id = resp.json()["id"]
        staff_client.post(f"/api/v1/reservations/{res_id}/submit")

        # Staff try to reject — should fail
        resp = staff_client.post(
            f"/api/v1/reservations/{res_id}/reject",
            json={"reason": "no"},
        )
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_approve_requires_approver_role(self, staff_client, api_prefix):
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(api_prefix.id)},
        )
        res_id = resp.json()["id"]
        staff_client.post(f"/api/v1/reservations/{res_id}/submit")

        # Staff try to approve — should fail
        resp = staff_client.post(f"/api/v1/reservations/{res_id}/approve")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_request_changes_requires_approver_role(self, staff_client, api_prefix):
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(api_prefix.id)},
        )
        res_id = resp.json()["id"]
        staff_client.post(f"/api/v1/reservations/{res_id}/submit")

        resp = staff_client.post(
            f"/api/v1/reservations/{res_id}/request-changes",
            json={"comments": "fix"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Release & Expiry Endpoints
# ---------------------------------------------------------------------------

class TestReleaseEndpoint:

    @pytest.mark.integration
    def test_release_own_reservation(self, staff_client, api_prefix):
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(api_prefix.id)},
        )
        res_id = resp.json()["id"]

        resp = staff_client.post(f"/api/v1/reservations/{res_id}/release")
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"


class TestExpiryEndpoint:

    @pytest.mark.integration
    def test_expire_requires_admin(self, staff_client):
        resp = staff_client.post("/api/v1/reservations/expire")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_expire_as_admin(self, admin_client):
        resp = admin_client.post("/api/v1/reservations/expire")
        assert resp.status_code == 200
        data = resp.json()
        assert "expired_count" in data


class TestExpiringEndpoint:

    @pytest.mark.integration
    def test_expiring_requires_admin(self, staff_client):
        resp = staff_client.get("/api/v1/reservations/expiring")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_expiring_as_admin(self, admin_client):
        resp = admin_client.get("/api/v1/reservations/expiring")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# List & Detail Endpoints
# ---------------------------------------------------------------------------

class TestListEndpoints:

    @pytest.mark.integration
    def test_list_my(self, staff_client, api_prefix):
        # Create a reservation first
        staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(api_prefix.id)},
        )
        resp = staff_client.get("/api/v1/reservations/my")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.integration
    def test_list_all(self, staff_client, api_prefix):
        resp = staff_client.get("/api/v1/reservations")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    @pytest.mark.integration
    def test_get_detail(self, staff_client, api_prefix):
        resp = staff_client.post(
            "/api/v1/reservations/generate",
            json={"prefix_id": str(api_prefix.id)},
        )
        res_id = resp.json()["id"]
        resp = staff_client.get(f"/api/v1/reservations/{res_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == res_id
        assert "prefix" in data

    @pytest.mark.integration
    def test_get_nonexistent_returns_404(self, staff_client):
        fake_id = str(uuid.uuid4())
        resp = staff_client.get(f"/api/v1/reservations/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_list_pending_as_admin(self, admin_client):
        resp = admin_client.get("/api/v1/reservations/pending")
        assert resp.status_code == 200
