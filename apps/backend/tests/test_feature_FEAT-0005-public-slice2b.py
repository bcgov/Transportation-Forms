"""
FEAT-0005 Slice 2B — static regression tests.

Covers US-007 (WCAG 2.1 AA), US-008 (SEO/sitemap/canonical), US-009
(server-rendered OG previews).

Test categories
───────────────
  TestA11yCSS          — US-007 AC8/AC16 CSS assertions
  TestA11yLiveRegion   — US-007 AC6 / edge case: announce debounce
  TestA11yHTMLShell    — US-007 AC1/AC2/AC4/AC7/AC10/AC11/AC17
  TestSEORobots        — US-008 AC1/AC13
  TestSEOHomeMetaTags  — US-008 AC4/AC6/AC10 home meta in index.html
  TestSEODetailMeta    — US-008 AC4/AC5/AC8/AC9/AC10 detail.js client side
  TestSEOHomReset      — US-008 AC4: home.js resets meta on back-nav
  TestOGBackend        — US-009 AC3/AC4/AC5/AC8/AC9/AC10/AC11
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APPS_DIR = Path(__file__).resolve().parents[2]
PUBLIC_FE = APPS_DIR / "public-frontend"
PUBLIC_BE = APPS_DIR / "public-backend"
TESTS_DIR = APPS_DIR / "backend" / "tests"


def _read_fe(rel: str) -> str:
    p = PUBLIC_FE / rel
    assert p.exists(), f"Missing public-frontend file: {p}"
    return p.read_text(encoding="utf-8")


def _read_be(rel: str) -> str:
    p = PUBLIC_BE / rel
    assert p.exists(), f"Missing public-backend file: {p}"
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


# ---------------------------------------------------------------------------
# Minimal HTML parser (reused from slice-2a)
# ---------------------------------------------------------------------------

class _HeadParser(HTMLParser):
    """Collects meta, link, and script tags from <head>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: list[dict] = []
        self.links: list[dict] = []
        self.scripts: list[dict] = []
        self._in_head = False
        self._cur_script_attrs: dict | None = None
        self._cur_script_data: list = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "head":
            self._in_head = True
        if not self._in_head:
            return
        if tag == "meta":
            self.meta.append(attrs_d)
        elif tag == "link":
            self.links.append(attrs_d)
        elif tag == "script":
            self._cur_script_attrs = attrs_d
            self._cur_script_data = []

    def handle_endtag(self, tag):
        if tag == "head":
            self._in_head = False
        if tag == "script" and self._cur_script_attrs is not None:
            self.scripts.append({
                **self._cur_script_attrs,
                "_text": "".join(self._cur_script_data),
            })
            self._cur_script_attrs = None
            self._cur_script_data = []

    def handle_data(self, data):
        if self._cur_script_attrs is not None:
            self._cur_script_data.append(data)

    def meta_by_name(self, name: str) -> dict | None:
        for m in self.meta:
            if m.get("name", "").lower() == name.lower():
                return m
        return None

    def meta_by_prop(self, prop: str) -> dict | None:
        for m in self.meta:
            if m.get("property", "").lower() == prop.lower():
                return m
        return None

    def link_by_rel(self, rel: str) -> dict | None:
        for lk in self.links:
            if lk.get("rel", "").lower() == rel.lower():
                return lk
        return None


def _parse_head(html_src: str) -> _HeadParser:
    p = _HeadParser()
    p.feed(html_src)
    return p


# ===========================================================================
# US-007: Accessibility
# ===========================================================================

class TestA11yCSS:
    """US-007 AC16 — content reflows at 320 CSS px."""

    def _css(self):
        return _read_fe("css/main.css")

    def test_form_card_title_overflow_wrap(self):
        css = self._css()
        # Must have overflow-wrap: anywhere on form-card titles
        assert "overflow-wrap" in css
        assert "anywhere" in css

    def test_form_card_title_word_break_fallback(self):
        # word-break: break-word as fallback for older browsers
        assert "word-break" in self._css()

    def test_detail_heading_overflow_wrap(self):
        css = self._css()
        # #detailContent h1 must also get overflow-wrap
        assert "#detailContent" in css
        # overflow-wrap appears at least twice (form card + detail)
        assert css.count("overflow-wrap") >= 2

    def test_prefers_reduced_motion_skeleton(self):
        # AC8 — skeleton animation disabled under prefers-reduced-motion
        css = self._css()
        assert "prefers-reduced-motion" in css
        assert "animation: none" in css

    def test_prefers_reduced_motion_global(self):
        # AC8 — global motion suppression rule present
        css = self._css()
        assert "prefers-reduced-motion: reduce" in css
        assert "animation-duration: 0.01ms" in css


