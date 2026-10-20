"""Protected, read-only launch-forward form activity endpoints (US-006)."""

from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.auth.authorization import require_all_permissions
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.models import Form, FormActivityEvent
from backend.services.forms import _activity_value, _safe_text

router = APIRouter(prefix="/staff/forms", tags=["Form Audit"])
_access = require_all_permissions("form:audit", "form:edit")
_unavailable = "Audit history unavailable"


def _form(db: Session, form_id: str) -> Form:
    try:
        form_uuid = UUID(form_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail=_unavailable) from None
    form = (
        db.query(Form)
        .filter(
            Form.id == form_uuid,
            Form.deleted_at.is_(None),
        )
        .first()
    )
    if form is None:
        raise HTTPException(status_code=404, detail=_unavailable)
    return form


def _instant(value) -> str:
    # Existing database timestamps are naive UTC. Always expose an explicit
    # machine-readable UTC instant; the client renders fixed UTC-07:00 PCT.
    return value.replace(tzinfo=timezone.utc).isoformat()


def _summary(event: FormActivityEvent) -> dict:
    return {
        "id": str(event.id),
        "event_name": event.event_name,
        "actor_label": event.actor_label,
        "occurred_at": _instant(event.occurred_at),
        "changed_fields": event.changed_fields,
    }


@router.get("/{form_id}/audit/summary")
async def audit_summary(
    form_id: str,
    response: Response,
    _user: TokenData = Depends(_access),
    db: Session = Depends(get_db),
) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    form = _form(db, form_id)
    last = (
        db.query(FormActivityEvent)
        .filter(
            FormActivityEvent.form_id == form.id,
            FormActivityEvent.event_name == "Form saved",
        )
        .order_by(
            FormActivityEvent.occurred_at.desc(),
            FormActivityEvent.id.desc(),
        )
        .first()
    )
    return {
        "last_edited_by": (
            {
                "actor_label": last.actor_label,
                "occurred_at": _instant(last.occurred_at),
            }
            if last
            else None
        )
    }


@router.get("/{form_id}/audit/events")
async def audit_events(
    form_id: str,
    response: Response,
    limit: int = Query(10, ge=1, le=10),
    cursor: str | None = Query(None, max_length=64),
    _user: TokenData = Depends(_access),
    db: Session = Depends(get_db),
) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    form = _form(db, form_id)
    query = db.query(FormActivityEvent).filter(
        FormActivityEvent.form_id == form.id,
    )
    if cursor is not None:
        try:
            cursor_id = UUID(cursor)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid audit cursor",
            ) from None
        anchor = query.filter(FormActivityEvent.id == cursor_id).first()
        if anchor is None:
            raise HTTPException(status_code=400, detail="Invalid audit cursor")
        query = query.filter(
            or_(
                FormActivityEvent.occurred_at < anchor.occurred_at,
                and_(
                    FormActivityEvent.occurred_at == anchor.occurred_at,
                    FormActivityEvent.id < anchor.id,
                ),
            )
        )
    rows = (
        query.order_by(
            FormActivityEvent.occurred_at.desc(),
            FormActivityEvent.id.desc(),
        )
        .limit(limit + 1)
        .all()
    )
    page = rows[:limit]
    return {
        "events": [_summary(event) for event in page],
        "next_cursor": str(page[-1].id) if len(rows) > limit else None,
    }


@router.get("/{form_id}/audit/events/{event_id}")
async def audit_event_detail(
    form_id: str,
    event_id: str,
    response: Response,
    _user: TokenData = Depends(_access),
    db: Session = Depends(get_db),
) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    form = _form(db, form_id)
    try:
        event_uuid = UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=_unavailable) from None
    event = (
        db.query(FormActivityEvent)
        .filter(
            FormActivityEvent.form_id == form.id,
            FormActivityEvent.id == event_uuid,
        )
        .first()
    )
    if event is None:
        raise HTTPException(status_code=404, detail=_unavailable)
    old = event.old_values or {}
    new = event.new_values or {}
    return {
        **_summary(event),
        "changes": [
            {
                "field": field,
                "old_value": _activity_value(field, old.get(field)),
                "new_value": _activity_value(field, new.get(field)),
            }
            for field in event.changed_fields
            if field in old or field in new
        ],
        "reason": _safe_text(event.reason) if event.reason else None,
    }
