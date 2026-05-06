"""Access request workflow service for TASK-423."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.models import AccessRequest, AuditLog, Role, User, UserRole


class AccessRequestNotFoundError(ValueError):
    """Raised when an access request cannot be found."""


class AccessRequestConflictError(ValueError):
    """Raised for access request conflict scenarios."""


class AccessRequestValidationError(ValueError):
    """Raised for invalid access request operations."""


class AccessRequestService:
    """Business logic for access request lifecycle."""

    @staticmethod
    def _get_user(db: Session, user_id: UUID) -> User:
        user = (
            db.query(User)
            .filter(
                User.id == user_id, User.deleted_at.is_(None), User.is_active.is_(True)
            )
            .first()
        )
        if not user:
            raise AccessRequestValidationError("User not found or inactive")
        return user

    @staticmethod
    def _has_active_roles(db: Session, user_id: UUID) -> bool:
        active_role = (
            db.query(UserRole)
            .join(Role, UserRole.role_id == Role.id)
            .filter(
                UserRole.user_id == user_id,
                UserRole.deleted_at.is_(None),
                Role.deleted_at.is_(None),
                Role.is_active.is_(True),
            )
            .first()
        )
        return active_role is not None

    @staticmethod
    def submit_request(db: Session, *, user_id: UUID) -> AccessRequest:
        """Submit an access request for a user without assigned roles."""
        AccessRequestService._get_user(db, user_id)

        if AccessRequestService._has_active_roles(db, user_id):
            raise AccessRequestValidationError(
                "User already has portal role assignments"
            )

        existing_pending = (
            db.query(AccessRequest)
            .filter(
                AccessRequest.user_id == user_id,
                AccessRequest.status == "pending",
                AccessRequest.deleted_at.is_(None),
            )
            .first()
        )
        if existing_pending:
            raise AccessRequestConflictError(
                "An active pending access request already exists for this user"
            )

        request = AccessRequest(
            user_id=user_id,
            status="pending",
        )
        db.add(request)
        db.flush()

        db.add(
            AuditLog(
                entity_type="access_requests",
                entity_id=str(request.id),
                action="SUBMIT",
                user_id=user_id,
                new_values={
                    "status": request.status,
                    "user_id": str(user_id),
                },
                description="Access request submitted",
            )
        )

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise AccessRequestConflictError(
                "An active pending access request already exists for this user"
            ) from exc

        db.refresh(request)
        return (
            db.query(AccessRequest)
            .options(
                joinedload(AccessRequest.user), joinedload(AccessRequest.processed_by)
            )
            .filter(AccessRequest.id == request.id)
            .first()
        )

    @staticmethod
    def get_latest_for_user(db: Session, *, user_id: UUID) -> Optional[AccessRequest]:
        """Return the newest access request for a specific user."""
        return (
            db.query(AccessRequest)
            .options(
                joinedload(AccessRequest.user), joinedload(AccessRequest.processed_by)
            )
            .filter(
                AccessRequest.user_id == user_id,
                AccessRequest.deleted_at.is_(None),
            )
            .order_by(AccessRequest.created_at.desc())
            .first()
        )

    @staticmethod
    def list_requests(
        db: Session,
        *,
        status_filter: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[AccessRequest], int]:
        """List access requests with optional status filter and pagination."""
        query = (
            db.query(AccessRequest)
            .options(
                joinedload(AccessRequest.user), joinedload(AccessRequest.processed_by)
            )
            .filter(AccessRequest.deleted_at.is_(None))
        )

        if status_filter:
            if status_filter not in {"pending", "approved", "rejected"}:
                raise AccessRequestValidationError(
                    "status must be one of: pending, approved, rejected"
                )
            query = query.filter(AccessRequest.status == status_filter)

        total = query.count()
        items = (
            query.order_by(AccessRequest.created_at.desc())
            .offset(max(skip, 0))
            .limit(max(min(limit, 100), 1))
            .all()
        )
        return items, total

    @staticmethod
    def _get_pending_or_raise(db: Session, request_id: UUID) -> AccessRequest:
        request = (
            db.query(AccessRequest)
            .filter(
                AccessRequest.id == request_id,
                AccessRequest.deleted_at.is_(None),
            )
            .with_for_update()
            .first()
        )
        if not request:
            raise AccessRequestNotFoundError("Access request not found")
        if request.status != "pending":
            raise AccessRequestConflictError("Only pending requests can be processed")
        return request

    @staticmethod
    def approve_request(
        db: Session,
        *,
        request_id: UUID,
        admin_user_id: UUID,
        review_notes: Optional[str] = None,
    ) -> AccessRequest:
        """Approve a pending access request and assign default staff_viewer role."""
        request = AccessRequestService._get_pending_or_raise(db, request_id)

        request.status = "approved"
        request.review_notes = review_notes
        request.processed_by_id = admin_user_id
        request.processed_at = datetime.utcnow()

        # Assign the default staff_viewer role if the user doesn't already have it.
        staff_viewer_role = (
            db.query(Role)
            .filter(
                Role.name == "staff_viewer",
                Role.deleted_at.is_(None),
                Role.is_active.is_(True),
            )
            .first()
        )
        if staff_viewer_role:
            already_assigned = (
                db.query(UserRole)
                .filter(
                    UserRole.user_id == request.user_id,
                    UserRole.role_id == staff_viewer_role.id,
                    UserRole.deleted_at.is_(None),
                )
                .first()
            )
            if not already_assigned:
                db.add(UserRole(user_id=request.user_id, role_id=staff_viewer_role.id))

        db.add(
            AuditLog(
                entity_type="access_requests",
                entity_id=str(request.id),
                action="APPROVE",
                user_id=admin_user_id,
                old_values={"status": "pending"},
                new_values={
                    "status": "approved",
                    "review_notes": review_notes,
                },
                description="Access request approved",
            )
        )

        db.commit()
        db.refresh(request)
        return (
            db.query(AccessRequest)
            .options(
                joinedload(AccessRequest.user), joinedload(AccessRequest.processed_by)
            )
            .filter(AccessRequest.id == request.id)
            .first()
        )

    @staticmethod
    def reject_request(
        db: Session,
        *,
        request_id: UUID,
        admin_user_id: UUID,
        review_notes: Optional[str] = None,
    ) -> AccessRequest:
        """Reject a pending access request."""
        request = AccessRequestService._get_pending_or_raise(db, request_id)

        request.status = "rejected"
        request.review_notes = review_notes
        request.processed_by_id = admin_user_id
        request.processed_at = datetime.utcnow()

        db.add(
            AuditLog(
                entity_type="access_requests",
                entity_id=str(request.id),
                action="REJECT",
                user_id=admin_user_id,
                old_values={"status": "pending"},
                new_values={
                    "status": "rejected",
                    "review_notes": review_notes,
                },
                description="Access request rejected",
            )
        )

        db.commit()
        db.refresh(request)
        return (
            db.query(AccessRequest)
            .options(
                joinedload(AccessRequest.user), joinedload(AccessRequest.processed_by)
            )
            .filter(AccessRequest.id == request.id)
            .first()
        )
