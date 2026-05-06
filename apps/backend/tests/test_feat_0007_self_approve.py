"""FEAT-0007: Tests for form:approve-self permission.

Covers TC-US-001 (permission seeding) and TC-US-002 (self-approval logic).
These tests are deliberately isolated from existing FEAT-0001 tests.

Markers:
    unit:        No DB required (service mock or in-memory logic only)
    integration: Real PostgreSQL DB required
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import DEFAULT_ROLES, Permission
from backend.database import get_db
from backend.main import app
from backend.models import Form
from backend.services.forms import FormService, FormWorkflowValidationError


# ---------------------------------------------------------------------------
# Helpers (mirror pattern used in test_forms_workflow.py)
# ---------------------------------------------------------------------------

def _create_user(user_factory, email: str):
    return user_factory(email=email, first_name="FEAT0007", last_name="Tester")


def _create_form(db, creator_id, *, status="pending_review"):
    form = Form(
        id=uuid.uuid4(),
        title="FEAT-0007 Test Form",
        description="Form used for self-approval tests",
        status=status,
        is_public=False,
        current_version=0,
        keywords=[],
        created_by_id=creator_id,
    )
    db.add(form)
    db.flush()
    return form


def _perms(*permission_values: str) -> list[str]:
    return list(permission_values)


def _all_perms_for_role(role_name: str) -> list[str]:
    role_cfg = DEFAULT_ROLES.get(role_name, {})
    return [p.value if hasattr(p, "value") else str(p) for p in role_cfg.get("permissions", [])]


# ---------------------------------------------------------------------------
# TC-US-001: Permission definition and admin role seeding
# ---------------------------------------------------------------------------

class TestApproveSelfPermissionDefinition:
    """TC-US-001: Verify permission constant exists and admin role includes it."""

    @pytest.mark.unit
    def test_form_approve_self_enum_exists(self):
        """TC1.1: form:approve-self is a defined Permission enum value."""
        assert Permission.FORM_APPROVE_SELF == "form:approve-self"

    @pytest.mark.unit
    def test_admin_role_includes_approve_self(self):
        """TC1.2: DEFAULT_ROLES['admin'] carries form:approve-self."""
        admin_perms = [
            p.value if hasattr(p, "value") else str(p)
            for p in DEFAULT_ROLES["admin"]["permissions"]
        ]
        assert "form:approve-self" in admin_perms

    @pytest.mark.unit
    def test_standard_roles_do_not_include_approve_self(self):
        """TC1.3: staff_manager, reviewer, staff_viewer do not carry form:approve-self."""
        for role_name in ("staff_manager", "reviewer", "staff_viewer"):
            role_perms = _all_perms_for_role(role_name)
            assert "form:approve-self" not in role_perms, (
                f"Role '{role_name}' must not carry form:approve-self by default"
            )


# ---------------------------------------------------------------------------
# TC-US-002: Service-layer self-approval logic
# ---------------------------------------------------------------------------

class TestSelfApprovalServiceLayer:
    """TC-US-002: Service-level approval guard respects allow_self_approve flag."""

    @pytest.mark.integration
    def test_self_approve_allowed_with_flag(self, db, user_factory):
        """TC2.1 service path: allow_self_approve=True bypasses SoD for own form."""
        creator = _create_user(user_factory, "feat7-svc-self-allow@example.com")
        form = _create_form(db, creator.id, status="pending_review")
        form_id = uuid.UUID(str(form.id))

        result = FormService.approve_form(db, form_id, creator.id, allow_self_approve=True)

        assert str(result.status) == "published"

    @pytest.mark.integration
    def test_self_approve_blocked_without_flag(self, db, user_factory):
        """TC2.2 service path: allow_self_approve=False (default) enforces SoD."""
        creator = _create_user(user_factory, "feat7-svc-self-block@example.com")
        form = _create_form(db, creator.id, status="pending_review")
        form_id = uuid.UUID(str(form.id))

        with pytest.raises(FormWorkflowValidationError, match="You cannot approve your own form submission"):
            FormService.approve_form(db, form_id, creator.id)

    @pytest.mark.integration
    def test_standard_approve_unaffected(self, db, user_factory):
        """TC2.3: Approving another user's form works with or without allow_self_approve."""
        creator = _create_user(user_factory, "feat7-svc-other-creator@example.com")
        approver = _create_user(user_factory, "feat7-svc-other-approver@example.com")
        form = _create_form(db, creator.id, status="pending_review")
        form_id = uuid.UUID(str(form.id))

        result = FormService.approve_form(db, form_id, approver.id)

        assert str(result.status) == "published"

    @pytest.mark.integration
    def test_self_reject_allowed(self, db, user_factory):
        """TC2.4: Self-rejection has never had a SoD guard — remains allowed."""
        creator = _create_user(user_factory, "feat7-svc-self-reject@example.com")
        form = _create_form(db, creator.id, status="pending_review")
        form_id = uuid.UUID(str(form.id))

        result = FormService.reject_form(db, form_id, creator.id, "Self-correction")

        assert str(result.status) == "draft"