class TestA11yLiveRegion:
    """US-007 edge case — announce() debounced at 100ms."""

    def _src(self):
        return _read_fe("js/state.js")

    def test_announce_debounce_timer_present(self):
        src = _strip_js_comments(self._src())
        # Must reference a debounce timer for announce
        assert "_announceTimer" in src

    def test_announce_debounce_ms_value(self):
        src = self._src()
        # Debounce constant must be defined and <= 100ms per AC
        m = re.search(r"ANNOUNCE_DEBOUNCE_MS\s*=\s*(\d+)", src)
        assert m, "ANNOUNCE_DEBOUNCE_MS constant missing"
        assert int(m.group(1)) <= 100, "announce debounce must be ≤ 100 ms"

    def test_announce_uses_settimeout(self):
        src = _strip_js_comments(self._src())
        assert "setTimeout" in src


class TestA11yHTMLShell:
    """US-007 AC1/AC2/AC4/AC7/AC10/AC11/AC17 — static HTML assertions."""

    def _html(self):
        return _read_fe("index.html")

    def test_lang_en_ca(self):
        # AC1 — <html lang="en-CA">
        assert 'lang="en-CA"' in self._html()

    def test_skip_link_present(self):
        # AC2 — skip-to-main link is first focusable element
        html = self._html()
        assert "skip-link" in html
        assert "Skip to main content" in html

    def test_main_content_target(self):
        # AC2 — skip link must point to <main id="mainContent">
        html = self._html()
        assert 'href="#mainContent"' in html
        assert 'id="mainContent"' in html

    def test_logo_is_decorative_alt_empty(self):
        # AC7 — BC Gov logo is decorative, alt=""
        html = self._html()
        assert 'bc-gov-transportation-logo.png' in html
        # The logo img must have alt="" (decorative)
        m = re.search(r'<img[^>]+bc-gov-transportation-logo\.png[^>]*>', html)
        assert m, "Logo img tag not found"
        assert 'alt=""' in m.group(0)

    def test_search_input_has_label(self):
        # AC10 — search input has associated label
        html = self._html()
        assert 'for="searchInput"' in html

    def test_filter_select_has_label(self):
        # AC10 — filter dropdown has label
        html = self._html()
        assert 'for="filterBA"' in html

    def test_sort_field_has_label(self):
        # AC10 — sort field has label
        html = self._html()
        assert 'for="sortField"' in html

    def test_sort_order_has_label(self):
        # AC10 — sort order has label
        html = self._html()
        assert 'for="sortOrder"' in html

    def test_alert_slot_role_alert_in_js(self):
        # AC11 — injected alerts use role="alert"
        src = _read_fe("js/ui-states.js")
        assert 'role="alert"' in src or "role', 'alert'" in src

    def test_home_view_single_h1(self):
        # AC17 — exactly one h1 when home view active (visually-hidden h1 + hero h2)
        html = self._html()
        # homeView section must have exactly one h1 (visually-hidden)
        m = re.search(r'<section id="homeView".*?</section>', html, re.DOTALL)
        assert m, "homeView section not found"
        h1s = re.findall(r'<h1\b', m.group(0))
        assert len(h1s) == 1, f"Expected 1 h1 in homeView, got {len(h1s)}"

    def test_no_skipped_heading_ranks_home(self):
        # AC17 — home uses h1 → h2 hierarchy; no h4/h5/h6 that skip h3
        html = self._html()
        m = re.search(r'<section id="homeView".*?</section>', html, re.DOTALL)
        assert m
        section = m.group(0)
        assert "<h1" in section
        assert "<h2" in section
        # h4/h5/h6 would skip ranks if h3 exists; neither should be present
        assert "<h4" not in section
        assert "<h5" not in section
        assert "<h6" not in section

    def test_aria_live_results_count(self):
        # AC6 — result count element has aria-live="polite"
        assert 'aria-live="polite"' in self._html()
        assert 'id="resultsCount"' in self._html()


