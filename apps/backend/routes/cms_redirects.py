"""FEAT-0026 US-008 — CMS redirect admin API."""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.authorization import require_permission
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.models import CmsPage
from backend.services.cms_pages import CmsNotFoundError, CmsPageService


class CmsRedirectResponse(BaseModel):
    """Redirect list-entry response."""

    id: str
    from_slug: str
    to_page_id: str
    to_slug: str
    created_at: str


admin_router = APIRouter(
    prefix="/admin/cms/redirects",
    tags=["Admin - CMS Redirects"],
)


def _user_uuid(user: TokenData) -> UUID:
    if not user or not user.sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth")
    return UUID(user.sub)


@admin_router.get(
    "",
    response_model=List[CmsRedirectResponse],
)
async def admin_list_redirects(
    db: Session = Depends(get_db),
    _user: TokenData = Depends(require_permission("cms", "manage")),
) -> List[CmsRedirectResponse]:
    """List all redirect rows including targets that are soft-deleted.

    The ``to_slug`` is resolved by joining ``cms_pages`` so admins can see
    which slug the redirect currently points to (may be an empty string if
    the target has since been hard-deleted, which normally cannot happen).
    """
    redirects = CmsPageService.list_redirects(db)
    if not redirects:
        return []
    page_ids = {r.to_page_id for r in redirects}
    pages = db.query(CmsPage).filter(CmsPage.id.in_(page_ids)).all()
    slug_by_id = {p.id: p.slug for p in pages}
    return [
        CmsRedirectResponse(
            id=str(r.id),
            from_slug=r.from_slug,
            to_page_id=str(r.to_page_id),
            to_slug=slug_by_id.get(r.to_page_id, ""),
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in redirects
    ]


@admin_router.delete(
    "/{redirect_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_redirect(
    redirect_id: UUID,
    db: Session = Depends(get_db),
    user: TokenData = Depends(require_permission("cms", "manage")),
) -> None:
    """Hard-delete a redirect (US-008 AC3)."""
    acting_user_id = _user_uuid(user)
    try:
        CmsPageService.delete_redirect(
            db, redirect_id, actor_id=acting_user_id
        )
    except CmsNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return None
