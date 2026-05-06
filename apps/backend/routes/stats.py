"""Dashboard statistics endpoint (TASK-430)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.models import Form, FormNumberReservation


class DashboardStatsResponse(BaseModel):
    published_forms: int
    forms_awaiting_approval: int
    reservations_awaiting_approval: int


router = APIRouter(tags=["Stats"])


@router.get("/stats/dashboard", response_model=DashboardStatsResponse)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    _current_user: TokenData = Depends(get_current_user),
) -> DashboardStatsResponse:
    """Return live dashboard statistics. Any valid JWT grants access."""
    published_forms = (
        db.query(func.count(Form.id))
        .filter(Form.status == "published", Form.deleted_at.is_(None))
        .scalar()
        or 0
    )
    forms_awaiting_approval = (
        db.query(func.count(Form.id))
        .filter(Form.status == "pending_review", Form.deleted_at.is_(None))
        .scalar()
        or 0
    )
    reservations_awaiting_approval = (
        db.query(func.count(FormNumberReservation.id))
        .filter(FormNumberReservation.status == "pending_approval")
        .scalar()
        or 0
    )
    return DashboardStatsResponse(
        published_forms=published_forms,
        forms_awaiting_approval=forms_awaiting_approval,
        reservations_awaiting_approval=reservations_awaiting_approval,
    )
