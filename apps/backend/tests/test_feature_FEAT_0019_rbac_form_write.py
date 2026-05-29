"""FEAT-0019 SEC-003: Enforce RBAC on form write and archive endpoints.

Covers test cases from TC-US-001:
- TC1.1–TC1.3:  staff_viewer denied on create / update / archive → 403
- TC1.4–TC1.6:  Authorized user succeeds on create / update / archive
- TC1.7–TC1.9:  Permission specificity (single-perm users denied elsewhere)
- TC1.11:       Regression — user with all perms succeeds on all three
- TC1.12:       Unarchive requires form:archive
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.models import Form


# ── Helpers ───────────────────────────────────────────────────────────────────

_FORM_CREATE_PAYLOAD = {
    "title": "FEAT-0019 New Form",
    "description": "Test form for write auth",
    "is_public": False,
    "keywords": ["test"],
    "collects_personal_info": "No",
    "form_source": "URL",
    "form_source_url": "https://example.com/new.pdf",
}

_FORM_UPDATE_PAYLOAD = {
    "title": "FEAT-0019 Updated Title",
}


def _make_client(db, user, permissions):
    """Build a TestClient with the given user/permissions override."""
    def _get_user(request: Request) -> TokenData:
        return TokenData(
            sub=str(user.id),
            email=user.email,
            name=f"{user.first_name} {user.last_name}",
            roles=["staff"],
            token_type="access",
            permissions=permissions,
        )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _get_user
    return TestClient(app)


def _cleanup():
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def seed_form(db, user_factory):
    """A published form suitable for update/archive tests."""
    owner = user_factory(email="form-owner-0019@example.com")
    form = Form(
        id=uuid.uuid4(),
        title="FEAT-0019 Existing Form",
        description="Existing form for write-auth tests",
        status="published",
        is_public=True,
        current_version=1,
        keywords=["test"],
        created_by_id=owner.id,
        collects_personal_info="No",
        form_source="URL",
        form_source_url="https://example.com/existing.pdf",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(form)
    db.flush()
    return form


@pytest.fixture()
def archived_form(db, user_factory):
    """An archived form suitable for unarchive permission tests."""
    owner = user_factory(email="archived-owner-0019@example.com")
    form = Form(
        id=uuid.uuid4(),
        title="FEAT-0019 Archived Form",
        description="Archived form for unarchive-auth tests",
        status="archived",
        is_public=True,
        current_version=1,
        keywords=["test"],
        created_by_id=owner.id,
        collects_personal_info="No",
        form_source="URL",
        form_source_url="https://example.com/archived.pdf",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(form)
    db.flush()
    return form


@pytest.fixture()
def test_user(user_factory):
    return user_factory(email="writer-0019@example.com")


# ===========================================================================
# TC1.1–TC1.3: staff_viewer (no write perms) → 403
# ===========================================================================


class TestStaffViewerDenied:

    def test_create_denied(self, db, test_user):
        """TC1.1: staff_viewer POST /forms → 403."""
        client = _make_client(db, test_user, permissions=["form:read"])
        try:
            resp = client.post("/api/v1/forms", json=_FORM_CREATE_PAYLOAD)
            assert resp.status_code == 403
        finally:
            _cleanup()

    def test_update_denied(self, db, test_user, seed_form):
        """TC1.2: staff_viewer PUT /forms/{id} → 403."""
        client = _make_client(db, test_user, permissions=["form:read"])
        try:
            resp = client.put(f"/api/v1/forms/{seed_form.id}", json=_FORM_UPDATE_PAYLOAD)
            assert resp.status_code == 403
        finally:
            _cleanup()

    def test_archive_denied(self, db, test_user, seed_form):
        """TC1.3: staff_viewer POST /forms/{id}/archive → 403."""
        client = _make_client(db, test_user, permissions=["form:read"])
        try:
            resp = client.post(f"/api/v1/forms/{seed_form.id}/archive")
            assert resp.status_code == 403
        finally:
            _cleanup()

    def test_unarchive_denied(self, db, test_user, archived_form):
        """TC1.12a: staff_viewer POST /forms/{id}/unarchive -> 403."""
        client = _make_client(db, test_user, permissions=["form:read"])
        try:
            resp = client.post(f"/api/v1/forms/{archived_form.id}/unarchive")
            assert resp.status_code == 403
            db.refresh(archived_form)
            assert archived_form.status == "archived"
        finally:
            _cleanup()


# ===========================================================================
# TC1.4–TC1.6: Authorized user succeeds
# ===========================================================================


class TestAuthorizedUserSucceeds:

    def test_create_with_permission(self, db, test_user):
        """TC1.4: User with form:create POST /forms → 201."""
        client = _make_client(db, test_user, permissions=["form:read", "form:create"])
        try:
            resp = client.post("/api/v1/forms", json=_FORM_CREATE_PAYLOAD)
            assert resp.status_code == 201
            assert resp.json()["title"] == _FORM_CREATE_PAYLOAD["title"]
        finally:
            _cleanup()

    def test_update_with_permission(self, db, test_user, seed_form):
        """TC1.5: User with form:edit PUT /forms/{id} → 200."""
        client = _make_client(db, test_user, permissions=["form:read", "form:edit"])
        try:
            resp = client.put(f"/api/v1/forms/{seed_form.id}", json=_FORM_UPDATE_PAYLOAD)
            assert resp.status_code == 200
            assert resp.json()["title"] == _FORM_UPDATE_PAYLOAD["title"]
        finally:
            _cleanup()

    def test_archive_with_permission(self, db, test_user, seed_form):
        """TC1.6: User with form:archive POST /forms/{id}/archive → 200."""
        client = _make_client(db, test_user, permissions=["form:read", "form:archive"])
        try:
            resp = client.post(f"/api/v1/forms/{seed_form.id}/archive")
            assert resp.status_code == 200
            assert resp.json()["status"] == "archived"
        finally:
            _cleanup()

    def test_unarchive_with_permission(self, db, test_user, archived_form):
        """TC1.12b: User with form:archive POST /forms/{id}/unarchive -> 200."""
        client = _make_client(db, test_user, permissions=["form:read", "form:archive"])
        try:
            resp = client.post(f"/api/v1/forms/{archived_form.id}/unarchive")
            assert resp.status_code == 200
            assert resp.json()["status"] == "published"
        finally:
            _cleanup()


# ===========================================================================
# TC1.7–TC1.9: Permission specificity (single-perm isolation)
# ===========================================================================


class TestPermissionSpecificity:

    def test_create_only_denied_on_update_and_archive(self, db, test_user, seed_form):
        """TC1.7: form:create-only user → 403 on update and archive."""
        client = _make_client(db, test_user, permissions=["form:read", "form:create"])
        try:
            resp_update = client.put(f"/api/v1/forms/{seed_form.id}", json=_FORM_UPDATE_PAYLOAD)
            assert resp_update.status_code == 403
            resp_archive = client.post(f"/api/v1/forms/{seed_form.id}/archive")
            assert resp_archive.status_code == 403
        finally:
            _cleanup()

    def test_edit_only_denied_on_create_and_archive(self, db, test_user, seed_form):
        """TC1.8: form:edit-only user → 403 on create and archive."""
        client = _make_client(db, test_user, permissions=["form:read", "form:edit"])
        try:
            resp_create = client.post("/api/v1/forms", json=_FORM_CREATE_PAYLOAD)
            assert resp_create.status_code == 403
            resp_archive = client.post(f"/api/v1/forms/{seed_form.id}/archive")
            assert resp_archive.status_code == 403
        finally:
            _cleanup()

    def test_archive_only_denied_on_create_and_update(self, db, test_user, seed_form):
        """TC1.9: form:archive-only user → 403 on create and update."""
        client = _make_client(db, test_user, permissions=["form:read", "form:archive"])
        try:
            resp_create = client.post("/api/v1/forms", json=_FORM_CREATE_PAYLOAD)
            assert resp_create.status_code == 403
            resp_update = client.put(f"/api/v1/forms/{seed_form.id}", json=_FORM_UPDATE_PAYLOAD)
            assert resp_update.status_code == 403
        finally:
            _cleanup()

    def test_edit_only_denied_on_unarchive(self, db, test_user, archived_form):
        """TC1.12c: form:edit without form:archive cannot unarchive."""
        client = _make_client(db, test_user, permissions=["form:read", "form:edit"])
        try:
            resp = client.post(f"/api/v1/forms/{archived_form.id}/unarchive")
            assert resp.status_code == 403
            db.refresh(archived_form)
            assert archived_form.status == "archived"
        finally:
            _cleanup()


# ===========================================================================
# TC1.11: Regression — user with all permissions succeeds on all three
# ===========================================================================


class TestRegressionAllPermissions:

    def test_full_lifecycle(self, db, test_user, seed_form):
        """TC1.11: User with all write perms can create, update, archive, unarchive."""
        all_perms = ["form:read", "form:create", "form:edit", "form:archive"]
        client = _make_client(db, test_user, permissions=all_perms)
        try:
            # Create
            resp = client.post("/api/v1/forms", json=_FORM_CREATE_PAYLOAD)
            assert resp.status_code == 201
            new_id = resp.json()["id"]

            # Update
            resp = client.put(f"/api/v1/forms/{new_id}", json=_FORM_UPDATE_PAYLOAD)
            assert resp.status_code == 200

            # Archive the seed form (published → archived)
            resp = client.post(f"/api/v1/forms/{seed_form.id}/archive")
            assert resp.status_code == 200

            # Unarchive restores the archived form to published
            resp = client.post(f"/api/v1/forms/{seed_form.id}/unarchive")
            assert resp.status_code == 200
            assert resp.json()["status"] == "published"
        finally:
            _cleanup()
