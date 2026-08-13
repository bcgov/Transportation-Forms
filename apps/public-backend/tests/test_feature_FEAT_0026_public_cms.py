"""FEAT-0026 public-backend tests: US-011..US-015.

Covers the anonymous, read-only CMS surface exposed by the public backend:

* US-011 — ``GET /api/public/v1/pages/{slug}`` (render + re-sanitize).
* US-012 — ``GET /api/public/v1/pages`` (nav-visible list).
* US-013 — ``GET /api/public/v1/redirects/{slug}`` (resolver).
* US-014 — ``GET /api/public/v1/cms/media/{id}`` (X-Accel-Redirect).
* US-015 — ``GET /api/public/v1/sitemap.xml`` includes CMS entries.

Data is seeded directly into the SQLite tables that stand in for the
Postgres views (see ``conftest.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session


PAGES_URL = "/api/public/v1/pages"
REDIRECTS_URL = "/api/public/v1/redirects"
SITEMAP_URL = "/api/public/v1/sitemap.xml"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _insert_page(
    db: Session,
    *,
    slug: str,
    title: str = "Page",
    body_html: str = "<p>Hello</p>",
    meta_description: str | None = None,
    show_in_nav: bool = True,
    nav_order: int | None = 1,
    updated_at: datetime | None = None,
) -> str:
    page_id = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO public_cms_pages_v
                (id, slug, title, meta_description, body_html,
                 show_in_nav, nav_order, updated_at)
            VALUES
                (:id, :slug, :title, :meta, :body, :nav, :ord, :upd)
            """
        ),
        {
            "id": page_id,
            "slug": slug,
            "title": title,
            "meta": meta_description,
            "body": body_html,
            "nav": 1 if show_in_nav else 0,
            "ord": nav_order,
            "upd": (updated_at or datetime(2026, 7, 3, 12, 0, 0)),
        },
    )
    db.commit()
    return page_id


