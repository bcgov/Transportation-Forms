"""Form Number Prefix service — business logic for prefix management.

Provides CRUD operations, archive, sequence conflict detection, detail
queries with reservation history and linked forms, and validation.
Permission enforcement is handled at the route level (FEAT-0012).
"""

from typing import Optional, List, Any, Dict
from uuid import UUID
from datetime import datetime, timezone
import re

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from backend.models import (
    FormNumberPrefix,
    FormNumberReservation,
    Form,
    AuditLog,
)

# Sentinel value to distinguish "not provided" from None
_UNSET: Any = object()

# Reservation statuses that do NOT block prefix deletion
_NON_BLOCKING_STATUSES = ("released", "expired", "rejected")


class PrefixService:
    """Service class for form number prefix management."""

    # =====================================================================
    # READ OPERATIONS
    # =====================================================================

    @staticmethod
    def list_active_prefixes(db: Session) -> List[FormNumberPrefix]:
        """Return all active, non-deleted prefixes ordered by prefix name."""
        return (
            db.query(FormNumberPrefix)
            .filter(
                FormNumberPrefix.is_active.is_(True),
                FormNumberPrefix.deleted_at.is_(None),
            )
            .order_by(FormNumberPrefix.prefix)
            .all()
        )

    @staticmethod
    def list_all_prefixes(db: Session) -> List[FormNumberPrefix]:
        """Return all non-deleted prefixes (active + inactive) for management view."""
        return (
            db.query(FormNumberPrefix)
            .filter(FormNumberPrefix.deleted_at.is_(None))
            .options(joinedload(FormNumberPrefix.created_by))
            .options(joinedload(FormNumberPrefix.updated_by))
            .order_by(FormNumberPrefix.prefix)
            .all()
        )

    @staticmethod
    def get_prefix_by_id(db: Session, prefix_id: UUID) -> Optional[FormNumberPrefix]:
        """Get a single prefix by its UUID (non-deleted only)."""
        return (
            db.query(FormNumberPrefix)
            .filter(
                FormNumberPrefix.id == prefix_id,
                FormNumberPrefix.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def get_prefix_by_value(
        db: Session, prefix_value: str
    ) -> Optional[FormNumberPrefix]:
        """Look up a prefix by its string value (case-insensitive)."""
        return (
            db.query(FormNumberPrefix)
            .filter(
                func.upper(FormNumberPrefix.prefix) == prefix_value.upper(),
                FormNumberPrefix.deleted_at.is_(None),
            )
            .first()
        )

    # =====================================================================
    # DETAIL — prefix + reservation history + linked forms (FEAT-0012)
    # =====================================================================

    @staticmethod
    def get_prefix_detail(db: Session, prefix_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Return a prefix with its reservation history and linked forms.

        Returns:
            Dictionary with keys ``prefix``, ``reservation_history``,
            ``linked_forms``, and ``has_linked_forms``, or ``None`` if
            the prefix does not exist.
        """
        pfx = (
            db.query(FormNumberPrefix)
            .filter(
                FormNumberPrefix.id == prefix_id,
                FormNumberPrefix.deleted_at.is_(None),
            )
            .options(joinedload(FormNumberPrefix.created_by))
            .options(joinedload(FormNumberPrefix.updated_by))
            .first()
        )
        if pfx is None:
            return None

        # Reservation history — newest first, non-deleted only
        reservations = (
            db.query(FormNumberReservation)
            .filter(
                FormNumberReservation.prefix_id == prefix_id,
                FormNumberReservation.deleted_at.is_(None),
            )
            .options(joinedload(FormNumberReservation.reserved_by))
            .order_by(FormNumberReservation.created_at.desc())
            .all()
        )

        # Linked forms — forms whose reservation belongs to this prefix
        reservation_ids = [r.id for r in reservations]
        linked_forms: List[Form] = []
        if reservation_ids:
            linked_forms = (
                db.query(Form)
                .filter(
                    Form.form_number_reservation_id.in_(reservation_ids),
                    Form.deleted_at.is_(None),
                )
                .options(joinedload(Form.created_by))
                .order_by(Form.created_at.desc())
                .all()
            )

        return {
            "prefix": pfx,
            "reservation_history": reservations,
            "linked_forms": linked_forms,
            "has_linked_forms": len(linked_forms) > 0,
        }

    # =====================================================================
    # CREATE (FEAT-0012 enhanced)
    # =====================================================================

    @staticmethod
    def create_prefix(
        db: Session,
        prefix: str,
        description: Optional[str],
        current_sequence: int = 0,
        padding_length: int = 4,
        max_number_length: int = 10,
        is_case_sensitive: bool = False,
        created_by_id: Optional[UUID] = None,
    ) -> FormNumberPrefix:
        """
        Create a new form number prefix.

        Raises:
            ValueError: If prefix already exists or validation fails
        """
        prefix_upper = prefix.strip().upper()

        if not prefix_upper or not prefix_upper.isalnum():
            raise ValueError("Prefix must be non-empty and alphanumeric.")

        if len(prefix_upper) > 10:
            raise ValueError("Prefix must be at most 10 characters.")

        if current_sequence < 0:
            raise ValueError("current_sequence must not be negative.")

        if padding_length < 1 or padding_length > 20:
            raise ValueError("padding_length must be between 1 and 20.")

        if max_number_length < 1 or max_number_length > 50:
            raise ValueError("max_number_length must be between 1 and 50.")

        existing = PrefixService.get_prefix_by_value(db, prefix_upper)
        if existing:
            raise ValueError(f"Prefix '{prefix_upper}' already exists.")

        new_prefix = FormNumberPrefix(
            prefix=prefix_upper,
            description=description,
            current_sequence=current_sequence,
            padding_length=padding_length,
            max_number_length=max_number_length,
            is_case_sensitive=is_case_sensitive,
            is_active=True,
            created_by_id=created_by_id,
            updated_by_id=created_by_id,
        )
        db.add(new_prefix)

        audit = AuditLog(
            entity_type="form_number_prefixes",
            entity_id=str(new_prefix.id),
            action="CREATE",
            user_id=created_by_id,
            new_values={
                "prefix": prefix_upper,
                "description": description,
                "current_sequence": current_sequence,
                "padding_length": padding_length,
                "max_number_length": max_number_length,
                "is_case_sensitive": is_case_sensitive,
            },
            description=f"Created form number prefix '{prefix_upper}'",
        )
        db.add(audit)

        db.commit()
        db.refresh(new_prefix)
        return new_prefix

    # =====================================================================
    # UPDATE (FEAT-0012 enhanced)
    # =====================================================================

    @staticmethod
    def _has_linked_forms(db: Session, prefix_id: UUID) -> bool:
        """Return True if any non-deleted form is linked to this prefix via a reservation."""
        return (
            db.query(Form)
            .join(
                FormNumberReservation,
                Form.form_number_reservation_id == FormNumberReservation.id,
            )
            .filter(
                FormNumberReservation.prefix_id == prefix_id,
                Form.deleted_at.is_(None),
            )
            .limit(1)
            .count()
        ) > 0

    @staticmethod
    def update_prefix(
        db: Session,
        prefix_id: UUID,
        *,
        prefix: Any = _UNSET,
        description: Any = _UNSET,
        current_sequence: Optional[int] = None,
        padding_length: Optional[int] = None,
        max_number_length: Optional[int] = None,
        is_case_sensitive: Optional[bool] = None,
        updated_by_id: Optional[UUID] = None,
    ) -> FormNumberPrefix:
        """
        Update a prefix's configuration.

        FEAT-0012 changes:
        - ``prefix`` text is now editable when no linked forms exist.
        - ``current_sequence`` is editable (validated >= 0).
        - Archived prefixes (is_active=False) cannot be updated.

        Raises:
            ValueError: If prefix not found, archived, validation fails,
                        or prefix text change is blocked by linked forms.
        """
        existing = PrefixService.get_prefix_by_id(db, prefix_id)
        if not existing:
            raise ValueError("Prefix not found.")

        if not existing.is_active:
            raise ValueError(
                "Archived prefixes cannot be edited. Delete is the only allowed action."
            )

        old_values: Dict[str, Any] = {}

        # Prefix text editing — blocked when linked forms exist
        if prefix is not _UNSET and prefix is not None:
            new_prefix = prefix.strip().upper()
            if not new_prefix or not new_prefix.isalnum():
                raise ValueError("Prefix must be non-empty and alphanumeric.")
            if len(new_prefix) > 10:
                raise ValueError("Prefix must be at most 10 characters.")

            if new_prefix != existing.prefix:
                if PrefixService._has_linked_forms(db, prefix_id):
                    raise ValueError(
                        "Prefix text cannot be changed while linked forms exist."
                    )
                # Uniqueness check for the new value
                dup = PrefixService.get_prefix_by_value(db, new_prefix)
                if dup and dup.id != existing.id:
                    raise ValueError(f"Prefix '{new_prefix}' already exists.")
                old_values["prefix"] = existing.prefix
                existing.prefix = new_prefix  # type: ignore[assignment]

        if description is not _UNSET:
            old_values["description"] = existing.description
            existing.description = description  # type: ignore[assignment]

        if current_sequence is not None:
            if current_sequence < 0:
                raise ValueError("current_sequence must not be negative.")
            old_values["current_sequence"] = existing.current_sequence
            existing.current_sequence = current_sequence  # type: ignore[assignment]

        if padding_length is not None:
            if padding_length < 1 or padding_length > 20:
                raise ValueError("padding_length must be between 1 and 20.")
            old_values["padding_length"] = existing.padding_length
            existing.padding_length = padding_length  # type: ignore[assignment]

        if max_number_length is not None:
            if max_number_length < 1 or max_number_length > 50:
                raise ValueError("max_number_length must be between 1 and 50.")
            old_values["max_number_length"] = existing.max_number_length
            existing.max_number_length = max_number_length  # type: ignore[assignment]

        if is_case_sensitive is not None:
            old_values["is_case_sensitive"] = existing.is_case_sensitive
            existing.is_case_sensitive = is_case_sensitive  # type: ignore[assignment]

        # Track updater
        existing.updated_by_id = updated_by_id  # type: ignore[assignment]

        if old_values:
            new_values = {k: getattr(existing, k) for k in old_values}
            audit = AuditLog(
                entity_type="form_number_prefixes",
                entity_id=str(existing.id),
                action="UPDATE",
                user_id=updated_by_id,
                old_values=old_values,
                new_values=new_values,
                description=f"Updated form number prefix '{existing.prefix}'",
            )
            db.add(audit)

        db.commit()
        db.refresh(existing)
        return existing

    # =====================================================================
    # ARCHIVE (FEAT-0012)
    # =====================================================================

    @staticmethod
    def archive_prefix(
        db: Session,
        prefix_id: UUID,
        archived_by_id: Optional[UUID] = None,
    ) -> FormNumberPrefix:
        """
        Archive a prefix by setting ``is_active`` to False.

        Raises:
            ValueError: If prefix not found, already archived, or soft-deleted.
        """
        existing = PrefixService.get_prefix_by_id(db, prefix_id)
        if not existing:
            raise ValueError("Prefix not found.")

        if not existing.is_active:
            raise ValueError("Prefix is already archived.")

        old_values = {"is_active": True}
        existing.is_active = False  # type: ignore[assignment]
        existing.updated_by_id = archived_by_id  # type: ignore[assignment]

        audit = AuditLog(
            entity_type="form_number_prefixes",
            entity_id=str(existing.id),
            action="ARCHIVE",
            user_id=archived_by_id,
            old_values=old_values,
            new_values={"is_active": False},
            description=f"Archived form number prefix '{existing.prefix}'",
        )
        db.add(audit)

        db.commit()
        db.refresh(existing)
        return existing

    # =====================================================================
    # SEQUENCE CONFLICT CHECK (FEAT-0012)
    # =====================================================================

    @staticmethod
    def check_sequence_conflicts(
        db: Session,
        prefix_id: UUID,
        proposed_sequence: int,
    ) -> Dict[str, Any]:
        """
        Dry-run check for sequence conflicts when resetting ``current_sequence``.

        Examines all non-deleted reservations for the prefix and determines
        whether the proposed sequence would overlap with any existing
        reservation numbers.

        Returns:
            ``{"has_conflicts": bool, "conflicting_numbers": [...],
              "suggested_sequence": int}``

        Raises:
            ValueError: If prefix not found or proposed_sequence < 0.
        """
        existing = PrefixService.get_prefix_by_id(db, prefix_id)
        if not existing:
            raise ValueError("Prefix not found.")
        if proposed_sequence < 0:
            raise ValueError("proposed_sequence must not be negative.")

        # Fetch all non-deleted reservations for this prefix
        reservations = (
            db.query(FormNumberReservation)
            .filter(
                FormNumberReservation.prefix_id == prefix_id,
                FormNumberReservation.deleted_at.is_(None),
            )
            .all()
        )

        # Extract numeric values from form_number fields
        used_numbers: set[int] = set()
        for res in reservations:
            nums = re.findall(r"\d+", res.form_number or "")
            if nums:
                try:
                    used_numbers.add(int(nums[0]))
                except (ValueError, IndexError):
                    pass

        # Determine conflicts: any used number > proposed_sequence means
        # the next generated number (proposed_sequence + 1, +2, ...) could
        # collide with an existing reservation.
        conflicting = sorted(n for n in used_numbers if n > proposed_sequence)

        if not conflicting:
            return {
                "has_conflicts": False,
                "conflicting_numbers": [],
                "suggested_sequence": proposed_sequence,
            }

        # Suggested safe sequence = highest used number so the next
        # auto-generated number won't collide.
        suggested = max(used_numbers)
        return {
            "has_conflicts": True,
            "conflicting_numbers": conflicting,
            "suggested_sequence": suggested,
        }

    # =====================================================================
    # SOFT DELETE
    # =====================================================================

    @staticmethod
    def soft_delete_prefix(
        db: Session,
        prefix_id: UUID,
        deleted_by_id: Optional[UUID] = None,
    ) -> FormNumberPrefix:
        """
        Soft-delete a prefix.

        Raises:
            ValueError: If prefix not found or has active reservations.
        """
        existing = PrefixService.get_prefix_by_id(db, prefix_id)
        if not existing:
            raise ValueError("Prefix not found.")

        # Guard: cannot delete prefix with active reservations
        active_count = (
            db.query(FormNumberReservation)
            .filter(
                FormNumberReservation.prefix_id == prefix_id,
                FormNumberReservation.deleted_at.is_(None),
                FormNumberReservation.status.notin_(_NON_BLOCKING_STATUSES),
            )
            .count()
        )
        if active_count > 0:
            raise ValueError(
                f"Cannot delete prefix '{existing.prefix}' — "
                f"it has {active_count} active reservation(s)."
            )

        existing.deleted_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        existing.is_active = False  # type: ignore[assignment]

        audit = AuditLog(
            entity_type="form_number_prefixes",
            entity_id=str(existing.id),
            action="DELETE",
            user_id=deleted_by_id,
            description=f"Soft-deleted form number prefix '{existing.prefix}'",
        )
        db.add(audit)

        db.commit()
        db.refresh(existing)
        return existing
