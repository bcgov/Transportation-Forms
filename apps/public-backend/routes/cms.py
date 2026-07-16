"""FEAT-0026 — Public CMS API endpoints.

Anonymous, cacheable, read-only surface for the public Forms Portal
Mini-CMS.  All routes are mounted under ``/api/public/v1/`` and gated by
the ``X-Internal-Auth`` middleware (same as ``forms.py``).

Endpoints:

* ``GET /pages``                      — nav-visible pages (US-012).
* ``GET /pages/{slug}``               — page render (US-011).
* ``GET /redirects/{slug}``           — redirect resolver (US-013).

Design notes:

* ETag/304 revalidation follows the same helper (``http_cache.py``) used
  by :mod:`routes.forms`.
* Every response uses ``application/json`` for data endpoints and
  ``application/problem+json`` for errors (RFC 7807).
* ``body_html`` returned by ``/pages/{slug}`` is re-sanitized on-read
  (defence in depth per CC-BR-11 / US-011 AC5). ``<img>`` and every
  other media construct are stripped by the sanitiser — CMS Media is
  out of scope (see FEAT-0026 remediation plan v2, 2026-07-16).
"""

from __future__ import annotations

import hashlib
import html
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from cms_sanitizer import sanitize_html
from config import settings
from database import get_db
from http_cache import compute_etag, etag_matches
from models import PublicCmsPage, PublicCmsRedirect
from problem import problem_response

router = APIRouter(prefix="/api/public/v1", tags=["public-cms"])


# ============================================================================
# Response schemas
# ============================================================================


class PublicPageNavItem(BaseModel):
    """Navbar list entry (US-012)."""

    slug: str
    title: str
    nav_order: Optional[int] = None


class PublicPageDetail(BaseModel):
    """Page detail response (US-011)."""

    slug: str
    title: str
    meta_description: Optional[str] = None
    body_html: str
    updated_at: Optional[str] = None


class PublicRedirectResponse(BaseModel):
    """Redirect resolver response (US-013)."""

    to_slug: str


# ============================================================================
# GET /pages — navbar list
# ============================================================================


def _list_etag(db: Session) -> str:
    """ETag for the nav-visible page list."""
    row = (
        db.query(
            func.max(PublicCmsPage.updated_at),
            func.count(PublicCmsPage.id),
        )
        .filter(PublicCmsPage.show_in_nav.is_(True))
        .one()
    )
    max_updated, count = row
    stamp = max_updated.isoformat() if max_updated else "0"
    digest = hashlib.sha256(
        f"public-cms-nav:{stamp}:{count}".encode("utf-8")
    ).hexdigest()[:32]
    return f'"{digest}"'


@router.get(
    "/pages",
    response_model=List[PublicPageNavItem],
)
def list_public_cms_pages(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> List[PublicPageNavItem] | Response:
    """Return nav-visible pages ordered by ``nav_order`` (US-012).

    * Cache-Control: public, max-age=60, must-revalidate (short so
      navbar reflects publishing changes quickly).
    * ETag/304 revalidation.
    """
    etag = _list_etag(db)
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": "public, max-age=60, must-revalidate",
            },
        )

    rows = (
        db.query(PublicCmsPage)
        .filter(PublicCmsPage.show_in_nav.is_(True))
        .order_by(
            PublicCmsPage.nav_order.asc().nullslast(),
            PublicCmsPage.title.asc(),
        )
        .all()
    )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=60, must-revalidate"
    return [
        PublicPageNavItem(
            slug=r.slug,
            title=r.title,
            nav_order=r.nav_order,
        )
        for r in rows
    ]


# ============================================================================
# GET /pages/{slug} — page detail
# ============================================================================


def _page_etag(page: PublicCmsPage) -> str:
    stamp = page.updated_at.isoformat() if page.updated_at else "0"
    digest = hashlib.sha256(
        f"public-cms-page:{page.id}:{stamp}".encode("utf-8")
    ).hexdigest()[:32]
    return f'"{digest}"'


def _slug_is_safe(slug: str) -> bool:
    """Cheap client-facing validation to reject obviously-bad slugs."""
    if not slug or len(slug) > 80:
        return False
    for ch in slug:
        if not (ch.islower() or ch.isdigit() or ch == "-"):
            return False
    if slug.startswith("-") or slug.endswith("-") or "--" in slug:
        return False
    return True