def _insert_redirect(
    db: Session,
    *,
    from_slug: str,
    to_page_id: str,
    to_slug: str,
) -> str:
    rid = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO public_cms_redirects_v
                (redirect_id, from_slug, to_page_id, to_slug, created_at)
            VALUES (:rid, :from_slug, :to_id, :to_slug, :ts)
            """
        ),
        {
            "rid": rid,
            "from_slug": from_slug,
            "to_id": to_page_id,
            "to_slug": to_slug,
            "ts": datetime(2026, 7, 3, 12, 0, 0),
        },
    )
    db.commit()
    return rid


# ===========================================================================
# US-012 — Nav-visible page list
# ===========================================================================


class TestUS012PageList:
    def test_returns_only_nav_visible_pages(self, public_client, db):
        _insert_page(db, slug="visible-1", nav_order=1, show_in_nav=True)
        _insert_page(
            db, slug="hidden", nav_order=None, show_in_nav=False
        )
        _insert_page(db, slug="visible-2", nav_order=2, show_in_nav=True)
        resp = public_client.get(PAGES_URL)
        assert resp.status_code == 200
        slugs = [p["slug"] for p in resp.json()]
        assert slugs == ["visible-1", "visible-2"]

    def test_ordered_by_nav_order(self, public_client, db):
        _insert_page(db, slug="b", nav_order=2)
        _insert_page(db, slug="a", nav_order=1)
        _insert_page(db, slug="c", nav_order=3)
        resp = public_client.get(PAGES_URL)
        assert resp.status_code == 200
        assert [p["slug"] for p in resp.json()] == ["a", "b", "c"]

    def test_etag_and_cache_control_headers(self, public_client, db):
        _insert_page(db, slug="etag-test")
        resp = public_client.get(PAGES_URL)
        assert resp.status_code == 200
        assert resp.headers.get("ETag")
        assert "max-age=60" in (resp.headers.get("Cache-Control") or "")

    def test_matching_if_none_match_returns_304(self, public_client, db):
        _insert_page(db, slug="cache-me")
        resp = public_client.get(PAGES_URL)
        etag = resp.headers["ETag"]
        resp2 = public_client.get(PAGES_URL, headers={"If-None-Match": etag})
        assert resp2.status_code == 304

    def test_empty_response_when_no_pages(self, public_client):
        resp = public_client.get(PAGES_URL)
        assert resp.status_code == 200
        assert resp.json() == []


# ===========================================================================
# US-011 — Page detail render
# ===========================================================================


class TestUS011PageDetail:
    def test_get_by_slug_returns_page(self, public_client, db):
        _insert_page(
            db,
            slug="detail",
            title="Detail Page",
            body_html="<p>Rendered</p>",
            meta_description="Meta",
        )
        resp = public_client.get(f"{PAGES_URL}/detail")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["slug"] == "detail"
        assert body["title"] == "Detail Page"
        assert body["meta_description"] == "Meta"
        assert "Rendered" in body["body_html"]

    def test_missing_slug_returns_404_problem_json(self, public_client):
        resp = public_client.get(f"{PAGES_URL}/does-not-exist")
        assert resp.status_code == 404
        assert resp.headers.get("content-type", "").startswith(
            "application/problem+json"
        )

    def test_invalid_slug_syntax_returns_404(self, public_client):
        # Uppercase → not a valid slug → 404.
        resp = public_client.get(f"{PAGES_URL}/BAD-Slug")
        assert resp.status_code == 404

    def test_body_html_is_resanitized_and_img_stripped(
        self, public_client, db
    ):
        # FEAT-0026 remediation plan v2 (2026-07-16): CMS Media is out of
        # scope; the sanitiser strips every <img> tag (any form) and the
        # public renderer no longer rewrites media tokens.
        body_html = (
            "<p>Text</p>"
            "<script>alert('xss')</script>"
            '<p><img data-cms-media="12345678-1234-5678-1234-567812345678" alt="fig"></p>'
            '<p><img src="https://example.com/x.jpg"></p>'
            "<p><img></p>"
        )
        _insert_page(db, slug="rw", body_html=body_html)
        resp = public_client.get(f"{PAGES_URL}/rw")
        assert resp.status_code == 200
        rendered = resp.json()["body_html"]
        # script tag is stripped by the on-read sanitizer.
        assert "<script" not in rendered.lower()
        # No <img> tag survives in any form.
        assert "<img" not in rendered.lower()
        # No lingering media-URL rewrite (the /cms/media/ endpoint no
        # longer exists).
        assert "/cms/media/" not in rendered
        # No lingering data-cms-media marker.
        assert "data-cms-media" not in rendered

    def test_etag_and_cache_control_no_cache(self, public_client, db):
        _insert_page(db, slug="hdrs")
        resp = public_client.get(f"{PAGES_URL}/hdrs")
        assert resp.status_code == 200
        assert resp.headers.get("ETag")
        assert "no-cache" in (resp.headers.get("Cache-Control") or "")

    def test_if_none_match_returns_304(self, public_client, db):
        _insert_page(db, slug="etag-detail")
        resp = public_client.get(f"{PAGES_URL}/etag-detail")
        etag = resp.headers["ETag"]
        resp2 = public_client.get(
            f"{PAGES_URL}/etag-detail",
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304


# ===========================================================================
# US-013 — Redirect resolver
# ===========================================================================


class TestUS013Redirects:
    def test_returns_target_slug(self, public_client, db):
        page_id = _insert_page(db, slug="new-home")
        _insert_redirect(
            db, from_slug="old-home", to_page_id=page_id, to_slug="new-home"
        )
        resp = public_client.get(f"{REDIRECTS_URL}/old-home")
        assert resp.status_code == 200
        assert resp.json()["to_slug"] == "new-home"

    def test_unknown_slug_returns_404(self, public_client):
        resp = public_client.get(f"{REDIRECTS_URL}/nope")
        assert resp.status_code == 404
        assert resp.headers.get("content-type", "").startswith(
            "application/problem+json"
        )

    def test_no_store_cache_control(self, public_client, db):
        page_id = _insert_page(db, slug="target")
        _insert_redirect(
            db, from_slug="legacy", to_page_id=page_id, to_slug="target"
        )
        resp = public_client.get(f"{REDIRECTS_URL}/legacy")
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_self_redirect_returns_404(self, public_client, db):
        # If a redirect somehow points at its own slug, resolver must 404.
        page_id = _insert_page(db, slug="loop")
        _insert_redirect(
            db, from_slug="loop", to_page_id=page_id, to_slug="loop"
        )
        resp = public_client.get(f"{REDIRECTS_URL}/loop")
        assert resp.status_code == 404


# ===========================================================================
# US-014 — Media stream (WITHDRAWN 2026-07-16)
# ===========================================================================
# CMS Media is out of scope per FEAT-0026 remediation plan v2. The
# /api/public/v1/cms/media/{id} endpoint has been removed. Regression
# guard: any request to that path must 404.


class TestUS014MediaEndpointRemoved:
    def test_media_endpoint_returns_404(self, public_client):
        resp = public_client.get(
            "/api/public/v1/cms/media/12345678-1234-5678-1234-567812345678"
        )
        assert resp.status_code == 404


# ===========================================================================
# US-011 AC2 / US-012 AC7 / US-013 AC6 — Bot-UA server-rendered OG endpoint
# ===========================================================================
# Added 2026-07-16 as part of FEAT-0026 remediation plan v2 Task A4.


class TestCmsOgEndpoint:
    def _og_url(self, slug: str) -> str:
        return f"/api/public/v1/pages/{slug}/og"

    def test_returns_html_with_correct_title_and_meta(self, public_client, db):
        _insert_page(
            db,
            slug="og-page",
            title="OG Page",
            meta_description="Meta blurb",
            body_html="<p>Body</p>",
        )
        resp = public_client.get(self._og_url("og-page"))
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        html_body = resp.text
        assert "<title>OG Page</title>" in html_body
        assert 'name="description" content="Meta blurb"' in html_body
        assert 'rel="canonical"' in html_body
        # Body is embedded as-is (already sanitised).
        assert "<p>Body</p>" in html_body

    def test_navbar_fragment_included(self, public_client, db):
        _insert_page(db, slug="nav-a", title="Alpha", nav_order=1)
        _insert_page(db, slug="nav-b", title="Bravo", nav_order=2)
        _insert_page(db, slug="og-target", title="Target", show_in_nav=False)
        resp = public_client.get(self._og_url("og-target"))
        assert resp.status_code == 200
        body = resp.text
        # Nav-visible entries appear (in order); non-nav entries do not.
        idx_a = body.find(">Alpha</a>")
        idx_b = body.find(">Bravo</a>")
        assert idx_a >= 0 and idx_b >= 0
        assert idx_a < idx_b

    def test_unknown_slug_returns_404_html_with_noindex(self, public_client):
        resp = public_client.get(self._og_url("does-not-exist"))
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.headers.get("X-Robots-Tag") == "noindex"
        assert "Page not found" in resp.text

    def test_body_html_is_resanitized_on_render(self, public_client, db):
        # Malicious body_html must not survive to the rendered OG page.
        _insert_page(
            db,
            slug="og-rw",
            body_html=(
                "<p>ok</p>"
                "<script>alert('xss')</script>"
                '<img src="https://example.com/x.jpg">'
            ),
        )
        resp = public_client.get(self._og_url("og-rw"))
        assert resp.status_code == 200
        body = resp.text
        assert "<script" not in body.lower()
        # <img> was withdrawn from the sanitiser allow-list on 2026-07-16.
        assert "example.com/x.jpg" not in body
        # No lingering media-URL rewrite either.
        assert "/cms/media/" not in body

    def test_invalid_slug_returns_404_html(self, public_client):
        # Uppercase / bad slug returns the branded 404 HTML (not JSON).
        resp = public_client.get(self._og_url("BAD-Slug"))
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.headers.get("X-Robots-Tag") == "noindex"

    def test_etag_and_cache_control(self, public_client, db):
        _insert_page(db, slug="og-cache")
        resp = public_client.get(self._og_url("og-cache"))
        assert resp.status_code == 200
        assert resp.headers.get("ETag")
        cache = resp.headers.get("Cache-Control", "")
        assert cache.startswith("public")
        assert "max-age=" in cache

    def test_if_none_match_returns_304(self, public_client, db):
        _insert_page(db, slug="og-304")
        resp = public_client.get(self._og_url("og-304"))
        etag = resp.headers["ETag"]
        resp2 = public_client.get(
            self._og_url("og-304"),
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304


# ===========================================================================
# US-015 — Sitemap contains CMS pages
# ===========================================================================


class TestUS015Sitemap:
    def test_sitemap_lists_cms_pages_with_lastmod(self, public_client, db):
        _insert_page(
            db,
            slug="in-sitemap",
            updated_at=datetime(2026, 7, 1, 0, 0, 0),
        )
        resp = public_client.get(SITEMAP_URL)
        assert resp.status_code == 200
        body = resp.text
        assert "/in-sitemap" in body
        # lastmod present.
        assert "<lastmod>2026-07-01</lastmod>" in body

    def test_sitemap_still_includes_home(self, public_client, db):
        _insert_page(db, slug="another")
        resp = public_client.get(SITEMAP_URL)
        assert resp.status_code == 200
        # Home URL present (from FEAT-0005).
        assert "<loc>" in resp.text
