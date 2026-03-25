"""Form Number Prefix API endpoints (TASK-402).

Provides:
  - Admin CRUD endpoints under /api/v1/admin/prefixes (admin role required)
  - Public read-only endpoint under /api/v1/prefixes (authenticated, any role)
"""

from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth.dependencies import get_current_user, require_admin
from backend.auth.jwt_handler import TokenData
from backend.services.prefixes import PrefixService


# ============================================================================
# Pydantic Schemas
# ============================================================================


class PrefixCreateRequest(BaseModel):
    """Request model for creating a new prefix."""

    prefix: str = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Alphanumeric prefix (stored uppercase)",
    )
    description: Optional[str] = Field(
        None, max_length=500, description="Optional description"
    )
    padding_length: int = Field(
        default=4, ge=1, le=20, description="Zero-pad width for auto-generated numbers"
    )
    max_number_length: int = Field(
        default=10, ge=1, le=50, description="Max length for custom form numbers"
    )
    is_case_sensitive: bool = Field(
        default=False, description="Whether custom number matching is case-sensitive"
    )

    @field_validator("prefix")
    @classmethod
    def validate_prefix_alphanumeric(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalnum():
            raise ValueError("Prefix must be alphanumeric (letters and digits only)")
        return v


class PrefixUpdateRequest(BaseModel):
    """Request model for updating a prefix's configuration."""

    description: Optional[str] = Field(None, max_length=500)
    padding_length: Optional[int] = Field(None, ge=1, le=20)
    max_number_length: Optional[int] = Field(None, ge=1, le=50)
    is_case_sensitive: Optional[bool] = None
    is_active: Optional[bool] = None


class PrefixResponse(BaseModel):
    """Response model for a form number prefix."""

    id: str
    prefix: str
    description: Optional[str]
    current_sequence: int
    padding_length: int
    max_number_length: int
    is_case_sensitive: bool
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class PrefixPublicResponse(BaseModel):
    """Lightweight response for the public dropdown endpoint."""

    id: str
    prefix: str
    description: Optional[str]

    class Config:
        from_attributes = True


# ============================================================================
# Helper: convert ORM → response
# ============================================================================


def _to_response(pfx) -> PrefixResponse:
    return PrefixResponse(
        id=str(pfx.id),
        prefix=pfx.prefix,
        description=pfx.description,
        current_sequence=pfx.current_sequence,
        padding_length=pfx.padding_length,
        max_number_length=pfx.max_number_length,
        is_case_sensitive=pfx.is_case_sensitive,
        is_active=pfx.is_active,
        created_at=pfx.created_at.isoformat() if pfx.created_at else "",
        updated_at=pfx.updated_at.isoformat() if pfx.updated_at else "",
    )


def _to_public_response(pfx) -> PrefixPublicResponse:
    return PrefixPublicResponse(
        id=str(pfx.id),
        prefix=pfx.prefix,
        description=pfx.description,
    )


# ============================================================================
# Public Router — /api/v1/prefixes
# ============================================================================

public_router = APIRouter(
    prefix="/prefixes",
    tags=["Prefixes"],
)


@public_router.get("", response_model=List[PrefixPublicResponse])
async def list_active_prefixes(
    db: Session = Depends(get_db),
    _user: TokenData = Depends(get_current_user),
) -> List[PrefixPublicResponse]:
    """
    List all active form number prefixes (for dropdown selection).

    Returns only active, non-deleted prefixes ordered alphabetically.
    """
    prefixes = PrefixService.list_active_prefixes(db)
    return [_to_public_response(p) for p in prefixes]


# ============================================================================
# Admin Router — /api/v1/admin/prefixes
# ============================================================================

admin_router = APIRouter(
    prefix="/admin/prefixes",
    tags=["Admin - Prefixes"],
)


@admin_router.get("", response_model=List[PrefixResponse])
async def admin_list_prefixes(
    db: Session = Depends(get_db),
    _user: TokenData = Depends(require_admin),
) -> List[PrefixResponse]:
    """
    List all form number prefixes (active + inactive) — admin only.
    """
    prefixes = PrefixService.list_all_prefixes(db)
    return [_to_response(p) for p in prefixes]


@admin_router.get("/{prefix_id}", response_model=PrefixResponse)
async def admin_get_prefix(
    prefix_id: UUID,
    db: Session = Depends(get_db),
    _user: TokenData = Depends(require_admin),
) -> PrefixResponse:
    """
    Get a single prefix by ID — admin only.
    """
    pfx = PrefixService.get_prefix_by_id(db, prefix_id)
    if not pfx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prefix not found",
        )
    return _to_response(pfx)


@admin_router.post(
    "", response_model=PrefixResponse, status_code=status.HTTP_201_CREATED
)
async def admin_create_prefix(
    body: PrefixCreateRequest,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_admin),
) -> PrefixResponse:
    """
    Create a new form number prefix — admin only.
    """
    try:
        pfx = PrefixService.create_prefix(
            db,
            prefix=body.prefix,
            description=body.description,
            padding_length=body.padding_length,
            max_number_length=body.max_number_length,
            is_case_sensitive=body.is_case_sensitive,
            created_by_id=UUID(user.sub) if user.sub else None,
        )
        return _to_response(pfx)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@admin_router.put("/{prefix_id}", response_model=PrefixResponse)
async def admin_update_prefix(
    prefix_id: UUID,
    body: PrefixUpdateRequest,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_admin),
) -> PrefixResponse:
    """
    Update a prefix's configuration — admin only.

    Only provided fields are updated. The prefix value itself and the
    current_sequence counter are not editable through this endpoint.
    """
    try:
        kwargs = {}
        if body.description is not None:
            kwargs["description"] = body.description
        if body.padding_length is not None:
            kwargs["padding_length"] = body.padding_length
        if body.max_number_length is not None:
            kwargs["max_number_length"] = body.max_number_length
        if body.is_case_sensitive is not None:
            kwargs["is_case_sensitive"] = body.is_case_sensitive
        if body.is_active is not None:
            kwargs["is_active"] = body.is_active

        pfx = PrefixService.update_prefix(
            db,
            prefix_id,
            updated_by_id=UUID(user.sub) if user.sub else None,
            **kwargs,
        )
        return _to_response(pfx)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@admin_router.delete("/{prefix_id}", status_code=status.HTTP_200_OK)
async def admin_delete_prefix(
    prefix_id: UUID,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_admin),
):
    """
    Soft-delete a prefix — admin only.

    Blocked if the prefix has active (non-released / non-expired) reservations.
    """
    try:
        pfx = PrefixService.soft_delete_prefix(
            db,
            prefix_id,
            deleted_by_id=UUID(user.sub) if user.sub else None,
        )
        return {"message": f"Prefix '{pfx.prefix}' deleted", "id": str(pfx.id)}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
