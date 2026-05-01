"""Public-facing form endpoints (FEAT-0004 + FEAT-0005).

Endpoints (mounted under ``/api/public/v1``):

* ``GET /forms``                      — list / search / sort / paginate.
* ``GET /forms/{form_number}``        — full detail for the SPA.
* ``GET /forms/{form_number}/file``   — issues ``X-Accel-Redirect``;
                                        body is empty.  Audit logged.
* ``GET /forms/{form_number}/og``     — server-rendered OG/Twitter HTML.

All endpoints honour ETag/304 (US-014 AC11) and use RFC 7807 problem
JSON for errors.  S3 object keys are NEVER returned in any body —
``s3_key`` only flows out as the value of the ``X-Accel-Redirect``
header on the ``/file`` endpoint, where the SPA cannot read it.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from enum import Enum
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import String, Text, cast, func as sa_func, text
from sqlalchemy.orm import Session

from audit import log_form_download
from config import settings
from database import get_db
from http_cache import compute_etag, etag_matches
from models import PublicForm
from problem import problem_response


router = APIRouter(prefix="/api/public/v1", tags=["public-forms"])


# ------------------------------------------------------------------
# Query-parameter enums
# ------------------------------------------------------------------

class SortField(str, Enum):
    effective_date = "effective_date"
    form_number = "form_number"
    title = "title"
    updated_at = "updated_at"  # FEAT-0005: powers the home "recently updated" feed


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


# ------------------------------------------------------------------
# Response schemas
# ------------------------------------------------------------------

class PublicFormItem(BaseModel):
    """List-row projection.

    ``s3_key``, ``form_id`` and ``business_area_id`` are deliberately
    omitted from the schema so they cannot leak through the response
    even if accidentally selected.
    """

    form_number: Optional[str] = None
    title: str
    description: Optional[str] = None
    business_area: Optional[str] = None
    keywords: list[str] = []
    file_type: Optional[str] = None
    effective_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PublicFormListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PublicFormItem]


class PublicFormFile(BaseModel):
    """Public file metadata — note the ABSENCE of any S3 reference."""

    filename: Optional[str] = None
    size: Optional[int] = None
    content_type: Optional[str] = None  # short type label (pdf, docx, ...)


class PublicFormDetail(BaseModel):
    form_number: Optional[str] = None
    title: str
    description: Optional[str] = None
    business_area: Optional[str] = None
    keywords: list[str] = []
    file_type: Optional[str] = None
    effective_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    file: Optional[PublicFormFile] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _apply_text_search(query, q: str):
    """Apply a safely-escaped ILIKE ``%q%`` filter across title /
    description / keywords (FEAT-0004 behaviour)."""
    safe_term = (
        q.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    like_pattern = f"%{safe_term}%"
    return query.filter(
        PublicForm.title.ilike(like_pattern)
        | PublicForm.description.ilike(like_pattern)
        | cast(PublicForm.keywords, Text).ilike(like_pattern)
    )


def _apply_sort(query, field: SortField, order: SortOrder):
    column_map = {
        SortField.effective_date: PublicForm.effective_date,
        SortField.form_number: PublicForm.form_number,
        SortField.title: PublicForm.title,
        SortField.updated_at: PublicForm.updated_at,
    }
    col = column_map[field]
    if order == SortOrder.asc:
        return query.order_by(col.asc().nullslast())
    return query.order_by(col.desc().nullslast())


def _conditional_json(
    request: Request,
    *,
    payload: BaseModel,
    cache_max_age: int,
) -> Response:
    """Serialise *payload* once, compute ETag, return either 304 or 200."""
    body_bytes = payload.model_dump_json().encode("utf-8")
    etag = compute_etag(body_bytes)
    cache_header = f"public, max-age={cache_max_age}"

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


def _public_origin(request: Request) -> str:
    """Canonical origin for absolute URLs in OG / sitemap.

    Falls back to the request's origin so local dev still produces
    well-formed URLs.
    """
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    if base:
        return base
    # request.base_url is always trailing-slash terminated.
    return str(request.base_url).rstrip("/")


# ------------------------------------------------------------------
# GET /forms — list / search / sort / paginate
# ------------------------------------------------------------------

@router.get("/forms")
def list_public_forms(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=100),
    f: Optional[str] = Query(default=None),
    s: Optional[SortField] = Query(default=None),
    o: Optional[SortOrder] = Query(default=None),
    limit: int = Query(default=None),  # validated below for problem+json shape
    offset: int = Query(default=0),
    db: Session = Depends(get_db),
):
    # --- limit / offset validation (US-014 AC3) ---
    effective_limit = settings.DEFAULT_LIMIT if limit is None else limit
    if effective_limit < 1 or effective_limit > settings.MAX_LIMIT:
        return problem_response(
            status=400,
            title="Invalid limit",
            detail=f"limit must be between 1 and {settings.MAX_LIMIT}.",
            instance=str(request.url.path),
        )
    if offset < 0:
        return problem_response(
            status=400,
            title="Invalid offset",
            detail="offset must be >= 0.",
            instance=str(request.url.path),
        )

    query = db.query(PublicForm)

    if q is not None and q.strip():
        query = _apply_text_search(query, q.strip())

    if f is not None:
        f_stripped = f.strip()
        if f_stripped:
            query = query.filter(
                sa_func.lower(PublicForm.business_area) == f_stripped.lower()
            )
        else:
            query = query.filter(text("1 = 0"))

    sort_field = s or SortField.updated_at
    sort_order = o or (SortOrder.desc if sort_field == SortField.updated_at else SortOrder.asc)
    query = _apply_sort(query, sort_field, sort_order)

    # Total *before* pagination.
    total = query.count()
    rows = query.offset(offset).limit(effective_limit).all()

    items = [PublicFormItem.model_validate(row) for row in rows]
    payload = PublicFormListResponse(
        total=total, limit=effective_limit, offset=offset, items=items
    )
    return _conditional_json(
        request, payload=payload, cache_max_age=settings.CACHE_MAX_AGE
    )


# ------------------------------------------------------------------
# GET /forms/{form_number} — detail
# ------------------------------------------------------------------

def _get_form_or_404(db: Session, form_number: str) -> PublicForm:
    row = (
        db.query(PublicForm)
        .filter(PublicForm.form_number == form_number)
        .first()
    )
    if row is None:
        # Generic 404 — never disclose whether the form exists privately
        # (US-014 AC5).
        raise HTTPException(status_code=404, detail="Not Found")
    return row


def _detail_payload(row: PublicForm) -> PublicFormDetail:
    file_info: Optional[PublicFormFile] = None
    if row.s3_key and row.file_name:
        file_info = PublicFormFile(
            filename=row.file_name,
            size=row.file_size,
            content_type=row.file_type,
        )
    return PublicFormDetail(
        form_number=row.form_number,
        title=row.title,
        description=row.description,
        business_area=row.business_area,
        keywords=list(row.keywords or []),
        file_type=row.file_type,
        effective_date=row.effective_date,
        updated_at=row.updated_at,
        file=file_info,
    )


@router.get("/forms/{form_number}")
def get_public_form(
    request: Request,
    form_number: str,
    db: Session = Depends(get_db),
):
    row = _get_form_or_404(db, form_number)
    payload = _detail_payload(row)
    return _conditional_json(
        request, payload=payload, cache_max_age=settings.CACHE_MAX_AGE
    )


# ------------------------------------------------------------------
# GET /forms/{form_number}/file — X-Accel-Redirect
# ------------------------------------------------------------------

def _content_disposition(filename: str) -> str:
    """Build a safe ``attachment`` header per RFC 6266.

    Filenames may contain Unicode; we provide both the ASCII fallback and
    the UTF-8 percent-encoded form.
    """
    ascii_fallback = "".join(
        c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename
    ) or "form"
    utf8 = quote(filename, safe="")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{utf8}'


@router.get("/forms/{form_number}/file")
def download_public_form(
    request: Request,
    form_number: str,
    db: Session = Depends(get_db),
):
    row = _get_form_or_404(db, form_number)
    if not row.s3_key or not row.file_name:
        # No attached file — same generic 404 as missing form (US-014 AC7).
        raise HTTPException(status_code=404, detail="Not Found")

    # Compose the X-Accel-Redirect target.  The S3 object key comes
    # exclusively from the server-side row; never from the request.
    prefix = settings.INTERNAL_S3_REDIRECT_PREFIX
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    redirect_target = prefix + row.s3_key.lstrip("/")

    # Audit BEFORE returning so a transport failure mid-flight still
    # produces a "user attempted download" trail.
    log_form_download(request, form_number=form_number, filename=row.file_name)

    headers = {
        "X-Accel-Redirect": redirect_target,
        "Content-Disposition": _content_disposition(row.file_name),
        # Defence-in-depth: clients must never cache the redirect itself.
        "Cache-Control": "private, no-store",
    }
    return Response(status_code=200, headers=headers, content=b"")


# ------------------------------------------------------------------
# GET /forms/{form_number}/og — server-rendered OG HTML
# ------------------------------------------------------------------

_OG_TEMPLATE = """<!doctype html>
<html lang="en-CA">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="BC Transportation Forms">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<script type="application/ld+json">{jsonld}</script>
</head>
<body>
<main>
<h1>{title}</h1>
<p>{description}</p>
<p><a href="{canonical}">View this form on BC Transportation Forms</a></p>
</main>
</body>
</html>
"""


def _truncate(text_value: str, limit: int = 280) -> str:
    if len(text_value) <= limit:
        return text_value
    return text_value[: limit - 1].rstrip() + "\u2026"


@router.get("/forms/{form_number}/og")
def get_form_og(
    request: Request,
    form_number: str,
    db: Session = Depends(get_db),
):
    row = _get_form_or_404(db, form_number)

    canonical = f"{_public_origin(request)}/forms/{quote(form_number, safe='')}"
    title = row.title or form_number
    description = _truncate((row.description or row.title or "").strip())

    jsonld_obj = {
        "@context": "https://schema.org",
        "@type": "DigitalDocument",
        "name": title,
        "description": description,
        "url": canonical,
        "identifier": form_number,
    }
    if row.business_area:
        jsonld_obj["publisher"] = {
            "@type": "Organization",
            "name": row.business_area,
        }
    if row.effective_date:
        jsonld_obj["dateCreated"] = row.effective_date.isoformat()
    if row.updated_at:
        jsonld_obj["dateModified"] = row.updated_at.isoformat()

    body = _OG_TEMPLATE.format(
        title=html.escape(title),
        description=html.escape(description),
        canonical=html.escape(canonical, quote=True),
        # Inside <script type="application/ld+json"> we must escape any
        # closing-tag sequence to prevent HTML injection.  json.dumps
        # already produces valid JSON; we only neutralise </ patterns.
        jsonld=json.dumps(jsonld_obj, separators=(",", ":")).replace("</", "<\\/"),
    ).encode("utf-8")

    etag = compute_etag(body)
    cache_header = f"public, max-age={settings.OG_CACHE_MAX_AGE}"

    if etag_matches(request.headers.get("If-None-Match"), etag):
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": cache_header},
        )

    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={"ETag": etag, "Cache-Control": cache_header},
    )
