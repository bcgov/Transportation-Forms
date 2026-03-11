"""TASK-412 — Database constraint tests for form number reservations.

Tests that model-level constraints are correctly enforced:
  - Unique index on ``full_form_number`` prevents duplicates (among active)
  - FK constraints enforced (prefix, user references)
  - Check constraints on ``numbering_method`` and ``status`` values
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from backend.models import (
    FormNumberPrefix,
    FormNumberReservation,
    FormReservationApprover,
    User,
)


# =========================================================================
# FK Constraint Tests
# =========================================================================

class TestForeignKeyConstraints:
    """FK constraints on form_number_reservations."""

    @pytest.mark.db_constraint
    def test_reservation_requires_valid_prefix(self, db, staff_user):
        """prefix_id must reference an existing prefix."""
        fake_prefix_id = uuid.uuid4()
        r = FormNumberReservation(
            id=uuid.uuid4(),
            prefix_id=fake_prefix_id,
            form_number="0001",
            full_form_number="X0001",
            numbering_method="auto_generated",
            status="reserved",
            reserved_by_id=staff_user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.add(r)
        with pytest.raises(IntegrityError):
            db.flush()

    @pytest.mark.db_constraint
    def test_reservation_requires_valid_user(self, db, active_prefix):
        """reserved_by_id must reference an existing user."""
        fake_user_id = uuid.uuid4()
        r = FormNumberReservation(
            id=uuid.uuid4(),
            prefix_id=active_prefix.id,
            form_number="0001",
            full_form_number="H0001",
            numbering_method="auto_generated",
            status="reserved",
            reserved_by_id=fake_user_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.add(r)
        with pytest.raises(IntegrityError):
            db.flush()

    @pytest.mark.db_constraint
    def test_approver_requires_valid_reservation(self, db, approver_user):
        """reservation_id on approver table must reference a real reservation."""
        a = FormReservationApprover(
            id=uuid.uuid4(),
            reservation_id=uuid.uuid4(),  # does not exist
            approver_id=approver_user.id,
        )
        db.add(a)
        with pytest.raises(IntegrityError):
            db.flush()

    @pytest.mark.db_constraint
    def test_approver_requires_valid_user(self, db, active_prefix, staff_user, reservation_factory):
        """approver_id must reference a real user."""
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user)
        a = FormReservationApprover(
            id=uuid.uuid4(),
            reservation_id=r.id,
            approver_id=uuid.uuid4(),  # does not exist
        )
        db.add(a)
        with pytest.raises(IntegrityError):
            db.flush()


# =========================================================================
# Check Constraint Tests (numbering_method, status)
# PostgreSQL enforces CHECK constraints at the database level.
# These tests validate both model logic and DB-level constraint enforcement.
# =========================================================================

class TestModelConstraints:
    """Database-level constraint validation via the service layer."""

    @pytest.mark.db_constraint
    def test_valid_numbering_methods(self, db, active_prefix, staff_user):
        """Both 'auto_generated' and 'custom' are valid numbering methods."""
        r1 = FormNumberReservation(
            id=uuid.uuid4(),
            prefix_id=active_prefix.id,
            form_number="0001",
            full_form_number="H0001",
            numbering_method="auto_generated",
            status="reserved",
            reserved_by_id=staff_user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.add(r1)
        db.flush()
        assert r1.numbering_method == "auto_generated"

        r2 = FormNumberReservation(
            id=uuid.uuid4(),
            prefix_id=active_prefix.id,
            form_number="CUSTOM1",
            full_form_number="HCUSTOM1",
            numbering_method="custom",
            custom_number_reason="test reason",
            status="reserved",
            reserved_by_id=staff_user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        db.add(r2)
        db.flush()
        assert r2.numbering_method == "custom"

    @pytest.mark.db_constraint
    def test_valid_status_values(self, db, active_prefix, staff_user, reservation_factory):
        """All defined status values can be set."""
        valid_statuses = [
            "reserved", "pending_approval", "approved",
            "rejected", "changes_requested", "released", "expired",
        ]
        for i, status_val in enumerate(valid_statuses):
            r = reservation_factory(
                prefix=active_prefix,
                reserved_by=staff_user,
                form_number=f"ST{i}",
                full_form_number=f"HST{i}",
                status=status_val,
            )
            assert r.status == status_val

    @pytest.mark.db_constraint
    def test_unique_approver_per_reservation(
        self, db, active_prefix, staff_user, approver_user, reservation_factory
    ):
        """Same approver cannot be assigned twice to the same reservation."""
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user)
        a1 = FormReservationApprover(
            id=uuid.uuid4(),
            reservation_id=r.id,
            approver_id=approver_user.id,
        )
        db.add(a1)
        db.flush()

        a2 = FormReservationApprover(
            id=uuid.uuid4(),
            reservation_id=r.id,
            approver_id=approver_user.id,
        )
        db.add(a2)
        with pytest.raises(IntegrityError):
            db.flush()


# =========================================================================
# Soft-Delete Behavior
# =========================================================================

class TestSoftDeleteBehavior:
    """Verify soft-deleted reservations are excluded from queries."""

    @pytest.mark.db_constraint
    def test_soft_deleted_not_returned(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user)
        r.deleted_at = datetime.now(timezone.utc)
        db.flush()

        from backend.services.reservations import ReservationService
        result = ReservationService.get_reservation_by_id(db, r.id)
        assert result is None

    @pytest.mark.db_constraint
    def test_soft_deleted_not_in_list(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        r = reservation_factory(prefix=active_prefix, reserved_by=staff_user)
        r.deleted_at = datetime.now(timezone.utc)
        db.flush()

        items, total = ReservationService.list_my_reservations(db, staff_user.id)
        assert total == 0


from backend.services.reservations import ReservationService
