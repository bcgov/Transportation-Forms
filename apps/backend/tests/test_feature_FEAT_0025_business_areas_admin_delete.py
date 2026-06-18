"""Tests for FEAT-0025 Business Areas Admin smart-delete behaviour.

Covers the bug where ``BusinessAreaAdminService.delete_business_area`` raised
``TypeError: 'resource_type' is an invalid keyword argument for AuditLog`` and
locks down the AC2 / AC4 / AC5 / AC6 acceptance criteria from
``plan/features/FEAT-0025-business-areas-admin/stories/US-003-smart-delete.md``.

All tests use the project's standard PostgreSQL-backed ``db`` fixture so they
exercise the real ``AuditLog`` schema and the BusinessArea/Form FK relationship
that broke the original implementation.
"""

import uuid
from datetime import datetime, timedelta, timezone

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
    Form,
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
        last_name="Tester",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_business_area(db, *, name: str | None = None, deleted: bool = False) -> BusinessArea:
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


def _make_form(db, *, business_area: BusinessArea, creator: User, title: str | None = None) -> Form:
    form = Form(
        id=uuid.uuid4(),
        title=title or f"Form-{uuid.uuid4().hex[:6]}",
        status="draft",
        is_public=False,
        keywords=[],
        created_by_id=creator.id,
        business_area_id=business_area.id,
    )
    db.add(form)
    db.flush()
    return form


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
    return _make_user(db, email="ba-admin-actor@example.com")


@pytest.fixture()
def actor_token(actor) -> TokenData:
    return _token_for(actor)


