"""Form workflow API endpoints (TASK-114)."""

from typing import List, Optional, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.services.forms import (
    FormService,
    FormNotFoundError,
    FormWorkflowConflictError,
    FormWorkflowValidationError,
)

router = APIRouter(prefix="/staff/forms", tags=["Form Workflow"])


class WorkflowStatusResponse(BaseModel):
    """Minimal workflow transition response."""

    form_number: Optional[str] = None
    title: str
    status: str


class RejectRequest(BaseModel):
    """Reject request body."""

    reason_notes: Optional[str] = Field(default=None)


class WorkflowHistoryItem(BaseModel):
    """Workflow history item."""

    id: str
    action: str
    from_status: str
    to_status: str
    triggered_by_id: str
    reason_notes: Optional[str] = None
    created_at: str


class WorkflowHistoryResponse(BaseModel):
    """Workflow history list response."""

    form_id: str
    items: List[WorkflowHistoryItem]


def _require_roles(current_user: TokenData, allowed_roles: set[str]) -> None:
    user_roles = set(current_user.roles or [])
    if not user_roles.intersection(allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for this action",
        )


def _to_status_response(form) -> WorkflowStatusResponse:
    reservation = form.form_number_reservation
    form_number = None
    if reservation:
        form_number = reservation.full_form_number or reservation.form_number

    return WorkflowStatusResponse(
        form_number=form_number,
        title=form.title,
        status=form.status,
    )


def _handle_workflow_error(exc: Exception) -> NoReturn:
    if isinstance(exc, FormNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Form not found"
        )
    if isinstance(exc, FormWorkflowConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, FormWorkflowValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid form ID format"
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Workflow transition failed",
    )


@router.post("/{form_id}/submit", response_model=WorkflowStatusResponse)
async def submit_form_for_review(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowStatusResponse:
    _require_roles(current_user, {"admin", "staff_manager", "reviewer"})

    try:
        form = FormService.submit_form_for_review(
            db, UUID(form_id), UUID(current_user.sub)
        )
        return _to_status_response(form)
    except Exception as exc:  # noqa: BLE001
        _handle_workflow_error(exc)


@router.post("/{form_id}/approve", response_model=WorkflowStatusResponse)
async def approve_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowStatusResponse:
    _require_roles(current_user, {"admin", "staff_manager", "reviewer"})

    try:
        form = FormService.approve_form(db, UUID(form_id), UUID(current_user.sub))
        return _to_status_response(form)
    except Exception as exc:  # noqa: BLE001
        _handle_workflow_error(exc)


@router.post("/{form_id}/reject", response_model=WorkflowStatusResponse)
async def reject_form(
    form_id: str,
    request: RejectRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowStatusResponse:
    _require_roles(current_user, {"admin", "staff_manager", "reviewer"})

    if not request.reason_notes or not request.reason_notes.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rejection reason (reason_notes) is required",
        )

    try:
        form = FormService.reject_form(
            db, UUID(form_id), UUID(current_user.sub), request.reason_notes
        )
        return _to_status_response(form)
    except Exception as exc:  # noqa: BLE001
        _handle_workflow_error(exc)


@router.post("/{form_id}/publish", response_model=WorkflowStatusResponse)
async def publish_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowStatusResponse:
    _require_roles(current_user, {"admin", "staff_manager", "reviewer"})

    try:
        form = FormService.publish_form(db, UUID(form_id), UUID(current_user.sub))
        return _to_status_response(form)
    except Exception as exc:  # noqa: BLE001
        _handle_workflow_error(exc)


@router.post("/{form_id}/unpublish", response_model=WorkflowStatusResponse)
async def unpublish_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowStatusResponse:
    _require_roles(current_user, {"admin", "staff_manager"})

    try:
        form = FormService.unpublish_form(db, UUID(form_id), UUID(current_user.sub))
        return _to_status_response(form)
    except Exception as exc:  # noqa: BLE001
        _handle_workflow_error(exc)


@router.post("/{form_id}/archive", response_model=WorkflowStatusResponse)
async def archive_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowStatusResponse:
    _require_roles(current_user, {"admin", "staff_manager"})

    try:
        form = FormService.archive_form(
            db, UUID(form_id), user_id=UUID(current_user.sub)
        )
        return _to_status_response(form)
    except Exception as exc:  # noqa: BLE001
        _handle_workflow_error(exc)


@router.post("/{form_id}/restore", response_model=WorkflowStatusResponse)
async def restore_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowStatusResponse:
    _require_roles(current_user, {"admin", "staff_manager"})

    try:
        form = FormService.restore_form(db, UUID(form_id), UUID(current_user.sub))
        return _to_status_response(form)
    except Exception as exc:  # noqa: BLE001
        _handle_workflow_error(exc)


@router.get("/{form_id}/workflow-history", response_model=WorkflowHistoryResponse)
async def get_workflow_history(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkflowHistoryResponse:
    _require_roles(current_user, {"admin", "staff_manager", "reviewer"})

    try:
        entries = FormService.get_workflow_history(db, UUID(form_id))
        items = [
            WorkflowHistoryItem(
                id=str(entry.id),
                action=str(entry.action),
                from_status=str(entry.from_status),
                to_status=str(entry.to_status),
                triggered_by_id=str(entry.triggered_by_id),
                reason_notes=(
                    str(entry.reason_notes) if entry.reason_notes is not None else None
                ),
                created_at=entry.created_at.isoformat(),
            )
            for entry in entries
        ]
        return WorkflowHistoryResponse(form_id=form_id, items=items)
    except Exception as exc:  # noqa: BLE001
        _handle_workflow_error(exc)