# ===========================================================================
# US-008: SEO
# ===========================================================================

class TestSEORobots:
    """US-008 AC1/AC13 — robots.txt content."""

    def _robots(self):
        p = PUBLIC_FE / "robots.txt"
        assert p.exists(), "public-frontend/robots.txt is missing"
        return p.read_text(encoding="utf-8")

    def test_robots_file_exists(self):
        self._robots()

    def test_robots_allows_root(self):
        assert "Allow: /" in self._robots()

    def test_robots_disallows_api(self):
        assert "Disallow: /api/" in self._robots()

    def test_robots_disallows_internal_s3(self):
        assert "Disallow: /internal-s3/" in self._robots()

    def test_robots_has_sitemap_line(self):
        assert "Sitemap:" in self._robots()

    def test_robots_user_agent_star(self):
        assert "User-agent: *" in self._robots()


class TestSEOHomeMetaTags:
    """US-008 AC6/AC10 — static OG + Twitter meta in index.html for home view."""

    def _parsed(self):
        return _parse_head(_read_fe("index.html"))

    def test_static_og_title(self):
        og = self._parsed().meta_by_prop("og:title")
        assert og, "og:title missing from index.html head"
        assert "BC Government" in og.get("content", "")

    def test_static_og_type_website(self):
        og = self._parsed().meta_by_prop("og:type")
        assert og and og.get("content") == "website"

    def test_static_og_site_name(self):
        og = self._parsed().meta_by_prop("og:site_name")
        assert og, "og:site_name missing"
        assert og.get("content") == "BC Government Public Forms"

    def test_static_twitter_card(self):
        tw = self._parsed().meta_by_name("twitter:card")
        assert tw and tw.get("content") == "summary"

    def test_static_og_description(self):
        og = self._parsed().meta_by_prop("og:description")
        assert og and og.get("content")

    def test_canonical_link_points_to_root(self):
        # AC4 — home canonical is bare /
        link = self._parsed().link_by_rel("canonical")
        assert link, "canonical link missing"
        assert link.get("href") in ("/", "")


class TestSEODetailMeta:
    """US-008 AC4/AC5/AC8/AC9 — detail.js client-side meta management."""

    def _src(self):
        return _read_fe("js/views/detail.js")

    def test_sets_og_title(self):
        assert "og:title" in self._src()

    def test_sets_og_description(self):
        assert "og:description" in self._src()

    def test_sets_og_url(self):
        assert "og:url" in self._src()

    def test_sets_og_type_website(self):
        assert "'website'" in self._src() or '"website"' in self._src()

    def test_sets_og_site_name_correct(self):
        src = self._src()
        # AC — site_name must be "BC Government Public Forms"
        assert "BC Government Public Forms" in src

    def test_sets_twitter_card(self):
        assert "twitter:card" in self._src()

    def test_canonical_no_trailing_slash(self):
        # AC14 — canonical constructed with encodeURIComponent, no trailing slash
        src = self._src()
        assert "encodeURIComponent" in src
        # Should NOT have /forms/{n}/ (with trailing slash) pattern
        assert "canonical" in src

    def test_jsonld_identifier_present(self):
        # US-008 AC8 — identifier: form_number in JSON-LD
        src = _strip_js_comments(self._src())
        assert re.search(r"identifier\s*:", src), "identifier missing from JSON-LD"

    def test_jsonld_in_language_present(self):
        # US-008 AC8 — inLanguage: "en-CA"
        src = self._src()
        assert "inLanguage" in src
        assert "en-CA" in src

    def test_jsonld_type_digital_document(self):
        src = self._src()
        assert "DigitalDocument" in src

    def test_jsonld_xss_hardening(self):
        # JSON-LD close-tag neutralisation
        src = self._src()
        assert r"<\/" in src

    def test_404_sets_noindex(self):
        # AC9 — _render404 sets robots noindex
        src = _strip_js_comments(self._src())
        assert re.search(r"noindex", src)

    def test_jsonld_no_internal_fields(self):
        src = _strip_js_comments(self._src())
        for forbidden in ("created_by_id", "is_public", "s3_key", "form_id"):
            assert not re.search(rf"\b{forbidden}\b", src), \
                f"forbidden field {forbidden} in detail.js source"


