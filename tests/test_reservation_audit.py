"""TASK-412 — Audit trail verification tests.

Verifies that every reservation action writes the correct audit log entry
with the expected fields: action type, timestamp, user, prefix, number,
request id, and description.

Covers:
  - RESERVE_NUMBER logged for auto-generated reservations
  - RESERVE_SPECIAL_NUMBER logged for custom reservations
  - SUBMIT_FOR_APPROVAL logged on submission
  - APPROVE_RESERVATION / REJECT_RESERVATION / REQUEST_CHANGES logged
  - RELEASE_NUMBER / RESERVATION_EXPIRED logged
  - Audit entries contain required fields
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import (
    AuditLog,
    FormNumberReservation,
)
from backend.services.reservations import ReservationService


def _get_audits(db, entity_id: str, action: str | None = None) -> list[AuditLog]:
    """Helper to fetch audit logs for a given entity."""
    q = db.query(AuditLog).filter(AuditLog.entity_id == entity_id)
    if action:
        q = q.filter(AuditLog.action == action)
    return q.all()


# =========================================================================
# RESERVE_NUMBER (auto-generated)
# =========================================================================

class TestAuditReserveNumber:
    """RESERVE_NUMBER audit log for auto-generated reservations."""

    @pytest.mark.audit
    def test_auto_generate_creates_audit(self, db, active_prefix, staff_user):
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        audits = _get_audits(db, str(r.id), "RESERVE_NUMBER")
        assert len(audits) == 1

        a = audits[0]
        assert a.entity_type == "form_number_reservations"
        assert a.user_id == staff_user.id
        assert a.new_values is not None
        assert a.new_values["prefix"] == "H"
        assert a.new_values["form_number"] == r.form_number
        assert a.new_values["full_form_number"] == r.full_form_number
        assert a.new_values["numbering_method"] == "auto_generated"
        assert "expires_at" in a.new_values
        assert a.description is not None
        assert r.full_form_number in a.description
        assert a.created_at is not None


# =========================================================================
# RESERVE_SPECIAL_NUMBER (custom)
# =========================================================================

class TestAuditReserveSpecialNumber:
    """RESERVE_SPECIAL_NUMBER audit log for custom reservations."""

    @pytest.mark.audit
    def test_custom_generates_audit(self, db, active_prefix, staff_user):
        r = ReservationService.reserve_custom(
            db, active_prefix.id, "CUST1", "Special reason", staff_user.id,
        )
        audits = _get_audits(db, str(r.id), "RESERVE_SPECIAL_NUMBER")
        assert len(audits) == 1

        a = audits[0]
        assert a.entity_type == "form_number_reservations"
        assert a.user_id == staff_user.id
        assert a.new_values["numbering_method"] == "custom"
        assert a.new_values["custom_number_reason"] == "Special reason"
        assert a.new_values["full_form_number"] == "HCUST1"
        assert a.created_at is not None


# =========================================================================
# SUBMIT_FOR_APPROVAL
# =========================================================================

class TestAuditSubmitForApproval:
    """SUBMIT_FOR_APPROVAL audit log on submission."""

    @pytest.mark.audit
    def test_submit_creates_audit(self, db, active_prefix, staff_user, approver_user):
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        r = ReservationService.submit_for_approval(db, r.id, staff_user.id)

        audits = _get_audits(db, str(r.id), "SUBMIT_FOR_APPROVAL")
        assert len(audits) == 1

        a = audits[0]
        assert a.user_id == staff_user.id
        assert a.old_values["status"] == "reserved"
        assert a.new_values["status"] == "pending_approval"
        assert a.description is not None
        assert "submitted" in a.description.lower()


# =========================================================================
# APPROVE_RESERVATION
# =========================================================================

class TestAuditApproveReservation:
    """APPROVE_RESERVATION audit log."""

    @pytest.mark.audit
    def test_approve_creates_audit(self, db, active_prefix, staff_user, approver_user):
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        ReservationService.submit_for_approval(db, r.id, staff_user.id)
        r = ReservationService.approve_reservation(db, r.id, approver_user.id)

        audits = _get_audits(db, str(r.id), "APPROVE_RESERVATION")
        assert len(audits) == 1

        a = audits[0]
        assert a.user_id == approver_user.id
        assert a.old_values["status"] == "pending_approval"
        assert a.new_values["status"] == "approved"
        assert "approved" in a.description.lower()


# =========================================================================
# REJECT_RESERVATION
# =========================================================================

class TestAuditRejectReservation:
    """REJECT_RESERVATION audit log."""

    @pytest.mark.audit
    def test_reject_creates_audit(self, db, active_prefix, staff_user, approver_user):
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        ReservationService.submit_for_approval(db, r.id, staff_user.id)
        r = ReservationService.reject_reservation(
            db, r.id, approver_user.id, reason="Not needed",
        )

        audits = _get_audits(db, str(r.id), "REJECT_RESERVATION")
        assert len(audits) == 1

        a = audits[0]
        assert a.user_id == approver_user.id
        assert a.old_values["status"] == "pending_approval"
        assert a.new_values["status"] == "rejected"
        assert a.new_values["reason"] == "Not needed"
        assert "rejected" in a.description.lower()


# =========================================================================
# REQUEST_CHANGES
# =========================================================================

class TestAuditRequestChanges:
    """REQUEST_CHANGES audit log."""

    @pytest.mark.audit
    def test_request_changes_creates_audit(
        self, db, active_prefix, staff_user, approver_user
    ):
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        ReservationService.submit_for_approval(db, r.id, staff_user.id)
        r = ReservationService.request_changes(
            db, r.id, approver_user.id, comments="Fix the description",
        )

        audits = _get_audits(db, str(r.id), "REQUEST_CHANGES")
        assert len(audits) == 1

        a = audits[0]
        assert a.user_id == approver_user.id
        assert a.old_values["status"] == "pending_approval"
        assert a.new_values["status"] == "changes_requested"
        assert a.new_values["comments"] == "Fix the description"


# =========================================================================
# RELEASE_NUMBER
# =========================================================================

class TestAuditReleaseNumber:
    """RELEASE_NUMBER audit log."""

    @pytest.mark.audit
    def test_release_creates_audit(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user)
        ReservationService.release_reservation(
            db, r.id, staff_user.id, user_roles=["staff"],
        )

        audits = _get_audits(db, str(r.id), "RELEASE_NUMBER")
        assert len(audits) == 1

        a = audits[0]
        assert a.user_id == staff_user.id
        assert a.old_values["status"] == "reserved"
        assert a.new_values["status"] == "released"
        assert "released" in a.description.lower()


# =========================================================================
# RESERVATION_EXPIRED
# =========================================================================

class TestAuditReservationExpired:
    """RESERVATION_EXPIRED audit log."""

    @pytest.mark.audit
    def test_expire_creates_audit(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        old_date = datetime.now(timezone.utc) - timedelta(days=15)
        r = reservation_factory(
            prefix=active_prefix,
            reserved_by=staff_user,
            status="reserved",
            created_at=old_date,
        )
        ReservationService.expire_stale_reservations(db)

        audits = _get_audits(db, str(r.id), "RESERVATION_EXPIRED")
        assert len(audits) == 1

        a = audits[0]
        assert a.user_id is None  # system action
        assert a.new_values["status"] == "expired"
        assert "expired" in a.description.lower()


# =========================================================================
# Full Audit Trail for a Complete Workflow
# =========================================================================

class TestFullAuditTrail:
    """Verify complete audit trail for an entire workflow lifecycle."""

    @pytest.mark.audit
    def test_full_workflow_audit_trail(
        self, db, active_prefix, staff_user, approver_user
    ):
        # 1. Reserve
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        # 2. Submit
        ReservationService.submit_for_approval(db, r.id, staff_user.id)
        # 3. Request changes
        ReservationService.request_changes(
            db, r.id, approver_user.id, comments="update",
        )
        # 4. Resubmit
        ReservationService.resubmit(db, r.id, staff_user.id)
        # 5. Approve
        ReservationService.approve_reservation(db, r.id, approver_user.id)

        all_audits = _get_audits(db, str(r.id))
        actions = [a.action for a in all_audits]

        assert "RESERVE_NUMBER" in actions
        assert "SUBMIT_FOR_APPROVAL" in actions
        assert "REQUEST_CHANGES" in actions
        # Resubmit also logs SUBMIT_FOR_APPROVAL
        assert actions.count("SUBMIT_FOR_APPROVAL") == 2
        assert "APPROVE_RESERVATION" in actions

        # All audit entries have required fields
        for a in all_audits:
            assert a.entity_type == "form_number_reservations"
            assert a.entity_id == str(r.id)
            assert a.created_at is not None
            assert a.description is not None