@pytest.fixture()
def admin_api_client(db, actor):
    """Test client whose user has the BA delete/manage permissions wired in
    the DB role (the runtime permission check uses DB roles, not the JWT)."""
    role = Role(
        id=uuid.uuid4(),
        name="admin",
        description="admin role for FEAT-0025 tests",
        permissions=[
            Permission.BUSINESS_AREA_READ.value,
            Permission.BUSINESS_AREA_DELETE.value,
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
# Service-level tests (close to the bug)
# ---------------------------------------------------------------------------

class TestDeleteBusinessAreaService:
    """Direct service-layer tests covering AC2/AC4/AC5/AC6."""

    # --- AC2: Hard delete (unreferenced) -------------------------------------

    def test_hard_delete_when_no_linked_forms(self, db, actor_token):
        ba = _make_business_area(db, name="HardDelete-Area")
        ba_id = str(ba.id)

        result = BusinessAreaAdminService.delete_business_area(
            db, ba_id, actor_token, replacement_id=None
        )

        assert result == {"status": "hard-deleted"}
        # Row is fully removed from the DB.
        assert db.query(BusinessArea).filter(BusinessArea.id == ba.id).first() is None
        # Exactly one audit row written, with the right schema.
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "business_areas", AuditLog.entity_id == ba_id)
            .one()
        )
        assert audit.action == "DELETE"
        assert audit.user_id == uuid.UUID(actor_token.sub)
        assert audit.old_values == {"name": "HardDelete-Area"}
        assert audit.new_values is None
        assert "Hard-deleted" in (audit.description or "")

    # --- AC4: Soft delete (linked forms, no replacement) ---------------------

    def test_soft_delete_when_forms_linked_and_no_replacement(self, db, actor, actor_token):
        ba = _make_business_area(db, name="SoftDelete-Area")
        form = _make_form(db, business_area=ba, creator=actor)
        ba_id = str(ba.id)

        result = BusinessAreaAdminService.delete_business_area(
            db, ba_id, actor_token, replacement_id=None
        )

        assert result == {"status": "soft-deleted"}
        # Row still exists, deleted_at populated.
        refreshed = db.query(BusinessArea).filter(BusinessArea.id == ba.id).one()
        assert refreshed.deleted_at is not None
        # Form still references the (now soft-deleted) BA.
        db.refresh(form)
        assert form.business_area_id == ba.id
        # Audit row written.
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "business_areas", AuditLog.entity_id == ba_id)
            .one()
        )
        assert audit.action == "DELETE"
        assert audit.old_values == {
            "name": "SoftDelete-Area",
            "linked_forms_count": 1,
        }
        assert "deleted_at" in (audit.new_values or {})
        assert "Soft-deleted" in (audit.description or "")

    # --- AC5: Reassign + hard delete -----------------------------------------

    def test_reassign_and_hard_delete_with_per_form_audit(self, db, actor, actor_token):
        source = _make_business_area(db, name="Source-Alpha")
        target = _make_business_area(db, name="Target-Beta")
        form_a = _make_form(db, business_area=source, creator=actor, title="form-A")
        form_b = _make_form(db, business_area=source, creator=actor, title="form-B")
        form_c = _make_form(db, business_area=source, creator=actor, title="form-C")
        source_id = str(source.id)
        target_id = str(target.id)
        form_ids = [form_a.id, form_b.id, form_c.id]

        result = BusinessAreaAdminService.delete_business_area(
            db, source_id, actor_token, replacement_id=target_id
        )

        assert result == {"status": "reassigned-and-hard-deleted"}
        # Source is gone.
        assert (
            db.query(BusinessArea).filter(BusinessArea.id == source.id).first()
            is None
        )

        # Re-read forms from the DB by dropping the identity map first; this
        # protects the assertion from any stale in-memory FK values that the
        # previous (broken) implementation left in the session even though
        # the persisted row had been nullified by SQLAlchemy's parent-delete
        # cascade.
        db.expire_all()
        refetched = (
            db.query(Form)
            .filter(Form.id.in_(form_ids))
            .all()
        )
        assert len(refetched) == 3
        for f in refetched:
            assert f.business_area_id == target.id, (
                f"Form {f.id} should have been reassigned to {target.id} "
                f"but got {f.business_area_id}"
            )

        # Per-form audit entries (UPDATE on forms).
        form_audits = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "forms", AuditLog.action == "UPDATE")
            .filter(AuditLog.entity_id.in_([str(fid) for fid in form_ids]))
            .all()
        )
        assert len(form_audits) == 3
        for fa in form_audits:
            assert fa.old_values == {"business_area_id": source_id}
            assert fa.new_values == {"business_area_id": target_id}
            assert fa.user_id == uuid.UUID(actor_token.sub)

        # One BA-level audit entry (DELETE on business_areas).
        ba_audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "business_areas",
                AuditLog.entity_id == source_id,
                AuditLog.action == "DELETE",
            )
            .one()
        )
        assert ba_audit.old_values == {
            "name": "Source-Alpha",
            "linked_forms_count": 3,
        }
        assert ba_audit.new_values == {
            "replacement_id": target_id,
            "replacement_name": "Target-Beta",
        }

    def test_reassign_survives_preloaded_forms_collection(
        self, db, actor, actor_token
    ):
        """Regression: when ``ba.forms`` is already loaded (warm relationship
        cache), SQLAlchemy's default delete behaviour was nullifying the FK
        on the children during flush, silently undoing the reassignment.

        This test forces the worst case by accessing ``source.forms`` before
        the service runs, then verifies (via a fresh read) that the forms
        are actually pointing at the replacement BA in the DB.
        """
        source = _make_business_area(db, name="Source-Warm")
        target = _make_business_area(db, name="Target-Warm")
        f1 = _make_form(db, business_area=source, creator=actor, title="warm-1")
        f2 = _make_form(db, business_area=source, creator=actor, title="warm-2")
        form_ids = [f1.id, f2.id]

        # Force the relationship collection to load. This is exactly what
        # tripped the original bug in the running app — by the time the
        # service called db.delete(ba), SA had a cached ba.forms collection
        # that it tried to "tidy up" by nullifying the children's FK.
        preloaded = list(source.forms)
        assert len(preloaded) == 2

        result = BusinessAreaAdminService.delete_business_area(
            db, str(source.id), actor_token, replacement_id=str(target.id)
        )
        assert result == {"status": "reassigned-and-hard-deleted"}

        # Source must be gone.
        assert (
            db.query(BusinessArea).filter(BusinessArea.id == source.id).first()
            is None
        )

        # Forms must be reassigned to the target — verified against a fresh
        # DB read, NOT the identity map.
        db.expire_all()
        refetched = db.query(Form).filter(Form.id.in_(form_ids)).all()
        assert len(refetched) == 2
        for f in refetched:
            assert f.business_area_id == target.id, (
                "Pre-loaded ba.forms caused the FK to be nullified during "
                "the parent delete (regression of the SQLAlchemy "
                "delete-cascade race)."
            )
            assert f.business_area_id is not None

    # --- AC6 + edge cases ----------------------------------------------------

    def test_self_reassignment_rejected(self, db, actor, actor_token):
        ba = _make_business_area(db)
        _make_form(db, business_area=ba, creator=actor)

        with pytest.raises(ValueError, match="same business area"):
            BusinessAreaAdminService.delete_business_area(
                db, str(ba.id), actor_token, replacement_id=str(ba.id)
            )
        # No mutation: BA still active.
        db.refresh(ba)
        assert ba.deleted_at is None

    def test_unknown_replacement_target_rejected(self, db, actor, actor_token):
        ba = _make_business_area(db)
        _make_form(db, business_area=ba, creator=actor)

        with pytest.raises(ValueError, match="Target Business Area"):
            BusinessAreaAdminService.delete_business_area(
                db, str(ba.id), actor_token, replacement_id=str(uuid.uuid4())
            )
        db.refresh(ba)
        assert ba.deleted_at is None

    def test_soft_deleted_replacement_target_rejected(self, db, actor, actor_token):
        ba = _make_business_area(db)
        target = _make_business_area(db, deleted=True)
        _make_form(db, business_area=ba, creator=actor)

        with pytest.raises(ValueError, match="Target Business Area"):
            BusinessAreaAdminService.delete_business_area(
                db, str(ba.id), actor_token, replacement_id=str(target.id)
            )

    def test_unknown_business_area_rejected(self, db, actor_token):
        with pytest.raises(ValueError, match="Business Area not found"):
            BusinessAreaAdminService.delete_business_area(
                db, str(uuid.uuid4()), actor_token, replacement_id=None
            )

    def test_already_soft_deleted_business_area_rejected(self, db, actor_token):
        ba = _make_business_area(db, deleted=True)

        with pytest.raises(ValueError, match="Business Area not found"):
            BusinessAreaAdminService.delete_business_area(
                db, str(ba.id), actor_token, replacement_id=None
            )


