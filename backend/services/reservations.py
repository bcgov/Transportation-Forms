"""Form Number Reservation service — TASK-404 through TASK-408 business logic.

Provides:
  - Auto-generated sequential number reservation (Story 1)
  - Custom form number reservation (Story 2)
  - Approval workflow (Story 3)
  - Release & auto-expiry
  - Enhanced listing with filters, sorting, and pagination

Uses row-level locking on the prefix row to guarantee atomic sequence
increments under concurrent access.
"""

from typing import Optional, List, Tuple
from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_

from backend.models import (
    FormNumberPrefix,
    FormNumberReservation,
    FormReservationApprover,
    AuditLog,
    User,
    UserRole,
    Role,
    Form,
)


class ReservationService:
    """Service class for form number reservation operations."""

    # =====================================================================
    # TASK-404 — Auto-Generated Sequential Number Reservation (Story 1)
    # =====================================================================

    @staticmethod
    def reserve_auto_generated(
        db: Session,
        prefix_id: UUID,
        reserved_by_id: UUID,
    ) -> FormNumberReservation:
        """
        Reserve the next auto-generated sequential form number.

        Atomically increments the prefix ``current_sequence`` using
        ``SELECT ... FOR UPDATE`` row-level locking, formats the number
        with zero-padding, and creates a reservation record.

        Args:
            db: Database session (must support transactions)
            prefix_id: UUID of the form number prefix to use
            reserved_by_id: UUID of the authenticated user

        Returns:
            Newly created ``FormNumberReservation``

        Raises:
            ValueError: If the prefix does not exist, is inactive,
                        or the sequence cannot advance.
        """
        # Lock the prefix row for atomic update
        prefix = (
            db.query(FormNumberPrefix)
            .filter(
                FormNumberPrefix.id == prefix_id,
                FormNumberPrefix.deleted_at.is_(None),
            )
            .with_for_update()
            .first()
        )

        if prefix is None:
            raise ValueError(
                f"Prefix with id '{prefix_id}' not found or has been deleted."
            )
        if not prefix.is_active:  # type: ignore[truthy-bool]
            raise ValueError(
                f"Prefix '{prefix.prefix}' is currently inactive. "
                "Contact an administrator to re-activate it before reserving numbers."
            )

        # Increment the sequence counter
        new_seq = prefix.current_sequence + 1
        prefix.current_sequence = new_seq  # type: ignore[assignment]

        # Format with zero-padding
        form_number = str(new_seq).zfill(int(prefix.padding_length))  # type: ignore[arg-type]
        full_form_number = f"{prefix.prefix}{form_number}"

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=1)

        reservation = FormNumberReservation(
            prefix_id=prefix_id,
            form_number=form_number,
            full_form_number=full_form_number,
            numbering_method="auto_generated",
            status="reserved",
            reserved_by_id=reserved_by_id,
            expires_at=expires_at,
        )
        db.add(reservation)
        db.flush()  # Generate reservation.id before creating audit entry

        # Audit log
        audit = AuditLog(
            entity_type="form_number_reservations",
            entity_id=str(reservation.id),
            action="RESERVE_NUMBER",
            user_id=reserved_by_id,
            new_values={
                "prefix": prefix.prefix,
                "form_number": form_number,
                "full_form_number": full_form_number,
                "numbering_method": "auto_generated",
                "expires_at": expires_at.isoformat(),
            },
            description=(
                f"Auto-generated reservation: {full_form_number} "
                f"(sequence #{new_seq})"
            ),
        )
        db.add(audit)

        db.commit()
        db.refresh(reservation)
        return reservation

    # =====================================================================
    # TASK-405 — Custom Form Number Reservation (Story 2)
    # =====================================================================

    @staticmethod
    def reserve_custom(
        db: Session,
        prefix_id: UUID,
        form_number: str,
        reason: str,
        reserved_by_id: UUID,
    ) -> FormNumberReservation:
        """
        Reserve a manually entered custom form number.

        Validates the format, checks uniqueness among active reservations,
        and creates a reservation record. Does **not** modify the prefix's
        ``current_sequence``.

        Args:
            db: Database session
            prefix_id: UUID of the prefix to use
            form_number: The custom number portion (e.g., ``'0020A'``)
            reason: Justification for using a custom number (required)
            reserved_by_id: UUID of the authenticated user

        Returns:
            Newly created ``FormNumberReservation``

        Raises:
            ValueError: Validation failures (format, uniqueness, etc.)
        """
        # --- Validate reason ---
        if not reason or not reason.strip():
            raise ValueError(
                "A reason is required when reserving a custom form number."
            )

        # --- Load prefix (no FOR UPDATE needed — we don't touch the sequence) ---
        prefix = (
            db.query(FormNumberPrefix)
            .filter(
                FormNumberPrefix.id == prefix_id,
                FormNumberPrefix.deleted_at.is_(None),
            )
            .first()
        )

        if prefix is None:
            raise ValueError(
                f"Prefix with id '{prefix_id}' not found or has been deleted."
            )
        if not prefix.is_active:  # type: ignore[truthy-bool]
            raise ValueError(
                f"Prefix '{prefix.prefix}' is currently inactive. "
                "Contact an administrator to re-activate it before reserving numbers."
            )

        # --- Validate form_number format ---
        cleaned = form_number.strip()
        if not cleaned:
            raise ValueError("form_number must not be empty.")
        if not cleaned.replace(" ", "").isalnum():
            raise ValueError(
                "form_number must be alphanumeric (letters and digits only)."
            )
        if len(cleaned) > int(prefix.max_number_length):  # type: ignore[arg-type]
            raise ValueError(
                f"form_number exceeds the maximum length of {prefix.max_number_length} "
                f"characters for prefix '{prefix.prefix}'."
            )

        # Build the full composite form number
        full_form_number = f"{prefix.prefix}{cleaned}"

        # --- Uniqueness check (case-insensitive if configured) ---
        uniqueness_query = db.query(FormNumberReservation).filter(
            FormNumberReservation.deleted_at.is_(None),
            FormNumberReservation.status.notin_(["released", "expired"]),
        )
        if prefix.is_case_sensitive:  # type: ignore[truthy-bool]
            uniqueness_query = uniqueness_query.filter(
                FormNumberReservation.full_form_number == full_form_number,
            )
        else:
            uniqueness_query = uniqueness_query.filter(
                func.upper(FormNumberReservation.full_form_number)
                == full_form_number.upper(),
            )

        existing = uniqueness_query.first()
        if existing:
            raise ValueError(
                f"'{full_form_number}' is already reserved. "
                "Choose a different number or release the existing reservation first."
            )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=14)

        reservation = FormNumberReservation(
            prefix_id=prefix_id,
            form_number=cleaned,
            full_form_number=full_form_number,
            numbering_method="custom",
            custom_number_reason=reason.strip(),
            status="reserved",
            reserved_by_id=reserved_by_id,
            expires_at=expires_at,
        )
        db.add(reservation)
        db.flush()  # Generate reservation.id before creating audit entry

        # Audit log
        audit = AuditLog(
            entity_type="form_number_reservations",
            entity_id=str(reservation.id),
            action="RESERVE_SPECIAL_NUMBER",
            user_id=reserved_by_id,
            new_values={
                "prefix": prefix.prefix,
                "form_number": cleaned,
                "full_form_number": full_form_number,
                "numbering_method": "custom",
                "custom_number_reason": reason.strip(),
                "expires_at": expires_at.isoformat(),
            },
            description=(
                f"Custom reservation: {full_form_number} — reason: {reason.strip()}"
            ),
        )
        db.add(audit)

        db.commit()
        db.refresh(reservation)
        return reservation

    # =====================================================================
    # READ HELPERS
    # =====================================================================

    @staticmethod
    def get_reservation_by_id(
        db: Session, reservation_id: UUID
    ) -> Optional[FormNumberReservation]:
        """Get a single reservation by its UUID (non-deleted only)."""
        return (
            db.query(FormNumberReservation)
            .filter(
                FormNumberReservation.id == reservation_id,
                FormNumberReservation.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def list_reservations(
        db: Session,
        *,
        prefix_id: Optional[UUID] = None,
        status: Optional[str] = None,
        reserved_by_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[FormNumberReservation], int]:
        """
        List reservations with optional filters and pagination.

        Returns:
            Tuple of (list of reservations, total count)
        """
        query = db.query(FormNumberReservation).filter(
            FormNumberReservation.deleted_at.is_(None),
        )

        if prefix_id is not None:
            query = query.filter(FormNumberReservation.prefix_id == prefix_id)
        if status is not None:
            query = query.filter(FormNumberReservation.status == status)
        if reserved_by_id is not None:
            query = query.filter(FormNumberReservation.reserved_by_id == reserved_by_id)

        total = query.count()
        items = (
            query.order_by(FormNumberReservation.created_at.desc())
            .offset(skip)
            .limit(min(limit, 100))
            .all()
        )
        return items, total

    # =====================================================================
    # VALID STATUS TRANSITIONS
    # =====================================================================

    VALID_TRANSITIONS = {
        "reserved": ["pending_approval"],
        "pending_approval": ["approved", "rejected", "changes_requested"],
        "changes_requested": ["pending_approval"],
        # rejected / released / expired / approved are terminal (no forward transitions)
    }

    # =====================================================================
    # TASK-406 — Approval Workflow
    # =====================================================================

    @staticmethod
    def _validate_transition(current_status: str, target_status: str) -> None:
        """Validate that a status transition is allowed.

        Raises:
            ValueError: If the transition is invalid.
        """
        allowed = ReservationService.VALID_TRANSITIONS.get(current_status, [])
        if target_status not in allowed:
            raise ValueError(
                f"Cannot transition from '{current_status}' to '{target_status}'. "
                f"Allowed transitions: {allowed or 'none (terminal state)'}."
            )

    @staticmethod
    def _get_reservation_or_raise(
        db: Session, reservation_id: UUID, *, lock: bool = False
    ) -> FormNumberReservation:
        """Fetch a non-deleted reservation or raise ValueError."""
        query = db.query(FormNumberReservation).filter(
            FormNumberReservation.id == reservation_id,
            FormNumberReservation.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        reservation = query.first()
        if reservation is None:
            raise ValueError(f"Reservation '{reservation_id}' not found.")
        return reservation

    @staticmethod
    def _find_approvers(db: Session) -> List[User]:
        """Find users who have an approver-eligible role (admin, reviewer, staff_manager)."""
        approver_roles = ["admin", "reviewer", "staff_manager"]
        users = (
            db.query(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .filter(
                Role.name.in_(approver_roles),
                Role.is_active.is_(True),
                Role.deleted_at.is_(None),
                UserRole.deleted_at.is_(None),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .distinct()
            .all()
        )
        return users

    @staticmethod
    def submit_for_approval(
        db: Session,
        reservation_id: UUID,
        submitted_by_id: UUID,
    ) -> FormNumberReservation:
        """Submit a reservation for approval (reserved → pending_approval).

        Only the requester may submit their own reservation.
        Creates approver assignments for all users with approver-eligible roles.
        """
        reservation = ReservationService._get_reservation_or_raise(
            db, reservation_id, lock=True
        )

        # Only the requester can submit
        if str(reservation.reserved_by_id) != str(submitted_by_id):
            raise ValueError(
                "Only the requester can submit their own reservation for approval."
            )

        ReservationService._validate_transition(
            reservation.status, "pending_approval"
        )  # type: ignore[arg-type]

        old_status = reservation.status
        reservation.status = "pending_approval"  # type: ignore[assignment]

        # Assign approvers
        approvers = ReservationService._find_approvers(db)
        if not approvers:
            raise ValueError(
                "No approvers available in the system. "
                "At least one user with an approver role is required."
            )

        for user in approvers:
            # Skip if already assigned
            existing = (
                db.query(FormReservationApprover)
                .filter(
                    FormReservationApprover.reservation_id == reservation_id,
                    FormReservationApprover.approver_id == user.id,
                    FormReservationApprover.deleted_at.is_(None),
                )
                .first()
            )
            if existing:
                # Reset decision for resubmit scenario
                existing.decision = None  # type: ignore[assignment]
                existing.decision_reason = None  # type: ignore[assignment]
                existing.decision_comments = None  # type: ignore[assignment]
                existing.decided_at = None  # type: ignore[assignment]
            else:
                db.add(
                    FormReservationApprover(
                        reservation_id=reservation_id,
                        approver_id=user.id,
                    )
                )

        # Audit log
        db.add(
            AuditLog(
                entity_type="form_number_reservations",
                entity_id=str(reservation_id),
                action="SUBMIT_FOR_APPROVAL",
                user_id=submitted_by_id,
                old_values={"status": old_status},
                new_values={"status": "pending_approval"},
                description=f"Reservation {reservation.full_form_number} submitted for approval.",
            )
        )

        db.commit()
        db.refresh(reservation)
        return reservation

    @staticmethod
    def approve_reservation(
        db: Session,
        reservation_id: UUID,
        approver_id: UUID,
    ) -> FormNumberReservation:
        """Approve a reservation (pending_approval → approved)."""
        reservation = ReservationService._get_reservation_or_raise(
            db, reservation_id, lock=True
        )
        ReservationService._validate_transition(
            reservation.status, "approved"
        )  # type: ignore[arg-type]

        now = datetime.now(timezone.utc)
        old_status = reservation.status
        reservation.status = "approved"  # type: ignore[assignment]

        # Record approver decision
        approver_record = (
            db.query(FormReservationApprover)
            .filter(
                FormReservationApprover.reservation_id == reservation_id,
                FormReservationApprover.approver_id == approver_id,
                FormReservationApprover.deleted_at.is_(None),
            )
            .first()
        )
        if approver_record:
            approver_record.decision = "approved"  # type: ignore[assignment]
            approver_record.decided_at = now  # type: ignore[assignment]
        else:
            db.add(
                FormReservationApprover(
                    reservation_id=reservation_id,
                    approver_id=approver_id,
                    decision="approved",
                    decided_at=now,
                )
            )

        db.add(
            AuditLog(
                entity_type="form_number_reservations",
                entity_id=str(reservation_id),
                action="APPROVE_RESERVATION",
                user_id=approver_id,
                old_values={"status": old_status},
                new_values={"status": "approved"},
                description=f"Reservation {reservation.full_form_number} approved.",
            )
        )

        db.commit()
        db.refresh(reservation)
        return reservation

    @staticmethod
    def reject_reservation(
        db: Session,
        reservation_id: UUID,
        approver_id: UUID,
        reason: str,
    ) -> FormNumberReservation:
        """Reject a reservation (pending_approval → rejected). Reason is mandatory.

        On rejection the reserved number is released (status → rejected,
        which means the number can be reserved again).
        """
        if not reason or not reason.strip():
            raise ValueError("A reason is required when rejecting a reservation.")

        reservation = ReservationService._get_reservation_or_raise(
            db, reservation_id, lock=True
        )
        ReservationService._validate_transition(
            reservation.status, "rejected"
        )  # type: ignore[arg-type]

        now = datetime.now(timezone.utc)
        old_status = reservation.status
        reservation.status = "rejected"  # type: ignore[assignment]
        reservation.released_at = now  # type: ignore[assignment]
        reservation.released_by_id = approver_id  # type: ignore[assignment]

        # Record approver decision
        approver_record = (
            db.query(FormReservationApprover)
            .filter(
                FormReservationApprover.reservation_id == reservation_id,
                FormReservationApprover.approver_id == approver_id,
                FormReservationApprover.deleted_at.is_(None),
            )
            .first()
        )
        if approver_record:
            approver_record.decision = "rejected"  # type: ignore[assignment]
            approver_record.decision_reason = reason.strip()  # type: ignore[assignment]
            approver_record.decided_at = now  # type: ignore[assignment]
        else:
            db.add(
                FormReservationApprover(
                    reservation_id=reservation_id,
                    approver_id=approver_id,
                    decision="rejected",
                    decision_reason=reason.strip(),
                    decided_at=now,
                )
            )

        db.add(
            AuditLog(
                entity_type="form_number_reservations",
                entity_id=str(reservation_id),
                action="REJECT_RESERVATION",
                user_id=approver_id,
                old_values={"status": old_status},
                new_values={"status": "rejected", "reason": reason.strip()},
                description=f"Reservation {reservation.full_form_number} "
                f"rejected: {reason.strip()}",
            )
        )

        db.commit()
        db.refresh(reservation)
        return reservation

    @staticmethod
    def request_changes(
        db: Session,
        reservation_id: UUID,
        approver_id: UUID,
        comments: str,
    ) -> FormNumberReservation:
        """Request changes on a reservation (changes_requested). Comments required."""
        if not comments or not comments.strip():
            raise ValueError("Comments are required when requesting changes.")

        reservation = ReservationService._get_reservation_or_raise(
            db, reservation_id, lock=True
        )
        ReservationService._validate_transition(
            reservation.status, "changes_requested"
        )  # type: ignore[arg-type]

        now = datetime.now(timezone.utc)
        old_status = reservation.status
        reservation.status = "changes_requested"  # type: ignore[assignment]

        # Record approver decision
        approver_record = (
            db.query(FormReservationApprover)
            .filter(
                FormReservationApprover.reservation_id == reservation_id,
                FormReservationApprover.approver_id == approver_id,
                FormReservationApprover.deleted_at.is_(None),
            )
            .first()
        )
        if approver_record:
            approver_record.decision = "changes_requested"  # type: ignore[assignment]
            approver_record.decision_comments = comments.strip()  # type: ignore[assignment]
            approver_record.decided_at = now  # type: ignore[assignment]
        else:
            db.add(
                FormReservationApprover(
                    reservation_id=reservation_id,
                    approver_id=approver_id,
                    decision="changes_requested",
                    decision_comments=comments.strip(),
                    decided_at=now,
                )
            )

        db.add(
            AuditLog(
                entity_type="form_number_reservations",
                entity_id=str(reservation_id),
                action="REQUEST_CHANGES",
                user_id=approver_id,
                old_values={"status": old_status},
                new_values={
                    "status": "changes_requested",
                    "comments": comments.strip(),
                },
                description=f"Changes requested for "
                f"{reservation.full_form_number}: {comments.strip()}",
            )
        )

        db.commit()
        db.refresh(reservation)
        return reservation

    @staticmethod
    def resubmit(
        db: Session,
        reservation_id: UUID,
        submitted_by_id: UUID,
    ) -> FormNumberReservation:
        """Resubmit a reservation after changes requested (changes_requested → pending_approval).

        Only the original requester may resubmit.
        """
        reservation = ReservationService._get_reservation_or_raise(
            db, reservation_id, lock=True
        )

        if str(reservation.reserved_by_id) != str(submitted_by_id):
            raise ValueError("Only the requester can resubmit their own reservation.")

        ReservationService._validate_transition(
            reservation.status, "pending_approval"
        )  # type: ignore[arg-type]

        old_status = reservation.status
        reservation.status = "pending_approval"  # type: ignore[assignment]

        # Reset approver decisions for fresh review
        approver_records = (
            db.query(FormReservationApprover)
            .filter(
                FormReservationApprover.reservation_id == reservation_id,
                FormReservationApprover.deleted_at.is_(None),
            )
            .all()
        )
        for record in approver_records:
            record.decision = None  # type: ignore[assignment]
            record.decision_reason = None  # type: ignore[assignment]
            record.decision_comments = None  # type: ignore[assignment]
            record.decided_at = None  # type: ignore[assignment]

        db.add(
            AuditLog(
                entity_type="form_number_reservations",
                entity_id=str(reservation_id),
                action="SUBMIT_FOR_APPROVAL",
                user_id=submitted_by_id,
                old_values={"status": old_status},
                new_values={"status": "pending_approval"},
                description=f"Reservation {reservation.full_form_number} resubmitted for approval.",
            )
        )

        db.commit()
        db.refresh(reservation)
        return reservation

    @staticmethod
    def list_pending_approvals(
        db: Session,
        approver_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[FormNumberReservation], int]:
        """List reservations with pending_approval status.

        If approver_id is provided, only returns reservations assigned to that approver.
        """
        query = db.query(FormNumberReservation).filter(
            FormNumberReservation.status == "pending_approval",
            FormNumberReservation.deleted_at.is_(None),
        )

        if approver_id is not None:
            query = query.join(
                FormReservationApprover,
                FormReservationApprover.reservation_id == FormNumberReservation.id,
            ).filter(
                FormReservationApprover.approver_id == approver_id,
                FormReservationApprover.deleted_at.is_(None),
            )

        total = query.count()
        items = (
            query.order_by(FormNumberReservation.created_at.asc())
            .offset(skip)
            .limit(min(limit, 100))
            .all()
        )
        return items, total

    # =====================================================================
    # TASK-407 — Release & Expiry
    # =====================================================================

    @staticmethod
    def release_reservation(
        db: Session,
        reservation_id: UUID,
        released_by_id: UUID,
        user_roles: List[str],
    ) -> FormNumberReservation:
        """Manually release a reserved form number.

        Access rules:
        - Requester (staff) can release their own reservation
        - Approver can release any reservation they are assigned to
        - Admin can release any reservation

        Cannot release already-approved reservations.
        """
        reservation = ReservationService._get_reservation_or_raise(
            db, reservation_id, lock=True
        )

        # Cannot release approved reservations
        if reservation.status == "approved":  # type: ignore[comparison-overlap]
            raise ValueError("Cannot release an already-approved reservation.")
        if reservation.status in ("released", "expired"):  # type: ignore[comparison-overlap]
            raise ValueError(f"Reservation is already '{reservation.status}'.")

        is_admin = "admin" in user_roles
        is_owner = str(reservation.reserved_by_id) == str(released_by_id)
        is_assigned_approver = False

        if not is_admin and not is_owner:
            # Check if user is an assigned approver
            approver_record = (
                db.query(FormReservationApprover)
                .filter(
                    FormReservationApprover.reservation_id == reservation_id,
                    FormReservationApprover.approver_id == released_by_id,
                    FormReservationApprover.deleted_at.is_(None),
                )
                .first()
            )
            is_assigned_approver = approver_record is not None

        if not (is_admin or is_owner or is_assigned_approver):
            raise ValueError(
                "You do not have permission to release this reservation. "
                "Only the requester, an assigned approver, or an admin can release it."
            )

        now = datetime.now(timezone.utc)
        old_status = reservation.status
        reservation.status = "released"  # type: ignore[assignment]
        reservation.released_at = now  # type: ignore[assignment]
        reservation.released_by_id = released_by_id  # type: ignore[assignment]

        db.add(
            AuditLog(
                entity_type="form_number_reservations",
                entity_id=str(reservation_id),
                action="RELEASE_NUMBER",
                user_id=released_by_id,
                old_values={"status": old_status},
                new_values={"status": "released"},
                description=f"Reservation {reservation.full_form_number} manually released.",
            )
        )

        db.commit()
        db.refresh(reservation)
        return reservation

    @staticmethod
    def expire_stale_reservations(db: Session) -> int:
        """Auto-expire reservations that have been in 'reserved' or 'changes_requested'
        status for more than 14 days.

        Returns:
            Number of reservations expired.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        now = datetime.now(timezone.utc)

        stale = (
            db.query(FormNumberReservation)
            .filter(
                FormNumberReservation.status.in_(["reserved", "changes_requested"]),
                FormNumberReservation.deleted_at.is_(None),
                FormNumberReservation.created_at < cutoff,
            )
            .all()
        )

        count = 0
        for reservation in stale:
            reservation.status = "expired"  # type: ignore[assignment]
            reservation.released_at = now  # type: ignore[assignment]
            db.add(
                AuditLog(
                    entity_type="form_number_reservations",
                    entity_id=str(reservation.id),
                    action="RESERVATION_EXPIRED",
                    user_id=None,
                    old_values={"status": reservation.status},
                    new_values={"status": "expired"},
                    description=f"Reservation "
                    f"{reservation.full_form_number} auto-expired after 14 days.",
                )
            )
            count += 1

        if count > 0:
            db.commit()
        return count

    @staticmethod
    def list_expiring_reservations(
        db: Session,
        days_threshold: int = 3,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[FormNumberReservation], int]:
        """List reservations approaching expiry (within `days_threshold` days of 14-day limit).

        Returns reservations in 'reserved' or 'changes_requested' status that were
        created more than (14 - days_threshold) days ago.
        """
        approaching_cutoff = datetime.now(timezone.utc) - timedelta(
            days=14 - days_threshold
        )

        query = db.query(FormNumberReservation).filter(
            FormNumberReservation.status.in_(["reserved", "changes_requested"]),
            FormNumberReservation.deleted_at.is_(None),
            FormNumberReservation.created_at < approaching_cutoff,
        )

        total = query.count()
        items = (
            query.order_by(FormNumberReservation.created_at.asc())
            .offset(skip)
            .limit(min(limit, 100))
            .all()
        )
        return items, total

    # =====================================================================
    # TASK-408 — Enhanced List & Detail
    # =====================================================================

    @staticmethod
    def list_reservations_enhanced(
        db: Session,
        *,
        prefix_id: Optional[UUID] = None,
        status: Optional[str] = None,
        numbering_method: Optional[str] = None,
        reserved_by_id: Optional[UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[FormNumberReservation], int]:
        """List reservations with extended filters, sorting, and pagination.

        Supports filter by: status, prefix_id, numbering_method, reserved_by_id, date range.
        Supports sort by: created_at, full_form_number, status.
        """
        query = db.query(FormNumberReservation).filter(
            FormNumberReservation.deleted_at.is_(None),
        )

        if prefix_id is not None:
            query = query.filter(FormNumberReservation.prefix_id == prefix_id)
        if status is not None:
            query = query.filter(FormNumberReservation.status == status)
        if numbering_method is not None:
            query = query.filter(
                FormNumberReservation.numbering_method == numbering_method
            )
        if reserved_by_id is not None:
            query = query.filter(FormNumberReservation.reserved_by_id == reserved_by_id)
        if date_from is not None:
            query = query.filter(FormNumberReservation.created_at >= date_from)
        if date_to is not None:
            query = query.filter(FormNumberReservation.created_at <= date_to)

        # Sorting
        sort_columns = {
            "created_at": FormNumberReservation.created_at,
            "full_form_number": FormNumberReservation.full_form_number,
            "status": FormNumberReservation.status,
        }
        sort_col = sort_columns.get(sort_by, FormNumberReservation.created_at)
        if sort_order.lower() == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        total = query.count()
        items = query.offset(skip).limit(min(limit, 100)).all()
        return items, total

    @staticmethod
    def get_reservation_detail(
        db: Session, reservation_id: UUID
    ) -> Optional[FormNumberReservation]:
        """Get full reservation detail including approver assignments and prefix info."""
        return (
            db.query(FormNumberReservation)
            .options(
                joinedload(FormNumberReservation.prefix),
                joinedload(FormNumberReservation.approvers).joinedload(
                    FormReservationApprover.approver
                ),
                joinedload(FormNumberReservation.reserved_by),
            )
            .filter(
                FormNumberReservation.id == reservation_id,
                FormNumberReservation.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def list_my_reservations(
        db: Session,
        user_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> Tuple[List[FormNumberReservation], int]:
        """List reservations for the current user."""
        query = db.query(FormNumberReservation).filter(
            FormNumberReservation.reserved_by_id == user_id,
            FormNumberReservation.deleted_at.is_(None),
        )

        total = query.count()
        items = (
            query.order_by(FormNumberReservation.created_at.desc())
            .offset(skip)
            .limit(min(limit, 100))
            .all()
        )
        return items, total

    @staticmethod
    def list_approved_unused_reservations(
        db: Session,
    ) -> List[FormNumberReservation]:
        """List all approved, unused reservations across all prefixes.

        Returns reservations that:
        - Have status = 'approved'
        - Are not released (released_at IS NULL)
        - Are not deleted (deleted_at IS NULL)
        - Have not expired (expires_at IS NULL OR expires_at > NOW())
        - Are NOT linked to any form (no form has this reservation_id)

        Ordered by created_at DESC (newest first).
        """
        now = datetime.now(timezone.utc)

        query = db.query(FormNumberReservation).filter(
            FormNumberReservation.status == "approved",
            FormNumberReservation.released_at.is_(None),
            FormNumberReservation.deleted_at.is_(None),
            or_(
                FormNumberReservation.expires_at.is_(None),
                FormNumberReservation.expires_at > now,
            ),
        )

        # Exclude reservations that are already linked to a form
        used_reservation_ids = (
            db.query(Form.form_number_reservation_id)
            .filter(
                Form.form_number_reservation_id.isnot(None),
                Form.deleted_at.is_(None),
            )
            .distinct()
        )

        query = query.filter(~FormNumberReservation.id.in_(used_reservation_ids))

        items = query.order_by(FormNumberReservation.created_at.desc()).all()
        return items
