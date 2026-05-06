"""Admin user management API endpoints for forms portal UI (TASK-425 support)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from backend.auth.dependencies import require_admin
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.models import AuditLog, Role, User, UserRole


class UserRoleSummaryResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_system: bool


class AdminUserSummaryResponse(BaseModel):
    id: str
    keycloak_id: Optional[str] = None
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool
    first_sign_in_at: str
    last_login: Optional[str] = None
    roles: List[UserRoleSummaryResponse]


class AdminUserDetailResponse(AdminUserSummaryResponse):
    created_at: str
    updated_at: str


class AdminUserListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[AdminUserSummaryResponse]


class UserRoleUpdateRequest(BaseModel):
    role_ids: List[str] = Field(default_factory=list)


def _active_user_roles(user: User) -> list[UserRole]:
    return [
        ur
        for ur in (user.roles or [])
        if ur.deleted_at is None and ur.role and ur.role.deleted_at is None
    ]


def _to_role_summary(role: Role) -> UserRoleSummaryResponse:
    return UserRoleSummaryResponse(
        id=str(role.id),
        name=role.name,
        description=role.description,
        is_system=bool(role.is_system),
    )


def _to_user_summary(user: User) -> AdminUserSummaryResponse:
    active_roles = sorted(
        _active_user_roles(user),
        key=lambda ur: (ur.role.name if ur.role else "").lower(),
    )
    first_sign_in = user.created_at or datetime.utcnow()
    return AdminUserSummaryResponse(
        id=str(user.id),
        keycloak_id=user.keycloak_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_active=bool(user.is_active),
        first_sign_in_at=first_sign_in.isoformat(),
        last_login=user.last_login.isoformat() if user.last_login else None,
        roles=[_to_role_summary(ur.role) for ur in active_roles if ur.role],
    )


def _to_user_detail(user: User) -> AdminUserDetailResponse:
    summary = _to_user_summary(user)
    return AdminUserDetailResponse(
        **summary.model_dump(),
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else "",
    )


router = APIRouter(
    prefix="/admin/users",
    tags=["Admin - Users"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    q: Optional[str] = Query(
        default=None,
        max_length=100,
        description="Search by first name, last name, or email",
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: TokenData = Depends(require_admin),
) -> AdminUserListResponse:
    query = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.deleted_at.is_(None))
    )

    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                User.email.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
            )
        )

    total = query.count()
    users = query.order_by(User.email.asc()).offset(skip).limit(limit).all()

    return AdminUserListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[_to_user_summary(user) for user in users],
    )


@router.get("/{user_id}", response_model=AdminUserDetailResponse)
async def get_user_detail(
    user_id: UUID,
    db: Session = Depends(get_db),
    _admin: TokenData = Depends(require_admin),
) -> AdminUserDetailResponse:
    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user_id, User.deleted_at.is_(None))
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return _to_user_detail(user)


@router.put("/{user_id}/roles", response_model=AdminUserDetailResponse)
async def update_user_roles(
    user_id: UUID,
    body: UserRoleUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: TokenData = Depends(require_admin),
) -> AdminUserDetailResponse:
    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user_id, User.deleted_at.is_(None))
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    target_role_ids: set[UUID] = set()
    for role_id_str in body.role_ids:
        try:
            target_role_ids.add(UUID(role_id_str))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role ID"
            ) from exc

    if target_role_ids:
        role_count = (
            db.query(Role)
            .filter(
                Role.id.in_(target_role_ids),
                Role.deleted_at.is_(None),
                Role.is_active.is_(True),
            )
            .count()
        )
        if role_count != len(target_role_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more role IDs are invalid",
            )

    now = datetime.utcnow()
    existing_memberships = db.query(UserRole).filter(UserRole.user_id == user.id).all()
    by_role_id = {membership.role_id: membership for membership in existing_memberships}

    current_active_role_ids = {
        membership.role_id
        for membership in existing_memberships
        if membership.deleted_at is None
    }

    for membership in existing_memberships:
        if membership.deleted_at is None and membership.role_id not in target_role_ids:
            membership.deleted_at = now

    for role_id in target_role_ids:
        membership = by_role_id.get(role_id)
        if membership is None:
            db.add(
                UserRole(
                    user_id=user.id,
                    role_id=role_id,
                    assigned_by_id=UUID(admin_user.sub),
                    deleted_at=None,
                )
            )
        elif membership.deleted_at is not None:
            membership.deleted_at = None
            membership.assigned_by_id = UUID(admin_user.sub)
            membership.assigned_at = now

    db.add(
        AuditLog(
            entity_type="users",
            entity_id=str(user.id),
            action="UPDATE_ROLES",
            user_id=UUID(admin_user.sub),
            old_values={
                "role_ids": [
                    str(role_id) for role_id in sorted(current_active_role_ids, key=str)
                ]
            },
            new_values={
                "role_ids": [
                    str(role_id) for role_id in sorted(target_role_ids, key=str)
                ]
            },
            description=f"Updated role assignments for user '{user.email}'",
        )
    )

    db.commit()

    refreshed_user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user.id, User.deleted_at.is_(None))
        .first()
    )
    if refreshed_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return _to_user_detail(refreshed_user)