@router.get(
    "/pages/{slug}",
)
def get_public_cms_page(
    slug: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Return a single CMS page (US-011).

    * 404 (RFC 7807) if the slug does not match an active page (soft-
      deleted rows are filtered out at the view layer).
    * Cache-Control: private, no-cache (must revalidate every hit) so
      admins never see stale content after editing.
    * ``body_html`` is re-sanitised on the way out and media tokens are
      rewritten to their public URLs.
    """
    if not _slug_is_safe(slug):
        # Return the same 404 as unknown slugs so we don't leak the
        # validation rules to abusive clients.
        return problem_response(
            status=404,
            title="Not Found",
            detail="Page not found.",
            instance=request.url.path,
        )

    page = (
        db.query(PublicCmsPage)
        .filter(func.lower(PublicCmsPage.slug) == slug.lower())
        .first()
    )
    if page is None:
        return problem_response(
            status=404,
            title="Not Found",
            detail="Page not found.",
            instance=request.url.path,
        )

    etag = _page_etag(page)
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": "private, no-cache, must-revalidate",
            },
        )

    # Defence-in-depth: re-sanitize on the way out. The sanitiser strips
    # every ``<img>`` tag (CMS Media is out of scope per FEAT-0026
    # remediation plan v2, 2026-07-16), so no media-URL rewrite is
    # needed.
    rendered_body = sanitize_html(page.body_html or "")
    payload = PublicPageDetail(
        slug=page.slug,
        title=page.title,
        meta_description=page.meta_description,
        body_html=rendered_body,
        updated_at=page.updated_at.isoformat() if page.updated_at else None,
    )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache, must-revalidate"
    return payload


# ============================================================================
# GET /pages/{slug}/og — bot-UA server-rendered page (US-011 AC2)
# ============================================================================
# Mirrors the FEAT-0005 ``/forms/{n}/og`` pattern. Returns a minimal
# HTML document with correct <title>, meta description, canonical, OG
# and Twitter tags, plus a nav fragment mirroring the CMS navbar so
# social-embed and search-engine snapshots see a coherent page.
# ``<img>`` was withdrawn from FEAT-0026 scope on 2026-07-16, so the
# body is served as-is (no media-URL rewrite).


_OG_TEMPLATE = """<!doctype html>
<html lang="en-CA">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<link rel="alternate" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="BC Government Public Forms">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
</head>
<body>
<nav aria-label="Site pages">
<ul>{nav_items}</ul>
</nav>
<main>
<h1>{title}</h1>
{body_html}
<p><a href="{canonical}">View this page on BC Government Public Forms</a></p>
</main>
</body>
</html>
"""


_OG_404_TEMPLATE = """<!doctype html>
<html lang="en-CA">
<head>
<meta charset="utf-8">
<title>Page not found — BC Government Public Forms</title>
<meta name="robots" content="noindex">
</head>
<body>
<main>
<h1>Page not found</h1>
<p>The requested page could not be found or is no longer published.</p>
<p><a href="{home}">Return home</a></p>
</main>
</body>
</html>
"""


def _public_origin(request: Request) -> str:
    """Canonical origin for absolute URLs in the OG payload.

    Mirrors :func:`routes.forms._public_origin` so both bot renders use
    the same host resolution.
    """
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    if base:
        return base
    return str(request.base_url).rstrip("/")


def _truncate(text_value: str, limit: int = 280) -> str:
    if len(text_value) <= limit:
        return text_value
    return text_value[: limit - 1].rstrip() + "\u2026"


def _build_nav_items_html(db: Session, origin: str) -> str:
    """Render the nav-visible page list as escaped ``<li><a>`` items.

    Uses the same ordering as :func:`list_public_cms_pages` so the OG
    render matches what the SPA would show.
    """
    rows = (
        db.query(PublicCmsPage)
        .filter(PublicCmsPage.show_in_nav.is_(True))
        .order_by(
            PublicCmsPage.nav_order.asc().nullslast(),
            PublicCmsPage.title.asc(),
        )
        .all()
    )
    parts = []
    for r in rows:
        slug = quote(r.slug or "", safe="")
        title = html.escape(r.title or "", quote=True)
        href = html.escape(f"{origin}/{slug}", quote=True)
        parts.append(f'<li><a href="{href}">{title}</a></li>')
    return "".join(parts)


@router.get("/pages/{slug}/og")
def get_public_cms_page_og(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Bot-UA server-rendered CMS page (US-011 AC2, US-012 AC7, US-013 AC6).

    * Returns text/html (not JSON) so social-embed and search-engine
      crawlers see a well-formed document.
    * Renders the sanitised ``body_html`` directly — ``<img>`` is
      stripped upstream by :func:`sanitize_html` (see FEAT-0026
      remediation plan v2, 2026-07-16).
    * Cache-Control derived from settings.OG_CACHE_MAX_AGE so the edge
      can hold it for the 24-hour bot/sitemap TTL (US-017 BR-02).
    """
    origin = _public_origin(request)
    home_href = html.escape(f"{origin}/", quote=True)

    if not _slug_is_safe(slug):
        body_404 = _OG_404_TEMPLATE.format(home=home_href).encode("utf-8")
        return Response(
            content=body_404,
            media_type="text/html; charset=utf-8",
            status_code=404,
            headers={"X-Robots-Tag": "noindex", "Cache-Control": "no-store"},
        )

    page = (
        db.query(PublicCmsPage)
        .filter(func.lower(PublicCmsPage.slug) == slug.lower())
        .first()
    )
    if page is None:
        body_404 = _OG_404_TEMPLATE.format(home=home_href).encode("utf-8")
        return Response(
            content=body_404,
            media_type="text/html; charset=utf-8",
            status_code=404,
            headers={"X-Robots-Tag": "noindex", "Cache-Control": "no-store"},
        )

    title = page.title or slug
    description = _truncate((page.meta_description or page.title or "").strip())
    canonical = f"{origin}/{quote(page.slug, safe='')}"
    # Re-sanitize on render (US-016 policy is applied twice).  ``<img>``
    # is stripped by the sanitiser, so no media-URL rewrite is needed.
    body_html = sanitize_html(page.body_html or "")
    nav_items = _build_nav_items_html(db, origin)

    rendered = _OG_TEMPLATE.format(
        title=html.escape(title),
        description=html.escape(description),
        canonical=html.escape(canonical, quote=True),
        body_html=body_html,
        nav_items=nav_items,
    ).encode("utf-8")

    etag = compute_etag(rendered)
    cache_max_age = getattr(settings, "OG_CACHE_MAX_AGE", 600) or 600
    cache_header = f"public, max-age={cache_max_age}"

    if etag_matches(request.headers.get("If-None-Match"), etag):
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": cache_header},
        )

    return Response(
        content=rendered,
        media_type="text/html; charset=utf-8",
        headers={"ETag": etag, "Cache-Control": cache_header},
    )


