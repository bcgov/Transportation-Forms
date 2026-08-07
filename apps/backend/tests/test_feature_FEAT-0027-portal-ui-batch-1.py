"""
FEAT-0027 Batch 1 — Public portal UX static regression tests.

Covers US-001 (search-results overflow fix), US-002 (themed Download pill),
US-003 (header logo natural aspect ratio), US-004 (form-number hyperlink),
and US-005 (tab title prefixed with form number).

These are static assertions against the `apps/public-frontend` source
tree, mirroring the pattern established for FEAT-0005 Slice 2A/2B. No
browser is required.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APPS_DIR = Path(__file__).resolve().parents[2]
PUBLIC_FE = APPS_DIR / "public-frontend"


def _read_fe(rel: str) -> str:
    p = PUBLIC_FE / rel
    assert p.exists(), f"Missing public-frontend file: {p}"
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


# ===========================================================================
# US-001 — Search results overflow fix
# ===========================================================================

class TestUS001SearchOverflow:
    """US-001 AC1/AC2/AC4 + BR-02 — description wraps within its container."""

    def _css(self):
        return _read_fe("css/main.css")

    def test_form_card_desc_wraps_not_nowrap(self):
        """AC1 — `.form-card__desc` must NOT force single-line via `nowrap`.

        The pre-fix rule set `white-space: nowrap` + `overflow: hidden` +
        `text-overflow: ellipsis`, which produced horizontal overflow /
        clipping on long descriptions. BR-02 explicitly forbids single-line
        ellipsis truncation on the public list.
        """
        css = self._css()
        # Isolate the form-card__desc block to avoid false negatives from
        # unrelated `nowrap` rules elsewhere in the file.
        m = re.search(r"form-card\s+\.form-card__desc\s*\{([^}]*)\}", css, re.DOTALL)
        assert m, "form-card .form-card__desc rule missing"
        block = m.group(1)
        assert "nowrap" not in block, \
            "form-card__desc must not use white-space: nowrap (US-001 AC1 / BR-02)"
        assert "text-overflow" not in block, \
            "form-card__desc must not use text-overflow ellipsis on public list (BR-02)"

    def test_form_card_desc_uses_overflow_wrap_anywhere(self):
        """AC2 — long unbroken tokens must wrap at a character boundary."""
        css = self._css()
        m = re.search(r"form-card\s+\.form-card__desc\s*\{([^}]*)\}", css, re.DOTALL)
        assert m
        block = m.group(1)
        assert "overflow-wrap" in block and "anywhere" in block, \
            "form-card__desc must set overflow-wrap: anywhere (US-001 AC2)"

    def test_form_card_desc_word_break_fallback(self):
        """AC2 — `word-break: break-word` fallback for legacy browsers."""
        css = self._css()
        m = re.search(r"form-card\s+\.form-card__desc\s*\{([^}]*)\}", css, re.DOTALL)
        assert m
        assert "word-break" in m.group(1), \
            "form-card__desc must include word-break fallback for older browsers"

    def test_form_card_no_client_side_truncate(self):
        """AC4 / BR-01 — no JS-side truncation on the public list."""
        src = _strip_js_comments(_read_fe("js/components/form-card.js"))
        # `truncate(...)` MUST NOT be called on the description in form-card.js.
        # Search the _render() function for a truncate() call.
        m = re.search(r"_render\s*\(\s*\)\s*\{(.*?)\n\s*\}\n", src, re.DOTALL)
        # If regex fails, just scan whole file.
        body = m.group(1) if m else src
        assert "truncate(" not in body, \
            "form-card must not truncate description client-side (US-001 BR-01/BR-02)"


# ===========================================================================
# US-002 — Themed "Download" pill button
# ===========================================================================

class TestUS002DownloadPill:
    """US-002 AC1/AC2/AC3/AC4 — pill Download button on every row."""

    def _src(self):
        return _read_fe("js/components/form-card.js")

    def test_download_button_has_pill_class(self):
        """AC2 — button uses `rounded-pill` from the theme (no one-off style)."""
        src = _strip_js_comments(self._src())
        # Any `class="..."` attribute containing `form-card__download` must
        # also contain `rounded-pill`.
        buttons = re.findall(
            r'<button[^>]*class="([^"]*form-card__download[^"]*)"',
            src,
        )
        assert buttons, "form-card__download button element not found"
        for cls in buttons:
            assert "rounded-pill" in cls, \
                f"Download button missing `rounded-pill` class: {cls!r}"

    def test_download_button_uses_theme_primary(self):
        """AC2 — button reuses theme primary token (no inline colour)."""
        src = self._src()
        buttons = re.findall(
            r'<button[^>]*class="([^"]*form-card__download[^"]*)"',
            src,
        )
        for cls in buttons:
            assert "btn-primary" in cls, \
                f"Download button must use `btn-primary` theme token: {cls!r}"
        assert 'style="' not in src, \
            "form-card must not use inline style attributes"

    def test_download_button_visible_text_label(self):
        """AC1 — visible text label "Download" (icon-only replaced)."""
        src = _strip_js_comments(self._src())
        # The visible label after `>` in the button element must be "Download".
        assert re.search(
            r'<button[^>]*form-card__download[^>]*>\s*Download\s*</button>',
            src,
        ), "Download pill must render visible text label 'Download'"

    def test_no_download_arrow_icon_remains(self):
        """AC1 — the previous ⬇ icon must no longer appear as the label."""
        src = self._src()
        # Guard: the ⬇ character (U+2B07 / U+2193) must not appear anywhere.
        assert "⬇" not in src and "\u2b07" not in src and "\u2193" not in src, \
            "Icon-only ⬇ download control must be replaced by the Download pill"

    def test_download_action_hook_preserved(self):
        """AC3 — same `data-action="download"` hook triggers the same handler."""
        src = _strip_js_comments(self._src())
        assert 'data-action="download"' in src
        # Handler must still call downloadFormFile(form_number) unchanged.
        assert "downloadFormFile(f.form_number)" in src

    def test_download_button_aria_label(self):
        """AC4 — accessible name is set via aria-label."""
        src = self._src()
        assert re.search(
            r'<button[^>]*form-card__download[^>]*aria-label="[^"]+"',
            src,
        ), "Download pill must expose an aria-label"

    def test_no_new_authenticated_call_public_api_base(self):
        """CC-BR-01 — public frontend must only use the anonymous API base."""
        constants_src = _read_fe("js/constants.js")
        assert "/api/public/v1" in constants_src, \
            "API_BASE must resolve to the anonymous public API surface"
        # form-card must not import or reference an authenticated endpoint.
        fc = self._src()
        assert "/api/v1/" not in fc, \
            "form-card must not call the authenticated API surface (CC-BR-01)"


# ===========================================================================
# US-003 — Header logo natural aspect ratio
# ===========================================================================

class TestUS003HeaderLogo:
    """US-003 AC1/AC2/AC4/AC5 — logo renders at natural aspect ratio."""

    def _html(self):
        return _read_fe("index.html")

    def _css(self):
        return _read_fe("css/main.css")

    def test_logo_img_uses_css_sizing_class(self):
        """AC1 (CLS) — the header logo is sized via the .bcgov-header-logo
        class (max-height + width:auto + display:block), preserving its
        natural aspect ratio without a layout shift. The current design sizes
        the logo in CSS rather than with fixed inline width/height attributes.
        """
        html = self._html()
        m = re.search(
            r'<img[^>]+bc-gov-transportation-logo\.png[^>]*>',
            html,
        )
        assert m, "Header logo img tag not found"
        assert "bcgov-header-logo" in m.group(0), \
            "Header logo img must carry the .bcgov-header-logo sizing class (AC1)"

    def test_logo_css_width_auto(self):
        """AC1 — CSS must NOT set a fixed width that forces a non-natural ratio.

        The rule may set `height` (visual sizing) and `width: auto` or omit
        width entirely; it must not set both to fixed pixel values.
        """
        css = self._css()
        m = re.search(r"\.bcgov-header-logo\s*\{([^}]*)\}", css, re.DOTALL)
        assert m, ".bcgov-header-logo rule missing"
        block = m.group(1)
        # Must not set both width AND height to fixed lengths.
        w = re.search(r"(^|\s)width:\s*([^;]+);", block)
        h = re.search(r"(^|\s)height:\s*([^;]+);", block)
        assert h, "Header logo needs a height for stable header size (AC2)"
        if w:
            assert "auto" in w.group(2) or "%" in w.group(2), \
                "Header logo width must be auto/percentage, not a fixed length"

    def test_logo_css_max_width_100_for_narrow_viewport(self):
        """AC4 — logo must not overflow the header at xs (320px)."""
        css = self._css()
        m = re.search(r"\.bcgov-header-logo\s*\{([^}]*)\}", css, re.DOTALL)
        assert m
        assert "max-width" in m.group(1), \
            "Header logo must set max-width to prevent overflow at narrow viewports (AC4)"

    def test_logo_css_xs_breakpoint_scaledown(self):
        """AC4 — a narrow-viewport override caps the logo height so it fits
        alongside the brand text on small screens without a horizontal
        scrollbar."""
        css = self._css()
        assert re.search(
            r"@media\s*\(\s*max-width:\s*5\d{2}(?:\.\d+)?px\s*\)",
            css,
        ), "Missing narrow-breakpoint media query for header logo scaledown (AC4)"

    def test_logo_alt_preserved(self):
        """AC5 — alt attribute preserved on the logo img (decorative empty)."""
        html = self._html()
        m = re.search(
            r'<img[^>]+bc-gov-transportation-logo\.png[^>]*>',
            html,
        )
        assert m
        # Existing implementation uses alt="" (decorative — a11y baseline
        # already covered by FEAT-0005 US-007 AC7). We must not remove it.
        assert 'alt="' in m.group(0), "Logo img must retain alt attribute"


# ===========================================================================
# US-004 — Form number hyperlink
# ===========================================================================

class TestUS004FormNumberLink:
    """US-004 AC1/AC2/AC3/AC6 — form number rendered as <a href> link."""

    def _src(self):
        return _read_fe("js/components/form-card.js")

    def test_form_number_is_anchor_with_href(self):
        """AC1 — form-card__num rendered as `<a href=...>` (not `<span>`)."""
        src = _strip_js_comments(self._src())
        assert re.search(
            r'<a\s+class="form-card__num"\s+href="',
            src,
        ), "form-card__num must be rendered as an <a href=...> link (US-004 AC1)"

    def test_form_number_href_uses_canonical_detail_url(self):
        """AC1/BR-01 — href reuses the same canonical `/forms/{form_number}` URL
        used by the "View more" link (and consumed by the router)."""
        src = _strip_js_comments(self._src())
        # The form-number anchor MUST use `/forms/{encodeURIComponent(form_number)}`
        # (US-004 AC3 requires URL-encoding of special characters, e.g. `/`).
        assert re.search(
            r'<a class="form-card__num"\s+href="/forms/\$\{encodeURIComponent\(f\.form_number\)\}"',
            src,
        ), "form-number link must use `/forms/${encodeURIComponent(form_number)}` (US-004 BR-01/AC3)"

    def test_form_number_link_no_click_handler_preventing_default(self):
        """AC6 — no custom handler overrides native middle/Ctrl-click.

        The form-card `_onClick` handler must only intercept the download
        button (`data-action="download"`); everything else falls through to
        the global router click handler, which honours modifier keys.
        """
        src = _strip_js_comments(self._src())
        m = re.search(r"_onClick\s*=\s*\(e\)\s*=>\s*\{(.*?)\}\s*\n", src, re.DOTALL)
        assert m, "form-card _onClick handler not found"
        body = m.group(1)
        # Only `data-action === 'download'` should call preventDefault.
        # Guard: no unconditional preventDefault on the anchor click path.
        assert "preventDefault" in body, "Expected preventDefault for download only"
        # There must be a conditional guard around preventDefault so anchors
        # are not intercepted here.
        assert "target.dataset.action === 'download'" in body, \
            "preventDefault must be scoped to the download action only (US-004 AC6)"

    def test_form_number_link_has_aria_label(self):
        """CC-BR-06 — accessible name is exposed for screen readers."""
        src = self._src()
        assert re.search(
            r'<a\s+class="form-card__num"[^`]*aria-label="Open details for form',
            src,
        ), "form-card__num link must expose an aria-label describing the target"

    def test_link_style_defined_in_css(self):
        """AC3 — link colour + underline treatment defined in main.css."""
        css = _read_fe("css/main.css")
        assert re.search(
            r"form-card\s+a\.form-card__num\s*\{[^}]*color:",
            css,
        ), "form-card__num link must have a themed color rule"
        assert re.search(
            r"form-card\s+a\.form-card__num\s*\{[^}]*text-decoration:\s*underline",
            css,
        ), "form-card__num link must have underline text-decoration"


# ===========================================================================
# US-005 — Public form-details tab title prefixed with form number
# ===========================================================================

class TestUS005TabTitle:
    """US-005 AC1/AC2/AC4/AC5 — tab title format."""

    def _detail(self):
        return _read_fe("js/views/detail.js")

    def _constants(self):
        return _read_fe("js/constants.js")

    def _home(self):
        return _read_fe("js/views/home.js")

    def test_site_name_constant_exported(self):
        """SITE_NAME is a single source of truth for the tab-title site chunk."""
        c = self._constants()
        m = re.search(r"export\s+const\s+SITE_NAME\s*=\s*['\"]([^'\"]+)['\"]", c)
        assert m, "SITE_NAME constant must be exported from constants.js"
        assert m.group(1) == "Transportation Forms — BC Government", \
            "SITE_NAME must equal 'Transportation Forms — BC Government'"

    def test_detail_imports_site_name(self):
        """detail.js consumes SITE_NAME (no hardcoded duplicate string)."""
        d = self._detail()
        assert "import { SITE_NAME }" in d or re.search(
            r"import\s*\{[^}]*\bSITE_NAME\b[^}]*\}\s*from\s*['\"]\.\./constants\.js['\"]",
            d,
        ), "detail.js must import SITE_NAME from constants.js"

    def test_detail_title_format_uses_colon_separator(self):
        """AC1 — format `<form_number>: <form_title> | <site_name>`."""
        d = self._detail()
        assert "${num}: ${rawTitle} | ${SITE_NAME}" in d, \
            "detail.js must produce '<num>: <title> | <site_name>' (US-005 AC1)"

    def test_detail_title_fallback_when_no_title(self):
        """AC4 — when title is missing/whitespace, format is `<num> | <site>`."""
        d = self._detail()
        assert "${num} | ${SITE_NAME}" in d, \
            "detail.js must fall back to '<num> | <site_name>' when title is empty (US-005 AC4)"

    def test_detail_title_no_undefined_or_null_placeholders(self):
        """AC4 — the fallback branch is entered when title is empty/whitespace."""
        d = _strip_js_comments(self._detail())
        # The implementation must trim() the title before deciding fallback.
        assert re.search(
            r"(rawTitle|title)\s*=.*?\.trim\(\)",
            d,
            re.DOTALL,
        ) or "f.title.trim()" in d, \
            "detail.js must trim the form title before choosing the fallback (US-005 AC4)"

    def test_detail_no_legacy_dash_dash_site_format(self):
        """The pre-fix format ' — Public Forms — BC Government' must NOT still be
        produced for the successful render path.  (The 404 branch may keep its
        own title unchanged; AC2 only scopes the details render.)"""
        d = _strip_js_comments(self._detail())
        # Guard: the successful render path must not build the old template.
        assert "(${f.form_number}) — Public Forms — BC Government" not in d, \
            "detail.js still emits the legacy tab-title format for the render path"

    def test_home_tab_title_unchanged(self):
        """AC2 — non-details pages retain their pre-fix titles."""
        h = self._home()
        assert "document.title = 'Public Forms — BC Government'" in h, \
            "home view tab title must remain 'Public Forms — BC Government' (US-005 AC2)"

    def test_no_new_authenticated_call(self):
        """CC-BR-01 — no new authenticated fetch introduced by this story."""
        d = self._detail()
        assert "/api/v1/" not in d, \
            "detail.js must not call the authenticated API surface (CC-BR-01)"
