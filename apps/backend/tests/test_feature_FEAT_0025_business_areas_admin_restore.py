"""Tests for FEAT-0025 Business Areas Admin AC3 (soft-deleted name collision).

Locks down the AC3 acceptance criteria from
``plan/features/FEAT-0025-business-areas-admin/stories/US-001-admin-crud.md``
and the matching service contract on
``BusinessAreaAdminService.restore_business_area``.

Covers:
- AC3 service: restoring a soft-deleted Business Area clears ``deleted_at``
  and writes a single ``RESTORE`` audit row.
- AC3 service: restoring a non-deleted / missing record raises ``ValueError``.
- AC3 API: ``POST /admin/business-areas`` returns a structured 409 detail
  containing ``existing_id`` when the supplied Name matches a soft-deleted
  record.
- AC3 API: ``POST /admin/business-areas/{id}/restore`` clears ``deleted_at``,
  returns the standard admin response shape, and writes an audit row.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import Permission
from backend.database import get_db
from backend.main import app as fastapi_app
from backend.models import (
    AuditLog,
    BusinessArea,
    Role,
    User,
    UserRole,
)
from backend.services.business_areas_admin_service import BusinessAreaAdminService


# ---------------------------------------------------------------------------
# Local helpers / factories
# ---------------------------------------------------------------------------

def _make_user(db, email: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        first_name="BA",
        last_name="Restore-Tester",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_business_area(
    db, *, name: str | None = None, deleted: bool = False
) -> BusinessArea:
    ba = BusinessArea(
        id=uuid.uuid4(),
        name=name or f"BA-{uuid.uuid4().hex[:8]}",
        mailbox=None,
    )
    if deleted:
        ba.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(ba)
    db.flush()
    return ba


def _token_for(user: User) -> TokenData:
    return TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        roles=["admin"],
        token_type="access",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def actor(db) -> User:
    return _make_user(db, email="ba-restore-actor@example.com")


@pytest.fixture()
def actor_token(actor) -> TokenData:
    return _token_for(actor)


@pytest.fixture()
def admin_api_client(db, actor):
    """TestClient whose user has the BA create/manage permissions wired in
    the DB role (the runtime permission check uses DB roles, not the JWT)."""
    role = Role(
        id=uuid.uuid4(),
        name="admin-restore-test",
        description="admin role for FEAT-0025 AC3 tests",
        permissions=[
            Permission.BUSINESS_AREA_READ.value,
            Permission.BUSINESS_AREA_CREATE.value,
            Permission.BUSINESS_AREA_EDIT.value,
            Permission.BUSINESS_AREA_MANAGE.value,
        ],
        is_system=True,
        is_active=True,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(id=uuid.uuid4(), user_id=actor.id, role_id=role.id))
    db.flush()

    fastapi_app.dependency_overrides[get_db] = lambda: db
    fastapi_app.dependency_overrides[get_current_user] = lambda: _token_for(actor)
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        fastapi_app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------

class TestRestoreBusinessAreaService:
    """Direct service-layer tests for AC3 restore behaviour."""

    def test_restore_clears_deleted_at_and_writes_audit(
        self, db, actor_token
    ):
        ba = _make_business_area(db, name="Restore-Me", deleted=True)
        ba_id = str(ba.id)
        original_deleted_at = ba.deleted_at
        assert original_deleted_at is not None  # sanity

        result = BusinessAreaAdminService.restore_business_area(
            db, ba_id, actor_token
        )

        assert result.id == ba.id
        assert result.deleted_at is None

        refreshed = (
            db.query(BusinessArea).filter(BusinessArea.id == ba.id).one()
        )
        assert refreshed.deleted_at is None

        # Exactly one RESTORE audit row written, with the right schema.
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "business_areas",
                AuditLog.entity_id == ba_id,
                AuditLog.action == "RESTORE",
            )
            .one()
        )
        assert audit.user_id == uuid.UUID(actor_token.sub)
        assert audit.old_values == {
            "name": "Restore-Me",
            "deleted_at": original_deleted_at.isoformat(),
        }
        assert audit.new_values == {"deleted_at": None}
        assert "Restored" in (audit.description or "")

    def test_restore_rejects_non_deleted_record(self, db, actor_token):
        ba = _make_business_area(db, name="Active-Already", deleted=False)

        with pytest.raises(ValueError, match="not deleted"):
            BusinessAreaAdminService.restore_business_area(
                db, str(ba.id), actor_token
            )

        # No audit row should have been written.
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "business_areas",
                AuditLog.entity_id == str(ba.id),
                AuditLog.action == "RESTORE",
            )
            .all()
        )
        assert audits == []

    def test_restore_rejects_missing_record(self, db, actor_token):
        with pytest.raises(ValueError, match="not found"):
            BusinessAreaAdminService.restore_business_area(
                db, str(uuid.uuid4()), actor_token
            )


# ---------------------------------------------------------------------------
# API-level tests (AC3 end-to-end)
# ---------------------------------------------------------------------------

class TestRestoreBusinessAreaApi:
    """End-to-end tests covering the AC3 frontend ↔ backend contract."""

    def test_create_returns_structured_409_when_name_matches_soft_deleted(
        self, db, admin_api_client
    ):
        ba = _make_business_area(db, name="Collision-Name", deleted=True)
        db.commit()  # ensure the API call sees the row

        response = admin_api_client.post(
            "/api/v1/admin/business-areas",
            json={"name": "Collision-Name", "mailbox": None},
        )

        assert response.status_code == 409
        body = response.json()
        detail = body.get("detail")
        assert isinstance(detail, dict), (
            f"Expected structured detail dict, got: {body!r}"
        )
        assert detail.get("code") == "soft_deleted_collision"
        assert detail.get("existing_id") == str(ba.id)
        assert "restore" in (detail.get("message") or "").lower()

    def test_restore_endpoint_clears_deleted_at_and_returns_admin_response(
        self, db, admin_api_client
    ):
        ba = _make_business_area(db, name="Endpoint-Restore", deleted=True)
        db.commit()
        ba_id = str(ba.id)

        response = admin_api_client.post(
            f"/api/v1/admin/business-areas/{ba_id}/restore"
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["id"] == ba_id
        assert payload["name"] == "Endpoint-Restore"
        assert payload["mailbox"] is None
        assert payload["contact_count"] == 0
        assert payload["linked_forms_count"] == 0

        # Persisted state: deleted_at cleared.
        db.expire_all()
        refreshed = (
            db.query(BusinessArea).filter(BusinessArea.id == ba.id).one()
        )
        assert refreshed.deleted_at is None

        # Audit row written.
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "business_areas",
                AuditLog.entity_id == ba_id,
                AuditLog.action == "RESTORE",
            )
            .one()
        )
        assert audit.new_values == {"deleted_at": None}

    def test_restore_endpoint_404_for_unknown_id(self, db, admin_api_client):
        response = admin_api_client.post(
            f"/api/v1/admin/business-areas/{uuid.uuid4()}/restore"
        )
        assert response.status_code == 404

    def test_restore_endpoint_400_for_active_record(
        self, db, admin_api_client
    ):
        ba = _make_business_area(db, name="Active-Cannot-Restore", deleted=False)
        db.commit()

        response = admin_api_client.post(
            f"/api/v1/admin/business-areas/{ba.id}/restore"
        )
        assert response.status_code == 400
        assert "not deleted" in response.json().get("detail", "").lower()

    def test_create_then_confirm_restore_full_round_trip(
        self, db, admin_api_client
    ):
        """End-to-end flow: collide on create, then restore via the
        ``existing_id`` returned in the 409 detail. Mirrors the frontend
        confirmation prompt."""
        ba = _make_business_area(db, name="Round-Trip", deleted=True)
        db.commit()

        # 1) Create attempt → structured 409 with existing_id.
        create_resp = admin_api_client.post(
            "/api/v1/admin/business-areas",
            json={"name": "Round-Trip", "mailbox": "round-trip@example.com"},
        )
        assert create_resp.status_code == 409
        detail = create_resp.json()["detail"]
        assert detail["existing_id"] == str(ba.id)

        # 2) Confirm restore via the existing_id.
        restore_resp = admin_api_client.post(
            f"/api/v1/admin/business-areas/{detail['existing_id']}/restore"
        )
        assert restore_resp.status_code == 200, restore_resp.text
        payload = restore_resp.json()
        assert payload["id"] == str(ba.id)
        assert payload["name"] == "Round-Trip"

        # 3) The area now appears in the active admin list.
        list_resp = admin_api_client.get("/api/v1/admin/business-areas")
        assert list_resp.status_code == 200
        names = {item["name"] for item in list_resp.json()}
        assert "Round-Trip" in names