# ============================================================================
# GET /redirects/{slug} — redirect resolver
# ============================================================================


@router.get(
    "/redirects/{slug}",
    response_model=PublicRedirectResponse,
)
def resolve_public_cms_redirect(
    slug: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Return the destination slug for a legacy slug (US-013).

    * 404 when the row does not exist OR when the target page is
      soft-deleted (the view filters those out automatically).
    * ``Cache-Control: no-store`` — redirects can be revoked and we
      never want a cached 301 hanging around at the browser level.
    """
    if not _slug_is_safe(slug):
        return problem_response(
            status=404,
            title="Not Found",
            detail="Redirect not found.",
            instance=request.url.path,
        )

    row = (
        db.query(PublicCmsRedirect)
        .filter(func.lower(PublicCmsRedirect.from_slug) == slug.lower())
        .first()
    )
    if row is None:
        return problem_response(
            status=404,
            title="Not Found",
            detail="Redirect not found.",
            instance=request.url.path,
        )

    # Prevent self-redirect (double-safety even though the resolver on
    # slug change removes these — see cms_pages service).
    if row.to_slug.lower() == slug.lower():
        return problem_response(
            status=404,
            title="Not Found",
            detail="Redirect not found.",
            instance=request.url.path,
        )

    response.headers["Cache-Control"] = "no-store"
    return PublicRedirectResponse(to_slug=row.to_slug)
