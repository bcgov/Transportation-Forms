"""GET /api/public/v1/business-areas — distinct business areas with at least
one published+public form (FEAT-0005 / US-014 AC9)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from http_cache import compute_etag, etag_matches
from models import PublicForm


router = APIRouter(prefix="/api/public/v1", tags=["public-business-areas"])


class BusinessArea(BaseModel):
    id: Optional[UUID] = None
    name: str


class BusinessAreaListResponse(BaseModel):
    items: list[BusinessArea]


@router.get("/business-areas")
def list_business_areas(
    request: Request,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(PublicForm.business_area_id, PublicForm.business_area)
        .filter(PublicForm.business_area.isnot(None))
        .distinct()
        .order_by(PublicForm.business_area.asc())
        .all()
    )

    items = [BusinessArea(id=r[0], name=r[1]) for r in rows if r[1]]
    payload = BusinessAreaListResponse(items=items)

    body_bytes = payload.model_dump_json().encode("utf-8")
    etag = compute_etag(body_bytes)
    cache_header = f"public, max-age={settings.BUSINESS_AREAS_CACHE_MAX_AGE}"

    if etag_matches(request.headers.get("If-None-Match"), etag):
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": cache_header},
        )

    return Response(
        content=body_bytes,
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": cache_header},
    )