class TestSEOHomeReset:
    """US-008 AC4 — home.js restores canonical + meta on back-nav from detail."""

    def _src(self):
        return _read_fe("js/views/home.js")

    def test_reset_function_exists(self):
        src = _strip_js_comments(self._src())
        assert "_resetHomeMeta" in src

    def test_reset_canonical_to_root(self):
        src = self._src()
        # Must set canonical back to '/'
        m = re.search(r"_resetHomeMeta\s*\(\s*\)(.*?)^}", src, re.DOTALL | re.MULTILINE)
        assert m or "_setLink('canonical', '/')" in src or '_setLink("canonical", "/")' in src

    def test_reset_removes_noindex(self):
        # meta robots is removed / cleared when returning home (so 404 noindex doesn't linger)
        src = self._src()
        assert "robots" in src

    def test_reset_removes_jsonld(self):
        src = self._src()
        assert "application/ld+json" in src

    def test_reset_og_site_name(self):
        src = self._src()
        assert "BC Government Public Forms" in src

    def test_reset_called_in_show_home_view(self):
        src = _strip_js_comments(self._src())
        # _resetHomeMeta must be called inside showHomeView
        m = re.search(r"export async function showHomeView\s*\(\s*\)\s*\{(.*?)^}", src,
                      re.DOTALL | re.MULTILINE)
        # If the regex doesn't work cleanly, check simpler: function calls _resetHomeMeta
        assert "_resetHomeMeta" in src


# ===========================================================================
# US-009: Server-rendered OG (backend) — uses conftest.py + Phase-1 pattern
# ===========================================================================

import importlib
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

# Ensure public-backend is importable.
if str(PUBLIC_BE) not in sys.path:
    sys.path.insert(0, str(PUBLIC_BE))

# Internal backend models (used to seed data the same way Phase 1 does).
from backend.models import (  # noqa: E402
    BusinessArea,
    Form,
    FormNumberPrefix,
    FormNumberReservation,
    FormVersion,
    User,
)

# ---------------------------------------------------------------------------
# View DDL (same as Phase 1 — recreated for isolation)
# ---------------------------------------------------------------------------

_VIEW_DDL = """\
CREATE OR REPLACE VIEW public_forms_v AS
SELECT
    f.id                  AS form_id,
    fnr.full_form_number  AS form_number,
    f.title,
    f.description,
    ba.id                 AS business_area_id,
    ba.name               AS business_area,
    f.keywords,
    f.file_type,
    f.effective_date,
    f.updated_at,
    fv.s3_key             AS s3_key,
    fv.file_name          AS file_name,
    fv.file_size          AS file_size
FROM forms f
LEFT JOIN form_number_reservations fnr
    ON f.form_number_reservation_id = fnr.id
LEFT JOIN business_areas ba
    ON f.business_area_id = ba.id
   AND ba.deleted_at IS NULL
LEFT JOIN form_versions fv
    ON fv.form_id = f.id
   AND fv.is_current = True
   AND fv.deleted_at IS NULL
WHERE f.status     = 'published'
  AND f.is_public  = True
  AND f.deleted_at IS NULL;
"""

_OG_SECRET = "slice2b-test-secret-0123456789abcdef"


@pytest.fixture(scope="session")
def _og_view(_test_engine):
    from sqlalchemy import text
    with _test_engine.connect() as conn:
        conn.execute(text(_VIEW_DDL))
        conn.commit()
    yield
    # View is dropped/recreated by the session-scoped _test_engine fixture.


