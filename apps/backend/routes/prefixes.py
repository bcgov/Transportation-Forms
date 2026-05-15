"""Form Number Prefix API endpoints.

Provides:
  - Public read-only endpoint under /api/v1/prefixes (authenticated, any role)
  - Admin CRUD endpoints under /api/v1/admin/prefixes (RBAC-gated, FEAT-0012)
"""

from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.authorization import require_permission
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
    current_sequence: int = Field(
        default=0, ge=0, description="Last issued sequence value (zero is allowed)"
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
    """Request model for updating a prefix's configuration (FEAT-0012)."""

    prefix: Optional[str] = Field(None, min_length=1, max_length=10)
    description: Optional[str] = Field(None, max_length=500)
    current_sequence: Optional[int] = Field(None, ge=0)
    padding_length: Optional[int] = Field(None, ge=1, le=20)
    max_number_length: Optional[int] = Field(None, ge=1, le=50)
    is_case_sensitive: Optional[bool] = None

    @field_validator("prefix")
    @classmethod
    def validate_prefix_alphanumeric(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        if not v.isalnum():
            raise ValueError("Prefix must be alphanumeric (letters and digits only)")
        return v


class CheckSequenceRequest(BaseModel):
    """Request model for the sequence conflict dry-run check."""

    proposed_sequence: int = Field(..., ge=0, description="Proposed new current_sequence value")


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
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ReservationHistoryItem(BaseModel):
    """An item in the reservation history list."""

    id: str
    form_number: str
    full_form_number: str
    numbering_method: str
    status: str
    reserved_by_name: Optional[str] = None
    created_at: str
    expires_at: Optional[str] = None


class LinkedFormItem(BaseModel):
    """An item in the linked forms list."""

    id: str
    title: str
    status: str
    created_by_name: Optional[str] = None
    created_at: str


class PrefixDetailResponse(PrefixResponse):
    """Extended prefix response with reservation history and linked forms."""

    reservation_history: List[ReservationHistoryItem] = []
    linked_forms: List[LinkedFormItem] = []
    has_linked_forms: bool = False


class CheckSequenceResponse(BaseModel):
    """Response for the sequence conflict check."""

    has_conflicts: bool
    conflicting_numbers: List[int]
    suggested_sequence: int


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


def _user_display_name(user) -> Optional[str]:
    if user is None:
        return None
    parts = [user.first_name, user.last_name]
    name = " ".join(p for p in parts if p)
    return name or str(user.email)


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
        created_by_name=_user_display_name(getattr(pfx, "created_by", None)),
        updated_by_name=_user_display_name(getattr(pfx, "updated_by", None)),
        created_at=pfx.created_at.isoformat() if pfx.created_at else "",
        updated_at=pfx.updated_at.isoformat() if pfx.updated_at else "",
    )


def _to_detail_response(detail: dict) -> PrefixDetailResponse:
    pfx = detail["prefix"]
    base = _to_response(pfx)

    history = []
    for r in detail.get("reservation_history", []):
        history.append(
            ReservationHistoryItem(
                id=str(r.id),
                form_number=r.form_number,
                full_form_number=r.full_form_number,
                numbering_method=r.numbering_method,
                status=r.status,
                reserved_by_name=_user_display_name(getattr(r, "reserved_by", None)),
                created_at=r.created_at.isoformat() if r.created_at else "",
                expires_at=r.expires_at.isoformat() if r.expires_at else None,
            )
        )

    forms = []
    for f in detail.get("linked_forms", []):
        forms.append(
            LinkedFormItem(
                id=str(f.id),
                title=f.title,
                status=f.status,
                created_by_name=_user_display_name(getattr(f, "created_by", None)),
                created_at=f.created_at.isoformat() if f.created_at else "",
            )
        )

    return PrefixDetailResponse(
        **base.model_dump(),
        reservation_history=history,
        linked_forms=forms,
        has_linked_forms=detail.get("has_linked_forms", False),
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
    """List all active form number prefixes (for dropdown selection)."""
    prefixes = PrefixService.list_active_prefixes(db)
    return [_to_public_response(p) for p in prefixes]


# ============================================================================
# Admin Router — /api/v1/admin/prefixes (RBAC-gated, FEAT-0012)
# ============================================================================

admin_router = APIRouter(
    prefix="/admin/prefixes",
    tags=["Admin - Prefixes"],
)


@admin_router.get("", response_model=List[PrefixResponse])
async def admin_list_prefixes(
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("form_number_prefixes", "read")),
) -> List[PrefixResponse]:
    """List all form number prefixes (active + archived)."""
    prefixes = PrefixService.list_all_prefixes(db)
    return [_to_response(p) for p in prefixes]


@admin_router.get("/{prefix_id}", response_model=PrefixDetailResponse)
async def admin_get_prefix(
    prefix_id: UUID,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("form_number_prefixes", "read")),
) -> PrefixDetailResponse:
    """Get a prefix with reservation history and linked forms."""
    detail = PrefixService.get_prefix_detail(db, prefix_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prefix not found",
        )
    return _to_detail_response(detail)


@admin_router.post(
    "", response_model=PrefixResponse, status_code=status.HTTP_201_CREATED
)
async def admin_create_prefix(
    body: PrefixCreateRequest,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("form_number_prefixes", "create")),
) -> PrefixResponse:
    """Create a new form number prefix."""
    try:
        pfx = PrefixService.create_prefix(
            db,
            prefix=body.prefix,
            description=body.description,
            current_sequence=body.current_sequence,
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
    user: TokenData = Depends(require_permission("form_number_prefixes", "update")),
) -> PrefixResponse:
    """Update a prefix's configuration."""
    try:
        from backend.services.prefixes import _UNSET

        kwargs: dict = {}
        if body.prefix is not None:
            kwargs["prefix"] = body.prefix
        if body.description is not None:
            kwargs["description"] = body.description
        else:
            kwargs["description"] = _UNSET
        if body.current_sequence is not None:
            kwargs["current_sequence"] = body.current_sequence
        if body.padding_length is not None:
            kwargs["padding_length"] = body.padding_length
        if body.max_number_length is not None:
            kwargs["max_number_length"] = body.max_number_length
        if body.is_case_sensitive is not None:
            kwargs["is_case_sensitive"] = body.is_case_sensitive

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


@admin_router.post("/{prefix_id}/archive", response_model=PrefixResponse)
async def admin_archive_prefix(
    prefix_id: UUID,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("form_number_prefixes", "archive")),
) -> PrefixResponse:
    """Archive a prefix (sets is_active to False)."""
    try:
        pfx = PrefixService.archive_prefix(
            db,
            prefix_id,
            archived_by_id=UUID(user.sub) if user.sub else None,
        )
        return _to_response(pfx)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@admin_router.post(
    "/{prefix_id}/check-sequence", response_model=CheckSequenceResponse
)
async def admin_check_sequence(
    prefix_id: UUID,
    body: CheckSequenceRequest,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("form_number_prefixes", "update")),
) -> CheckSequenceResponse:
    """Dry-run check for sequence conflicts before updating current_sequence."""
    try:
        result = PrefixService.check_sequence_conflicts(
            db, prefix_id, body.proposed_sequence
        )
        return CheckSequenceResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@admin_router.delete("/{prefix_id}", status_code=status.HTTP_200_OK)
async def admin_delete_prefix(
    prefix_id: UUID,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("form_number_prefixes", "delete")),
):
    """Soft-delete a prefix. Blocked if active reservations exist."""
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
