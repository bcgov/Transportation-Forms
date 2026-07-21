"""FEAT-0026 — Mini-CMS admin API endpoints.

Routes are mounted under ``/api/v1/admin/cms/pages`` in ``main.py`` and are
gated by the ``cms:manage`` permission (US-010).  All payloads are validated
by Pydantic before the service layer is invoked; the service layer remains
the single source of truth for slug rules, sanitization, and audit writes.

Endpoints (this module):
- US-001 — POST /admin/cms/pages  (create)
- US-002 — PUT /admin/cms/pages/{id}  (edit, If-Match required)
- US-003 — DELETE /admin/cms/pages/{id}  (soft delete)
- US-003 — POST /admin/cms/pages/{id}/restore
- US-004 — implicit via PUT slug change
- US-005 — GET /admin/cms/pages/{id}/revisions
             POST /admin/cms/pages/{id}/revisions/{rid}/restore
- US-006 — POST /admin/cms/pages/reorder
- US-007 — GET /admin/cms/pages/reserved-slugs
- (list/get) — GET /admin/cms/pages, GET /admin/cms/pages/{id}
"""

from __future__ import annotations

import hashlib
import json
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.auth.authorization import require_permission
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.models import CmsPage, CmsPageRevision
from backend.services.cms_pages import (
    CmsConcurrencyError,
    CmsInvalidStateError,
    CmsNotFoundError,
    CmsPageService,
    CmsPreconditionRequiredError,
    CmsSlugConflictError,
    CmsValidationError,
)
from backend.services.cms_reserved_slugs import get_reserved_slugs


# ============================================================================
# Pydantic Schemas
# ============================================================================


class CmsPageCreateRequest(BaseModel):
    """Request body for POST /admin/cms/pages."""

    title: str = Field(..., min_length=1, max_length=120)
    slug: str = Field(..., min_length=1, max_length=80)
    body_html: str = Field(..., min_length=1)
    meta_description: Optional[str] = Field(default=None, max_length=180)
    show_in_nav: bool = Field(default=True)


class CmsPageUpdateRequest(BaseModel):
    """Request body for PUT /admin/cms/pages/{id}.

    All fields optional so callers can send only the fields they want to
    change (US-002).
    """

    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=80)
    body_html: Optional[str] = Field(default=None, min_length=1)
    meta_description: Optional[str] = Field(default=None, max_length=180)
    show_in_nav: Optional[bool] = None


class CmsPageRestoreRequest(BaseModel):
    """Optional body for POST /admin/cms/pages/{id}/restore."""

    alternate_slug: Optional[str] = Field(default=None, min_length=1, max_length=80)


class CmsReorderRequest(BaseModel):
    """Request body for POST /admin/cms/pages/reorder (US-006)."""

    ordered_ids: List[UUID] = Field(..., min_length=0)


class CmsPageResponse(BaseModel):
    """Public-facing representation of a CMS page."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    title: str
    meta_description: Optional[str]
    body_html: str
    show_in_nav: bool
    nav_order: Optional[int]
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None


class CmsPageListResponse(BaseModel):
    """Envelope for GET /admin/cms/pages that also returns the list ETag."""

    pages: List[CmsPageResponse]
    list_etag: str


class CmsRevisionResponse(BaseModel):
    """Revision list entry (US-005)."""

    id: str
    page_id: str
    title: str
    slug: str
    meta_description: Optional[str]
    body_html: str
    edited_at: str
    edited_by_id: Optional[str]


class ReservedSlugsResponse(BaseModel):
    """Response model for the reserved-slugs endpoint (US-007)."""

    reserved: List[str]


# ============================================================================
# Helpers
# ============================================================================


def _to_response(page: CmsPage) -> CmsPageResponse:
    return CmsPageResponse(
        id=str(page.id),
        slug=page.slug,
        title=page.title,
        meta_description=page.meta_description,
        body_html=page.body_html,
        show_in_nav=bool(page.show_in_nav),
        nav_order=page.nav_order,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
        deleted_at=page.deleted_at.isoformat() if page.deleted_at else None,
    )


def _to_revision_response(rev: CmsPageRevision) -> CmsRevisionResponse:
    return CmsRevisionResponse(
        id=str(rev.id),
        page_id=str(rev.page_id),
        title=rev.title,
        slug=rev.slug,
        meta_description=rev.meta_description,
        body_html=rev.body_html,
        edited_at=rev.edited_at.isoformat() if rev.edited_at else "",
        edited_by_id=str(rev.edited_by_id) if rev.edited_by_id else None,
    )


def _user_uuid(user: TokenData) -> UUID:
    """Extract the acting user's UUID from the token or raise 401."""
    if not user or not user.sub:
        # The require_permission dependency already enforces authentication,
        # but defense-in-depth keeps us from constructing UUID("None").
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user identifier is required.",
        )
    try:
        return UUID(user.sub)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user identifier is invalid.",
        ) from exc


