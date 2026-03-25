"""Form Number Reservation API endpoints (TASK-404, TASK-405, TASK-406, TASK-407, TASK-408).

Provides:
  - POST /api/v1/reservations/generate      — auto-generated sequential reservation
  - POST /api/v1/reservations/custom        — custom (manual) form number reservation
  - POST /api/v1/reservations/{id}/submit   — submit reservation for approval
  - POST /api/v1/reservations/{id}/approve  — approve a reservation
  - POST /api/v1/reservations/{id}/reject   — reject a reservation
  - POST /api/v1/reservations/{id}/request-changes — request changes on a reservation
  - POST /api/v1/reservations/{id}/resubmit — resubmit after changes requested
  - POST /api/v1/reservations/{id}/release  — manually release a reserved number
  - GET  /api/v1/reservations/pending       — list pending approval requests
  - GET  /api/v1/reservations/expiring      — list reservations approaching expiry
  - POST /api/v1/reservations/expire        — trigger auto-expiry of stale reservations
  - GET  /api/v1/reservations/my            — list current user's reservations
  - GET  /api/v1/reservations               — list reservations (with filters)
  - GET  /api/v1/reservations/{id}          — get single reservation detail
"""

from typing import Optional, List
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.services.reservations import ReservationService


# ============================================================================
# Pydantic Schemas
# ============================================================================


class AutoGenerateRequest(BaseModel):
    """Request body for auto-generating the next sequential form number."""

    prefix_id: str = Field(..., description="UUID of the form number prefix to use")


