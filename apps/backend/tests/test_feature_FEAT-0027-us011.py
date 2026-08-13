"""
FEAT-0027 — US-011 (Preserve newlines in form Description: save + display).

Two layers:
  * Backend round-trip tests exercise FormService.create_form / update_form to
    prove newlines are normalised (\\r\\n, \\r -> \\n) and preserved verbatim
    (idempotent, no stripping/collapsing).
  * Static assertions against `apps/frontend` prove the display path escapes the
    description (no raw-HTML/innerHTML path) and renders newlines via CSS
    `white-space: pre-wrap`, while US-010's single-line list truncation is kept.

Traceability (TC-US-011):
    AC1 / AC4 / AC5 / BR-04 — save-path normalisation + idempotency (backend).
    AC2 / AC7 / BR-02       — display escapes HTML, pre-wrap for newlines (static).
    AC3                     — historical single-line descriptions render unchanged.
    AC6                     — Approvals popup reuses the same component (static).
    US-010 preserved        — forms-list description stays nowrap + ellipsis.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from backend.services.forms import FormService


# ===========================================================================
# Backend — save-path normalisation & round-trip (AC1 / AC4 / AC5 / BR-04)
# ===========================================================================


class TestUS011SavePathNormalisation:
    def test_normalize_newlines_converts_crlf_and_cr_to_lf(self):
        """AC5 / BR-04 — \\r\\n and \\r collapse to a single \\n each."""
        raw = "line1\r\nline2\rline3\nline4"
        assert FormService._normalize_newlines(raw) == "line1\nline2\nline3\nline4"

    def test_normalize_newlines_is_idempotent(self):
        """AC4 — re-normalising already-LF text is byte-identical."""
        normalised = "a\nb\n\nc"
        assert FormService._normalize_newlines(normalised) == normalised

    def test_normalize_newlines_preserves_consecutive_and_tabs(self):
        """Edge cases — consecutive newlines and tabs are preserved verbatim."""
        raw = "a\r\n\r\n\r\n\tb"
        assert FormService._normalize_newlines(raw) == "a\n\n\n\tb"

    def test_normalize_newlines_none_passthrough(self):
        assert FormService._normalize_newlines(None) is None

    def test_create_form_persists_normalised_newlines(self, db, user_factory):
        """AC1 / AC5 — create_form stores the description with \\n newlines."""
        user = user_factory()
        form = FormService.create_form(
            db,
            title="US-011 create",
            description="First line\r\nSecond line\r\n\r\nThird paragraph",
            is_public=False,
            keywords=None,
            business_area_id=None,
            created_by_id=user.id,
        )
        assert form.description == "First line\nSecond line\n\nThird paragraph"

    def test_update_form_normalises_newlines(self, db, user_factory):
        """AC1 / AC5 — update_form normalises pasted CRLF/CR to \\n."""
        user = user_factory()
        form = FormService.create_form(
            db,
            title="US-011 update",
            description="orig",
            is_public=False,
            keywords=None,
            business_area_id=None,
            created_by_id=user.id,
        )
        updated = FormService.update_form(
            db,
            form_id=form.id,
            updated_by_id=user.id,
            description="win\r\nmac\rnix\nend",
        )
        assert updated is not None
        assert updated.description == "win\nmac\nnix\nend"

    def test_resave_unchanged_description_is_byte_identical(self, db, user_factory):
        """AC4 — re-saving already-normalised text produces no spurious diff."""
        user = user_factory()
        form = FormService.create_form(
            db,
            title="US-011 idempotent",
            description="one\r\ntwo\r\nthree",
            is_public=False,
            keywords=None,
            business_area_id=None,
            created_by_id=user.id,
        )
        first = form.description
        again = FormService.update_form(
            db,
            form_id=form.id,
            updated_by_id=user.id,
            description=first,  # already \n-normalised
        )
        assert again is not None
        assert again.description == first == "one\ntwo\nthree"


# ===========================================================================
# Frontend static assertions — display path (AC2 / AC3 / AC6 / AC7 / BR-02)
# ===========================================================================

APPS_DIR = Path(__file__).resolve().parents[2]
FRONTEND = APPS_DIR / "frontend"

SHARED_POPUP = FRONTEND / "js" / "shared" / "form-view-popup.js"
FORMS_LIST_VIEW = FRONTEND / "js" / "views" / "forms-list.js"
MAIN_CSS = FRONTEND / "css" / "main.css"


def _read(path: Path) -> str:
    assert path.exists(), f"Missing frontend file: {path}"
    return path.read_text(encoding="utf-8")


def _extract_css_rule(src: str, selector: str) -> str:
    idx = src.index(selector)
    brace = src.index("{", idx)
    end = src.index("}", brace)
    return src[brace + 1 : end]


class TestUS011DisplayPath:
    def test_popup_description_is_escaped_not_raw_html(self):
        """AC2 / AC7 / BR-02 — the popup description is rendered via escapeHtml,
        never as raw HTML."""
        src = _read(SHARED_POPUP)
        assert (
            'form-view-popup__description">${escapeHtml(form.description'
            in src
        ), "US-011 AC2/AC7 — popup description must be escaped (escapeHtml)"

    def test_popup_description_css_preserves_newlines(self):
        """AC1 / AC2 / BR-02 — pre-wrap on the escaped text node visualises
        newlines without any HTML injection path."""
        css = _read(MAIN_CSS)
        assert ".form-view-popup__description" in css, (
            "US-011 — '.form-view-popup__description' CSS rule must exist"
        )
        block = _extract_css_rule(css, ".form-view-popup__description")
        norm = re.sub(r"\s+", " ", block).strip().lower()
        assert "white-space: pre-wrap" in norm, (
            "US-011 AC1 — newlines must render via white-space: pre-wrap"
        )

    def test_no_inner_html_for_description_value(self):
        """AC7 / BR-02 — the description value is never interpolated raw into
        markup; it is only ever output through escapeHtml (a `${form.description}`
        or `${form.description || ...}` raw sink would be an XSS path)."""
        for path in (SHARED_POPUP, FORMS_LIST_VIEW):
            src = _read(path)
            assert "${form.description}" not in src, (
                f"US-011 AC7 — raw ${{form.description}} sink found in {path.name}"
            )
            assert not re.search(r"\$\{\s*form\.description\s*\|\|", src), (
                f"US-011 AC7 — raw ${{form.description || ...}} sink found in "
                f"{path.name} (must go through escapeHtml)"
            )

    def test_approvals_popup_reuses_same_component(self):
        """AC6 — the Approvals queue opens the SAME popup component, so newline
        preservation applies there too."""
        approvals = _read(FRONTEND / "js" / "views" / "approvals.js")
        assert "openFormViewPopup" in approvals, (
            "US-011 AC6 — Approvals must reuse openFormViewPopup so newline "
            "rendering is shared"
        )


class TestUS011PreservesUS010:
    def test_forms_list_description_still_single_line_truncated(self):
        """US-010 preserved — the list description keeps nowrap + ellipsis; the
        pre-wrap change is confined to the popup selector."""
        css = _read(MAIN_CSS)
        block = _extract_css_rule(css, ".forms-list__description")
        norm = re.sub(r"\s+", " ", block).strip().lower()
        assert "white-space: nowrap" in norm, (
            "US-010 regression — list description must remain single-line (nowrap)"
        )
        assert "text-overflow: ellipsis" in norm, (
            "US-010 regression — list description must keep its ellipsis"
        )

    def test_list_description_is_escaped(self):
        """AC7 — the list surface also treats the description as text."""
        src = _read(FORMS_LIST_VIEW)
        assert "escapeHtml(form.description || 'No description')" in src, (
            "US-011 AC7 — list description must be escaped as text"
        )