def _raise_precondition(exc: BaseException, *, missing: bool) -> None:
    status_code = (
        status.HTTP_428_PRECONDITION_REQUIRED
        if missing
        else status.HTTP_412_PRECONDITION_FAILED
    )
    raise HTTPException(status_code=status_code, detail=str(exc))


# ============================================================================
# Router — /api/v1/admin/cms/pages
# ============================================================================

admin_router = APIRouter(
    prefix="/admin/cms/pages",
    tags=["Admin - CMS Pages"],
)


@admin_router.get(
    "/reserved-slugs",
    response_model=ReservedSlugsResponse,
)
async def admin_get_reserved_slugs(
    request: Request,
    response: Response,
    _user: TokenData = Depends(require_permission("cms", "manage")),
) -> ReservedSlugsResponse:
    """Return the reserved-slug list with caching headers (US-007).

    Returns 304 when the client supplies a matching ``If-None-Match`` header.
    """
    reserved = get_reserved_slugs()
    payload = {"reserved": reserved}
    # Stable ETag derived from the canonical JSON form of the response so the
    # value only changes when the registry changes.
    body_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    etag = '"' + hashlib.sha256(body_bytes).hexdigest()[:32] + '"'

    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match == etag:
        # 304 Not Modified — must still carry the ETag/Cache-Control.
        response.status_code = status.HTTP_304_NOT_MODIFIED
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
        return ReservedSlugsResponse(reserved=[])

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
    return ReservedSlugsResponse(reserved=reserved)


@admin_router.get(
    "",
    response_model=CmsPageListResponse,
)
async def admin_list_cms_pages(
    response: Response,
    include_deleted: bool = Query(False),
    search: Optional[str] = Query(None, max_length=200),
    db: Session = Depends(get_db),
    _user: TokenData = Depends(require_permission("cms", "manage")),
) -> CmsPageListResponse:
    """List all pages ordered for the admin navbar builder."""
    pages = CmsPageService.list_pages(
        db, include_deleted=include_deleted, search=search
    )
    list_etag = CmsPageService.list_etag(db)
    response.headers["ETag"] = list_etag
    return CmsPageListResponse(
        pages=[_to_response(p) for p in pages],
        list_etag=list_etag,
    )


@admin_router.post(
    "",
    response_model=CmsPageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_cms_page(
    body: CmsPageCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("cms", "manage")),
) -> CmsPageResponse:
    """Create a new CMS page (US-001)."""
    acting_user_id = _user_uuid(user)
    try:
        page = CmsPageService.create_page(
            db,
            title=body.title,
            slug=body.slug,
            body_html=body.body_html,
            meta_description=body.meta_description,
            show_in_nav=body.show_in_nav,
            created_by_id=acting_user_id,
        )
    except CmsSlugConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "slug": exc.slug, "field": "slug"},
        )
    except CmsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc), "field": exc.field},
        )

    response.headers["ETag"] = CmsPageService.page_etag(page)
    return _to_response(page)


@admin_router.post(
    "/reorder",
    response_model=CmsPageListResponse,
)
async def admin_reorder_cms_pages(
    body: CmsReorderRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("cms", "manage")),
) -> CmsPageListResponse:
    """Persist a new navbar order (US-006)."""
    if_match = request.headers.get("if-match")
    acting_user_id = _user_uuid(user)
    try:
        ordered = CmsPageService.reorder_pages(
            db,
            ordered_ids=body.ordered_ids,
            if_match=if_match,
            actor_id=acting_user_id,
        )
    except CmsPreconditionRequiredError as exc:
        _raise_precondition(exc, missing=True)
    except CmsConcurrencyError as exc:
        _raise_precondition(exc, missing=False)
    except CmsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc), "field": exc.field},
        )
    list_etag = CmsPageService.list_etag(db)
    response.headers["ETag"] = list_etag
    return CmsPageListResponse(
        pages=[_to_response(p) for p in ordered],
        list_etag=list_etag,
    )


@admin_router.get(
    "/{page_id}",
    response_model=CmsPageResponse,
)
async def admin_get_cms_page(
    page_id: UUID,
    response: Response,
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
    _user: TokenData = Depends(require_permission("cms", "manage")),
) -> CmsPageResponse:
    """Return a single page (with soft-deleted rows on request)."""
    try:
        page = CmsPageService.get_page(
            db, page_id, include_deleted=include_deleted
        )
    except CmsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    response.headers["ETag"] = CmsPageService.page_etag(page)
    return _to_response(page)


