"""TASK-412 — Integration tests for the form reservation feature.

End-to-end workflow scenarios exercised at the service layer with a
real PostgreSQL database through the full call stack.

Covers:
  - Happy path: generate → submit → approve
  - Reject path: generate → submit → reject → number released
  - Changes requested path: generate → submit → request changes → resubmit → approve
  - Custom number path: enter custom → submit → approve
  - Duplicate custom number blocked with correct error
  - Custom number does not affect auto-generation sequence
  - Released/expired numbers can be re-reserved
  - Role-based authorization enforcement
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import (
    AuditLog,
    FormNumberPrefix,
    FormNumberReservation,
    FormReservationApprover,
    Role,
    User,
    UserRole,
)
from backend.services.reservations import ReservationService


# =========================================================================
# Full Happy Path: generate → submit → approve
# =========================================================================

class TestHappyPath:
    """End-to-end happy path through the approval workflow."""

    @pytest.mark.integration
    def test_generate_submit_approve(
        self, db, active_prefix, staff_user, approver_user
    ):
        # 1. Generate a number
        reservation = ReservationService.reserve_auto_generated(
            db, active_prefix.id, staff_user.id,
        )
        assert reservation.status == "reserved"
        assert reservation.full_form_number == "H0001"

        # 2. Submit for approval
        reservation = ReservationService.submit_for_approval(
            db, reservation.id, staff_user.id,
        )
        assert reservation.status == "pending_approval"

        # 3. Approve
        reservation = ReservationService.approve_reservation(
            db, reservation.id, approver_user.id,
        )
        assert reservation.status == "approved"

        # Verify approver decision recorded
        approver_records = (
            db.query(FormReservationApprover)
            .filter(FormReservationApprover.reservation_id == reservation.id)
            .all()
        )
        approved_record = [
            a for a in approver_records if str(a.approver_id) == str(approver_user.id)
        ]
        assert len(approved_record) == 1
        assert approved_record[0].decision == "approved"
        assert approved_record[0].decided_at is not None


# =========================================================================
# Reject Path: generate → submit → reject → number released
# =========================================================================

class TestRejectPath:
    """Full reject workflow."""

    @pytest.mark.integration
    def test_generate_submit_reject(
        self, db, active_prefix, staff_user, approver_user
    ):
        reservation = ReservationService.reserve_auto_generated(
            db, active_prefix.id, staff_user.id,
        )
        reservation = ReservationService.submit_for_approval(
            db, reservation.id, staff_user.id,
        )
        assert reservation.status == "pending_approval"

        reservation = ReservationService.reject_reservation(
            db, reservation.id, approver_user.id, reason="Does not meet criteria",
        )
        assert reservation.status == "rejected"
        assert reservation.released_at is not None
        assert reservation.released_by_id == approver_user.id

    @pytest.mark.integration
    def test_reject_requires_reason(
        self, db, active_prefix, staff_user, approver_user
    ):
        reservation = ReservationService.reserve_auto_generated(
            db, active_prefix.id, staff_user.id,
        )
        ReservationService.submit_for_approval(db, reservation.id, staff_user.id)
        with pytest.raises(ValueError, match="reason is required"):
            ReservationService.reject_reservation(
                db, reservation.id, approver_user.id, reason="",
            )


# =========================================================================
# Changes Requested Path: generate → submit → request changes → resubmit → approve
# =========================================================================

class TestChangesRequestedPath:
    """Full changes-requested workflow cycle."""

    @pytest.mark.integration
    def test_full_changes_cycle(
        self, db, active_prefix, staff_user, approver_user
    ):
        # Generate & submit
        reservation = ReservationService.reserve_auto_generated(
            db, active_prefix.id, staff_user.id,
        )
        reservation = ReservationService.submit_for_approval(
            db, reservation.id, staff_user.id,
        )
        assert reservation.status == "pending_approval"

        # Request changes
        reservation = ReservationService.request_changes(
            db, reservation.id, approver_user.id, comments="Please update the description",
        )
        assert reservation.status == "changes_requested"

        # Resubmit (by the original requester)
        reservation = ReservationService.resubmit(
            db, reservation.id, staff_user.id,
        )
        assert reservation.status == "pending_approval"

        # Approve
        reservation = ReservationService.approve_reservation(
            db, reservation.id, approver_user.id,
        )
        assert reservation.status == "approved"

    @pytest.mark.integration
    def test_request_changes_requires_comments(
        self, db, active_prefix, staff_user, approver_user
    ):
        reservation = ReservationService.reserve_auto_generated(
            db, active_prefix.id, staff_user.id,
        )
        ReservationService.submit_for_approval(db, reservation.id, staff_user.id)
        with pytest.raises(ValueError, match="Comments are required"):
            ReservationService.request_changes(
                db, reservation.id, approver_user.id, comments="",
            )

    @pytest.mark.integration
    def test_only_owner_can_resubmit(
        self, db, active_prefix, staff_user, approver_user
    ):
        reservation = ReservationService.reserve_auto_generated(
            db, active_prefix.id, staff_user.id,
        )
        ReservationService.submit_for_approval(db, reservation.id, staff_user.id)
        ReservationService.request_changes(
            db, reservation.id, approver_user.id, comments="fix it",
        )
        with pytest.raises(ValueError, match="Only the requester"):
            ReservationService.resubmit(db, reservation.id, approver_user.id)


# =========================================================================
# Custom Number Path: enter custom → submit → approve
# =========================================================================

class TestCustomNumberPath:
    """Custom number end-to-end workflow."""

    @pytest.mark.integration
    def test_custom_submit_approve(
        self, db, active_prefix, staff_user, approver_user
    ):
        reservation = ReservationService.reserve_custom(
            db, active_prefix.id, "SPEC42", "Special allocation request", staff_user.id,
        )
        assert reservation.numbering_method == "custom"
        assert reservation.custom_number_reason == "Special allocation request"
        assert reservation.full_form_number == "HSPEC42"

        reservation = ReservationService.submit_for_approval(
            db, reservation.id, staff_user.id,
        )
        assert reservation.status == "pending_approval"

        reservation = ReservationService.approve_reservation(
            db, reservation.id, approver_user.id,
        )
        assert reservation.status == "approved"


# =========================================================================
# Duplicate Custom Number
# =========================================================================

class TestDuplicateCustomNumber:
    """Ensure duplicate custom numbers are blocked with correct error."""

    @pytest.mark.integration
    def test_duplicate_custom_blocked(self, db, active_prefix, staff_user):
        ReservationService.reserve_custom(
            db, active_prefix.id, "UNIQ1", "reason1", staff_user.id,
        )
        with pytest.raises(ValueError, match="already reserved"):
            ReservationService.reserve_custom(
                db, active_prefix.id, "UNIQ1", "reason2", staff_user.id,
            )

    @pytest.mark.integration
    def test_duplicate_after_release_ok(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Once a number is released, it can be reserved again."""
        reservation_factory(
            prefix=active_prefix,
            form_number="REISSUE",
            full_form_number="HREISSUE",
            numbering_method="custom",
            custom_number_reason="first",
            reserved_by=staff_user,
            status="released",
        )
        r = ReservationService.reserve_custom(
            db, active_prefix.id, "REISSUE", "re-issued", staff_user.id,
        )
        assert r.status == "reserved"