# ---------------------------------------------------------------------------
# API-level regression test: original 500 must now be 200
# ---------------------------------------------------------------------------

class TestDeleteBusinessAreaApi:
    """End-to-end check that the DELETE endpoint no longer 500s."""

    def test_delete_unreferenced_returns_200(self, db, admin_api_client):
        ba = _make_business_area(db, name="Api-Hard-Delete")
        db.commit()

        response = admin_api_client.delete(f"/api/v1/admin/business-areas/{ba.id}")

        assert response.status_code == 200, response.text
        assert response.json() == {"status": "hard-deleted"}

    def test_delete_with_replacement_returns_200(self, db, actor, admin_api_client):
        source = _make_business_area(db, name="Api-Source")
        target = _make_business_area(db, name="Api-Target")
        form = _make_form(db, business_area=source, creator=actor)
        form_id = form.id
        db.commit()

        response = admin_api_client.delete(
            f"/api/v1/admin/business-areas/{source.id}",
            params={"replacement_id": str(target.id)},
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"status": "reassigned-and-hard-deleted"}

        # End-to-end DB assertion: the form must actually be reassigned
        # (not nullified) after the BA hard-delete completes.
        db.expire_all()
        refetched = db.query(Form).filter(Form.id == form_id).one()
        assert refetched.business_area_id == target.id
        assert (
            db.query(BusinessArea).filter(BusinessArea.id == source.id).first()
            is None
        )

    def test_delete_referenced_without_replacement_soft_deletes(
        self, db, actor, admin_api_client
    ):
        ba = _make_business_area(db, name="Api-Soft")
        _make_form(db, business_area=ba, creator=actor)
        db.commit()

        response = admin_api_client.delete(f"/api/v1/admin/business-areas/{ba.id}")

        assert response.status_code == 200, response.text
        assert response.json() == {"status": "soft-deleted"}
        db.refresh(ba)
        assert ba.deleted_at is not None