# ---------------------------------------------------------------------------
# TC-US-002: API-layer self-approval logic
# ---------------------------------------------------------------------------

class TestSelfApprovalApi:
    """TC-US-002: HTTP endpoints honour form:approve-self in JWT claims."""

    @pytest.fixture()
    def client_factory(self, db):
        def _build(user, permissions: list[str]):
            token = TokenData(
                sub=str(user.id),
                email=user.email,
                name=f"{user.first_name} {user.last_name}",
                roles=[],
                permissions=permissions,
                token_type="access",
            )
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: token
            return TestClient(app)

        yield _build
        app.dependency_overrides.clear()

    @pytest.mark.integration
    def test_api_self_approve_allowed_with_approve_self_permission(
        self, db, user_factory, client_factory
    ):
        """TC2.1 API: creator with form:create+form:approve+form:approve-self can self-approve."""
        creator = _create_user(user_factory, "feat7-api-self-allow@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        client = client_factory(
            creator,
            _perms("form:approve", "form:review", "form:approve-self"),
        )
        resp = client.post(f"/api/v1/staff/forms/{form.id}/approve")

        assert resp.status_code == 200
        assert resp.json()["status"] == "published"

    @pytest.mark.integration
    def test_api_self_approve_blocked_without_approve_self_permission(
        self, db, user_factory, client_factory
    ):
        """TC2.2 API: creator with form:approve but missing form:approve-self gets 400."""
        creator = _create_user(user_factory, "feat7-api-self-block@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        client = client_factory(
            creator,
            _perms("form:approve", "form:review"),  # no form:approve-self
        )
        resp = client.post(f"/api/v1/staff/forms/{form.id}/approve")

        assert resp.status_code == 400
        assert "cannot approve your own" in resp.json()["detail"].lower()

    @pytest.mark.integration
    def test_api_standard_approval_unaffected_by_approve_self(
        self, db, user_factory, client_factory
    ):
        """TC2.3 API: approving another user's form still works regardless of form:approve-self."""
        creator = _create_user(user_factory, "feat7-api-other-creator@example.com")
        approver = _create_user(user_factory, "feat7-api-other-approver@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        # Approver does NOT have form:approve-self — should still work
        client = client_factory(
            approver,
            _perms("form:approve", "form:review"),
        )
        resp = client.post(f"/api/v1/staff/forms/{form.id}/approve")

        assert resp.status_code == 200
        assert resp.json()["status"] == "published"

    @pytest.mark.integration
    def test_api_approve_self_permission_alone_does_not_bypass_approve_review(
        self, db, user_factory, client_factory
    ):
        """Security: form:approve-self without form:approve+form:review still gets 403."""
        creator = _create_user(user_factory, "feat7-api-perm-only@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        # Only has form:approve-self — missing form:approve and form:review
        client = client_factory(creator, _perms("form:approve-self"))
        resp = client.post(f"/api/v1/staff/forms/{form.id}/approve")

        assert resp.status_code == 403
