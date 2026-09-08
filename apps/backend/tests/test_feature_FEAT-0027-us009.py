"""
FEAT-0027 — US-009 (Forms list per-card source action button).

Static assertions against the internal `apps/frontend` source tree. Mirrors the
FEAT-0027 batch-1 static-regression pattern established for US-001..US-008.
No browser is required.

Traceability (TC-US-009):
    AC1 / TC 9.1, 9.8  — exactly one action button, chosen by form_source.
    AC2 / TC 9.2, 9.3  — Download reuses the shared internal Download control.
    AC3 / TC 9.9       — Form Link opens form_source_url, calls no download endpoint.
    AC4 / TC 9.4       — RBAC unchanged (no new endpoint / permission).
    AC5 / TC 9.5       — no layout regression (flex-wrap container + button class).
    AC6 / TC 9.6       — missing file/link → disabled "No Attachment" + tooltip.
    AC7 / TC 9.7       — accessibility: accessible name = action + form context.
    AC8 / TC 9.10      — Form Link hardening: rel + http/https-only scheme guard.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APPS_DIR = Path(__file__).resolve().parents[2]
FRONTEND = APPS_DIR / "frontend"

FORMS_LIST_VIEW = FRONTEND / "js" / "views" / "forms-list.js"
SHARED_POPUP = FRONTEND / "js" / "shared" / "form-details-drawer.js"
MAIN_CSS = FRONTEND / "css" / "main.css"


def _read(path: Path) -> str:
    assert path.exists(), f"Missing frontend file: {path}"
    return path.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str:
    """Return the body of a top-level `function <name>(...) { ... }` block."""
    start = src.index(f"function {name}(")
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"Unbalanced braces while extracting {name}")


# ===========================================================================
# AC1 / AC8 — exactly one button, chosen by form_source (mutual exclusivity)
# ===========================================================================


class TestUS009SourceButtonSelection:
    def test_render_helper_exists_and_is_wired_into_the_card(self):
        """AC1 — a single per-card source button helper is rendered next to
        the title inside displayForms()."""
        src = _read(FORMS_LIST_VIEW)
        assert "function _renderFormSourceButton(" in src, (
            "US-009 AC1 — _renderFormSourceButton helper must exist"
        )
        assert "${_renderFormSourceButton(form)}" in src, (
            "US-009 AC1 — the source button must be rendered on each card"
        )

    def test_download_and_url_branches_are_mutually_exclusive(self):
        """AC1 / TC 9.8 — the helper returns a Download button for
        form_source === 'Download' and a Form Link for 'URL', never both."""
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert "form.form_source === 'Download'" in fn
        assert "form.form_source === 'URL'" in fn
        # Each source branch returns early, so a single card can never emit
        # both the Download button and the Form Link anchor.
        assert 'data-action="download-form-file"' in fn
        assert 'data-action="open-form-link"' in fn

    def test_download_button_requires_an_attachment(self):
        """AC1 / AC6 — the Download button is only emitted when
        form_attachment_url is present."""
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert "if (form.form_attachment_url)" in fn


# ===========================================================================
# AC2 / TC 9.2, 9.3 — Download reuses the shared internal control
# ===========================================================================


class TestUS009DownloadReusesSharedControl:
    def test_forms_list_imports_shared_download_helper(self):
        src = _read(FORMS_LIST_VIEW)
        assert (
            "import { openFormDetailsDrawer, downloadFormAttachment } "
            "from '../shared/form-details-drawer.js';" in src
        ), "US-009 AC2 — forms-list must import the shared downloadFormAttachment"

    def test_shared_popup_exports_download_helper(self):
        src = _read(SHARED_POPUP)
        assert "export async function downloadFormAttachment(" in src, (
            "US-009 AC2 / BR-01 — the internal Download control must be a single "
            "exported helper reused by every entry point"
        )

    def test_shared_download_hits_the_existing_file_endpoint(self):
        fn = _extract_function(
            _read(SHARED_POPUP).replace("export async ", "async "),
            "downloadFormAttachment",
        )
        assert "/forms/${encodeURIComponent(formId)}/file" in fn, (
            "US-009 AC2 — download must target the same /forms/{id}/file endpoint"
        )
        assert "Bearer ${getAuthToken()}" in fn, (
            "US-009 AC2 — download must send the same Authorization header"
        )

    def test_card_click_invokes_shared_helper_not_a_new_endpoint(self):
        src = _read(FORMS_LIST_VIEW)
        assert (
            "downloadFormAttachment(downloadBtn.dataset.formId, "
            "downloadBtn.dataset.formFilename)" in src
        ), "US-009 AC2 — the card Download click must call the shared helper"
        # AC4 / BR-01 — forms-list introduces no new download endpoint of its own.
        assert "/file" not in _extract_function(
            src, "_renderFormSourceButton"
        ), "US-009 AC4 — the card must not build its own download URL"


# ===========================================================================
# AC3 / TC 9.9 — Form Link opens form_source_url, no download endpoint
# ===========================================================================


class TestUS009FormLink:
    def test_form_link_anchor_uses_source_url_and_new_tab(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert 'href="${href}"' in fn
        assert "form.form_source_url" in fn
        assert 'target="_blank"' in fn, "US-009 AC3 — Form Link opens in a new tab"

    def test_form_link_calls_no_download_endpoint(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        # The URL branch must not reference the file-download action.
        url_branch = fn[fn.index("form.form_source === 'URL'") :]
        assert "download-form-file" not in url_branch, (
            "US-009 AC3 / BR-04 — Form Link must not trigger a file download"
        )


# ===========================================================================
# AC8 / TC 9.10 — external-navigation hardening
# ===========================================================================


class TestUS009FormLinkHardening:
    def test_anchor_carries_noopener_noreferrer(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert 'rel="noopener noreferrer"' in fn, (
            "US-009 AC8 — Form Link anchor must carry rel=noopener noreferrer"
        )

    def test_scheme_guard_allows_only_http_https(self):
        src = _read(FORMS_LIST_VIEW)
        assert "function _isSafeHttpUrl(" in src
        guard = _extract_function(src, "_isSafeHttpUrl")
        assert "url.protocol === 'http:'" in guard
        assert "url.protocol === 'https:'" in guard
        # Invalid / non-absolute values fall through to false.
        assert "return false;" in guard

    def test_url_branch_is_guarded_by_scheme_check(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert "_isSafeHttpUrl(form.form_source_url)" in fn, (
            "US-009 AC8 — unsafe schemes must be rejected before rendering the link"
        )


# ===========================================================================
# AC6 / TC 9.6 — missing file / link → disabled "No Attachment"
# ===========================================================================


class TestUS009NoAttachment:
    def test_no_attachment_button_is_disabled_with_tooltip(self):
        src = _read(FORMS_LIST_VIEW)
        assert "function _renderNoAttachmentButton(" in src
        fn = _extract_function(src, "_renderNoAttachmentButton")
        assert "disabled" in fn
        assert "title=" in fn

    def test_download_missing_file_tooltip(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert "'No file available'" in fn

    def test_url_missing_link_tooltip(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert "'No link available'" in fn

    def test_unknown_source_falls_back_to_no_attachment(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert "'No file or URL attached'" in fn


# ===========================================================================
# AC7 / TC 9.7 — accessibility: accessible name includes action + form context
# ===========================================================================


class TestUS009Accessibility:
    def test_download_button_aria_label_includes_action_and_form(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert 'aria-label="Download form ${formLabel}"' in fn

    def test_form_link_aria_label_includes_action_and_form(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFormSourceButton")
        assert 'aria-label="Open form link for ${formLabel}"' in fn

    def test_no_attachment_aria_label_includes_no_attachment(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderNoAttachmentButton")
        assert 'aria-label="No attachment for form ${formLabel}' in fn


# ===========================================================================
# AC5 / TC 9.5 — no layout regression
# ===========================================================================


class TestUS009Layout:
    def test_title_row_uses_flex_wrap_container(self):
        src = _read(FORMS_LIST_VIEW)
        assert 'class="d-flex align-items-start justify-content-between gap-2 flex-wrap"' in src, (
            "US-009 AC5 — title/button row must wrap so long titles don't overflow"
        )

    def test_source_button_css_prevents_shrink_and_wrap(self):
        css = _read(MAIN_CSS)
        assert ".forms-list__source-btn" in css
        assert "flex-shrink: 0;" in css
        assert "white-space: nowrap;" in css


# ===========================================================================
# Regression guard — the US-009 edit must not drop existing exported view
# helpers. A previous revision accidentally deleted the `export function
# searchForms()` declaration while inserting the source-button helpers, which
# broke the search box and every filter that reruns the list.
# ===========================================================================


class TestUS009SearchFilterRegressionGuard:
    def test_search_and_filter_helpers_remain_top_level_exports(self):
        src = _read(FORMS_LIST_VIEW)
        assert re.search(r"(?m)^export function searchForms\(\)", src), (
            "searchForms must remain a top-level exported function "
            "(regression: it was dropped by the US-009 edit)"
        )
        assert re.search(r"(?m)^export function applyFilters\(\)", src), (
            "applyFilters must remain a top-level exported function"
        )

    def test_search_wiring_references_search_forms(self):
        src = _read(FORMS_LIST_VIEW)
        # Search button click + Enter-key handler both call searchForms.
        assert "addEventListener('click', searchForms)" in src, (
            "Search button must be wired to searchForms"
        )
        assert re.search(r"e\.key === 'Enter'[\s\S]{0,80}searchForms\(\)", src), (
            "Enter key in the search box must call searchForms"
        )

    def test_filter_wiring_references_apply_filters(self):
        src = _read(FORMS_LIST_VIEW)
        assert "addEventListener('change', applyFilters)" in src, (
            "Sort dropdown must be wired to applyFilters"
        )
        assert "initFilterBusinessAreaCombobox(applyFilters)" in src, (
            "Business-area filter combobox must be wired to applyFilters"
        )

