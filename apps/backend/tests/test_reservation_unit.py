"""TASK-412 — Unit tests for the ReservationService.

Covers:
  - Sequence generator increments correctly per prefix
  - Zero-padding formatting for various padding lengths
  - Custom number validation (alphanumeric, max length, required reason)
  - Status transition validation (valid and invalid transitions)
  - Uniqueness constraint behavior for form numbers
  - Expiry date calculation (14 days from creation for custom, 1 day for auto)
  - Release permission checks (staff own, approver assigned, admin all)
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
# Sequence Generator Tests
# =========================================================================

class TestSequenceGenerator:
    """Verify auto-generated sequence increments correctly."""

    @pytest.mark.unit
    def test_first_auto_generates_sequence_1(self, db, active_prefix, staff_user):
        """First reservation should produce sequence 1."""
        reservation = ReservationService.reserve_auto_generated(
            db, prefix_id=active_prefix.id, reserved_by_id=staff_user.id,
        )
        assert reservation.form_number == "0001"
        assert reservation.full_form_number == "H0001"

    @pytest.mark.unit
    def test_sequential_increments(self, db, active_prefix, staff_user):
        """Successive calls must produce incrementing sequences."""
        r1 = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        r2 = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        r3 = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)

        assert r1.form_number == "0001"
        assert r2.form_number == "0002"
        assert r3.form_number == "0003"

    @pytest.mark.unit
    def test_prefix_sequence_is_updated(self, db, active_prefix, staff_user):
        """Prefix current_sequence should be updated after reservation."""
        ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        db.refresh(active_prefix)
        assert active_prefix.current_sequence == 1

        ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        db.refresh(active_prefix)
        assert active_prefix.current_sequence == 2

    @pytest.mark.unit
    def test_inactive_prefix_raises(self, db, prefix_factory, staff_user):
        """Cannot auto-generate from an inactive prefix."""
        prefix = prefix_factory(prefix="X", is_active=False)
        with pytest.raises(ValueError, match="inactive"):
            ReservationService.reserve_auto_generated(db, prefix.id, staff_user.id)

    @pytest.mark.unit
    def test_deleted_prefix_raises(self, db, prefix_factory, staff_user):
        """Cannot auto-generate from a soft-deleted prefix."""
        prefix = prefix_factory(prefix="DEL")
        prefix.deleted_at = datetime.now(timezone.utc)
        db.flush()

        with pytest.raises(ValueError, match="not found"):
            ReservationService.reserve_auto_generated(db, prefix.id, staff_user.id)

    @pytest.mark.unit
    def test_nonexistent_prefix_raises(self, db, staff_user):
        """Referencing a non-existent prefix UUID raises ValueError."""
        fake_id = uuid.uuid4()
        with pytest.raises(ValueError, match="not found"):
            ReservationService.reserve_auto_generated(db, fake_id, staff_user.id)

    @pytest.mark.unit
    def test_independent_prefix_sequences(self, db, prefix_factory, staff_user):
        """Different prefixes maintain independent sequences."""
        p1 = prefix_factory(prefix="AA")
        p2 = prefix_factory(prefix="BB")

        r1 = ReservationService.reserve_auto_generated(db, p1.id, staff_user.id)
        r2 = ReservationService.reserve_auto_generated(db, p2.id, staff_user.id)

        assert r1.form_number == "0001"
        assert r2.form_number == "0001"  # independent counters
        assert r1.full_form_number == "AA0001"
        assert r2.full_form_number == "BB0001"


# =========================================================================
# Zero-Padding Tests
# =========================================================================

class TestZeroPadding:
    """Verify zero-padding formatting for various padding lengths."""

    @pytest.mark.unit
    @pytest.mark.parametrize("padding,expected", [
        (2, "01"),
        (3, "001"),
        (4, "0001"),
        (6, "000001"),
        (8, "00000001"),
    ])
    def test_padding_formats(self, db, prefix_factory, staff_user, padding, expected):
        pfx = prefix_factory(prefix=f"P{padding}", padding_length=padding)
        r = ReservationService.reserve_auto_generated(db, pfx.id, staff_user.id)
        assert r.form_number == expected

    @pytest.mark.unit
    def test_padding_overflow(self, db, prefix_factory, staff_user):
        """When the sequence exceeds the padding width, digits are not truncated."""
        pfx = prefix_factory(prefix="SM", padding_length=2, current_sequence=99)
        r = ReservationService.reserve_auto_generated(db, pfx.id, staff_user.id)
        assert r.form_number == "100"  # 3 digits, padding is 2 -> no truncation


# =========================================================================
# Custom Number Validation Tests
# =========================================================================

class TestCustomNumberValidation:
    """Verify custom number validation logic."""

    @pytest.mark.unit
    def test_valid_custom_number(self, db, active_prefix, staff_user):
        r = ReservationService.reserve_custom(
            db, active_prefix.id, "0020A", "test reason", staff_user.id,
        )
        assert r.form_number == "0020A"
        assert r.full_form_number == "H0020A"
        assert r.numbering_method == "custom"
        assert r.custom_number_reason == "test reason"

    @pytest.mark.unit
    def test_custom_number_must_be_alphanumeric(self, db, active_prefix, staff_user):
        with pytest.raises(ValueError, match="alphanumeric"):
            ReservationService.reserve_custom(
                db, active_prefix.id, "00-20!", "reason", staff_user.id,
            )

    @pytest.mark.unit
    def test_custom_number_max_length(self, db, prefix_factory, staff_user):
        pfx = prefix_factory(prefix="LEN", max_number_length=5)
        with pytest.raises(ValueError, match="exceeds the maximum length"):
            ReservationService.reserve_custom(
                db, pfx.id, "ABCDEF", "reason", staff_user.id,  # 6 chars > 5
            )

    @pytest.mark.unit
    def test_custom_number_at_max_length_ok(self, db, prefix_factory, staff_user):
        pfx = prefix_factory(prefix="LEN2", max_number_length=5)
        r = ReservationService.reserve_custom(
            db, pfx.id, "ABCDE", "reason", staff_user.id,
        )
        assert r.form_number == "ABCDE"

    @pytest.mark.unit
    def test_custom_requires_reason(self, db, active_prefix, staff_user):
        with pytest.raises(ValueError, match="reason is required"):
            ReservationService.reserve_custom(
                db, active_prefix.id, "001", "", staff_user.id,
            )

    @pytest.mark.unit
    def test_custom_requires_reason_whitespace(self, db, active_prefix, staff_user):
        with pytest.raises(ValueError, match="reason is required"):
            ReservationService.reserve_custom(
                db, active_prefix.id, "001", "   ", staff_user.id,
            )

    @pytest.mark.unit
    def test_custom_empty_form_number(self, db, active_prefix, staff_user):
        with pytest.raises(ValueError, match="must not be empty"):
            ReservationService.reserve_custom(
                db, active_prefix.id, "   ", "reason", staff_user.id,
            )


# =========================================================================
# Status Transition Tests
# =========================================================================

class TestStatusTransition:
    """Verify valid and invalid status transitions."""

    @pytest.mark.unit
    @pytest.mark.parametrize("from_status,to_status,valid", [
        # Valid transitions
        ("reserved", "pending_approval", True),
        ("pending_approval", "approved", True),
        ("pending_approval", "rejected", True),
        ("pending_approval", "changes_requested", True),
        ("changes_requested", "pending_approval", True),
        # Invalid transitions
        ("reserved", "approved", False),
        ("reserved", "rejected", False),
        ("approved", "pending_approval", False),
        ("approved", "rejected", False),
        ("rejected", "pending_approval", False),
        ("released", "reserved", False),
        ("expired", "reserved", False),
    ])
    def test_validate_transition(self, from_status, to_status, valid):
        if valid:
            # Should not raise
            ReservationService._validate_transition(from_status, to_status)
        else:
            with pytest.raises(ValueError, match="Cannot transition"):
                ReservationService._validate_transition(from_status, to_status)

    @pytest.mark.unit
    def test_submit_changes_status(self, db, active_prefix, staff_user, approver_user):
        """Submit for approval moves reserved → pending_approval."""
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        assert r.status == "reserved"
        r2 = ReservationService.submit_for_approval(db, r.id, staff_user.id)
        assert r2.status == "pending_approval"

    @pytest.mark.unit
    def test_submit_by_non_owner_raises(self, db, active_prefix, staff_user, approver_user):
        """Only the requester can submit their own reservation."""
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        with pytest.raises(ValueError, match="Only the requester"):
            ReservationService.submit_for_approval(db, r.id, approver_user.id)

    @pytest.mark.unit
    def test_approve_from_wrong_status_raises(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Cannot approve a reservation in 'reserved' status."""
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user, status="reserved")
        with pytest.raises(ValueError, match="Cannot transition"):
            ReservationService.approve_reservation(db, r.id, staff_user.id)

    @pytest.mark.unit
    def test_reject_from_wrong_status_raises(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Cannot reject a reservation in 'reserved' status."""
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user, status="reserved")
        with pytest.raises(ValueError, match="Cannot transition"):
            ReservationService.reject_reservation(db, r.id, staff_user.id, "bad")

    @pytest.mark.unit
    def test_request_changes_from_wrong_status_raises(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Cannot request changes on a 'reserved' reservation."""
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user, status="reserved")
        with pytest.raises(ValueError, match="Cannot transition"):
            ReservationService.request_changes(db, r.id, staff_user.id, "fix it")


