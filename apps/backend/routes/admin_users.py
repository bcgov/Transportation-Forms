"""Admin user management API endpoints for forms portal UI (TASK-425 support)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from backend.auth.authorization import require_permission
from backend.auth.business_area_scope import (
    BUSINESS_AREA_MANAGER_ROLE,
    add_linked_contacts,
    qualifying_contact_area_ids,
)
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.models import AuditLog, BusinessArea, Role, User, UserRole

MAX_BUSINESS_AREA_SELECTIONS = 500


def _utc_naive_now() -> datetime:
    """Return current UTC time as a naive ``datetime`` (no tzinfo).

    FEAT-0015: replaces ``datetime.utcnow()`` which is deprecated on
    Python 3.12+ but matches the historical naive-UTC value stored in the
    SQLAlchemy ``DateTime`` columns used here.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


class ContactBusinessAreaResponse(BaseModel):
    id: str
    name: str


class AdminUserDetailResponse(AdminUserSummaryResponse):
    created_at: str
    updated_at: str
    # FEAT-0032 US-005: active areas where the user is already a qualifying contact.
    contact_business_areas: List[ContactBusinessAreaResponse] = Field(
        default_factory=list
    )


class AdminUserListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[AdminUserSummaryResponse]


class UserRoleUpdateRequest(BaseModel):
    role_ids: List[str] = Field(default_factory=list)
    # FEAT-0032 US-005: required (non-empty) when Business Area Manager is selected.
    business_area_ids: List[str] = Field(
        default_factory=list, max_length=MAX_BUSINESS_AREA_SELECTIONS
    )


def _active_user_roles(user: User) -> list[UserRole]:
    return [
        ur
        for ur in (user.roles or [])
        if ur.deleted_at is None
        and ur.role
        and ur.role.is_active
        and ur.role.deleted_at is None
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
    first_sign_in = user.created_at or _utc_naive_now()
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


def _contact_business_areas(
    db: Session, user_id: UUID
) -> list[ContactBusinessAreaResponse]:
    area_ids = qualifying_contact_area_ids(db, user_id)
    if not area_ids:
        return []
    areas = (
        db.query(BusinessArea.id, BusinessArea.name)
        .filter(BusinessArea.id.in_(area_ids), BusinessArea.deleted_at.is_(None))
        .order_by(BusinessArea.name)
        .all()
    )
    return [ContactBusinessAreaResponse(id=str(a.id), name=a.name) for a in areas]


def _to_user_detail(db: Session, user: User) -> AdminUserDetailResponse:
    summary = _to_user_summary(user)
    return AdminUserDetailResponse(
        **summary.model_dump(),
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else "",
        contact_business_areas=_contact_business_areas(db, user.id),
    )


def _parse_uuids(values: List[str], detail: str) -> set[UUID]:
    parsed: set[UUID] = set()
    for value in values:
        try:
            parsed.add(UUID(value))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=detail
            ) from exc
    return parsed


def _validate_business_area_selection(
    db: Session, target_role_ids: set[UUID], area_ids: set[UUID]
) -> bool:
    """Validate US-005 area rules before any change; return whether BAM is selected.

    Selected areas are locked ``FOR SHARE`` so a concurrent business-area delete
    cannot commit between this check and the contact insert.
    """
    manager_role_id = (
        db.query(Role.id)
        .filter(
            Role.name == BUSINESS_AREA_MANAGER_ROLE,
            Role.deleted_at.is_(None),
            Role.is_active.is_(True),
        )
        .scalar()
    )
    manager_selected = (
        manager_role_id is not None and manager_role_id in target_role_ids
    )

    if not manager_selected:
        if area_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Business areas can only be selected with the "
                    "Business Area Manager role"
                ),
            )
        return False

    if not area_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Select at least one active business area for the "
                "Business Area Manager role"
            ),
        )

    active_count = len(
        db.query(BusinessArea.id)
        .filter(BusinessArea.id.in_(area_ids), BusinessArea.deleted_at.is_(None))
        .with_for_update(read=True)
        .all()
    )
    if active_count != len(area_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more business areas are invalid or inactive",
        )
    return True


router = APIRouter(
    prefix="/admin/users",
    tags=["Admin - Users"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient permissions"},
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
    _admin: TokenData = Depends(require_permission("users", "manage_roles")),
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
    _admin: TokenData = Depends(require_permission("users", "manage_roles")),
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
    return _to_user_detail(db, user)


@router.put("/{user_id}/roles", response_model=AdminUserDetailResponse)
async def update_user_roles(
    user_id: UUID,
    body: UserRoleUpdateRequest,
    db: Session = Depends(get_db),
    admin_user: TokenData = Depends(require_permission("users", "manage_roles")),
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

    target_role_ids = _parse_uuids(body.role_ids, "Invalid role ID")
    target_area_ids = _parse_uuids(body.business_area_ids, "Invalid business area ID")

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

    manager_selected = _validate_business_area_selection(
        db, target_role_ids, target_area_ids
    )

    now = _utc_naive_now()
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

    added_contact_area_ids: list[UUID] = []
    if manager_selected:
        added_contact_area_ids = add_linked_contacts(
            db, user.id, frozenset(target_area_ids)
        )

    new_audit_values: dict = {
        "role_ids": [str(role_id) for role_id in sorted(target_role_ids, key=str)]
    }
    if manager_selected:
        # Contact additions ride on the existing UPDATE_ROLES event (US-005 AC8).
        new_audit_values["business_area_ids"] = [
            str(area_id) for area_id in sorted(target_area_ids, key=str)
        ]
        new_audit_values["added_contact_business_area_ids"] = [
            str(area_id) for area_id in added_contact_area_ids
        ]

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
            new_values=new_audit_values,
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

    return _to_user_detail(db, refreshed_user)
