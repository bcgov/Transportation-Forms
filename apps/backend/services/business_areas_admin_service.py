"""Service for handling Business Areas complex Admin logic."""

from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.models import BusinessArea, BusinessAreaContact, Form, AuditLog
from backend.auth.jwt_handler import TokenData


def _utc_naive_now() -> datetime:
    """Return current UTC time as a naive ``datetime`` (matches DB columns).

    Mirrors the helper in ``backend.services.forms`` so we don't rely on the
    deprecated ``datetime.utcnow()`` on Python 3.12+.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user_uuid(user: TokenData | None) -> UUID | None:
    """Safely coerce a TokenData ``sub`` to a UUID for audit FK columns."""
    if user is None or not getattr(user, "sub", None):
        return None
    try:
        return UUID(str(user.sub))
    except (ValueError, TypeError):
        return None


class BusinessAreaAdminService:
    @staticmethod
    def get_business_area_contacts(db: Session, business_area_id: str):
        return db.query(BusinessAreaContact).filter(
            BusinessAreaContact.business_area_id == business_area_id
        ).all()

    @staticmethod
    def delete_business_area(
        db: Session,
        business_area_id: str,
        user: TokenData,
        replacement_id: str | None = None,
    ):
        """Hard delete, soft delete, or reassignment logic.

        - Zero linked forms (AC2): hard-delete the row.
        - Linked forms + replacement (AC5): reassign all forms to the
          replacement, then hard-delete the source. One audit entry per form,
          plus one for the BA.
        - Linked forms, no replacement (AC4): soft-delete (sets ``deleted_at``).

        Audit columns follow the ``AuditLog`` model contract:
        ``entity_type`` / ``entity_id`` (string) / uppercase ``action`` /
        ``old_values`` / ``new_values`` / ``description``.
        """
        ba = (
            db.query(BusinessArea)
            .filter(BusinessArea.id == business_area_id)
            .first()
        )
        if not ba or ba.deleted_at:
            raise ValueError("Business Area not found")

        actor_id = _user_uuid(user)
        forms_count = (
            db.query(Form)
            .filter(Form.business_area_id == business_area_id)
            .count()
        )

        if forms_count == 0:
            # AC2: Hard Delete (Unreferenced)
            name = ba.name
            ba_id_str = str(ba.id)
            db.delete(ba)

            audit = AuditLog(
                entity_type="business_areas",
                entity_id=ba_id_str,
                action="DELETE",
                user_id=actor_id,
                old_values={"name": name},
                new_values=None,
                description=(
                    f"Hard-deleted business area '{name}' (0 linked forms)"
                ),
            )
            db.add(audit)
            db.commit()
            return {"status": "hard-deleted"}

        if replacement_id:
            # AC5: Reassign and Delete
            if str(replacement_id) == str(business_area_id):
                raise ValueError("Cannot reassign to the same business area")

            target_ba = (
                db.query(BusinessArea)
                .filter(BusinessArea.id == replacement_id)
                .first()
            )
            if not target_ba or target_ba.deleted_at:
                raise ValueError("Target Business Area not found or deleted")

            forms = (
                db.query(Form)
                .filter(Form.business_area_id == business_area_id)
                .all()
            )
            ba_id_str = str(ba.id)
            target_id_str = str(target_ba.id)
            source_name = ba.name
            target_name = target_ba.name

            for form in forms:
                form.business_area_id = target_ba.id
                form_audit = AuditLog(
                    entity_type="forms",
                    entity_id=str(form.id),
                    action="UPDATE",
                    user_id=actor_id,
                    old_values={"business_area_id": ba_id_str},
                    new_values={"business_area_id": target_id_str},
                    description=(
                        f"Reassigned business area from '{source_name}' to "
                        f"'{target_name}' due to source business area deletion"
                    ),
                )
                db.add(form_audit)

            # CRITICAL: persist the reassignment BEFORE marking ``ba`` for
            # deletion. SQLAlchemy's default relationship behaviour
            # (``passive_deletes=False``, no ``cascade='delete'``) reconciles
            # ``BusinessArea.forms`` while processing the parent DELETE and
            # will issue ``UPDATE forms SET business_area_id = NULL`` for any
            # rows it still considers children — silently undoing our
            # reassignment. Flushing first writes the new FK values to the
            # DB, and expiring ``ba.forms`` forces a fresh (now empty)
            # lazy-load so the unit-of-work has nothing to nullify.
            db.flush()
            db.expire(ba, ["forms"])

            db.delete(ba)

            ba_audit = AuditLog(
                entity_type="business_areas",
                entity_id=ba_id_str,
                action="DELETE",
                user_id=actor_id,
                old_values={
                    "name": source_name,
                    "linked_forms_count": forms_count,
                },
                new_values={
                    "replacement_id": target_id_str,
                    "replacement_name": target_name,
                },
                description=(
                    f"Hard-deleted business area '{source_name}' after "
                    f"reassigning {forms_count} form(s) to '{target_name}'"
                ),
            )
            db.add(ba_audit)
            db.commit()
            return {"status": "reassigned-and-hard-deleted"}

        # AC4: Soft-Delete (linked forms, no replacement provided)
        ba.deleted_at = _utc_naive_now()
        ba_audit = AuditLog(
            entity_type="business_areas",
            entity_id=str(ba.id),
            action="DELETE",
            user_id=actor_id,
            old_values={"name": ba.name, "linked_forms_count": forms_count},
            new_values={"deleted_at": ba.deleted_at.isoformat()},
            description=(
                f"Soft-deleted business area '{ba.name}' "
                f"({forms_count} linked form(s) retained)"
            ),
        )
        db.add(ba_audit)
        db.commit()
        return {"status": "soft-deleted"}

    @staticmethod
    def restore_business_area(
        db: Session,
        business_area_id: str,
        user: TokenData,
    ) -> BusinessArea:
        """Restore a previously soft-deleted Business Area.

        AC3 from ``US-001-admin-crud`` (FEAT-0025): when a duplicate Name
        collision is confirmed, the existing soft-deleted record has its
        ``deleted_at`` cleared and an audit event is logged.

        Raises ``ValueError`` if:
          - the business area does not exist; or
          - the business area is not soft-deleted (``deleted_at`` is ``None``).

        Returns the refreshed ``BusinessArea`` ORM instance on success.
        """
        ba = (
            db.query(BusinessArea)
            .filter(BusinessArea.id == business_area_id)
            .first()
        )
        if not ba:
            raise ValueError("Business Area not found")
        if ba.deleted_at is None:
            raise ValueError("Business Area is not deleted")

        previous_deleted_at = ba.deleted_at
        ba.deleted_at = None

        audit = AuditLog(
            entity_type="business_areas",
            entity_id=str(ba.id),
            action="RESTORE",
            user_id=_user_uuid(user),
            old_values={
                "name": ba.name,
                "deleted_at": previous_deleted_at.isoformat(),
            },
            new_values={"deleted_at": None},
            description=(
                f"Restored soft-deleted business area '{ba.name}'"
            ),
        )
        db.add(audit)
        db.commit()
        db.refresh(ba)
        return ba
