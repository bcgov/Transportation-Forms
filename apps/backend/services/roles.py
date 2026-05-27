"""Role management service for admin role-management APIs (TASK-422)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from backend.models import AuditLog, Role, UserRole


def _utc_naive_now() -> datetime:
    """Return current UTC time as a naive ``datetime`` (no tzinfo).

    FEAT-0015: replaces ``datetime.utcnow()`` which is deprecated on
    Python 3.12+ but matches the historical naive-UTC value stored in the
    SQLAlchemy ``DateTime`` columns used here.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RoleNotFoundError(ValueError):
    """Raised when a role cannot be found."""


class RoleConflictError(ValueError):
    """Raised for role conflicts such as duplicate names or invalid operations."""


class RoleService:
    """Business logic for admin role management."""

    SYSTEM_ROLE_NAMES = {"admin", "staff_manager", "reviewer", "staff_viewer"}

    @staticmethod
    def list_roles(
        db: Session,
        *,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Role], int]:
        """List non-deleted roles with optional search and pagination."""
        query = db.query(Role).filter(Role.deleted_at.is_(None))

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Role.name.ilike(pattern),
                    Role.description.ilike(pattern),
                )
            )

        total = query.count()
        roles = (
            query.order_by(Role.name.asc())
            .offset(max(skip, 0))
            .limit(max(min(limit, 100), 1))
            .all()
        )
        return roles, total

    @staticmethod
    def get_role_by_id(db: Session, role_id: UUID) -> Optional[Role]:
        """Fetch role by ID with user membership preloaded."""
        return (
            db.query(Role)
            .options(joinedload(Role.user_roles).joinedload(UserRole.user))
            .filter(
                Role.id == role_id,
                Role.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def _normalize_permissions(permissions: list[str]) -> list[str]:
        cleaned = [perm.strip() for perm in permissions if perm and perm.strip()]
        deduped = sorted(set(cleaned))
        if not deduped:
            raise ValueError("permissions must include at least one permission string")
        return deduped

    @staticmethod
    def _get_by_name(db: Session, role_name: str) -> Optional[Role]:
        return (
            db.query(Role)
            .filter(
                func.lower(Role.name) == role_name.lower(),
                Role.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def create_role(
        db: Session,
        *,
        name: str,
        description: Optional[str],
        permissions: list[str],
        created_by_id: UUID,
    ) -> Role:
        """Create a custom role."""
        role_name = name.strip()
        if not role_name:
            raise ValueError("name is required")

        if RoleService._get_by_name(db, role_name):
            raise RoleConflictError(f"Role '{role_name}' already exists")

        normalized_permissions = RoleService._normalize_permissions(permissions)

        role = Role(
            name=role_name,
            description=description,
            permissions=normalized_permissions,
            is_system=False,
            is_active=True,
        )
        db.add(role)
        db.flush()

        db.add(
            AuditLog(
                entity_type="roles",
                entity_id=str(role.id),
                action="CREATE",
                user_id=created_by_id,
                new_values={
                    "name": role.name,
                    "description": role.description,
                    "permissions": normalized_permissions,
                    "is_system": role.is_system,
                },
                description=f"Created role '{role.name}'",
            )
        )

        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def update_role(
        db: Session,
        *,
        role_id: UUID,
        name: str,
        description: Optional[str],
        permissions: list[str],
        updated_by_id: UUID,
    ) -> Role:
        """Update role metadata and permissions (system roles included)."""
        role = RoleService.get_role_by_id(db, role_id)
        if not role:
            raise RoleNotFoundError("Role not found")

        role_name = name.strip()
        if not role_name:
            raise ValueError("name is required")

        existing_by_name = RoleService._get_by_name(db, role_name)
        if existing_by_name and existing_by_name.id != role.id:  # type: ignore
            raise RoleConflictError(f"Role '{role_name}' already exists")

        normalized_permissions = RoleService._normalize_permissions(permissions)

        old_values = {
            "name": role.name,
            "description": role.description,
            "permissions": list(role.permissions or []),  # type: ignore
        }

        role.name = role_name  # type: ignore
        role.description = description  # type: ignore
        role.permissions = normalized_permissions  # type: ignore

        db.add(
            AuditLog(
                entity_type="roles",
                entity_id=str(role.id),
                action="UPDATE",
                user_id=updated_by_id,
                old_values=old_values,
                new_values={
                    "name": role.name,
                    "description": role.description,
                    "permissions": normalized_permissions,
                },
                description=f"Updated role '{role.name}'",
            )
        )

        if old_values["permissions"] != normalized_permissions:
            db.add(
                AuditLog(
                    entity_type="roles",
                    entity_id=str(role.id),
                    action="UPDATE_PERMISSIONS",
                    user_id=updated_by_id,
                    old_values={"permissions": old_values["permissions"]},
                    new_values={"permissions": normalized_permissions},
                    description=f"Updated permissions for role '{role.name}'",
                )
            )

        db.commit()
        db.refresh(role)
        return role

    @staticmethod
    def delete_role(db: Session, *, role_id: UUID, deleted_by_id: UUID) -> Role:
        """Soft-delete a custom role. System roles cannot be deleted."""
        role = RoleService.get_role_by_id(db, role_id)
        if not role:
            raise RoleNotFoundError("Role not found")

        if role.is_system or role.name in RoleService.SYSTEM_ROLE_NAMES:  # type: ignore
            raise RoleConflictError("System roles cannot be deleted")

        now = _utc_naive_now()
        role.deleted_at = now  # type: ignore
        role.is_active = False  # type: ignore

        user_roles = (
            db.query(UserRole)
            .filter(
                UserRole.role_id == role.id,
                UserRole.deleted_at.is_(None),
            )
            .all()
        )
        for user_role in user_roles:
            user_role.deleted_at = now  # type: ignore

        db.add(
            AuditLog(
                entity_type="roles",
                entity_id=str(role.id),
                action="DELETE",
                user_id=deleted_by_id,
                old_values={
                    "name": role.name,
                    "description": role.description,
                    "permissions": list(role.permissions or []),  # type: ignore
                    "is_system": role.is_system,
                },
                description=f"Deleted role '{role.name}'",
            )
        )

        db.commit()
        db.refresh(role)
        return role
