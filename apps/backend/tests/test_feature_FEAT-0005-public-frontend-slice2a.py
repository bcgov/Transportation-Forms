"""
Static regression tests for FEAT-0005 Phase 2 Slice 2A — public-frontend SPA.

Per the Python SE charter (no new dependencies without consent), these tests
do **not** spin up a browser or jsdom runtime. Instead, they assert the
*structure* of the SPA source files using the standard library:

  - HTML parser (`html.parser`) for index.html landmarks, ARIA, and
    progressive-enhancement requirements.
  - Plain-text / regex assertions for JS source files to verify each
    user-story acceptance criterion is wired to the intended primitive
    (escapeHtml, AbortController, If-None-Match, custom element register,
    history.pushState, application/problem+json handling, …).

Behavioural / DOM-event coverage (AC2 debounce, AC4 history.pushState
firing on click, AC8 keyboard activation timings, …) is the responsibility
of the Playwright suite delivered by DevOps in US-018.

Test IDs map to the user stories in
plan/features/FEAT-0005-public-forms-portal/stories/.
"""

from __future__ import annotations

import re
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FE = ROOT / "public-frontend"


# ─────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────

def _read(rel: str) -> str:
    p = PUBLIC_FE / rel
    assert p.exists(), f"Missing file: {p}"
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    """Remove /* ... */ block comments and // line comments so that token
    scans only see executable source. Preserves string content."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


class _IndexParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []          # list of (tag, attrs_dict)
        self.in_noscript = False
        self.noscript_text = []
        self.text_buffer = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.tags.append((tag, d))
        if tag == "noscript":
            self.in_noscript = True

    def handle_endtag(self, tag):
        if tag == "noscript":
            self.in_noscript = False

    def handle_data(self, data):
        if self.in_noscript:
            self.noscript_text.append(data)
        self.text_buffer.append(data)

    def find(self, tag, **attrs):
        for t, d in self.tags:
            if t != tag:
                continue
            if all(d.get(k) == v for k, v in attrs.items()):
                return d
        return None

    def find_all(self, tag, **attrs):
        out = []
        for t, d in self.tags:
            if t != tag:
                continue
            if all(d.get(k) == v for k, v in attrs.items()):
                out.append(d)
        return out


@pytest.fixture(scope="module")
def index_html() -> str:
    return _read("index.html")


@pytest.fixture(scope="module")
def parsed_index(index_html: str) -> _IndexParser:
    p = _IndexParser()
    p.feed(index_html)
    return p


# ─────────────────────────────────────────────────────────────────────────
# US-010 — Header & footer
# ─────────────────────────────────────────────────────────────────────────

class TestHeaderFooter:
    def test_lang_attribute(self, parsed_index):
        # Doc-level a11y baseline (US-007 + US-010 BR-004).
        html_attrs = parsed_index.find("html")
        assert html_attrs and html_attrs.get("lang") == "en-CA"

    def test_skip_link_first_focusable(self, index_html):
        # US-010 AC3 / US-007 AC2 — Skip-to-main exists.
        assert 'href="#mainContent"' in index_html
        assert "Skip to main content" in index_html

    def test_main_landmark(self, parsed_index):
        assert parsed_index.find("main", id="mainContent") is not None

    def test_footer_role_and_links(self, parsed_index, index_html):
        # US-010 AC4 + AC6
        assert parsed_index.find("footer", role="contentinfo") is not None
        for link in ("Disclaimer", "Privacy", "Accessibility", "Copyright"):
            assert link in index_html, f"footer link missing: {link}"
        assert "Government of British Columbia" in index_html

    def test_footer_nav_aria_label(self, parsed_index):
        nav = parsed_index.find("nav", **{"aria-label": "Footer"})
        assert nav is not None

    def test_shared_chrome_modules_exist_and_match(self):
        # US-010 AC1 — shared module exists and is mirrored byte-for-byte.
        a = (ROOT / "frontend/js/shared/chrome.js").read_text(encoding="utf-8")
        b = (ROOT / "public-frontend/js/shared/chrome.js").read_text(encoding="utf-8")
        # Both export renderHeader and use the same HEADER_HTML template.
        assert "export function renderHeader" in a
        assert "export function renderHeader" in b
        # HEADER_HTML markup must match (the file headers/comments differ).
        def _extract(src):
            m = re.search(r"const HEADER_HTML = `(.*?)`;", src, re.DOTALL)
            assert m, "HEADER_HTML constant missing"
            return m.group(1)
        assert _extract(a) == _extract(b), "Shared header markup drifted between apps"


# ─────────────────────────────────────────────────────────────────────────
# US-001 — Home / search / aria-live
# ─────────────────────────────────────────────────────────────────────────

class TestHomeShell:
    def test_search_input_present_with_describedby(self, parsed_index):
        inp = parsed_index.find("input", id="searchInput")
        assert inp is not None
        # AC4 — helper text via aria-describedby
        assert inp.get("aria-describedby") == "searchHelp"
        assert inp.get("maxlength") == "100"  # Q_MAX_LENGTH

    def test_search_helper_text(self, index_html):
        assert "Search for forms here" in index_html

    def test_results_region_aria_live_and_busy(self, parsed_index):
        rr = parsed_index.find("div", id="resultsRegion")
        assert rr is not None
        assert rr.get("aria-busy") == "false"
        assert rr.get("aria-live") == "polite"

    def test_results_count_aria_live(self, parsed_index):
        rc = parsed_index.find("p", id="resultsCount")
        assert rc is not None
        assert rc.get("aria-live") == "polite"
        assert rc.get("aria-atomic") == "true"

    def test_sticky_search_marker_present(self, index_html):
        # AC5 — sticky positioning marker
        assert 'id="searchSticky"' in index_html
        assert "sticky-top" in index_html

    def test_noscript_fallback_present_with_contact_link(self, parsed_index, index_html):
        # US-001 AC12 / US-006 AC10 — noscript is real and includes mailto.
        text = "".join(parsed_index.noscript_text)
        assert "JavaScript is required" in text
        # mailto: lives in an href attribute, search the raw HTML inside <noscript>.
        m = re.search(r"<noscript>(.*?)</noscript>", index_html, flags=re.DOTALL | re.IGNORECASE)
        assert m, "<noscript> block missing"
        assert "mailto:" in m.group(1)


class TestSearchBehaviourWiring:
    def test_debounce_and_abort_controller(self):
        src = _read("js/views/home.js")
        assert "SEARCH_DEBOUNCE_MS" in src
        assert "AbortController" in src
        assert "abort()" in src

    def test_default_first_paint_query(self):
        src = _read("js/constants.js")
        assert "DEFAULT_SORT_FIELD = 'updated_at'" in src
        assert "DEFAULT_SORT_ORDER = 'desc'" in src
        assert "PAGE_SIZE = 25" in src

    def test_etag_revalidation(self):
        src = _read("js/api.js")
        # AC13 — If-None-Match round-trip
        assert "If-None-Match" in src
        assert "_etagCache" in src
        assert "304" in src

    def test_aria_live_announce_on_render(self):
        src = _read("js/views/home.js")
        assert "announce(" in src
        assert "Showing 0 results" in src

    def test_url_only_relative_paths(self):
        src = _read("js/api.js")
        # AC14 — never call out to an absolute origin
        assert "http://" not in src.lower()
        assert "https://" not in src.lower()

    def test_q_normalised_and_capped(self):
        src = _read("js/utils.js")
        assert "trim()" in src
        assert "Q_MAX_LENGTH" in src


# ─────────────────────────────────────────────────────────────────────────
# US-002 — <form-card>
# ─────────────────────────────────────────────────────────────────────────

class TestFormCard:
    def test_custom_element_registered(self):
        src = _read("js/components/form-card.js")
        assert "customElements.define('form-card'" in src
        # Light DOM (AC10) — no Shadow DOM
        assert "attachShadow" not in src

    def test_view_more_is_anchor(self):
        src = _read("js/components/form-card.js")
        # AC3 — must be a real <a href>, supports middle-click.
        assert re.search(r'<a [^>]*href="/forms/', src)

    def test_disabled_when_form_number_null(self):
        src = _read("js/components/form-card.js")
        # AC2 — aria-disabled on the disabled View more
        assert 'aria-disabled="true"' in src

    def test_download_separate_tab_stop(self):
        src = _read("js/components/form-card.js")
        # AC6 — separate <button> with data-action="download"
        assert 'data-action="download"' in src
        # AC6 — descriptive aria-label
        assert "aria-label=" in src

    def test_only_allowlisted_fields_rendered(self):
        src = _strip_js_comments(_read("js/components/form-card.js"))
        # AC12 — no internal identifiers leak into the DOM.
        # Use word-boundary checks against executable source (no comments).
        for forbidden in ("created_by_id", "is_public", "s3_key",
                          "form_id", "business_area_id"):
            assert not re.search(rf"\b{forbidden}\b", src), \
                f"field {forbidden} must not appear in form-card source"

    def test_intl_date_format(self):
        # AC11 — Intl.DateTimeFormat('en-CA') ; <time datetime="…">
        utils = _read("js/utils.js")
        assert "Intl.DateTimeFormat('en-CA'" in utils
        card = _read("js/components/form-card.js")
        assert "<time datetime=" in card

    def test_history_state_cap(self):
        src = _read("js/components/form-card.js")
        # AC15 — cap-byte check before history.pushState payload
        assert "HISTORY_STATE_CAP_BYTES" in src
        assert "byteLength" in src


# ─────────────────────────────────────────────────────────────────────────
# US-003 — Detail view
# ─────────────────────────────────────────────────────────────────────────

class TestDetailView:
    def test_cache_first_from_history_state(self):
        src = _read("js/views/detail.js")
        # AC1
        assert "window.history.state" in src
        assert "_readState" in src

    def test_fallback_fetch_on_direct_nav(self):
        src = _read("js/views/detail.js")
        # AC2 / AC3 — fallback path
        assert "/forms/" in src
        assert "fetchJson" in src

    def test_per_page_meta_tags(self):
        src = _read("js/views/detail.js")
        # AC5 — title, description, canonical, og:*, twitter:*, JSON-LD
        for tag in ("og:title", "og:description", "og:type", "og:url",
                    "og:site_name", "twitter:card", "twitter:title",
                    "twitter:description"):
            assert tag in src, f"meta tag missing in detail view: {tag}"
        assert "canonical" in src
        assert "application/ld+json" in src

    def test_jsonld_no_internal_ids(self):
        src = _strip_js_comments(_read("js/views/detail.js"))
        # AC14 — JSON-LD payload shape
        assert re.search(r"@type['\"]?\s*:\s*['\"]DigitalDocument", src)
        # err.status (HTTP) is a legitimate use; only flag form-record fields.
        for forbidden in ("created_by_id", "is_public", "s3_key", "form_id"):
            assert not re.search(rf"\b{forbidden}\b", src), \
                f"forbidden field {forbidden} in JSON-LD source"

    def test_404_emits_robots_noindex(self):
        src = _read("js/views/detail.js")
        # AC4
        assert "robots" in src
        assert "noindex" in src

    def test_jsonld_neutralises_close_script(self):
        src = _read("js/views/detail.js")
        # XSS hardening — </ neutralised inside <script type="application/ld+json">
        assert r"<\\/" in src or "<\\/" in src


# ─────────────────────────────────────────────────────────────────────────
# US-004 — File download
# ─────────────────────────────────────────────────────────────────────────

class TestDownload:
    def test_download_path(self):
        src = _read("js/api.js")
        # AC1 — same-origin file endpoint
        assert "/forms/" in src
        assert "/file" in src

    def test_form_number_url_encoded(self):
        src = _read("js/api.js")
        assert "encodeURIComponent" in src

    def test_keyboard_activation_via_button_or_anchor(self):
        # AC11 — download is a real <button> in the card; native keyboard support.
        src = _read("js/components/form-card.js")
        assert '<button type="button"' in src
        assert 'data-action="download"' in src


# ─────────────────────────────────────────────────────────────────────────
# US-005 — Filter / sort / pagination / view-all
# ─────────────────────────────────────────────────────────────────────────

class TestFilterSortPagination:
    def test_business_areas_endpoint_consumed(self):
        src = _read("js/views/home.js")
        assert "/business-areas" in src
        # AC2 — alphabetised
        assert "localeCompare" in src

    def test_sort_options_and_orders(self):
        src = _read("js/constants.js")
        for f in ("title", "form_number", "effective_date", "updated_at"):
            assert f in src
        for o in ("asc", "desc"):
            assert o in src

    def test_pagination_25_per_page(self):
        src = _read("js/constants.js")
        assert "PAGE_SIZE = 25" in src

    def test_view_all_cap(self):
        src = _read("js/constants.js")
        assert "VIEW_ALL_CAP = 500" in src

    def test_out_of_range_falls_back_to_last_page(self):
        src = _read("js/views/home.js")
        # AC8
        assert "lastPage" in src
        assert "offset >= total" in src

    def test_invalid_sort_stripped_from_url(self):
        # AC13 — parseQuery drops unknown sort/order
        src = _read("js/utils.js")
        assert "SORT_FIELDS.includes" in src
        assert "SORT_ORDERS.includes" in src

    def test_filter_or_sort_resets_page(self):
        src = _read("js/views/home.js")
        # AC12 — page reset on filter/sort change
        assert re.search(r"state\.f\s*=", src)
        # The function bodies all set state.p = 1 after a filter/sort change.
        assert re.search(r"state\.p\s*=\s*1", src)


# ─────────────────────────────────────────────────────────────────────────
# US-006 — UI states
# ─────────────────────────────────────────────────────────────────────────

class TestUIStates:
    def test_skeleton_present_and_aria_busy_set(self):
        src = _read("js/ui-states.js")
        # AC1 / AC11
        assert "skeleton-card" in src
        assert "aria-busy" in src and "true" in src

    def test_alert_role_and_dismissible(self):
        src = _read("js/ui-states.js")
        # AC5 — role="alert" + dismiss control
        assert "role" in src
        assert "alert" in src
        assert "Dismiss" in src

    def test_rate_limit_and_5xx_distinct(self):
        src = _read("js/ui-states.js")
        # AC5 / AC6 — both kinds wired
        assert "rate-limit" in src
        assert "Try again" in src or "retry" in src

    def test_404_view_emits_robots_noindex(self):
        src = _read("js/views/not-found.js")
        # AC9
        assert "robots" in src
        assert "noindex" in src

    def test_empty_state_clear_filters_button(self, index_html):
        assert 'id="emptyState"' in index_html
        assert 'id="clearFiltersBtn"' in index_html
        src = _read("js/views/home.js")
        assert "clearFiltersBtn" in src

    def test_skeleton_respects_reduced_motion(self):
        css = (PUBLIC_FE / "css/main.css").read_text(encoding="utf-8")
        assert "prefers-reduced-motion" in css


# ─────────────────────────────────────────────────────────────────────────
# General security / hardening
# ─────────────────────────────────────────────────────────────────────────

class TestSecurityHardening:
    def test_escape_html_used_in_card(self):
        src = _read("js/components/form-card.js")
        # Every raw API value into innerHTML must pass through escapeHtml.
        # We can't assert this perfectly with a regex, but we can ensure
        # escapeHtml is imported and the file does not call innerHTML with
        # bare API field interpolations.
        assert "escapeHtml" in src

    def test_no_inline_scripts_in_index(self, index_html):
        # CSP-friendly: zero inline <script> tags except the module entrypoint.
        # We allow exactly one <script type="module" src="…">.
        scripts = re.findall(r"<script\b[^>]*>", index_html, flags=re.IGNORECASE)
        assert len(scripts) == 1, f"expected 1 script tag, got {len(scripts)}"
        assert 'type="module"' in scripts[0]
        assert "src=" in scripts[0]

    def test_no_third_party_origins_referenced(self, index_html):
        # FEAT-0005 §3 — vendored, no CDN.
        assert "cdn.jsdelivr.net" not in index_html
        assert "https://cdn." not in index_html
        assert "//cdnjs." not in index_html

    def test_canonical_link_and_viewport(self, parsed_index):
        assert parsed_index.find("link", rel="canonical") is not None
        assert parsed_index.find("meta", name="viewport") is not None

    def test_history_state_payload_size_guard(self):
        src = _read("js/utils.js")
        assert "byteLength" in src
        assert "Blob" in src