# =========================================================================
# Auto-Generation Sequence Independence
# =========================================================================

class TestAutoSequenceIndependence:
    """Custom numbers must not affect auto-generated sequence counter."""

    @pytest.mark.integration
    def test_custom_does_not_change_sequence(self, db, active_prefix, staff_user):
        r1 = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        assert r1.form_number == "0001"

        # Custom reservation
        ReservationService.reserve_custom(
            db, active_prefix.id, "ZZZ", "reason", staff_user.id,
        )
        db.refresh(active_prefix)
        # Sequence should still be 1 (only auto-generated increments it)
        assert active_prefix.current_sequence == 1

        r2 = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        assert r2.form_number == "0002"


# =========================================================================
# Listing & Detail Queries
# =========================================================================

class TestListAndDetail:
    """Verify list/detail operations."""

    @pytest.mark.integration
    def test_list_my_reservations(
        self, db, active_prefix, staff_user, user_factory, reservation_factory
    ):
        other = user_factory(email="other2@example.com")
        reservation_factory(prefix=active_prefix, reserved_by=staff_user, form_number="A1", full_form_number="HA1")
        reservation_factory(prefix=active_prefix, reserved_by=staff_user, form_number="A2", full_form_number="HA2")
        reservation_factory(prefix=active_prefix, reserved_by=other, form_number="B1", full_form_number="HB1")

        items, total = ReservationService.list_my_reservations(db, staff_user.id)
        assert total == 2
        assert all(str(r.reserved_by_id) == str(staff_user.id) for r in items)

    @pytest.mark.integration
    def test_list_pending_approvals(
        self, db, active_prefix, staff_user, approver_user, reservation_factory
    ):
        r1 = reservation_factory(
            prefix=active_prefix, reserved_by=staff_user,
            form_number="P1", full_form_number="HP1", status="pending_approval",
        )
        reservation_factory(
            prefix=active_prefix, reserved_by=staff_user,
            form_number="P2", full_form_number="HP2", status="reserved",
        )
        # Assign approver to r1
        db.add(FormReservationApprover(
            id=uuid.uuid4(), reservation_id=r1.id, approver_id=approver_user.id,
        ))
        db.flush()

        items, total = ReservationService.list_pending_approvals(
            db, approver_id=approver_user.id,
        )
        assert total == 1
        assert items[0].id == r1.id

    @pytest.mark.integration
    def test_get_reservation_detail(
        self, db, active_prefix, staff_user, approver_user
    ):
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        ReservationService.submit_for_approval(db, r.id, staff_user.id)

        detail = ReservationService.get_reservation_detail(db, r.id)
        assert detail is not None
        assert detail.prefix is not None
        assert detail.prefix.prefix == "H"
        assert len(detail.approvers) >= 1

    @pytest.mark.integration
    def test_list_reservations_enhanced_filters(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        reservation_factory(
            prefix=active_prefix, reserved_by=staff_user,
            form_number="F1", full_form_number="HF1", status="reserved",
            numbering_method="auto_generated",
        )
        reservation_factory(
            prefix=active_prefix, reserved_by=staff_user,
            form_number="F2", full_form_number="HF2", status="approved",
            numbering_method="custom", custom_number_reason="test",
        )

        # Filter by status
        items, total = ReservationService.list_reservations_enhanced(
            db, status="reserved",
        )
        assert total == 1
        assert items[0].full_form_number == "HF1"

        # Filter by numbering_method
        items2, total2 = ReservationService.list_reservations_enhanced(
            db, numbering_method="custom",
        )
        assert total2 == 1
        assert items2[0].full_form_number == "HF2"


# =========================================================================
# Expiring Reservations Listing
# =========================================================================

class TestExpiringReservations:
    """Verify listing of reservations approaching expiry."""

    @pytest.mark.integration
    def test_list_expiring(self, db, active_prefix, staff_user, reservation_factory):
        # Old reservation (12 days old — within 3-day threshold of 14-day limit)
        old = reservation_factory(
            prefix=active_prefix,
            reserved_by=staff_user,
            form_number="OLD1",
            full_form_number="HOLD1",
            status="reserved",
            created_at=datetime.now(timezone.utc) - timedelta(days=12),
        )
        # Fresh reservation
        reservation_factory(
            prefix=active_prefix,
            reserved_by=staff_user,
            form_number="NEW1",
            full_form_number="HNEW1",
            status="reserved",
        )

        items, total = ReservationService.list_expiring_reservations(
            db, days_threshold=3,
        )
        assert total == 1
        assert items[0].id == old.id
