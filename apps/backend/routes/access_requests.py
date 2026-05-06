"""Access request workflow API endpoints (TASK-423)."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user, require_admin
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.services.access_requests import (
    AccessRequestConflictError,
    AccessRequestNotFoundError,
    AccessRequestService,
    AccessRequestValidationError,
)


class AccessRequestResponse(BaseModel):
    """Access request response payload."""

    id: str
    user_id: str
    user_email: Optional[str] = None
    status: str
    review_notes: Optional[str] = None
    processed_by_id: Optional[str] = None
    processed_by_email: Optional[str] = None
    processed_at: Optional[str] = None
    created_at: str
    updated_at: str


class AccessRequestListResponse(BaseModel):
    """Paginated access request list."""

    total: int
    skip: int
    limit: int
    items: List[AccessRequestResponse]


class AccessRequestDecisionRequest(BaseModel):
    """Approve/reject request body."""

    review_notes: Optional[str] = Field(default=None, max_length=2000)


def _to_response(request) -> AccessRequestResponse:
    return AccessRequestResponse(
        id=str(request.id),
        user_id=str(request.user_id),
        user_email=request.user.email if request.user else None,
        status=request.status,
        review_notes=request.review_notes,
        processed_by_id=(
            str(request.processed_by_id) if request.processed_by_id else None
        ),
        processed_by_email=request.processed_by.email if request.processed_by else None,
        processed_at=request.processed_at.isoformat() if request.processed_at else None,
        created_at=request.created_at.isoformat() if request.created_at else "",
        updated_at=request.updated_at.isoformat() if request.updated_at else "",
    )


def _handle_error(exc: Exception) -> None:
    if isinstance(exc, AccessRequestValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, AccessRequestConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, AccessRequestNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID format"
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Access request operation failed",
    )


router = APIRouter(tags=["Access Requests"])


@router.post(
    "/access-requests",
    response_model=AccessRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_access_request(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessRequestResponse:
    """Submit a generic access request for authenticated users with no assigned roles."""
    try:
        request = AccessRequestService.submit_request(
            db, user_id=UUID(current_user.sub)
        )
        return _to_response(request)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/access-requests/me", response_model=AccessRequestResponse)
async def get_my_access_request(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessRequestResponse:
    """Get the current user's latest access request status."""
    request = AccessRequestService.get_latest_for_user(
        db, user_id=UUID(current_user.sub)
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No access request found for user",
        )
    return _to_response(request)


@router.get("/admin/access-requests", response_model=AccessRequestListResponse)
async def admin_list_access_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AccessRequestListResponse:
    """Admin list/filter endpoint for access requests."""
    try:
        items, total = AccessRequestService.list_requests(
            db,
            status_filter=status_filter,
            skip=skip,
            limit=limit,
        )
        return AccessRequestListResponse(
            total=total,
            skip=skip,
            limit=limit,
            items=[_to_response(item) for item in items],
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post(
    "/admin/access-requests/{request_id}/approve", response_model=AccessRequestResponse
)
async def admin_approve_access_request(
    request_id: str,
    body: AccessRequestDecisionRequest,
    admin_user: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AccessRequestResponse:
    """Approve a pending access request (admin only)."""
    try:
        request = AccessRequestService.approve_request(
            db,
            request_id=UUID(request_id),
            admin_user_id=UUID(admin_user.sub),
            review_notes=body.review_notes,
        )
        return _to_response(request)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post(
    "/admin/access-requests/{request_id}/reject", response_model=AccessRequestResponse
)
async def admin_reject_access_request(
    request_id: str,
    body: AccessRequestDecisionRequest,
    admin_user: TokenData = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AccessRequestResponse:
    """Reject a pending access request (admin only)."""
    try:
        request = AccessRequestService.reject_request(
            db,
            request_id=UUID(request_id),
            admin_user_id=UUID(admin_user.sub),
            review_notes=body.review_notes,
        )
        return _to_response(request)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
