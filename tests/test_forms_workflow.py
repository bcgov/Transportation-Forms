import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import DEFAULT_ROLES
from backend.database import get_db
from backend.main import app
from backend.models import Form, FormWorkflow
from backend.services.forms import (
    FormService,
    FormWorkflowConflictError,
    FormWorkflowValidationError,
)


def _create_user(user_factory, email: str):
    return user_factory(email=email, first_name="Workflow", last_name="Tester")


def _create_form(db, creator_id, *, status="draft", reservation_id=None):
    form = Form(
        id=uuid.uuid4(),
        title="Workflow Test Form",
        description="Form used for workflow tests",
        status=status,
        is_public=False,
        current_version=0,
        keywords=[],
        created_by_id=creator_id,
        form_number_reservation_id=reservation_id,
    )
    db.add(form)
    db.flush()
    return form


def _perms_for_roles(*role_names: str) -> list:
    """Return the flat union of permissions for the given role names."""
    perms = set()
    for name in role_names:
        role_cfg = DEFAULT_ROLES.get(name, {})
        for p in role_cfg.get("permissions", []):
            perms.add(p.value if hasattr(p, "value") else str(p))
    return list(perms)


class TestFormWorkflowService:
    @pytest.mark.integration
    def test_happy_path_draft_to_archived(self, db, user_factory):
        """FEAT-0001: approve_form now transitions directly to published (no intermediate approved state)."""
        creator = _create_user(user_factory, "creator-happy@example.com")
        reviewer = _create_user(user_factory, "reviewer-happy@example.com")
        form = _create_form(db, creator.id, status="draft")
        form_id = uuid.UUID(str(form.id))

        submitted = FormService.submit_form_for_review(db, form_id, reviewer.id)
        assert str(submitted.status) == "pending_review"

        # FEAT-0001: approve now goes directly to published
        published = FormService.approve_form(db, form_id, reviewer.id)
        assert str(published.status) == "published"

        archived = FormService.archive_form(db, form_id, user_id=reviewer.id)
        assert archived is not None
        assert str(archived.status) == "archived"

        history = (
            db.query(FormWorkflow)
            .filter(FormWorkflow.form_id == form.id)
            .order_by(FormWorkflow.created_at.asc())
            .all()
        )
        # FEAT-0001: 3 steps — no more separate "approve" + "publish"
        assert [entry.action for entry in history] == ["submit", "approve", "archive"]

    @pytest.mark.integration
    def test_reject_requires_reason_and_returns_to_draft(self, db, user_factory):
        creator = _create_user(user_factory, "creator-reject@example.com")
        reviewer = _create_user(user_factory, "reviewer-reject@example.com")
        form = _create_form(db, creator.id, status="draft")
        form_id = uuid.UUID(str(form.id))

        FormService.submit_form_for_review(db, form_id, reviewer.id)

        with pytest.raises(FormWorkflowValidationError, match=r"Rejection reason \(reason_notes\) is required"):
            FormService.reject_form(db, form_id, reviewer.id, "")

        rejected = FormService.reject_form(db, form_id, reviewer.id, "Missing legal text")
        assert str(rejected.status) == "draft"

        latest = (
            db.query(FormWorkflow)
            .filter(FormWorkflow.form_id == form.id)
            .order_by(FormWorkflow.created_at.desc())
            .first()
        )
        assert latest.action == "reject"
        assert latest.reason_notes == "Missing legal text"

    @pytest.mark.integration
    def test_submit_requires_approved_reservation_when_linked(
        self, db, user_factory, prefix_factory, reservation_factory
    ):
        creator = _create_user(user_factory, "creator-resv@example.com")
        reviewer = _create_user(user_factory, "reviewer-resv@example.com")
        prefix = prefix_factory(prefix="WF")
        reservation = reservation_factory(
            prefix=prefix,
            form_number="9001",
            full_form_number="WF9001",
            status="reserved",
            reserved_by=creator,
        )
        form = _create_form(db, creator.id, status="draft", reservation_id=reservation.id)
        form_id = uuid.UUID(str(form.id))

        with pytest.raises(FormWorkflowConflictError, match="Form number reservation must be approved before submission"):
            FormService.submit_form_for_review(db, form_id, reviewer.id)

    @pytest.mark.integration
    def test_invalid_transition_draft_to_published_rejected(self, db, user_factory):
        """FEAT-0001: draft→published is not a valid transition (HTTP 400)."""
        creator = _create_user(user_factory, "creator-transition@example.com")
        reviewer = _create_user(user_factory, "reviewer-transition@example.com")

        draft_form = _create_form(db, creator.id, status="draft")
        draft_form_id = uuid.UUID(str(draft_form.id))
        with pytest.raises(FormWorkflowValidationError, match="Invalid transition from 'draft' to 'published'"):
            FormService.publish_form(db, draft_form_id, reviewer.id)

    @pytest.mark.integration
    def test_idempotency_already_published_blocked(self, db, user_factory):
        """FEAT-0001: approving a form already in published state is rejected."""
        creator = _create_user(user_factory, "creator-published-idem@example.com")
        reviewer = _create_user(user_factory, "reviewer-published-idem@example.com")

        published_form = _create_form(db, creator.id, status="published")
        published_form_id = uuid.UUID(str(published_form.id))
        with pytest.raises(FormWorkflowValidationError, match="Form is already in 'published' state"):
            FormService.approve_form(db, published_form_id, reviewer.id)

    @pytest.mark.integration
    def test_separation_of_duties_always_blocks_self_approval(self, db, user_factory):
        """FEAT-0001: SoD is always enforced — no DB toggle needed."""
        creator = _create_user(user_factory, "creator-sod@example.com")
        form = _create_form(db, creator.id, status="pending_review")
        form_id = uuid.UUID(str(form.id))

        with pytest.raises(FormWorkflowValidationError, match="You cannot approve your own form submission"):
            FormService.approve_form(db, form_id, creator.id)

    @pytest.mark.integration
    def test_reject_whitespace_reason_rejected(self, db, user_factory):
        """FEAT-0001: A whitespace-only reason string is rejected (TC-004.2)."""
        creator = _create_user(user_factory, "creator-ws@example.com")
        reviewer = _create_user(user_factory, "reviewer-ws@example.com")
        form = _create_form(db, creator.id, status="pending_review")
        form_id = uuid.UUID(str(form.id))

        with pytest.raises(FormWorkflowValidationError, match=r"Rejection reason \(reason_notes\) is required"):
            FormService.reject_form(db, form_id, reviewer.id, "    ")


