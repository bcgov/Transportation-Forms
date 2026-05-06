"""Form Number Prefix service — business logic for prefix management (TASK-402).

Provides CRUD operations, validation, and query helpers for form number prefixes.
Admin-only operations are enforced at the route level.
"""

from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.models import FormNumberPrefix, AuditLog

# Sentinel value to distinguish "not provided" from None
_UNSET: Any = object()


class PrefixService:
    """Service class for form number prefix management."""

    # =====================================================================
    # READ OPERATIONS
    # =====================================================================

    @staticmethod
    def list_active_prefixes(db: Session) -> List[FormNumberPrefix]:
        """
        Return all active, non-deleted prefixes ordered by prefix name.

        Used by the public dropdown endpoint.
        """
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
        """
        Return all non-deleted prefixes (active + inactive) for admin view.
        """
        return (
            db.query(FormNumberPrefix)
            .filter(FormNumberPrefix.deleted_at.is_(None))
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
    # CREATE
    # =====================================================================

    @staticmethod
    def create_prefix(
        db: Session,
        prefix: str,
        description: Optional[str],
        padding_length: int = 4,
        max_number_length: int = 10,
        is_case_sensitive: bool = False,
        created_by_id: Optional[UUID] = None,
    ) -> FormNumberPrefix:
        """
        Create a new form number prefix.

        Args:
            db: Database session
            prefix: The prefix string (stored uppercase)
            description: Optional description
            padding_length: Zero-padding width for auto-generated numbers
            max_number_length: Maximum length for custom form numbers
            is_case_sensitive: Whether custom number matching is case-sensitive
            created_by_id: UUID of the admin creating the prefix

        Returns:
            Newly created FormNumberPrefix

        Raises:
            ValueError: If prefix already exists or validation fails
        """
        # Normalise to uppercase
        prefix_upper = prefix.strip().upper()

        if not prefix_upper or not prefix_upper.isalnum():
            raise ValueError("Prefix must be non-empty and alphanumeric.")

        if len(prefix_upper) > 10:
            raise ValueError("Prefix must be at most 10 characters.")

        if padding_length < 1 or padding_length > 20:
            raise ValueError("padding_length must be between 1 and 20.")

        if max_number_length < 1 or max_number_length > 50:
            raise ValueError("max_number_length must be between 1 and 50.")

        # Check uniqueness
        existing = PrefixService.get_prefix_by_value(db, prefix_upper)
        if existing:
            raise ValueError(f"Prefix '{prefix_upper}' already exists.")

        new_prefix = FormNumberPrefix(
            prefix=prefix_upper,
            description=description,
            current_sequence=0,
            padding_length=padding_length,
            max_number_length=max_number_length,
            is_case_sensitive=is_case_sensitive,
            is_active=True,
            created_by_id=created_by_id,
        )
        db.add(new_prefix)

        # Audit log
        audit = AuditLog(
            entity_type="form_number_prefixes",
            entity_id=str(new_prefix.id),
            action="CREATE",
            user_id=created_by_id,
            new_values={
                "prefix": prefix_upper,
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
    # UPDATE
    # =====================================================================

    @staticmethod
    def update_prefix(
        db: Session,
        prefix_id: UUID,
        *,
        description: Any = _UNSET,
        padding_length: Optional[int] = None,
        max_number_length: Optional[int] = None,
        is_case_sensitive: Optional[bool] = None,
        is_active: Optional[bool] = None,
        updated_by_id: Optional[UUID] = None,
    ) -> FormNumberPrefix:
        """
        Update a prefix's configuration.

        The `prefix` value itself and `current_sequence` are NOT editable via
        this method to preserve referential integrity and sequence safety.

        Args:
            All optional; only provided values are applied.

        Returns:
            Updated FormNumberPrefix

        Raises:
            ValueError: If prefix not found or validation fails
        """
        existing = PrefixService.get_prefix_by_id(db, prefix_id)
        if not existing:
            raise ValueError("Prefix not found.")

        old_values = {}

        if description is not _UNSET:
            old_values["description"] = existing.description
            existing.description = description  # type: ignore[assignment]

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

        if is_active is not None:
            old_values["is_active"] = existing.is_active
            existing.is_active = is_active  # type: ignore[assignment]

        # Audit log
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
            ValueError: If prefix not found or has active reservations
        """
        existing = PrefixService.get_prefix_by_id(db, prefix_id)
        if not existing:
            raise ValueError("Prefix not found.")

        # Guard: cannot delete prefix with active reservations
        # (FormNumberReservation will be introduced in TASK-403; import
        #  conditionally to avoid circular import before that table exists.)
        try:
            from backend.models import FormNumberReservation

            active_count = (
                db.query(FormNumberReservation)
                .filter(
                    FormNumberReservation.prefix_id == prefix_id,
                    FormNumberReservation.deleted_at.is_(None),
                    FormNumberReservation.status.notin_(
                        ["released", "expired", "rejected"]
                    ),
                )
                .count()
            )
            if active_count > 0:
                raise ValueError(
                    f"Cannot delete prefix '{existing.prefix}' — "
                    f"it has {active_count} active reservation(s)."
                )
        except ImportError:
            # FormNumberReservation table does not exist yet (TASK-403)
            pass

        existing.deleted_at = datetime.utcnow()  # type: ignore[assignment]
        existing.is_active = False  # type: ignore[assignment]

        # Audit log
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
