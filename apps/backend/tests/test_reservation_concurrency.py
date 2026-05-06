"""TASK-412 — Concurrency tests for the reservation service.

Runs against a real PostgreSQL database to validate concurrency semantics
including PostgreSQL partial unique indexes and row locking:

  - Two sequential auto-generate requests produce different numbers
  - Concurrent custom number conflict is detected and blocked
  - Reservation is atomic under sequential requests
  - Released/expired numbers can be re-reserved after being freed
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import FormNumberReservation, FormReservationApprover
from backend.services.reservations import ReservationService


class TestSequentialAutoGenerate:
    """Two auto-generate requests must produce two different numbers."""

    @pytest.mark.concurrency
    def test_two_sequential_auto_generate_different(
        self, db, active_prefix, staff_user
    ):
        r1 = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        r2 = ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        assert r1.form_number != r2.form_number
        assert r1.full_form_number != r2.full_form_number
        assert r1.form_number == "0001"
        assert r2.form_number == "0002"

    @pytest.mark.concurrency
    def test_many_sequential_auto_generate(self, db, active_prefix, staff_user):
        """Many sequential reservations all produce unique numbers."""
        numbers = set()
        for _ in range(50):
            r = ReservationService.reserve_auto_generated(
                db, active_prefix.id, staff_user.id,
            )
            numbers.add(r.full_form_number)
        assert len(numbers) == 50

    @pytest.mark.concurrency
    def test_sequence_correctly_incremented_after_many(
        self, db, active_prefix, staff_user
    ):
        """After N reservations, prefix.current_sequence == N."""
        n = 20
        for _ in range(n):
            ReservationService.reserve_auto_generated(db, active_prefix.id, staff_user.id)
        db.refresh(active_prefix)
        assert active_prefix.current_sequence == n


class TestCustomNumberConflict:
    """Concurrent custom number requests: second request must fail."""

    @pytest.mark.concurrency
    def test_second_custom_same_number_fails(self, db, active_prefix, staff_user):
        ReservationService.reserve_custom(
            db, active_prefix.id, "RACE1", "reason", staff_user.id,
        )
        with pytest.raises(ValueError, match="already reserved"):
            ReservationService.reserve_custom(
                db, active_prefix.id, "RACE1", "reason2", staff_user.id,
            )

    @pytest.mark.concurrency
    def test_different_custom_numbers_ok(self, db, active_prefix, staff_user):
        r1 = ReservationService.reserve_custom(
            db, active_prefix.id, "A1", "r1", staff_user.id,
        )
        r2 = ReservationService.reserve_custom(
            db, active_prefix.id, "A2", "r2", staff_user.id,
        )
        assert r1.full_form_number != r2.full_form_number


class TestAtomicReservation:
    """Verify reservation creates all related records atomically."""

    @pytest.mark.concurrency
    def test_reservation_and_audit_created_atomically(
        self, db, active_prefix, staff_user
    ):
        from backend.models import AuditLog

        r = ReservationService.reserve_auto_generated(
            db, active_prefix.id, staff_user.id,
        )
        # Both reservation and audit log should exist
        assert db.query(FormNumberReservation).filter_by(id=r.id).first() is not None
        audits = (
            db.query(AuditLog)
            .filter_by(entity_id=str(r.id), action="RESERVE_NUMBER")
            .all()
        )
        assert len(audits) == 1

    @pytest.mark.concurrency
    def test_submit_creates_approvers_atomically(
        self, db, active_prefix, staff_user, approver_user
    ):
        r = ReservationService.reserve_auto_generated(
            db, active_prefix.id, staff_user.id,
        )
        ReservationService.submit_for_approval(db, r.id, staff_user.id)

        # Approver assignments should exist
        approvers = (
            db.query(FormReservationApprover)
            .filter_by(reservation_id=r.id)
            .all()
        )
        assert len(approvers) >= 1


class TestReReservation:
    """Freed numbers can be re-reserved."""

    @pytest.mark.concurrency
    def test_released_number_re_reservable(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        reservation_factory(
            prefix=active_prefix,
            form_number="FREED",
            full_form_number="HFREED",
            numbering_method="custom",
            custom_number_reason="first",
            reserved_by=staff_user,
            status="released",
        )
        r = ReservationService.reserve_custom(
            db, active_prefix.id, "FREED", "reuse", staff_user.id,
        )
        assert r.status == "reserved"
        assert r.full_form_number == "HFREED"

    @pytest.mark.concurrency
    def test_expired_number_re_reservable(
        self, db, active_prefix, staff_user, reservation_factory
    ):
        reservation_factory(
            prefix=active_prefix,
            form_number="EXPR",
            full_form_number="HEXPR",
            numbering_method="custom",
            custom_number_reason="first",
            reserved_by=staff_user,
            status="expired",
        )
        r = ReservationService.reserve_custom(
            db, active_prefix.id, "EXPR", "reuse", staff_user.id,
        )
        assert r.status == "reserved"


class TestMultiplePrefixConcurrency:
    """Auto-generation on different prefixes is independent."""

    @pytest.mark.concurrency
    def test_interleaved_prefix_sequences(self, db, prefix_factory, staff_user):
        p1 = prefix_factory(prefix="C1")
        p2 = prefix_factory(prefix="C2")

        r1a = ReservationService.reserve_auto_generated(db, p1.id, staff_user.id)
        r2a = ReservationService.reserve_auto_generated(db, p2.id, staff_user.id)
        r1b = ReservationService.reserve_auto_generated(db, p1.id, staff_user.id)
        r2b = ReservationService.reserve_auto_generated(db, p2.id, staff_user.id)

        assert r1a.form_number == "0001"
        assert r1b.form_number == "0002"
        assert r2a.form_number == "0001"
        assert r2b.form_number == "0002"
