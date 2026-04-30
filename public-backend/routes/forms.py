"""GET /api/public/v1/forms — list publicly visible forms with caching."""

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import String, Text, cast, func as sa_func, text
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import PublicForm

router = APIRouter(prefix="/api/public/v1", tags=["public-forms"])


# ------------------------------------------------------------------
# Query-parameter enums / validation
# ------------------------------------------------------------------

class SortField(str, Enum):
    effective_date = "effective_date"
    form_number = "form_number"
    title = "title"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


# ------------------------------------------------------------------
# Response schemas
# ------------------------------------------------------------------

class PublicFormItem(BaseModel):
    form_number: Optional[str] = None
    title: str
    description: Optional[str] = None
    business_area: Optional[str] = None
    keywords: list[str] = []
    file_type: Optional[str] = None
    effective_date: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PublicFormListResponse(BaseModel):
    total: int
    items: list[PublicFormItem]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _compute_etag(body: bytes) -> str:
    """Return a quoted ETag from the SHA-256 of *body*."""
    digest = hashlib.sha256(body).hexdigest()[:32]
    return f'"{digest}"'


def _etag_matches(if_none_match: Optional[str], etag: str) -> bool:
    """Check whether the client's If-None-Match header matches *etag*."""
    if not if_none_match:
        return False
    # Support multiple ETags: "a", "b", "c"
    candidates = [t.strip() for t in if_none_match.split(",")]
    return etag in candidates or "*" in candidates


# ------------------------------------------------------------------
# Endpoint
# ------------------------------------------------------------------

@router.get("/forms", response_model=PublicFormListResponse)
def list_public_forms(
    request: Request,
    response: Response,
    q: Optional[str] = Query(default=None, max_length=100),
    f: Optional[str] = Query(default=None),
    s: Optional[SortField] = Query(default=None),
    o: Optional[SortOrder] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(PublicForm)

    # --- Free-text search (ILIKE across title, description, keywords) ---
    if q is not None:
        q_stripped = q.strip()
        if q_stripped:
            # Escape LIKE wildcards in the user-supplied term
            safe_term = (
                q_stripped
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            like_pattern = f"%{safe_term}%"
            query = query.filter(
                PublicForm.title.ilike(like_pattern)
                | PublicForm.description.ilike(like_pattern)
                | cast(PublicForm.keywords, Text).ilike(like_pattern)
            )

    # --- Filter by business area (case-insensitive exact match) ---
    if f is not None:
        f_stripped = f.strip()
        if f_stripped:
            query = query.filter(
                sa_func.lower(PublicForm.business_area) == f_stripped.lower()
            )
        else:
            # Empty filter string — return nothing (no BA with empty name)
            query = query.filter(text("1 = 0"))

    # --- Sorting ---
    sort_field = s or SortField.title
    sort_order = o or SortOrder.asc

    column_map = {
        SortField.effective_date: PublicForm.effective_date,
        SortField.form_number: PublicForm.form_number,
        SortField.title: PublicForm.title,
    }
    col = column_map[sort_field]
    order_expr = col.asc() if sort_order == SortOrder.asc else col.desc()

    # Push NULLs to the end regardless of sort direction
    if sort_order == SortOrder.asc:
        query = query.order_by(col.asc().nullslast())
    else:
        query = query.order_by(col.desc().nullslast())

    # --- Execute ---
    rows = query.all()

    items = [PublicFormItem.model_validate(row) for row in rows]
    result = PublicFormListResponse(total=len(items), items=items)

    # --- Serialise once for ETag computation ---
    body_bytes = result.model_dump_json().encode("utf-8")
    etag = _compute_etag(body_bytes)

    # --- 304 Not Modified ---
    if_none_match = request.headers.get("If-None-Match")
    if _etag_matches(if_none_match, etag):
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": f"public, max-age={settings.CACHE_MAX_AGE}",
            },
        )

    # --- 200 with caching headers ---
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f"public, max-age={settings.CACHE_MAX_AGE}"

    return result