@admin_router.put(
    "/{page_id}",
    response_model=CmsPageResponse,
)
async def admin_update_cms_page(
    page_id: UUID,
    body: CmsPageUpdateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("cms", "manage")),
) -> CmsPageResponse:
    """Update a CMS page (US-002).  Requires ``If-Match`` header."""
    if_match = request.headers.get("if-match")
    acting_user_id = _user_uuid(user)
    try:
        page, _changed = CmsPageService.update_page(
            db,
            page_id,
            title=body.title,
            slug=body.slug,
            body_html=body.body_html,
            meta_description=body.meta_description,
            show_in_nav=body.show_in_nav,
            if_match=if_match,
            updated_by_id=acting_user_id,
        )
    except CmsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CmsPreconditionRequiredError as exc:
        _raise_precondition(exc, missing=True)
    except CmsConcurrencyError as exc:
        _raise_precondition(exc, missing=False)
    except CmsSlugConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "slug": exc.slug, "field": "slug"},
        )
    except CmsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc), "field": exc.field},
        )

    response.headers["ETag"] = CmsPageService.page_etag(page)
    return _to_response(page)


@admin_router.delete(
    "/{page_id}",
    response_model=CmsPageResponse,
)
async def admin_soft_delete_cms_page(
    page_id: UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("cms", "manage")),
) -> CmsPageResponse:
    """Soft-delete a CMS page (US-003)."""
    if_match = request.headers.get("if-match")
    acting_user_id = _user_uuid(user)
    try:
        page = CmsPageService.soft_delete_page(
            db,
            page_id,
            if_match=if_match,
            actor_id=acting_user_id,
        )
    except CmsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CmsPreconditionRequiredError as exc:
        _raise_precondition(exc, missing=True)
    except CmsConcurrencyError as exc:
        _raise_precondition(exc, missing=False)

    response.headers["ETag"] = CmsPageService.page_etag(page)
    return _to_response(page)


@admin_router.post(
    "/{page_id}/restore",
    response_model=CmsPageResponse,
)
async def admin_restore_cms_page(
    page_id: UUID,
    body: Optional[CmsPageRestoreRequest] = None,
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("cms", "manage")),
) -> CmsPageResponse:
    """Restore a soft-deleted CMS page (US-003 AC7/AC8/AC9)."""
    if_match = request.headers.get("if-match") if request else None
    alternate = body.alternate_slug if body else None
    acting_user_id = _user_uuid(user)
    try:
        page = CmsPageService.restore_page(
            db,
            page_id,
            if_match=if_match,
            actor_id=acting_user_id,
            alternate_slug=alternate,
        )
    except CmsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CmsInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except CmsPreconditionRequiredError as exc:
        _raise_precondition(exc, missing=True)
    except CmsConcurrencyError as exc:
        _raise_precondition(exc, missing=False)
    except CmsSlugConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "slug": exc.slug, "field": "slug"},
        )
    except CmsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc), "field": exc.field},
        )

    if response is not None:
        response.headers["ETag"] = CmsPageService.page_etag(page)
    return _to_response(page)


@admin_router.get(
    "/{page_id}/revisions",
    response_model=List[CmsRevisionResponse],
)
async def admin_list_cms_revisions(
    page_id: UUID,
    db: Session = Depends(get_db),
    _user: TokenData = Depends(require_permission("cms", "manage")),
) -> List[CmsRevisionResponse]:
    """List revisions for a page ordered newest first (US-005)."""
    try:
        revisions = CmsPageService.list_revisions(db, page_id)
    except CmsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return [_to_revision_response(r) for r in revisions]


@admin_router.post(
    "/{page_id}/revisions/{revision_id}/restore",
    response_model=CmsPageResponse,
)
async def admin_restore_cms_revision(
    page_id: UUID,
    revision_id: UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("cms", "manage")),
) -> CmsPageResponse:
    """Restore a prior revision onto the page (US-005 AC5)."""
    if_match = request.headers.get("if-match")
    acting_user_id = _user_uuid(user)
    try:
        page, _changed = CmsPageService.restore_revision(
            db,
            page_id,
            revision_id,
            if_match=if_match,
            actor_id=acting_user_id,
        )
    except CmsNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CmsPreconditionRequiredError as exc:
        _raise_precondition(exc, missing=True)
    except CmsConcurrencyError as exc:
        _raise_precondition(exc, missing=False)
    except CmsSlugConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "slug": exc.slug, "field": "slug"},
        )
    except CmsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc), "field": exc.field},
        )

    response.headers["ETag"] = CmsPageService.page_etag(page)
    return _to_response(page)
