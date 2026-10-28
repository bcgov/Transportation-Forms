"""Dashboard statistics endpoint (TASK-430)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from uuid import UUID
import structlog

from backend.auth.authorization import require_permission
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.models import Form, FormNumberReservation
from backend.services import engagement_stats

logger = structlog.get_logger()


class DashboardStatsResponse(BaseModel):
    published_forms: int
    forms_awaiting_approval: int
    reservations_awaiting_approval: int


router = APIRouter(tags=["Stats"])


@router.get("/staff/forms/{form_id}/stats")
def get_form_engagement_stats(
    form_id: str,
    response: Response,
    period: str = "30d",
    refresh: bool = False,
    _user: TokenData = Depends(require_permission("forms", "stats")),
    db: Session = Depends(get_db),
) -> dict:
    """Return authorized aggregates without the analytics writer account."""
    response.headers["Cache-Control"] = "private, no-store"
    if period not in engagement_stats.PERIOD_DAYS:
        raise HTTPException(
            status_code=400, detail="Invalid statistics period"
        )
    try:
        form_uuid = UUID(form_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=404, detail="Statistics unavailable"
        ) from None
    try:
        exists = (
            db.query(Form.id)
            .filter(Form.id == form_uuid, Form.deleted_at.is_(None))
            .first()
        )
        if exists is None:
            raise HTTPException(
                status_code=404, detail="Statistics unavailable"
            )
        cutoff = engagement_stats.pct_today()
        engagement_stats.mark_transaction_read_only(db)
        if refresh:
            return engagement_stats.aggregate(
                db, form_uuid, period, cutoff, refresh=True
            )
        return engagement_stats.aggregate(db, form_uuid, period, cutoff)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning(
            "engagement_stats_unavailable", error_type=type(exc).__name__
        )
        raise HTTPException(
            status_code=503, detail="Statistics temporarily unavailable"
        ) from None


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
