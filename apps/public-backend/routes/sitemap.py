"""GET /api/public/v1/sitemap.xml — dynamic sitemap (FEAT-0005 / US-014 AC10).

Lists the home page and every published+public form's deep URL.  Output
conforms to the sitemap.org 0.9 schema.  The XML is built by hand
(html.escape / xml.sax.saxutils.escape) — no new dependencies.
"""

from __future__ import annotations

from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from http_cache import compute_etag, etag_matches
from models import PublicForm

router = APIRouter(tags=["public-sitemap"])


def _origin(request: Request) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    if base:
        return base
    return str(request.base_url).rstrip("/")


@router.get("/api/public/v1/sitemap.xml")
def sitemap_xml(request: Request, db: Session = Depends(get_db)):
    origin = _origin(request)

    rows = (
        db.query(PublicForm.form_number, PublicForm.updated_at)
        .filter(PublicForm.form_number.isnot(None))
        .order_by(PublicForm.form_number.asc())
        .all()
    )

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"<url><loc>{xml_escape(origin)}/</loc></url>",
    ]
    for form_number, updated_at in rows:
        loc = f"{origin}/forms/{quote(form_number, safe='')}"
        if updated_at is not None:
            parts.append(
                f"<url><loc>{xml_escape(loc)}</loc>"
                f"<lastmod>{xml_escape(updated_at.date().isoformat())}</lastmod></url>"
            )
        else:
            parts.append(f"<url><loc>{xml_escape(loc)}</loc></url>")
    parts.append("</urlset>")

    body = "".join(parts).encode("utf-8")
    etag = compute_etag(body)
    cache_header = f"public, max-age={settings.SITEMAP_CACHE_MAX_AGE}"

    if etag_matches(request.headers.get("If-None-Match"), etag):
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": cache_header},
        )

    return Response(
        content=body,
        media_type="application/xml",
        headers={"ETag": etag, "Cache-Control": cache_header},
    )