# =========================================================================
# Uniqueness Tests
# =========================================================================

class TestUniqueness:
    """Verify uniqueness constraint on form numbers."""

    @pytest.mark.unit
    def test_duplicate_custom_number_blocked(self, db, active_prefix, staff_user):
        """Cannot reserve the same custom number twice while active."""
        ReservationService.reserve_custom(
            db, active_prefix.id, "DUP1", "reason", staff_user.id,
        )
        with pytest.raises(ValueError, match="already reserved"):
            ReservationService.reserve_custom(
                db, active_prefix.id, "DUP1", "another reason", staff_user.id,
            )

    @pytest.mark.unit
    def test_case_insensitive_uniqueness(self, db, prefix_factory, staff_user):
        """Case-insensitive prefixes block mixed-case duplicates."""
        pfx = prefix_factory(prefix="CI", is_case_sensitive=False)
        ReservationService.reserve_custom(db, pfx.id, "ABC", "r", staff_user.id)
        with pytest.raises(ValueError, match="already reserved"):
            ReservationService.reserve_custom(db, pfx.id, "abc", "r", staff_user.id)

    @pytest.mark.unit
    def test_released_number_can_be_re_reserved(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """A released number should be available for re-reservation."""
        reservation_factory(
            prefix=active_prefix,
            form_number="REUSE1",
            full_form_number="HREUSE1",
            numbering_method="custom",
            custom_number_reason="first",
            reserved_by=staff_user,
            status="released",
        )
        # Should succeed since previous is released
        r = ReservationService.reserve_custom(
            db, active_prefix.id, "REUSE1", "second use", staff_user.id,
        )
        assert r.form_number == "REUSE1"

    @pytest.mark.unit
    def test_expired_number_can_be_re_reserved(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """An expired number should be available for re-reservation."""
        reservation_factory(
            prefix=active_prefix,
            form_number="REUSE2",
            full_form_number="HREUSE2",
            numbering_method="custom",
            custom_number_reason="first",
            reserved_by=staff_user,
            status="expired",
        )
        r = ReservationService.reserve_custom(
            db, active_prefix.id, "REUSE2", "second use", staff_user.id,
        )
        assert r.form_number == "REUSE2"


# =========================================================================
# Expiry Date Calculation Tests
# =========================================================================

class TestExpiryDate:
    """Verify expiry date is set correctly."""

    @pytest.mark.unit
    def test_auto_generated_expiry_1_day(self, db, active_prefix, staff_user):
        """Auto-generated reservations expire in 1 day."""
        before = datetime.now(timezone.utc)
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        after = datetime.now(timezone.utc)

        # expires_at should be approximately 1 day from now
        expected_min = before + timedelta(days=1) - timedelta(seconds=5)
        expected_max = after + timedelta(days=1) + timedelta(seconds=5)
        assert expected_min <= r.expires_at.replace(tzinfo=timezone.utc) <= expected_max

    @pytest.mark.unit
    def test_custom_expiry_14_days(self, db, active_prefix, staff_user):
        """Custom reservations expire in 14 days."""
        before = datetime.now(timezone.utc)
        r = ReservationService.reserve_custom(
            db, active_prefix.id, "EXP1", "reason", staff_user.id,
        )
        after = datetime.now(timezone.utc)

        expected_min = before + timedelta(days=14) - timedelta(seconds=5)
        expected_max = after + timedelta(days=14) + timedelta(seconds=5)
        assert expected_min <= r.expires_at.replace(tzinfo=timezone.utc) <= expected_max


# =========================================================================
# Release Permission Tests
# =========================================================================

class TestReleasePermissions:
    """Verify release permission logic."""

    @pytest.mark.unit
    def test_owner_can_release_own(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Staff user can release their own reservation."""
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user)
        released = ReservationService.release_reservation(
            db, r.id, staff_user.id,
        )
        assert released.status == "released"
        assert released.released_by_id == staff_user.id

    @pytest.mark.unit
    def test_admin_can_release_any(
        self, db, active_prefix, staff_user, admin_user, reservation_factory
    ):
        """Admin can release any reservation."""
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user)
        released = ReservationService.release_reservation(
            db, r.id, admin_user.id, can_release_any=True,
        )
        assert released.status == "released"
        assert released.released_by_id == admin_user.id

    @pytest.mark.unit
    def test_assigned_approver_can_release(
        self, db, active_prefix, staff_user, approver_user, reservation_factory
    ):
        """Approver assigned to the reservation can release it."""
        r = reservation_factory(
            prefix=active_prefix, reserved_by=staff_user, status="pending_approval",
        )
        # Assign the approver
        db.add(FormReservationApprover(
            id=uuid.uuid4(),
            reservation_id=r.id,
            approver_id=approver_user.id,
        ))
        db.flush()

        released = ReservationService.release_reservation(
            db, r.id, approver_user.id,
        )
        assert released.status == "released"

    @pytest.mark.unit
    def test_unrelated_user_cannot_release(
        self, db, active_prefix, staff_user, user_factory, reservation_factory
    ):
        """A user who is neither owner, approver, nor admin cannot release."""
        other = user_factory(email="other@example.com")
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user)
        with pytest.raises(ValueError, match="permission"):
            ReservationService.release_reservation(
                db, r.id, other.id,
            )

    @pytest.mark.unit
    def test_cannot_release_approved(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Cannot release an already-approved reservation."""
        r = reservation_factory(
            prefix=active_prefix, reserved_by=staff_user, status="approved",
        )
        with pytest.raises(ValueError, match="already-approved"):
            ReservationService.release_reservation(
                db, r.id, staff_user.id,
            )

    @pytest.mark.unit
    def test_cannot_release_already_released(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Cannot release an already-released reservation."""
        r = reservation_factory(
            prefix=active_prefix, reserved_by=staff_user, status="released",
        )
        with pytest.raises(ValueError, match="already 'released'"):
            ReservationService.release_reservation(
                db, r.id, staff_user.id,
            )

    @pytest.mark.unit
    def test_cannot_release_expired(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Cannot release an already-expired reservation."""
        r = reservation_factory(
            prefix=active_prefix, reserved_by=staff_user, status="expired",
        )
        with pytest.raises(ValueError, match="already 'expired'"):
            ReservationService.release_reservation(
                db, r.id, staff_user.id,
            )


# =========================================================================
# Auto-Expiry Tests
# =========================================================================

class TestAutoExpiry:
    """Verify auto-expiry of stale reservations."""

    @pytest.mark.unit
    def test_expire_stale_reserved(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Reservations older than 14 days in 'reserved' status get expired."""
        old_date = datetime.now(timezone.utc) - timedelta(days=15)
        r = reservation_factory(
            prefix=active_prefix,
            reserved_by=staff_user,
            status="reserved",
            created_at=old_date,
        )
        count = ReservationService.expire_stale_reservations(db)
        assert count == 1
        db.refresh(r)
        assert r.status == "expired"

    @pytest.mark.unit
    def test_expire_stale_changes_requested(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """'changes_requested' reservations older than 14 days get expired."""
        old_date = datetime.now(timezone.utc) - timedelta(days=15)
        r = reservation_factory(
            prefix=active_prefix,
            reserved_by=staff_user,
            status="changes_requested",
            created_at=old_date,
        )
        count = ReservationService.expire_stale_reservations(db)
        assert count == 1
        db.refresh(r)
        assert r.status == "expired"

    @pytest.mark.unit
    def test_fresh_reservations_not_expired(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Recent reservations should NOT be expired."""
        reservation_factory(
            prefix=active_prefix,
            reserved_by=staff_user,
            status="reserved",
        )
        count = ReservationService.expire_stale_reservations(db)
        assert count == 0

    @pytest.mark.unit
    def test_approved_not_expired(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        """Approved reservations should never be expired even if old."""
        old_date = datetime.now(timezone.utc) - timedelta(days=20)
        reservation_factory(
            prefix=active_prefix,
            reserved_by=staff_user,
            status="approved",
            created_at=old_date,
        )
        count = ReservationService.expire_stale_reservations(db)
        assert count == 0


# =========================================================================
# Custom Number Does Not Affect Auto-Generation Sequence
# =========================================================================

class TestCustomVsAutoSequence:
    """Custom reservations should not modify the prefix sequence counter."""

    @pytest.mark.unit
    def test_custom_does_not_affect_sequence(self, db, active_prefix, staff_user):
        assert active_prefix.current_sequence == 0

        # Reserve a custom number
        ReservationService.reserve_custom(
            db, active_prefix.id, "CUSTOM1", "reason", staff_user.id,
        )
        db.refresh(active_prefix)
        assert active_prefix.current_sequence == 0  # unchanged

        # Auto-generate should still start at 1
        r = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        assert r.form_number == "0001"