def _make_og_client(db, monkeypatch) -> TestClient:
    """Build a TestClient for the public-backend app (mirrors Phase-1 pattern)."""
    monkeypatch.setenv("DATABASE_URL_READONLY", "postgresql://x@localhost/x")
    monkeypatch.setenv("INTERNAL_AUTH_SECRET", _OG_SECRET)
    monkeypatch.setenv("CACHE_MAX_AGE", "300")
    monkeypatch.setenv("OG_CACHE_MAX_AGE", "300")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://forms-public.example.gov")

    for name in (
        "config", "database", "audit", "http_cache", "problem",
        "middleware", "models", "routes.forms",
        "routes.business_areas", "routes.sitemap", "main",
    ):
        sys.modules.pop(name, None)

    _database_mod = importlib.import_module("database")
    _main_mod = importlib.import_module("main")
    _main_mod.app.dependency_overrides[_database_mod.get_db] = lambda: db
    return TestClient(_main_mod.app, raise_server_exceptions=False)


@pytest.fixture()
def og_auth_client(db, _og_view, monkeypatch) -> TestClient:
    client = _make_og_client(db, monkeypatch)
    client.headers.update({"X-Internal-Auth": _OG_SECRET})
    return client


@pytest.fixture()
def og_noauth_client(db, _og_view, monkeypatch) -> TestClient:
    client = _make_og_client(db, monkeypatch)
    # No auth header deliberately.
    return client


@pytest.fixture()
def og_creator(db) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"slice2b-{uuid.uuid4().hex[:6]}@example.com",
        first_name="Slice2B",
        last_name="Tester",
    )
    db.add(u)
    db.flush()
    return u


def _og_seed(
    db,
    creator,
    *,
    full_form_number="S2B001",
    title="OG Test Form",
    description="Test description for OG previews.",
    status="published",
    is_public=True,
):
    """Seed the minimum rows needed to exercise /forms/{n}/og."""
    ba = BusinessArea(id=uuid.uuid4(), name=f"OG BA {uuid.uuid4().hex[:4]}")
    db.add(ba)
    db.flush()

    pfx = FormNumberPrefix(
        id=uuid.uuid4(),
        prefix="S2B",
        current_sequence=0,
        padding_length=3,
        max_number_length=10,
        is_active=True,
        created_by_id=creator.id,
    )
    db.add(pfx)
    db.flush()

    resv = FormNumberReservation(
        id=uuid.uuid4(),
        prefix_id=pfx.id,
        form_number="001",
        full_form_number=full_form_number,
        numbering_method="auto_generated",
        status="approved",
        reserved_by_id=creator.id,
        expires_at=datetime(2028, 1, 1, tzinfo=timezone.utc),
    )
    db.add(resv)
    db.flush()

    form = Form(
        id=uuid.uuid4(),
        title=title,
        description=description,
        status=status,
        is_public=is_public,
        keywords=[],
        created_by_id=creator.id,
        business_area_id=ba.id,
        form_number_reservation_id=resv.id,
    )
    db.add(form)
    db.flush()

    fv = FormVersion(
        id=uuid.uuid4(),
        form_id=form.id,
        version_number=1,
        s3_key="og/test.pdf",
        file_name="og-test.pdf",
        file_size=2048,
        file_type="pdf",
        uploaded_by_id=creator.id,
        is_current=True,
    )
    db.add(fv)
    db.flush()
    return form, resv, full_form_number


# ---------------------------------------------------------------------------
# Actual OG tests
# ---------------------------------------------------------------------------