class CustomReserveRequest(BaseModel):
    """Request body for reserving a custom (manual) form number."""

    prefix_id: str = Field(..., description="UUID of the form number prefix to use")
    form_number: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="The custom number portion (e.g., '0020A')",
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Justification for requesting a special number",
    )

    @field_validator("form_number")
    @classmethod
    def validate_form_number_alnum(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("form_number must not be empty")
        if not cleaned.replace(" ", "").isalnum():
            raise ValueError(
                "form_number must be alphanumeric (letters and digits only)"
            )
        return cleaned


class ReservationResponse(BaseModel):
    """Response model for a form number reservation."""

    id: str
    prefix_id: str
    form_number: str
    full_form_number: str
    numbering_method: str
    custom_number_reason: Optional[str] = None
    status: str
    reserved_by_id: str
    expires_at: Optional[str] = None
    released_at: Optional[str] = None
    released_by_id: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# TASK-406: Approval workflow schemas


class RejectRequest(BaseModel):
    """Request body for rejecting a reservation."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Reason for rejection (mandatory)",
    )


class RequestChangesRequest(BaseModel):
    """Request body for requesting changes on a reservation."""

    comments: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Comments describing required changes (mandatory)",
    )


class ApproverDecisionResponse(BaseModel):
    """Response model for an approver's decision."""

    id: str
    approver_id: str
    approver_email: Optional[str] = None
    approver_name: Optional[str] = None
    decision: Optional[str] = None
    decision_reason: Optional[str] = None
    decision_comments: Optional[str] = None
    decided_at: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class PrefixInfoResponse(BaseModel):
    """Compact prefix info included in reservation detail."""

    id: str
    prefix: str
    description: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class ReservationDetailResponse(BaseModel):
    """Detailed response with nested approver and prefix information (TASK-408)."""

    id: str
    prefix_id: str
    form_number: str
    full_form_number: str
    numbering_method: str
    custom_number_reason: Optional[str] = None
    status: str
    reserved_by_id: str
    reserved_by_email: Optional[str] = None
    reserved_by_name: Optional[str] = None
    expires_at: Optional[str] = None
    released_at: Optional[str] = None
    released_by_id: Optional[str] = None
    created_at: str
    updated_at: str
    prefix: Optional[PrefixInfoResponse] = None
    approvers: List[ApproverDecisionResponse] = []

    class Config:
        from_attributes = True


class ReservationListResponse(BaseModel):
    """Paginated list of reservations."""

    total: int
    skip: int
    limit: int
    items: List[ReservationResponse]


class ApprovedUnusedReservationsResponse(BaseModel):
    """Response for approved and unused reservations (TASK-413)."""

    reservations: List[ReservationResponse]

    class Config:
        from_attributes = True


class ExpiryResultResponse(BaseModel):
    """Response for the expiry trigger endpoint."""

    expired_count: int
    message: str


# ============================================================================
# Helper: ORM → response
# ============================================================================


def _to_response(r) -> ReservationResponse:
    return ReservationResponse(
        id=str(r.id),
        prefix_id=str(r.prefix_id),
        form_number=r.form_number,
        full_form_number=r.full_form_number,
        numbering_method=r.numbering_method,
        custom_number_reason=r.custom_number_reason,
        status=r.status,
        reserved_by_id=str(r.reserved_by_id),
        expires_at=r.expires_at.isoformat() if r.expires_at else None,
        released_at=r.released_at.isoformat() if r.released_at else None,
        released_by_id=str(r.released_by_id) if r.released_by_id else None,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


def _to_detail_response(r) -> ReservationDetailResponse:
    """Convert ORM reservation with eagerly loaded relationships to detail response."""
    prefix_info = None
    if r.prefix:
        prefix_info = PrefixInfoResponse(
            id=str(r.prefix.id),
            prefix=r.prefix.prefix,
            description=r.prefix.description,
            is_active=r.prefix.is_active,
        )

    approver_list = []
    if r.approvers:
        for a in r.approvers:
            if a.deleted_at is not None:
                continue
            approver_list.append(
                ApproverDecisionResponse(
                    id=str(a.id),
                    approver_id=str(a.approver_id),
                    approver_email=a.approver.email if a.approver else None,
                    approver_name=(
                        f"{a.approver.first_name or ''} {a.approver.last_name or ''}".strip()
                        if a.approver
                        else None
                    ),
                    decision=a.decision,
                    decision_reason=a.decision_reason,
                    decision_comments=a.decision_comments,
                    decided_at=a.decided_at.isoformat() if a.decided_at else None,
                    created_at=a.created_at.isoformat() if a.created_at else "",
                )
            )

    reserved_by_email = None
    reserved_by_name = None
    if r.reserved_by:
        reserved_by_email = r.reserved_by.email
        reserved_by_name = (
            f"{r.reserved_by.first_name or ''} {r.reserved_by.last_name or ''}".strip()
        )

    return ReservationDetailResponse(
        id=str(r.id),
        prefix_id=str(r.prefix_id),
        form_number=r.form_number,
        full_form_number=r.full_form_number,
        numbering_method=r.numbering_method,
        custom_number_reason=r.custom_number_reason,
        status=r.status,
        reserved_by_id=str(r.reserved_by_id),
        reserved_by_email=reserved_by_email,
        reserved_by_name=reserved_by_name,
        expires_at=r.expires_at.isoformat() if r.expires_at else None,
        released_at=r.released_at.isoformat() if r.released_at else None,
        released_by_id=str(r.released_by_id) if r.released_by_id else None,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
        prefix=prefix_info,
        approvers=approver_list,
    )


# ============================================================================
# Router
# ============================================================================

router = APIRouter(
    prefix="/reservations",
    tags=["Reservations"],
    responses={
        400: {"description": "Bad request / validation error"},
        401: {"description": "Not authenticated"},
        409: {"description": "Conflict — duplicate form number"},
    },
)


# ============================================================================
# TASK-404 — POST /api/v1/reservations/generate
# ============================================================================


@router.post(
    "/generate",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve next auto-generated sequential number",
)
async def reserve_auto_generated(
    body: AutoGenerateRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    """
    Generate and reserve the next sequential form number for the given prefix.

    - Atomically increments the prefix sequence counter.
    - Returns the newly reserved number with status ``reserved``.
    - Expiry is set to **1 day** from creation.
    - Requires an authenticated staff user.
    """
    try:
        prefix_uuid = UUID(body.prefix_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prefix_id must be a valid UUID",
        )

    try:
        reservation = ReservationService.reserve_auto_generated(
            db=db,
            prefix_id=prefix_uuid,
            reserved_by_id=UUID(current_user.sub),
        )
        return _to_response(reservation)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate sequential number: {e}",
        )


# ============================================================================
# TASK-405 — POST /api/v1/reservations/custom
# ============================================================================


@router.post(
    "/custom",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve a custom (manual) form number",
)
async def reserve_custom(
    body: CustomReserveRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    """
    Reserve a manually entered custom form number.

    - The custom number must be alphanumeric and within the prefix's
      ``max_number_length``.
    - A ``reason`` is required.
    - Does **not** affect the auto-generated sequence counter.
    - Expiry is set to **14 days** from creation.
    - Returns ``409 Conflict`` if the number is already reserved.
    """
    try:
        prefix_uuid = UUID(body.prefix_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prefix_id must be a valid UUID",
        )

    try:
        reservation = ReservationService.reserve_custom(
            db=db,
            prefix_id=prefix_uuid,
            form_number=body.form_number,
            reason=body.reason,
            reserved_by_id=UUID(current_user.sub),
        )
        return _to_response(reservation)
    except ValueError as e:
        error_msg = str(e)
        # Duplicate → 409 Conflict
        if "already reserved" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reserve custom number: {e}",
        )


# ============================================================================
# TASK-406 — Approval Workflow Endpoints
# ============================================================================


@router.post(
    "/{reservation_id}/submit",
    response_model=ReservationResponse,
    summary="Submit reservation for approval",
)
async def submit_for_approval(
    reservation_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    """
    Submit a reservation for internal approval (reserved → pending_approval).

    Only the original requester may submit their own reservation.
    Approvers are automatically assigned from users with appropriate roles.
    """
    try:
        reservation = ReservationService.submit_for_approval(
            db=db,
            reservation_id=reservation_id,
            submitted_by_id=UUID(current_user.sub),
        )
        return _to_response(reservation)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/pending",
    response_model=ReservationListResponse,
    summary="List pending approval requests",
)
async def list_pending_approvals(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationListResponse:
    """
    List reservations in pending_approval status. For approvers, shows
    reservations assigned to them. Admins see all pending requests.
    """
    approver_id = None
    if "admin" not in current_user.roles:
        approver_id = UUID(current_user.sub)

    items, total = ReservationService.list_pending_approvals(
        db,
        approver_id=approver_id,
        skip=skip,
        limit=limit,
    )
    return ReservationListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[_to_response(r) for r in items],
    )


@router.post(
    "/{reservation_id}/approve",
    response_model=ReservationResponse,
    summary="Approve a reservation",
)
async def approve_reservation(
    reservation_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    """
    Approve a reservation (pending_approval → approved).

    Requires an approver role (admin, reviewer, or staff_manager).
    """
    _require_approver_role(current_user)
    try:
        reservation = ReservationService.approve_reservation(
            db=db,
            reservation_id=reservation_id,
            approver_id=UUID(current_user.sub),
        )
        return _to_response(reservation)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/{reservation_id}/reject",
    response_model=ReservationResponse,
    summary="Reject a reservation",
)
async def reject_reservation(
    reservation_id: UUID,
    body: RejectRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    """
    Reject a reservation (pending_approval → rejected).

    Requires an approver role and a mandatory rejection reason.
    The reserved number is released and becomes available.
    """
    _require_approver_role(current_user)
    try:
        reservation = ReservationService.reject_reservation(
            db=db,
            reservation_id=reservation_id,
            approver_id=UUID(current_user.sub),
            reason=body.reason,
        )
        return _to_response(reservation)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/{reservation_id}/request-changes",
    response_model=ReservationResponse,
    summary="Request changes on a reservation",
)
async def request_changes(
    reservation_id: UUID,
    body: RequestChangesRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    """
    Request changes on a reservation (pending_approval → changes_requested).

    Requires an approver role and mandatory comments describing what needs to change.
    """
    _require_approver_role(current_user)
    try:
        reservation = ReservationService.request_changes(
            db=db,
            reservation_id=reservation_id,
            approver_id=UUID(current_user.sub),
            comments=body.comments,
        )
        return _to_response(reservation)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/{reservation_id}/resubmit",
    response_model=ReservationResponse,
    summary="Resubmit reservation after changes requested",
)
async def resubmit_reservation(
    reservation_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    """
    Resubmit a reservation after changes were requested (changes_requested → pending_approval).

    Only the original requester may resubmit.
    """
    try:
        reservation = ReservationService.resubmit(
            db=db,
            reservation_id=reservation_id,
            submitted_by_id=UUID(current_user.sub),
        )
        return _to_response(reservation)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ============================================================================
# TASK-407 — Release & Expiry Endpoints
# ============================================================================


@router.post(
    "/{reservation_id}/release",
    response_model=ReservationResponse,
    summary="Manually release a reserved number",
)
async def release_reservation(
    reservation_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    """
    Manually release a reserved form number.

    - Staff can release their own reservations.
    - Approvers can release any reservation assigned to them.
    - Admins can release any reservation.
    - Cannot release already-approved reservations (returns 400).
    """
    try:
        reservation = ReservationService.release_reservation(
            db=db,
            reservation_id=reservation_id,
            released_by_id=UUID(current_user.sub),
            user_roles=current_user.roles,
        )
        return _to_response(reservation)
    except ValueError as e:
        error_msg = str(e)
        if "permission" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )


@router.get(
    "/expiring",
    response_model=ReservationListResponse,
    summary="List reservations approaching expiry",
)
async def list_expiring_reservations(
    days_threshold: int = Query(
        3, ge=1, le=14, description="Days before expiry to flag"
    ),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max records to return"),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationListResponse:
    """
    List reservations approaching expiry (admin view).

    Returns reservations in 'reserved' or 'changes_requested' status that are
    within the specified number of days of the 14-day expiry limit.
    """
    _require_admin_role(current_user)
    items, total = ReservationService.list_expiring_reservations(
        db,
        days_threshold=days_threshold,
        skip=skip,
        limit=limit,
    )
    return ReservationListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[_to_response(r) for r in items],
    )


@router.post(
    "/expire",
    response_model=ExpiryResultResponse,
    summary="Trigger auto-expiry of stale reservations",
)
async def trigger_expiry(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExpiryResultResponse:
    """
    Admin endpoint to trigger auto-expiry of stale reservations.

    Expires all reservations in 'reserved' or 'changes_requested' status
    that are older than 14 days.
    """
    _require_admin_role(current_user)
    count = ReservationService.expire_stale_reservations(db)
    return ExpiryResultResponse(
        expired_count=count,
        message=(
            f"{count} reservation(s) expired."
            if count > 0
            else "No stale reservations found."
        ),
    )


# ============================================================================
# TASK-408 — List & Detail Endpoints (enhanced)
# ============================================================================


@router.get(
    "/my",
    response_model=ReservationListResponse,
    summary="List current user's reservations",
)
async def list_my_reservations(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationListResponse:
    """
    List reservations belonging to the currently authenticated user.
    """
    items, total = ReservationService.list_my_reservations(
        db,
        user_id=UUID(current_user.sub),
        skip=skip,
        limit=limit,
    )
    return ReservationListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[_to_response(r) for r in items],
    )


@router.get(
    "",
    response_model=ReservationListResponse,
    summary="List reservations with optional filters",
)
async def list_reservations(
    prefix_id: Optional[str] = Query(None, description="Filter by prefix UUID"),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status"
    ),
    numbering_method: Optional[str] = Query(
        None, description="Filter by numbering method (auto_generated or custom)"
    ),
    reserved_by_id: Optional[str] = Query(None, description="Filter by requester UUID"),
    date_from: Optional[str] = Query(
        None, description="Filter by creation date (ISO format, inclusive lower bound)"
    ),
    date_to: Optional[str] = Query(
        None, description="Filter by creation date (ISO format, inclusive upper bound)"
    ),
    sort_by: Optional[str] = Query(
        "created_at", description="Sort by: created_at, full_form_number, status"
    ),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationListResponse:
    """
    List form number reservations with optional filters, sorting, and pagination.

    Supports filtering by status, prefix, numbering method, requester, and date range.
    Supports sorting by created_at, full_form_number, or status.
    """
    pfx_uuid = None
    if prefix_id:
        try:
            pfx_uuid = UUID(prefix_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="prefix_id must be a valid UUID",
            )

    rby_uuid = None
    if reserved_by_id:
        try:
            rby_uuid = UUID(reserved_by_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="reserved_by_id must be a valid UUID",
            )

    dt_from = None
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_from must be in ISO 8601 format",
            )

    dt_to = None
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_to must be in ISO 8601 format",
            )

    # Validate sort parameters
    valid_sort_fields = {"created_at", "full_form_number", "status"}
    if sort_by not in valid_sort_fields:
        sort_by = "created_at"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    items, total = ReservationService.list_reservations_enhanced(
        db,
        prefix_id=pfx_uuid,
        status=status_filter,
        numbering_method=numbering_method,
        reserved_by_id=rby_uuid,
        date_from=dt_from,
        date_to=dt_to,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )
    return ReservationListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[_to_response(r) for r in items],
    )


# Get approved and unused reservations - MUST be before /{reservation_id} route
@router.get(
    "/approved-unused",
    response_model=ApprovedUnusedReservationsResponse,
    summary="Get all approved and unused form number reservations",
)
async def get_approved_unused_reservations(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApprovedUnusedReservationsResponse:
    """
    Retrieve all approved, unused form number reservations across all prefixes.

    Returns reservations that are:
    - Status = 'approved'
    - Not released
    - Not deleted
    - Not expired (or have no expiry set)
    - Not linked to an existing form

    Ordered by created_at DESC (newest first).

    **Authentication:** Required (staff role minimum)
    """
    reservations = ReservationService.list_approved_unused_reservations(db)
    return ApprovedUnusedReservationsResponse(
        reservations=[_to_response(r) for r in reservations]
    )


# Get single reservation by ID - MUST be after specific routes like /approved-unused
@router.get(
    "/{reservation_id}",
    response_model=ReservationDetailResponse,
    summary="Get a single reservation by ID with full detail",
)
async def get_reservation(
    reservation_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservationDetailResponse:
    """
    Retrieve detailed information for a single form number reservation,
    including prefix info, approver assignments, and decisions.
    """
    reservation = ReservationService.get_reservation_detail(db, reservation_id)
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )
    return _to_detail_response(reservation)


# ============================================================================
# Helpers
# ============================================================================


def _require_approver_role(user: TokenData) -> None:
    """Raise 403 if user lacks an approver role."""
    approver_roles = {"admin", "reviewer", "staff_manager"}
    if not any(r in approver_roles for r in user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approver role required (admin, reviewer, or staff_manager).",
        )


def _require_admin_role(user: TokenData) -> None:
    """Raise 403 if user is not an admin."""
    if "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
