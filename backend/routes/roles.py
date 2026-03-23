"""Admin role management API endpoints (TASK-422)."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.dependencies import require_admin
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.services.roles import RoleConflictError, RoleNotFoundError, RoleService


class RoleUserResponse(BaseModel):
    """Assigned user details for role detail response."""

    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    assigned_at: str
    assigned_by_id: Optional[str] = None


class RoleSummaryResponse(BaseModel):
    """Summary response for role list endpoint."""

    id: str
    name: str
    description: Optional[str] = None
    permissions: List[str]
    is_system: bool
    is_active: bool
    user_count: int
    created_at: str
    updated_at: str


class RoleDetailResponse(BaseModel):
    """Role detail response with membership."""

    id: str
    name: str
    description: Optional[str] = None
    permissions: List[str]
    is_system: bool
    is_active: bool
    created_at: str
    updated_at: str
    users: List[RoleUserResponse]


class RoleListResponse(BaseModel):
    """Paginated role list response."""

    total: int
    skip: int
    limit: int
    items: List[RoleSummaryResponse]


class RoleCreateRequest(BaseModel):
    """Create role request model."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    permissions: List[str] = Field(..., min_length=1)


class RoleUpdateRequest(BaseModel):
    """Update role request model."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    permissions: List[str] = Field(..., min_length=1)


def _to_role_summary_response(role) -> RoleSummaryResponse:
    active_memberships = [ur for ur in (role.user_roles or []) if ur.deleted_at is None]
    return RoleSummaryResponse(
        id=str(role.id),
        name=role.name,
        description=role.description,
        permissions=[str(p) for p in (role.permissions or [])],
        is_system=bool(role.is_system),
        is_active=bool(role.is_active),
        user_count=len(active_memberships),
        created_at=role.created_at.isoformat() if role.created_at else "",
        updated_at=role.updated_at.isoformat() if role.updated_at else "",
    )


def _to_role_detail_response(role) -> RoleDetailResponse:
    users: List[RoleUserResponse] = []
    for membership in role.user_roles or []:
        if membership.deleted_at is not None:
            continue
        if membership.user is None or membership.user.deleted_at is not None:
            continue
        users.append(
            RoleUserResponse(
                id=str(membership.user.id),
                email=membership.user.email,
                first_name=membership.user.first_name,
                last_name=membership.user.last_name,
                assigned_at=membership.assigned_at.isoformat() if membership.assigned_at else "",
                assigned_by_id=str(membership.assigned_by_id) if membership.assigned_by_id else None,
            )
        )

    users.sort(key=lambda item: item.email.lower())

    return RoleDetailResponse(
        id=str(role.id),
        name=role.name,
        description=role.description,
        permissions=[str(p) for p in (role.permissions or [])],
        is_system=bool(role.is_system),
        is_active=bool(role.is_active),
        created_at=role.created_at.isoformat() if role.created_at else "",
        updated_at=role.updated_at.isoformat() if role.updated_at else "",
        users=users,
    )


router = APIRouter(
    prefix="/admin/roles",
    tags=["Admin - Roles"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
        404: {"description": "Role not found"},
        409: {"description": "Conflict"},
    },
)


@router.get("", response_model=RoleListResponse)
async def list_roles(
    q: Optional[str] = Query(default=None, max_length=100, description="Search by role name or description"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: TokenData = Depends(require_admin),
) -> RoleListResponse:
    roles, total = RoleService.list_roles(db, search=q, skip=skip, limit=limit)
    return RoleListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[_to_role_summary_response(role) for role in roles],
    )


@router.post("", response_model=RoleDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreateRequest,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_admin),
) -> RoleDetailResponse:
    try:
        role = RoleService.create_role(
            db,
            name=body.name,
            description=body.description,
            permissions=body.permissions,
            created_by_id=UUID(user.sub),
        )
        role_with_users = RoleService.get_role_by_id(db, role.id)
        if role_with_users is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load created role")
        return _to_role_detail_response(role_with_users)
    except RoleConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{role_id}", response_model=RoleDetailResponse)
async def get_role(
    role_id: UUID,
    db: Session = Depends(get_db),
    _user: TokenData = Depends(require_admin),
) -> RoleDetailResponse:
    role = RoleService.get_role_by_id(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return _to_role_detail_response(role)


@router.put("/{role_id}", response_model=RoleDetailResponse)
async def update_role(
    role_id: UUID,
    body: RoleUpdateRequest,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_admin),
) -> RoleDetailResponse:
    try:
        RoleService.update_role(
            db,
            role_id=role_id,
            name=body.name,
            description=body.description,
            permissions=body.permissions,
            updated_by_id=UUID(user.sub),
        )
        role = RoleService.get_role_by_id(db, role_id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        return _to_role_detail_response(role)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RoleConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{role_id}", status_code=status.HTTP_200_OK)
async def delete_role(
    role_id: UUID,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_admin),
):
    try:
        deleted = RoleService.delete_role(
            db,
            role_id=role_id,
            deleted_by_id=UUID(user.sub),
        )
        return {"id": str(deleted.id), "message": f"Role '{deleted.name}' deleted"}
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RoleConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
