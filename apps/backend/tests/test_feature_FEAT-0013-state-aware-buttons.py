"""Tests for FEAT-0013: State-Aware Action Buttons.

Covers:
  US-003 — Backend DELETE permission, state restriction, ownership enforcement
  US-004 — Backend submit-for-review creator-only enforcement
  US-005 — Reviewer role gains form:archive permission
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import DEFAULT_ROLES
from backend.database import get_db
from backend.main import app
from backend.models import AuditLog, Form


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _perms_for_roles(*role_names: str) -> list[str]:
    """Return the flat union of permissions for the given role names."""
    perms: set[str] = set()
    for name in role_names:
        role_cfg = DEFAULT_ROLES.get(name, {})
        for p in role_cfg.get("permissions", []):
            perms.add(p.value if hasattr(p, "value") else str(p))
    return list(perms)


def _create_form(
    db, creator_id, *, status="draft", title="Test Form",
) -> Form:
    form = Form(
        id=uuid.uuid4(),
        title=title,
        description="A test form for FEAT-0013",
        status=status,
        is_public=False,
        current_version=0,
        keywords=[],
        created_by_id=creator_id,
    )
    db.add(form)
    db.flush()
    return form


# ---------------------------------------------------------------------------
# US-003: DELETE endpoint enforcement
# ---------------------------------------------------------------------------

class TestDeleteEndpointEnforcement:
    """TC-003: Backend DELETE /api/v1/forms/{form_id} enforcement."""

    @pytest.fixture()
    def client_factory(self, db):
        def _build(user, roles, permissions=None):
            effective_permissions = (
                permissions if permissions is not None else _perms_for_roles(*roles)
            )
            token = TokenData(
                sub=str(user.id),
                email=str(user.email),
                name=f"{user.first_name} {user.last_name}",
                roles=roles,
                permissions=effective_permissions,
                token_type="access",
            )
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: token
            return TestClient(app)

        yield _build
        app.dependency_overrides.clear()

    # -- Permission denied ---------------------------------------------------

    @pytest.mark.integration
    def test_tc003_1_staff_viewer_without_delete_perm_gets_403(
        self, db, user_factory, client_factory,
    ):
        """TC-003.1: Staff viewer (no form:delete) gets 403."""
        creator = user_factory(email="tc003-1-creator@example.com")
        viewer = user_factory(email="tc003-1-viewer@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(viewer, ["staff_viewer"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 403
        assert "permissions" in resp.json()["detail"].lower()

    @pytest.mark.integration
    def test_tc003_1b_reviewer_without_delete_perm_gets_403(
        self, db, user_factory, client_factory,
    ):
        """TC-003.1b: Reviewer (no form:delete) gets 403."""
        creator = user_factory(email="tc003-1b-creator@example.com")
        reviewer = user_factory(email="tc003-1b-reviewer@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(reviewer, ["reviewer"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 403

    # -- Happy path ----------------------------------------------------------

    @pytest.mark.integration
    def test_tc003_2_owner_with_delete_perm_can_delete_own_draft(
        self, db, user_factory, client_factory,
    ):
        """TC-003.2: Staff with form:delete can delete own draft → 204."""
        creator = user_factory(email="tc003-2-creator@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(creator, ["staff_manager"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 204

        # Verify soft-deleted
        db.expire_all()
        deleted_form = db.query(Form).filter(Form.id == form.id).first()
        assert deleted_form.deleted_at is not None

    @pytest.mark.integration
    def test_tc003_6_admin_can_delete_any_draft(
        self, db, user_factory, client_factory,
    ):
        """TC-003.6: Admin can delete any user's draft form → 204."""
        creator = user_factory(email="tc003-6-creator@example.com")
        admin = user_factory(email="tc003-6-admin@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(admin, ["admin"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 204

    @pytest.mark.integration
    def test_tc003_8_nonadmin_can_delete_own_draft(
        self, db, user_factory, client_factory,
    ):
        """TC-003.8: Non-admin (staff_manager) can delete own draft → 204."""
        creator = user_factory(email="tc003-8-creator@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(creator, ["staff_manager"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 204

    # -- State restriction: non-draft forms ----------------------------------

    @pytest.mark.integration
    def test_tc003_3_cannot_delete_pending_review(
        self, db, user_factory, client_factory,
    ):
        """TC-003.3: Cannot delete form in pending_review state → 400."""
        creator = user_factory(email="tc003-3-creator@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        client = client_factory(creator, ["staff_manager"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 400
        assert "draft" in resp.json()["detail"].lower()

    @pytest.mark.integration
    def test_tc003_4_cannot_delete_published(
        self, db, user_factory, client_factory,
    ):
        """TC-003.4: Cannot delete form in published state → 400."""
        creator = user_factory(email="tc003-4-creator@example.com")
        form = _create_form(db, creator.id, status="published")

        client = client_factory(creator, ["staff_manager"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 400

    @pytest.mark.integration
    def test_tc003_5_cannot_delete_archived(
        self, db, user_factory, client_factory,
    ):
        """TC-003.5: Cannot delete form in archived state → 400."""
        creator = user_factory(email="tc003-5-creator@example.com")
        form = _create_form(db, creator.id, status="archived")

        client = client_factory(creator, ["staff_manager"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 400

    # -- Ownership restriction -----------------------------------------------

    @pytest.mark.integration
    def test_tc003_7_nonadmin_cannot_delete_another_users_draft(
        self, db, user_factory, client_factory,
    ):
        """TC-003.7: Non-admin cannot delete another user's draft → 403."""
        creator = user_factory(email="tc003-7-creator@example.com")
        other = user_factory(email="tc003-7-other@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(other, ["staff_manager"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 403
        assert "own" in resp.json()["detail"].lower()

    # -- Boundary: not found / invalid ID ------------------------------------

    @pytest.mark.integration
    def test_tc003_9_nonexistent_form_returns_404(
        self, db, user_factory, client_factory,
    ):
        """TC-003.9: Deleting a non-existent form returns 404."""
        user = user_factory(email="tc003-9-user@example.com")
        fake_id = uuid.uuid4()

        client = client_factory(user, ["admin"])
        resp = client.delete(f"/api/v1/forms/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_tc003_9c_invalid_uuid_returns_400(
        self, db, user_factory, client_factory,
    ):
        """TC-003.9c: Invalid UUID format returns 400."""
        user = user_factory(email="tc003-9c-user@example.com")

        client = client_factory(user, ["admin"])
        resp = client.delete("/api/v1/forms/not-a-uuid")
        assert resp.status_code == 400

    @pytest.mark.integration
    def test_tc003_10_audit_log_created_on_delete(
        self, db, user_factory, client_factory,
    ):
        """TC-003.10: Successful delete creates an audit log entry."""
        creator = user_factory(email="tc003-10-creator@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(creator, ["staff_manager"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 204

        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "forms",
                AuditLog.entity_id == str(form.id),
                AuditLog.action == "DELETE",
            )
            .first()
        )
        assert audit is not None


# ---------------------------------------------------------------------------
# US-004: Submit-for-review creator-only enforcement
# ---------------------------------------------------------------------------

class TestSubmitOwnershipEnforcement:
    """TC-004: Backend POST /api/v1/staff/forms/{form_id}/submit enforcement."""

    @pytest.fixture()
    def client_factory(self, db):
        def _build(user, roles, permissions=None):
            effective_permissions = (
                permissions if permissions is not None else _perms_for_roles(*roles)
            )
            token = TokenData(
                sub=str(user.id),
                email=str(user.email),
                name=f"{user.first_name} {user.last_name}",
                roles=roles,
                permissions=effective_permissions,
                token_type="access",
            )
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: token
            return TestClient(app)

        yield _build
        app.dependency_overrides.clear()

    @pytest.mark.integration
    def test_tc004_1_creator_with_perm_can_submit_own_draft(
        self, db, user_factory, client_factory,
    ):
        """TC-004.1: Creator with form:submit_for_review submits own draft."""
        creator = user_factory(email="tc004-1-creator@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(creator, ["staff_manager"])
        resp = client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_review"

    @pytest.mark.integration
    def test_tc004_2_noncreator_with_perm_gets_403(
        self, db, user_factory, client_factory,
    ):
        """TC-004.2: Non-creator with form:submit_for_review gets 403."""
        creator = user_factory(email="tc004-2-creator@example.com")
        other = user_factory(email="tc004-2-other@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(other, ["staff_manager"])
        resp = client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 403
        assert "creator" in resp.json()["detail"].lower()

    @pytest.mark.integration
    def test_tc004_3_admin_noncreator_gets_403(
        self, db, user_factory, client_factory,
    ):
        """TC-004.3: Admin non-creator gets 403; no submit bypass."""
        creator = user_factory(email="tc004-3-creator@example.com")
        admin = user_factory(email="tc004-3-admin@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(admin, ["admin"])
        resp = client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_tc004_4_creator_without_perm_gets_403(
        self, db, user_factory, client_factory,
    ):
        """TC-004.4: Creator without form:submit_for_review gets 403."""
        creator = user_factory(email="tc004-4-creator@example.com")
        form = _create_form(db, creator.id, status="draft")

        # staff_viewer has no submit permission
        client = client_factory(creator, ["staff_viewer"])
        resp = client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_tc004_5_nondraft_form_returns_400(
        self, db, user_factory, client_factory,
    ):
        """TC-004.5: Submitting a non-draft form returns 400."""
        creator = user_factory(email="tc004-5-creator@example.com")
        form = _create_form(db, creator.id, status="published")

        client = client_factory(creator, ["staff_manager"])
        resp = client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 400

    @pytest.mark.integration
    def test_tc004_6_reviewer_cannot_submit(
        self, db, user_factory, client_factory,
    ):
        """TC-004.6: Reviewer (no submit permission) cannot submit."""
        creator = user_factory(email="tc004-6-creator@example.com")
        reviewer = user_factory(email="tc004-6-reviewer@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(reviewer, ["reviewer"])
        resp = client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_tc004_7_staff_viewer_cannot_submit(
        self, db, user_factory, client_factory,
    ):
        """TC-004.7: Staff viewer cannot submit (no permission)."""
        creator = user_factory(email="tc004-7-creator@example.com")
        form = _create_form(db, creator.id, status="draft")

        client = client_factory(creator, ["staff_viewer"])
        resp = client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# US-005: Reviewer gains form:archive permission
# ---------------------------------------------------------------------------

class TestReviewerArchivePermission:
    """TC-005: Reviewer role includes form:archive permission."""

    @pytest.fixture()
    def client_factory(self, db):
        def _build(user, roles, permissions=None):
            effective_permissions = (
                permissions if permissions is not None else _perms_for_roles(*roles)
            )
            token = TokenData(
                sub=str(user.id),
                email=str(user.email),
                name=f"{user.first_name} {user.last_name}",
                roles=roles,
                permissions=effective_permissions,
                token_type="access",
            )
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: token
            return TestClient(app)

        yield _build
        app.dependency_overrides.clear()

    @pytest.mark.integration
    def test_tc005_1_reviewer_role_includes_form_archive(self):
        """TC-005.1: Reviewer role includes form:archive in DEFAULT_ROLES."""
        reviewer_perms = DEFAULT_ROLES["reviewer"]["permissions"]
        perm_values = [
            p.value if hasattr(p, "value") else str(p) for p in reviewer_perms
        ]
        assert "form:archive" in perm_values

    @pytest.mark.integration
    def test_tc005_2_reviewer_can_archive_published_form(
        self, db, user_factory, client_factory,
    ):
        """TC-005.2: Reviewer can archive a published form via API."""
        creator = user_factory(email="tc005-2-creator@example.com")
        reviewer = user_factory(email="tc005-2-reviewer@example.com")
        form = _create_form(db, creator.id, status="published")

        client = client_factory(reviewer, ["reviewer"])
        resp = client.post(f"/api/v1/staff/forms/{form.id}/archive")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    @pytest.mark.integration
    def test_tc005_4_no_other_permissions_changed(self):
        """TC-005.4: Only form:archive was added to reviewer; other roles untouched."""
        # Staff viewer should NOT have form:archive
        viewer_perms = DEFAULT_ROLES["staff_viewer"]["permissions"]
        viewer_values = [
            p.value if hasattr(p, "value") else str(p) for p in viewer_perms
        ]
        assert "form:archive" not in viewer_values

        # Admin should still have form:archive
        admin_perms = DEFAULT_ROLES["admin"]["permissions"]
        admin_values = [
            p.value if hasattr(p, "value") else str(p) for p in admin_perms
        ]
        assert "form:archive" in admin_values

        # Staff manager should still have form:archive
        mgr_perms = DEFAULT_ROLES["staff_manager"]["permissions"]
        mgr_values = [
            p.value if hasattr(p, "value") else str(p) for p in mgr_perms
        ]
        assert "form:archive" in mgr_values


# ---------------------------------------------------------------------------
# Error precedence for DELETE: 403 (no perm) > 400 (wrong state) > 403 (not owner) > 404
# ---------------------------------------------------------------------------

class TestDeleteErrorPrecedence:
    """Verify that error precedence is correct for edge cases."""

    @pytest.fixture()
    def client_factory(self, db):
        def _build(user, roles, permissions=None):
            effective_permissions = (
                permissions if permissions is not None else _perms_for_roles(*roles)
            )
            token = TokenData(
                sub=str(user.id),
                email=str(user.email),
                name=f"{user.first_name} {user.last_name}",
                roles=roles,
                permissions=effective_permissions,
                token_type="access",
            )
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: token
            return TestClient(app)

        yield _build
        app.dependency_overrides.clear()

    @pytest.mark.integration
    def test_no_permission_takes_precedence_over_state(
        self, db, user_factory, client_factory,
    ):
        """403 for missing permission before checking state."""
        creator = user_factory(email="prec-perm-state@example.com")
        form = _create_form(db, creator.id, status="published")

        # staff_viewer has no form:delete
        client = client_factory(creator, ["staff_viewer"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_state_check_before_ownership(
        self, db, user_factory, client_factory,
    ):
        """400 for wrong state before checking ownership (non-admin with perm)."""
        creator = user_factory(email="prec-state-own@example.com")
        other = user_factory(email="prec-state-own-other@example.com")
        form = _create_form(db, creator.id, status="published")

        client = client_factory(other, ["staff_manager"])
        resp = client.delete(f"/api/v1/forms/{form.id}")
        # Should be 400 (wrong state), not 403 (not owner)
        assert resp.status_code == 400