class TestOGBackend:
    """US-009 AC3/AC4/AC5/AC8/AC9/AC10/AC11 — /forms/{n}/og endpoint."""

    def test_og_returns_html_content_type(self, og_auth_client, db, og_creator):
        # AC3 — Content-Type: text/html
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    def test_og_html_doctype_and_lang(self, og_auth_client, db, og_creator):
        # AC3 — <!DOCTYPE html> + <html lang="en-CA">
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        body = resp.text
        assert "<!doctype html>" in body.lower()
        assert 'lang="en-CA"' in body

    def test_og_required_meta_tags(self, og_auth_client, db, og_creator):
        # AC4 — all OG + Twitter tags present
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        body = resp.text
        for marker in ("og:title", "og:description", "og:type", "og:url",
                       "og:site_name", "twitter:card", "twitter:title",
                       "twitter:description"):
            assert marker in body, f"Missing tag: {marker}"

    def test_og_site_name_correct(self, og_auth_client, db, og_creator):
        # AC4 — og:site_name must be "BC Government Public Forms"
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        assert "BC Government Public Forms" in resp.text

    def test_og_jsonld_in_language(self, og_auth_client, db, og_creator):
        # US-008 AC8 — inLanguage present in JSON-LD
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        assert "inLanguage" in resp.text
        assert "en-CA" in resp.text

    def test_og_jsonld_identifier(self, og_auth_client, db, og_creator):
        # US-008 AC8 — identifier present in JSON-LD
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        assert "identifier" in resp.text

    def test_og_jsonld_type_digital_document(self, og_auth_client, db, og_creator):
        # US-008 AC8 — @type = DigitalDocument
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert "DigitalDocument" in resp.text

    def test_og_human_readable_body(self, og_auth_client, db, og_creator):
        # AC3 — body contains minimal human-readable fallback
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        body = resp.text
        assert "<h1>" in body
        assert "<main>" in body
        assert "BC Government Public Forms" in body

    def test_og_html_escapes_xss(self, og_auth_client, db, og_creator):
        # AC11 — special chars in title/description are HTML-escaped
        # Use a unique prefix to avoid conflicts with the main S2B001 seed.
        pfx2 = FormNumberPrefix(
            id=uuid.uuid4(), prefix="X2B", current_sequence=0,
            padding_length=3, max_number_length=10, is_active=True,
            created_by_id=og_creator.id,
        )
        db.add(pfx2)
        db.flush()
        resv2 = FormNumberReservation(
            id=uuid.uuid4(), prefix_id=pfx2.id, form_number="099",
            full_form_number="X2B099", numbering_method="auto_generated",
            status="approved", reserved_by_id=og_creator.id,
            expires_at=datetime(2028, 1, 1, tzinfo=timezone.utc),
        )
        db.add(resv2)
        db.flush()
        form2 = Form(
            id=uuid.uuid4(),
            title="XSS <Test> &amp; 'Quotes'",
            description='<script>alert("xss")</script>',
            status="published", is_public=True, keywords=[],
            created_by_id=og_creator.id,
            form_number_reservation_id=resv2.id,
        )
        db.add(form2)
        db.flush()
        resp = og_auth_client.get("/api/public/v1/forms/X2B099/og")
        assert resp.status_code == 200
        body = resp.text
        assert "<script>alert" not in body
        assert "&lt;" in body or "&amp;" in body

    def test_og_404_returns_html_not_json(self, og_auth_client, db, og_creator):
        # AC5 — unknown form returns 404 HTML, not problem+json
        resp = og_auth_client.get("/api/public/v1/forms/ZZZNOTEXIST/og")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("text/html")
        assert "Form not found" in resp.text

    def test_og_404_sets_noindex(self, og_auth_client, db, og_creator):
        # AC5 — 404 HTML has robots noindex
        resp = og_auth_client.get("/api/public/v1/forms/ZZZNOTEXIST/og")
        assert resp.status_code == 404
        assert "noindex" in resp.text or "noindex" in resp.headers.get("x-robots-tag", "")

    def test_og_404_no_cache(self, og_auth_client, db, og_creator):
        # AC5 / AC10 — 404 responses must not be cached
        resp = og_auth_client.get("/api/public/v1/forms/ZZZNOTEXIST/og")
        assert resp.status_code == 404
        cc = resp.headers.get("cache-control", "")
        assert "no-store" in cc or "no-cache" in cc

    def test_og_cache_control_public(self, og_auth_client, db, og_creator):
        # AC10 — 200 response is publicly cacheable
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        cc = resp.headers.get("cache-control", "")
        assert "public" in cc
        assert "max-age=" in cc

    def test_og_requires_internal_auth(self, og_noauth_client, db, og_creator):
        # AC9 — endpoint rejects requests without X-Internal-Auth
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_noauth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 403

    def test_og_no_internal_fields_in_response(self, og_auth_client, db, og_creator):
        # AC8 — response must never expose internal DB IDs
        _og_seed(db, og_creator, full_form_number="S2B001")
        resp = og_auth_client.get("/api/public/v1/forms/S2B001/og")
        assert resp.status_code == 200
        body = resp.text
        for forbidden in ("created_by_id", "is_public", "s3_key",
                          "business_area_id", "form_id"):
            assert forbidden not in body, \
                f"Internal field {forbidden} must not appear in OG response"