class TestFormWorkflowApi:
    @pytest.fixture()
    def client_factory(self, db):
        def _build(user, roles, permissions=None):
            # If permissions not explicitly provided, derive from role names
            effective_permissions = (
                permissions if permissions is not None else _perms_for_roles(*roles)
            )
            token = TokenData(
                sub=str(user.id),
                email=user.email,
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
    def test_reviewer_can_approve_directly_to_published(self, db, user_factory, client_factory):
        """FEAT-0001: /approve endpoint transitions pending_review → published directly."""
        creator = _create_user(user_factory, "creator-api-role@example.com")
        reviewer = _create_user(user_factory, "reviewer-api-role@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        reviewer_client = client_factory(reviewer, ["reviewer"])

        approve_resp = reviewer_client.post(f"/api/v1/staff/forms/{form.id}/approve")
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "published"

    @pytest.mark.integration
    def test_reviewer_cannot_archive(self, db, user_factory, client_factory):
        """Reviewer role does not carry form:approve sufficient for archive."""
        creator = _create_user(user_factory, "creator-arch@example.com")
        reviewer = _create_user(user_factory, "reviewer-arch@example.com")
        form = _create_form(db, creator.id, status="published")

        reviewer_client = client_factory(reviewer, ["reviewer"])
        archive_resp = reviewer_client.post(f"/api/v1/staff/forms/{form.id}/archive")
        assert archive_resp.status_code == 403

    @pytest.mark.integration
    def test_reject_endpoint_requires_reason_notes(self, db, user_factory, client_factory):
        creator = _create_user(user_factory, "creator-api-reject@example.com")
        reviewer = _create_user(user_factory, "reviewer-api-reject@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.post(
            f"/api/v1/staff/forms/{form.id}/reject",
            json={"reason_notes": ""},
        )
        assert resp.status_code == 400
        assert "reason" in resp.json()["detail"].lower()

    @pytest.mark.integration
    def test_workflow_history_returns_desc_order(self, db, user_factory, client_factory):
        creator = _create_user(user_factory, "creator-api-history@example.com")
        reviewer = _create_user(user_factory, "reviewer-api-history@example.com")
        form = _create_form(db, creator.id, status="draft")
        form_id = uuid.UUID(str(form.id))

        FormService.submit_form_for_review(db, form_id, reviewer.id)
        FormService.reject_form(db, form_id, reviewer.id, "Needs edits")

        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.get(f"/api/v1/staff/forms/{form.id}/workflow-history")

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 2
        assert items[0]["action"] == "reject"
        assert items[1]["action"] == "submit"

    @pytest.mark.integration
    def test_creator_cannot_submit_without_permission(self, db, user_factory, client_factory):
        """FEAT-0001 US-002: user without form:submit_for_review gets 403."""
        creator = _create_user(user_factory, "creator-noperm@example.com")
        form = _create_form(db, creator.id, status="draft")
        # staff_viewer has no form:submit_for_review
        no_submit_client = client_factory(creator, ["staff_viewer"])
        resp = no_submit_client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_creator_cannot_approve_own_form_via_api(self, db, user_factory, client_factory):
        """FEAT-0001 BR-002: creator with approve permission cannot approve own form."""
        creator = _create_user(user_factory, "creator-sod-api@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        # Give creator both submit and approve permissions (unusual but possible)
        both_perms = _perms_for_roles("staff_manager", "reviewer")
        creator_client = client_factory(creator, ["staff_manager", "reviewer"], permissions=both_perms)
        resp = creator_client.post(f"/api/v1/staff/forms/{form.id}/approve")
        assert resp.status_code == 400
        assert "cannot approve your own" in resp.json()["detail"].lower()

    @pytest.mark.integration
    def test_creator_cannot_publish_pending_form(self, db, user_factory, client_factory):
        """FEAT-0001 US-002 AC2: creator-only user cannot approve (publish) a form."""
        creator = _create_user(user_factory, "creator-noapprove@example.com")
        form = _create_form(db, creator.id, status="pending_review")
        # staff_manager has form:submit_for_review but not form:approve+form:review alone
        creator_client = client_factory(
            creator, ["staff_manager"],
            permissions=_perms_for_roles("staff_manager"),
        )
        # Remove approve permission to simulate creator-only
        creator_perms = [p for p in _perms_for_roles("staff_manager")
                         if p not in ("form:approve", "form:review")]
        limited_client = client_factory(creator, ["staff_manager"], permissions=creator_perms)
        resp = limited_client.post(f"/api/v1/staff/forms/{form.id}/approve")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_pending_review_form_cannot_be_edited(self, db, user_factory, client_factory):
        """FEAT-0001 BR-003: forms in pending_review state cannot be edited by anyone."""
        creator = _create_user(user_factory, "creator-locked@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        manager_client = client_factory(creator, ["staff_manager"])
        resp = manager_client.put(
            f"/api/v1/forms/{form.id}",
            json={"title": "Attempted edit"},
        )
        assert resp.status_code == 403
        assert "pending review" in resp.json()["detail"].lower()

    @pytest.mark.integration
    def test_pending_approvals_endpoint_returns_pending_review_forms(
        self, db, user_factory, client_factory
    ):
        """FEAT-0001 US-005: GET /staff/forms/pending-approvals returns forms in pending_review."""
        creator = _create_user(user_factory, "creator-pending-list@example.com")
        reviewer = _create_user(user_factory, "reviewer-pending-list@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.get("/api/v1/staff/forms/pending-approvals")

        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        ids = [item["form_id"] for item in data["items"]]
        assert str(form.id) in ids

    @pytest.mark.integration
    def test_pending_approvals_endpoint_requires_approve_and_review_permissions(
        self, db, user_factory, client_factory
    ):
        """FEAT-0001: pending-approvals endpoint requires form:approve AND form:review."""
        user = _create_user(user_factory, "creator-pending-unauth@example.com")
        # staff_viewer has no review/approve permissions
        no_perms_client = client_factory(user, ["staff_viewer"])
        resp = no_perms_client.get("/api/v1/staff/forms/pending-approvals")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_submit_form_not_found_returns_404(self, db, user_factory, client_factory):
        reviewer = _create_user(user_factory, "reviewer-notfound@example.com")
        reviewer_client = client_factory(reviewer, ["staff_manager"])
        resp = reviewer_client.post(f"/api/v1/staff/forms/{uuid.uuid4()}/submit")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_approve_form_not_found_returns_404(self, db, user_factory, client_factory):
        reviewer = _create_user(user_factory, "reviewer-notfound2@example.com")
        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.post(f"/api/v1/staff/forms/{uuid.uuid4()}/approve")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_archive_form_not_found_returns_404(self, db, user_factory, client_factory):
        admin = _create_user(user_factory, "admin-notfound@example.com")
        admin_client = client_factory(admin, ["admin"])
        resp = admin_client.post(f"/api/v1/staff/forms/{uuid.uuid4()}/archive")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_history_form_not_found_returns_404(self, db, user_factory, client_factory):
        reviewer = _create_user(user_factory, "reviewer-hist404@example.com")
        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.get(f"/api/v1/staff/forms/{uuid.uuid4()}/workflow-history")
        assert resp.status_code == 404


def _create_user(user_factory, email: str):
    return user_factory(email=email, first_name="Workflow", last_name="Tester")


def _create_form(db, creator_id, *, status="draft", reservation_id=None):
    form = Form(
        id=uuid.uuid4(),
        title="Workflow Test Form",
        description="Form used for workflow tests",
        status=status,
        is_public=False,
        current_version=0,
        keywords=[],
        created_by_id=creator_id,
        form_number_reservation_id=reservation_id,
    )
    db.add(form)
    db.flush()
    return form


class TestFormWorkflowService:
    @pytest.mark.integration
    def test_happy_path_draft_to_archived(self, db, user_factory):
        creator = _create_user(user_factory, "creator-happy@example.com")
        reviewer = _create_user(user_factory, "reviewer-happy@example.com")
        form = _create_form(db, creator.id, status="draft")
        form_id = uuid.UUID(str(form.id))

        submitted = FormService.submit_form_for_review(db, form_id, reviewer.id)
        assert str(submitted.status) == "pending_review"

        approved = FormService.approve_form(db, form_id, reviewer.id)
        assert str(approved.status) == "approved"

        published = FormService.publish_form(db, form_id, reviewer.id)
        assert str(published.status) == "published"

        archived = FormService.archive_form(db, form_id, user_id=reviewer.id)
        assert archived is not None
        assert str(archived.status) == "archived"

        history = (
            db.query(FormWorkflow)
            .filter(FormWorkflow.form_id == form.id)
            .order_by(FormWorkflow.created_at.asc())
            .all()
        )
        assert [entry.action for entry in history] == ["submit", "approve", "publish", "archive"]

    @pytest.mark.integration
    def test_reject_requires_reason_and_returns_to_draft(self, db, user_factory):
        creator = _create_user(user_factory, "creator-reject@example.com")
        reviewer = _create_user(user_factory, "reviewer-reject@example.com")
        form = _create_form(db, creator.id, status="draft")
        form_id = uuid.UUID(str(form.id))

        FormService.submit_form_for_review(db, form_id, reviewer.id)

        with pytest.raises(FormWorkflowValidationError, match=r"Rejection reason \(reason_notes\) is required"):
            FormService.reject_form(db, form_id, reviewer.id, "")

        rejected = FormService.reject_form(db, form_id, reviewer.id, "Missing legal text")
        assert str(rejected.status) == "draft"

        latest = (
            db.query(FormWorkflow)
            .filter(FormWorkflow.form_id == form.id)
            .order_by(FormWorkflow.created_at.desc())
            .first()
        )
        assert latest.action == "reject"
        assert latest.reason_notes == "Missing legal text"

    @pytest.mark.integration
    def test_submit_requires_approved_reservation_when_linked(
        self, db, user_factory, prefix_factory, reservation_factory
    ):
        creator = _create_user(user_factory, "creator-resv@example.com")
        reviewer = _create_user(user_factory, "reviewer-resv@example.com")
        prefix = prefix_factory(prefix="WF")
        reservation = reservation_factory(
            prefix=prefix,
            form_number="9001",
            full_form_number="WF9001",
            status="reserved",
            reserved_by=creator,
        )
        form = _create_form(db, creator.id, status="draft", reservation_id=reservation.id)
        form_id = uuid.UUID(str(form.id))

        with pytest.raises(FormWorkflowConflictError, match="Form number reservation must be approved before submission"):
            FormService.submit_form_for_review(db, form_id, reviewer.id)

    @pytest.mark.integration
    def test_invalid_transition_and_strict_idempotency(self, db, user_factory):
        creator = _create_user(user_factory, "creator-transition@example.com")
        reviewer = _create_user(user_factory, "reviewer-transition@example.com")

        draft_form = _create_form(db, creator.id, status="draft")
        draft_form_id = uuid.UUID(str(draft_form.id))
        with pytest.raises(FormWorkflowValidationError, match="Invalid transition from 'draft' to 'published'"):
            FormService.publish_form(db, draft_form_id, reviewer.id)

        approved_form = _create_form(db, creator.id, status="approved")
        approved_form_id = uuid.UUID(str(approved_form.id))
        with pytest.raises(FormWorkflowValidationError, match="Form is already in 'approved' state"):
            FormService.approve_form(db, approved_form_id, reviewer.id)

    @pytest.mark.integration
    def test_separation_of_duties_toggle_blocks_self_approval(self, db, user_factory):
        creator = _create_user(user_factory, "creator-sod@example.com")
        form = _create_form(db, creator.id, status="pending_review")
        form_id = uuid.UUID(str(form.id))

        db.execute(text("SELECT set_config('app.enforce_separation_of_duties', 'true', true)"))
        with pytest.raises(FormWorkflowValidationError, match="You cannot approve your own form submission"):
            FormService.approve_form(db, form_id, creator.id)


class TestFormWorkflowApi:
    @pytest.fixture()
    def client_factory(self, db):
        def _build(user, roles):
            token = TokenData(
                sub=str(user.id),
                email=user.email,
                name=f"{user.first_name} {user.last_name}",
                roles=roles,
                token_type="access",
            )
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_current_user] = lambda: token
            return TestClient(app)

        yield _build
        app.dependency_overrides.clear()

    @pytest.mark.integration
    def test_reviewer_can_publish_but_cannot_archive(self, db, user_factory, client_factory):
        creator = _create_user(user_factory, "creator-api-role@example.com")
        reviewer = _create_user(user_factory, "reviewer-api-role@example.com")
        form = _create_form(db, creator.id, status="approved")

        reviewer_client = client_factory(reviewer, ["reviewer"])

        publish_resp = reviewer_client.post(f"/api/v1/staff/forms/{form.id}/publish")
        assert publish_resp.status_code == 200
        assert publish_resp.json()["status"] == "published"

        archive_resp = reviewer_client.post(f"/api/v1/staff/forms/{form.id}/archive")
        assert archive_resp.status_code == 403

    @pytest.mark.integration
    def test_reject_endpoint_requires_reason_notes(self, db, user_factory, client_factory):
        creator = _create_user(user_factory, "creator-api-reject@example.com")
        reviewer = _create_user(user_factory, "reviewer-api-reject@example.com")
        form = _create_form(db, creator.id, status="pending_review")

        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.post(
            f"/api/v1/staff/forms/{form.id}/reject",
            json={"reason_notes": ""},
        )
        assert resp.status_code == 400
        assert "reason_notes" in resp.json()["detail"]

    @pytest.mark.integration
    def test_workflow_history_returns_desc_order(self, db, user_factory, client_factory):
        creator = _create_user(user_factory, "creator-api-history@example.com")
        reviewer = _create_user(user_factory, "reviewer-api-history@example.com")
        form = _create_form(db, creator.id, status="draft")
        form_id = uuid.UUID(str(form.id))

        FormService.submit_form_for_review(db, form_id, reviewer.id)
        FormService.reject_form(db, form_id, reviewer.id, "Needs edits")

        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.get(f"/api/v1/staff/forms/{form.id}/workflow-history")

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 2
        assert items[0]["action"] == "reject"
        assert items[1]["action"] == "submit"

    @pytest.mark.integration
    def test_insufficient_role_returns_403(self, db, user_factory, client_factory):
        """A user with no allowed role gets 403 on workflow endpoints."""
        creator = _create_user(user_factory, "creator-norole@example.com")
        form = _create_form(db, creator.id, status="draft")
        staff_client = client_factory(creator, ["staff_viewer"])
        resp = staff_client.post(f"/api/v1/staff/forms/{form.id}/submit")
        assert resp.status_code == 403

    @pytest.mark.integration
    def test_submit_form_not_found_returns_404(self, db, user_factory, client_factory):
        reviewer = _create_user(user_factory, "reviewer-notfound@example.com")
        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.post(f"/api/v1/staff/forms/{uuid.uuid4()}/submit")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_approve_form_not_found_returns_404(self, db, user_factory, client_factory):
        reviewer = _create_user(user_factory, "reviewer-notfound2@example.com")
        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.post(f"/api/v1/staff/forms/{uuid.uuid4()}/approve")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_publish_form_not_found_returns_404(self, db, user_factory, client_factory):
        reviewer = _create_user(user_factory, "reviewer-notfound3@example.com")
        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.post(f"/api/v1/staff/forms/{uuid.uuid4()}/publish")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_archive_form_not_found_returns_404(self, db, user_factory, client_factory):
        admin = _create_user(user_factory, "admin-notfound@example.com")
        admin_client = client_factory(admin, ["admin"])
        resp = admin_client.post(f"/api/v1/staff/forms/{uuid.uuid4()}/archive")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_history_form_not_found_returns_404(self, db, user_factory, client_factory):
        reviewer = _create_user(user_factory, "reviewer-hist404@example.com")
        reviewer_client = client_factory(reviewer, ["reviewer"])
        resp = reviewer_client.get(f"/api/v1/staff/forms/{uuid.uuid4()}/workflow-history")
        assert resp.status_code == 404
