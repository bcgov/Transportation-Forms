import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
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
