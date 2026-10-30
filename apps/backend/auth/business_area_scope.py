"""Business-area contact matching shared by login role sync and form scope.

A user qualifies as a contact of an active (not soft-deleted) business area when
either a contact row links to their account, or an email-only contact row's
email equals their account email after trimming and case folding (FEAT-0032
US-003). Linked contacts match on account identity: the staff-portal login
resolves the account by the authenticated email, so the linked account's email
is the authenticated email.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.models import BusinessArea, BusinessAreaContact, Role, User, UserRole

BUSINESS_AREA_MANAGER_ROLE = "business_area_manager"


def normalized_email_expression(column):
    """SQL expression matching ``ix_business_area_contacts_email_normalized``."""
    return func.lower(func.btrim(column))


def qualifying_contact_area_ids(db: Session, user_id: UUID) -> frozenset[UUID]:
    """Return active business areas where ``user_id`` is a qualifying contact.

    Runs as a single indexed query: the account email is resolved once by
    primary key, and email-only contacts are found through the normalized-email
    functional index.
    """
    normalized_user_email = (
        select(normalized_email_expression(User.email))
        .where(User.id == user_id)
        .scalar_subquery()
    )
    rows = (
        db.query(BusinessAreaContact.business_area_id)
        .join(BusinessArea, BusinessArea.id == BusinessAreaContact.business_area_id)
        .filter(
            BusinessArea.deleted_at.is_(None),
            or_(
                BusinessAreaContact.contact_user_id == user_id,
                and_(
                    BusinessAreaContact.email.isnot(None),
                    normalized_email_expression(BusinessAreaContact.email)
                    == normalized_user_email,
                ),
            ),
        )
        .distinct()
        .all()
    )
    return frozenset(area_id for (area_id,) in rows)


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _membership(db: Session, user_id: UUID, role_id: UUID) -> UserRole | None:
    return (
        db.query(UserRole)
        .filter(UserRole.user_id == user_id, UserRole.role_id == role_id)
        .first()
    )


def sync_business_area_manager_role(db: Session, user_id: UUID) -> None:
    """Grant or revoke the contact-managed role inside the caller's login transaction.

    Only the ``business_area_manager`` membership is touched; other roles are
    never modified. Revocation soft-deletes the membership so a later grant
    reactivates the same row. No audit event is written (US-003 AC10).
    """
    role = (
        db.query(Role)
        .filter(
            Role.name == BUSINESS_AREA_MANAGER_ROLE,
            Role.deleted_at.is_(None),
            Role.is_active.is_(True),
        )
        .first()
    )
    if role is None:
        return

    qualifies = bool(qualifying_contact_area_ids(db, user_id))
    membership = _membership(db, user_id, role.id)

    if not qualifies:
        if membership is not None and membership.deleted_at is None:
            membership.deleted_at = _utc_naive_now()
        return

    if membership is None:
        # Concurrent logins for the same user may race to insert this row;
        # the unique constraint makes the insert a no-op for the loser.
        db.execute(
            insert(UserRole)
            .values(id=uuid4(), user_id=user_id, role_id=role.id)
            .on_conflict_do_nothing(constraint="unique_user_role")
        )
        membership = _membership(db, user_id, role.id)
        if membership is None:
            raise RuntimeError("business_area_manager membership was not persisted")

    if membership.deleted_at is not None:
        membership.deleted_at = None
        membership.assigned_at = _utc_naive_now()
        membership.assigned_by_id = None
