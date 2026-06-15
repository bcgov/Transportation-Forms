"""FEAT-0016: Revert Published Form to Draft.

Covers all test cases from:
  TC-US-001 (TC1.1 – TC1.14) — Revert Published Form to Draft (US-001)
  TC-US-002 (TC2.1 – TC2.7)  — Reverted Draft Ownership and Review (US-002)

Traceability:
  AC1  → TC1.1
  AC2  → TC1.2, TC1.3, TC1.4, TC1.14
  AC3  → TC1.5, TC1.6
  AC4  → TC1.7
  AC5  → TC1.8
  AC6  → TC1.9
  AC7  → TC1.10, TC1.12
  AC8  → TC1.11
  CONFLICT-01 (state machine)    → TC1.13
  CONFLICT-03 (audit ownership)  → TC1.12
  GAP-03 (reviewer role denial)  → TC1.14
  US-002 AC1–AC7                 → TC2.1 – TC2.7
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import DEFAULT_ROLES, Permission
from backend.database import get_db
from backend.main import app
from backend.models import AuditLog, Form, FormWorkflow, Role, UserRole
from backend.services.forms import (
    FormService,
    FormWorkflowValidationError,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REVERT_URL = "/api/v1/staff/forms/{form_id}/revert"
_SUBMIT_URL = "/api/v1/staff/forms/{form_id}/submit"
_VALID_REASON = "Correcting published content"
_REVIEWER_PERMS = [
    p.value if hasattr(p, "value") else str(p)
    for p in DEFAULT_ROLES["reviewer"]["permissions"]
]
_STAFF_MANAGER_PERMS = [
    p.value if hasattr(p, "value") else str(p)
    for p in DEFAULT_ROLES["staff_manager"]["permissions"]
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_factory, email: str):
    return user_factory(email=email, first_name="FEAT0016", last_name="Tester")


def _make_published_form(db: Session, owner_id) -> Form:
    form = Form(
        id=uuid.uuid4(),
        title="FEAT-0016 Published Form",
        description="Form for revert tests",
        status="published",
        is_public=True,
        current_version=1,
        keywords=["test"],
        created_by_id=owner_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(form)
    db.flush()
    return form


def _make_client(db: Session, user, permissions: list[str]) -> TestClient:
    """Build a TestClient with the given permission set."""
    role = Role(
        id=uuid.uuid4(),
        name=f"feat_0016_{uuid.uuid4().hex}",
        permissions=permissions,
        is_active=True,
    )
    db.add(role)
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()

    def _get_user(_request: Request) -> TokenData:
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


def _cleanup() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def _revert_perms() -> list[str]:
    return ["form:create", "form:edit"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def original_owner(user_factory):
    return _make_user(user_factory, "orig-owner-0016@example.com")


@pytest.fixture()
def reverting_user(user_factory):
    return _make_user(user_factory, "reverter-0016@example.com")


@pytest.fixture()
def published_form(db: Session, original_owner) -> Form:
    return _make_published_form(db, original_owner.id)


# ===========================================================================
# TC1 — US-001: Revert Published Form to Draft
# ===========================================================================


class TestTC1RevertPublishedFormToDraft:

    # --- TC1.1: Positive path -----------------------------------------------

    def test_tc1_1_authorized_revert_succeeds(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.1 (AC1): Authorized staff with both permissions reverts successfully."""
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "draft"
        finally:
            _cleanup()

    # --- TC1.2: Missing form:create -----------------------------------------

    def test_tc1_2_missing_form_create_denied(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.2 (AC2): form:edit only → 403; form remains published."""
        client = _make_client(db, reverting_user, ["form:edit"])
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 403
            db.refresh(published_form)
            assert published_form.status == "published"
        finally:
            _cleanup()

    # --- TC1.3: Missing form:edit -------------------------------------------

    def test_tc1_3_missing_form_edit_denied(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.3 (AC2): form:create only → 403; form remains published."""
        client = _make_client(db, reverting_user, ["form:create"])
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 403
            db.refresh(published_form)
            assert published_form.status == "published"
        finally:
            _cleanup()

    # --- TC1.4: Unauthenticated / no permissions ----------------------------

    def test_tc1_4_no_permissions_denied(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.4 (AC2): No relevant permissions → 403; form remains published."""
        client = _make_client(db, reverting_user, ["form:read"])
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 403
            db.refresh(published_form)
            assert published_form.status == "published"
        finally:
            _cleanup()

    # --- TC1.5: Reason missing (422 from Pydantic) --------------------------

    def test_tc1_5_missing_reason_rejected(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.5 (AC3): Body with no reason_notes → 422; form remains published."""
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={},
            )
            assert resp.status_code == 422
            db.refresh(published_form)
            assert published_form.status == "published"
        finally:
            _cleanup()

    # --- TC1.6: Whitespace-only reason --------------------------------------

    def test_tc1_6_whitespace_reason_rejected(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.6 (AC3): Whitespace-only reason → 400; form remains published."""
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": "   "},
            )
            assert resp.status_code == 400
            db.refresh(published_form)
            assert published_form.status == "published"
        finally:
            _cleanup()

    # --- TC1.7: Non-published form cannot be reverted -----------------------

    def test_tc1_7_non_published_form_rejected(
        self, db: Session, reverting_user, original_owner
    ):
        """TC1.7 (AC4): Draft form reverted → 400; status unchanged."""
        draft_form = Form(
            id=uuid.uuid4(),
            title="Draft Form",
            description="Not published",
            status="draft",
            is_public=False,
            current_version=0,
            keywords=[],
            created_by_id=original_owner.id,
        )
        db.add(draft_form)
        db.flush()

        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(draft_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 400
            db.refresh(draft_form)
            assert draft_form.status == "draft"
        finally:
            _cleanup()

    # --- TC1.8: Reverted draft is not publicly visible ----------------------

    def test_tc1_8_reverted_form_hidden_from_public(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.8 (AC5): After revert, form status is 'draft' — excluded by
        public_forms_v (which filters status='published' AND is_public=True)."""
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        db.refresh(published_form)
        # The public_forms_v view filters status='published'; a draft form is hidden.
        assert published_form.status == "draft"

    # --- TC1.9: Same record, no duplicate -----------------------------------

    def test_tc1_9_same_record_no_duplicate(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.9 (AC6): Form ID and record are unchanged after revert."""
        original_id = published_form.id
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        all_forms = db.query(Form).filter(Form.id == original_id).all()
        assert len(all_forms) == 1
        assert all_forms[0].status == "draft"

    # --- TC1.10: Workflow and audit history captured ------------------------

    def test_tc1_10_workflow_and_audit_history(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.10 (AC7): Workflow and audit history exist after revert."""
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        workflow_entry = (
            db.query(FormWorkflow)
            .filter(
                FormWorkflow.form_id == published_form.id,
                FormWorkflow.action == "revert",
            )
            .first()
        )
        assert workflow_entry is not None
        assert str(workflow_entry.from_status) == "published"
        assert str(workflow_entry.to_status) == "draft"
        assert str(workflow_entry.triggered_by_id) == str(reverting_user.id)
        assert workflow_entry.reason_notes == _VALID_REASON

        audit_entry = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_id == str(published_form.id),
                AuditLog.action == "WORKFLOW_TRANSITION",
            )
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert audit_entry is not None
        assert str(audit_entry.user_id) == str(reverting_user.id)

    # --- TC1.11: No original owner notification -----------------------------

    def test_tc1_11_no_original_owner_notification(
        self, db: Session, reverting_user, published_form, original_owner
    ):
        """TC1.11 (AC8): The feature does not emit any notification record.

        The system has no notification table/mechanism; this verifies that
        the only workflow entry created is the revert action itself and does
        not include any 'notify' or 'email' action rows.
        """
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        notification_entries = (
            db.query(FormWorkflow)
            .filter(
                FormWorkflow.form_id == published_form.id,
                FormWorkflow.action.in_(["notify", "email", "notification"]),
            )
            .all()
        )
        assert notification_entries == []

    # --- TC1.12: Audit log captures ownership change fields (CONFLICT-03) ---

    def test_tc1_12_audit_log_captures_ownership_change(
        self, db: Session, reverting_user, published_form, original_owner
    ):
        """TC1.12 (AC7 / CONFLICT-03): Audit log includes prior and new owner UUIDs."""
        prior_owner_id = str(published_form.created_by_id)

        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        audit_entry = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_id == str(published_form.id),
                AuditLog.action == "WORKFLOW_TRANSITION",
            )
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert audit_entry is not None
        old_vals = audit_entry.old_values
        new_vals = audit_entry.new_values

        assert old_vals["created_by_id"] == prior_owner_id
        assert new_vals["created_by_id"] == str(reverting_user.id)
        assert old_vals["status"] == "published"
        assert new_vals["status"] == "draft"
        assert new_vals["reason_notes"] == _VALID_REASON

    # --- TC1.13: State machine allows published → draft (CONFLICT-01) -------

    def test_tc1_13_state_machine_allows_published_to_draft(self):
        """TC1.13 (CONFLICT-01): VALID_TRANSITIONS["published"] now includes 'draft'."""
        allowed = FormService.VALID_TRANSITIONS.get("published", [])
        assert "draft" in allowed

    # --- TC1.14: Reviewer role (form:approve only) cannot revert (GAP-03) ---

    def test_tc1_14_reviewer_role_denied(
        self, db: Session, reverting_user, published_form
    ):
        """TC1.14 (AC2 / GAP-03): reviewer role lacks form:create/form:edit → 403."""
        # Reviewer has form:approve, form:review, form:archive but NOT form:create or form:edit
        client = _make_client(db, reverting_user, _REVIEWER_PERMS)
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 403
            db.refresh(published_form)
            assert published_form.status == "published"
        finally:
            _cleanup()


# ===========================================================================
# TC2 — US-002: Reverted Draft Ownership and Review Continuation
# ===========================================================================


class TestTC2RevertedDraftOwnershipAndReview:

    # --- TC2.1: Ownership transfer is visible --------------------------------

    def test_tc2_1_ownership_transfer(
        self, db: Session, reverting_user, published_form, original_owner
    ):
        """TC2.1 (AC1): After revert, reverting user is the form owner."""
        assert str(published_form.created_by_id) == str(original_owner.id)

        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        db.refresh(published_form)
        assert str(published_form.created_by_id) == str(reverting_user.id)

    # --- TC2.2: New owner can edit as Draft ---------------------------------

    def test_tc2_2_new_owner_can_edit_draft(
        self, db: Session, reverting_user, published_form
    ):
        """TC2.2 (AC2): New owner can PUT the reverted draft under normal edit rules."""
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            resp = client.put(
                f"/api/v1/forms/{published_form.id}",
                json={"title": "Updated after revert"},
            )
            assert resp.status_code == 200
            assert resp.json()["title"] == "Updated after revert"
        finally:
            _cleanup()

    # --- TC2.3: New owner can submit for review ------------------------------

    def test_tc2_3_new_owner_can_submit_for_review(
        self, db: Session, reverting_user, published_form
    ):
        """TC2.3 (AC3): New owner can submit the reverted Draft through normal flow."""
        client = _make_client(
            db,
            reverting_user,
            _revert_perms() + ["form:submit_for_review"],
        )
        try:
            revert_resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert revert_resp.status_code == 200

            submit_resp = client.post(
                _SUBMIT_URL.format(form_id=str(published_form.id))
            )
            assert submit_resp.status_code == 200
            assert submit_resp.json()["status"] == "pending_review"
        finally:
            _cleanup()

    # --- TC2.4: Previous owner cannot submit after transfer ------------------

    def test_tc2_4_previous_owner_cannot_submit(
        self, db: Session, reverting_user, published_form, original_owner, user_factory
    ):
        """TC2.4 (AC4): Previous owner is denied submit after ownership transfer."""
        # Revert as reverting_user (new owner)
        revert_client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = revert_client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        # Previous owner attempts submit → 403 (no longer owner)
        prev_owner_client = _make_client(
            db,
            original_owner,
            ["form:submit_for_review"],
        )
        try:
            submit_resp = prev_owner_client.post(
                _SUBMIT_URL.format(form_id=str(published_form.id))
            )
            assert submit_resp.status_code == 403
            db.refresh(published_form)
            assert published_form.status == "draft"
        finally:
            _cleanup()

    # --- TC2.5: Non-owner cannot submit -------------------------------------

    def test_tc2_5_non_owner_cannot_submit(
        self, db: Session, reverting_user, published_form, user_factory
    ):
        """TC2.5 (AC5): Any non-owner is denied submit on the reverted Draft."""
        # Revert as reverting_user
        revert_client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = revert_client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        other_user = _make_user(user_factory, "other-0016@example.com")
        other_client = _make_client(db, other_user, ["form:submit_for_review"])
        try:
            submit_resp = other_client.post(
                _SUBMIT_URL.format(form_id=str(published_form.id))
            )
            assert submit_resp.status_code == 403
        finally:
            _cleanup()

    # --- TC2.6: Review workflow continues unchanged -------------------------

    def test_tc2_6_review_workflow_continues_unchanged(
        self, db: Session, reverting_user, published_form, user_factory
    ):
        """TC2.6 (AC6): Revert does not break the subsequent review/approve cycle."""
        # Revert and submit for review as reverting_user
        revert_and_submit_client = _make_client(
            db,
            reverting_user,
            _revert_perms() + ["form:submit_for_review"],
        )
        try:
            client_resp = revert_and_submit_client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert client_resp.status_code == 200
            submit_resp = revert_and_submit_client.post(
                _SUBMIT_URL.format(form_id=str(published_form.id))
            )
            assert submit_resp.status_code == 200
            assert submit_resp.json()["status"] == "pending_review"
        finally:
            _cleanup()

        # Approve as a different user
        approver = _make_user(user_factory, "approver-0016@example.com")
        approve_client = _make_client(
            db, approver, ["form:approve", "form:review"]
        )
        try:
            approve_resp = approve_client.post(
                f"/api/v1/staff/forms/{published_form.id}/approve"
            )
            assert approve_resp.status_code == 200
            assert approve_resp.json()["status"] == "published"
        finally:
            _cleanup()

    # --- TC2.7: Public visibility follows Draft state -----------------------

    def test_tc2_7_public_visibility_follows_draft_state(
        self, db: Session, reverting_user, published_form
    ):
        """TC2.7 (AC7): After revert the form is Draft; public_forms_v
        (status='published' AND is_public=True) therefore excludes it."""
        client = _make_client(db, reverting_user, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(published_form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        db.refresh(published_form)
        assert published_form.status == "draft"
        # is_public is irrelevant once status is draft — the view's WHERE clause
        # (status='published') already excludes the form.

    # --- Self-revert: reverting user was already the owner ------------------

    def test_self_revert_owner_unchanged(
        self, db: Session, original_owner, user_factory
    ):
        """EC-001 (US-002): Reverting user already owns the form — ownership
        stays with that user and the revert is still audited."""
        form = _make_published_form(db, original_owner.id)

        client = _make_client(db, original_owner, _revert_perms())
        try:
            resp = client.post(
                _REVERT_URL.format(form_id=str(form.id)),
                json={"reason_notes": _VALID_REASON},
            )
            assert resp.status_code == 200
        finally:
            _cleanup()

        db.refresh(form)
        assert form.status == "draft"
        assert str(form.created_by_id) == str(original_owner.id)

        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_id == str(form.id),
                AuditLog.action == "WORKFLOW_TRANSITION",
            )
            .first()
        )
        assert audit is not None


# ===========================================================================
# Service-layer unit tests (no HTTP)
# ===========================================================================


class TestRevertFormToDraftServiceUnit:

    @pytest.mark.integration
    def test_blank_reason_raises_validation_error(self, db: Session, user_factory):
        """Service rejects blank reason before hitting the database."""
        owner = _make_user(user_factory, "svc-blank-0016@example.com")
        form = _make_published_form(db, owner.id)

        with pytest.raises(FormWorkflowValidationError, match="reason_notes"):
            FormService.revert_form_to_draft(db, form.id, owner.id, "   ")

    @pytest.mark.integration
    def test_pending_review_form_rejected_by_state_machine(
        self, db: Session, user_factory
    ):
        """Service raises FormWorkflowValidationError for non-published form."""
        owner = _make_user(user_factory, "svc-pr-0016@example.com")
        form = Form(
            id=uuid.uuid4(),
            title="Pending",
            status="pending_review",
            is_public=False,
            current_version=0,
            keywords=[],
            created_by_id=owner.id,
        )
        db.add(form)
        db.flush()

        with pytest.raises(FormWorkflowValidationError, match="Invalid transition"):
            FormService.revert_form_to_draft(
                db, form.id, owner.id, "A valid reason"
            )

    @pytest.mark.integration
    def test_ownership_transfer_persisted(self, db: Session, user_factory):
        """Service sets created_by_id to reverting user."""
        owner = _make_user(user_factory, "svc-owner-0016@example.com")
        reverter = _make_user(user_factory, "svc-reverter-0016@example.com")
        form = _make_published_form(db, owner.id)

        result = FormService.revert_form_to_draft(
            db, form.id, reverter.id, "Valid reason"
        )

        assert str(result.created_by_id) == str(reverter.id)
        assert result.status == "draft"

    @pytest.mark.integration
    def test_workflow_entry_created(self, db: Session, user_factory):
        """Service writes a FormWorkflow row with action='revert'."""
        owner = _make_user(user_factory, "svc-wf-0016@example.com")
        form = _make_published_form(db, owner.id)
        reason = "Revert reason for workflow test"

        FormService.revert_form_to_draft(db, form.id, owner.id, reason)

        entry = (
            db.query(FormWorkflow)
            .filter(
                FormWorkflow.form_id == form.id,
                FormWorkflow.action == "revert",
            )
            .first()
        )
        assert entry is not None
        assert entry.reason_notes == reason
        assert entry.from_status == "published"
        assert entry.to_status == "draft"

    @pytest.mark.integration
    def test_audit_log_includes_owner_fields(self, db: Session, user_factory):
        """Service writes old and new created_by_id in AuditLog (CONFLICT-03)."""
        owner = _make_user(user_factory, "svc-audit-owner-0016@example.com")
        reverter = _make_user(user_factory, "svc-audit-rev-0016@example.com")
        form = _make_published_form(db, owner.id)
        reason = "Audit ownership test reason"

        FormService.revert_form_to_draft(db, form.id, reverter.id, reason)

        entry = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_id == str(form.id),
                AuditLog.action == "WORKFLOW_TRANSITION",
            )
            .first()
        )
        assert entry is not None
        assert entry.old_values["created_by_id"] == str(owner.id)
        assert entry.new_values["created_by_id"] == str(reverter.id)
        assert entry.old_values["status"] == "published"
        assert entry.new_values["status"] == "draft"
        assert entry.new_values["reason_notes"] == reason
