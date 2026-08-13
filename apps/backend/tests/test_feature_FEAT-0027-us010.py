"""
FEAT-0027 — US-010 (Forms list description truncated to a single line + ellipsis).

Static assertions against the internal `apps/frontend` source tree. Mirrors the
FEAT-0027 batch-1 static-regression pattern established for US-001..US-009.
No browser is required.

Traceability (TC-US-010):
    AC1 — description truncates to a single line via CSS (nowrap/overflow/ellipsis).
    AC2 — consistent card sizing: truncation caps the description at one line so
          cards do not grow with description length.
    AC4 — short descriptions are not degraded (no forced ellipsis rendering; the
          same truncation rule applies uniformly and shows no ellipsis when text
          fits).
    AC5 — ellipsis indicator present (text-overflow: ellipsis).
    AC7 — accessibility: full description available to assistive tech via `title`.
    BR-01 — display-only: the full description is still passed to the popup and is
          not truncated at the data layer.
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
MAIN_CSS = FRONTEND / "css" / "main.css"


def _read(path: Path) -> str:
    assert path.exists(), f"Missing frontend file: {path}"
    return path.read_text(encoding="utf-8")


def _extract_css_rule(src: str, selector: str) -> str:
    """Return the declaration block for a `.selector { ... }` rule."""
    idx = src.index(selector)
    brace = src.index("{", idx)
    end = src.index("}", brace)
    return src[brace + 1 : end]


# ===========================================================================
# AC1 / AC5 — single-line truncation with a visible ellipsis via CSS
# ===========================================================================


class TestUS010DescriptionTruncationCss:
    def test_description_paragraph_carries_the_truncation_class(self):
        """AC1 — the Forms-list description <p> must carry the truncation hook."""
        src = _read(FORMS_LIST_VIEW)
        assert "card-text text-muted mt-2 forms-list__description" in src, (
            "US-010 AC1 — description <p> must include the "
            "'forms-list__description' class"
        )

    def test_css_rule_exists_with_single_line_truncation(self):
        """AC1 / AC5 — the CSS rule applies nowrap + overflow hidden + ellipsis."""
        css = _read(MAIN_CSS)
        assert ".forms-list__description" in css, (
            "US-010 — '.forms-list__description' CSS rule must exist"
        )
        block = _extract_css_rule(css, ".forms-list__description")
        norm = re.sub(r"\s+", " ", block).strip().lower()
        assert "white-space: nowrap" in norm, (
            "US-010 AC1 — description must not wrap (white-space: nowrap)"
        )
        assert "overflow: hidden" in norm, (
            "US-010 AC1 — overflowing description must be clipped (overflow: hidden)"
        )
        assert "text-overflow: ellipsis" in norm, (
            "US-010 AC5 — truncated description must show an ellipsis "
            "(text-overflow: ellipsis)"
        )

    def test_css_rule_constrains_width_for_ellipsis(self):
        """AC2 — the description is bounded so text-overflow can engage and card
        height stays fixed at one line."""
        css = _read(MAIN_CSS)
        block = _extract_css_rule(css, ".forms-list__description")
        norm = re.sub(r"\s+", " ", block).strip().lower()
        assert "max-width: 100%" in norm, (
            "US-010 AC2 — description must be width-bounded (max-width: 100%)"
        )


# ===========================================================================
# AC7 — accessibility: full description exposed to assistive tech via title
# ===========================================================================


class TestUS010Accessibility:
    def test_full_description_exposed_via_title_attribute(self):
        """AC7 — when a description exists, the full (escaped) text is placed on a
        title attribute so it is not lost to assistive tech after truncation."""
        src = _read(FORMS_LIST_VIEW)
        assert (
            'form.description ? ` title="${escapeHtml(form.description)}"` : \'\''
            in src
        ), (
            "US-010 AC7 — full description must be exposed via a title attribute "
            "(escaped) when present"
        )

    def test_title_attribute_is_conditional_on_presence(self):
        """AC4 / empty-description edge case — no title is emitted when there is no
        description, so an empty card is not degraded with an empty tooltip."""
        src = _read(FORMS_LIST_VIEW)
        # The ternary must guard the title so absent descriptions emit no attribute.
        assert re.search(
            r"forms-list__description\"\$\{form\.description \? ` title=",
            src,
        ), "US-010 AC4 — title attribute must be conditional on form.description"


# ===========================================================================
# BR-01 — display-only: full description still flows to the View Details popup
# ===========================================================================


class TestUS010DisplayOnly:
    def test_description_text_is_not_truncated_at_data_layer(self):
        """BR-01 — the card still renders the full escaped description as its text
        content; truncation is purely visual (CSS), never a substring/slice."""
        src = _read(FORMS_LIST_VIEW)
        # The visible text node uses the whole description, not a JS-side slice.
        assert "${escapeHtml(form.description || 'No description')}</p>" in src, (
            "US-010 BR-01 — description text content must remain the full value; "
            "truncation must be CSS-only, not a data-layer slice"
        )
        assert ".slice(" not in _extract_description_line(src), (
            "US-010 BR-01 — description must not be sliced/substringed on the card"
        )


def _extract_description_line(src: str) -> str:
    for line in src.splitlines():
        if "forms-list__description" in line:
            return line
    raise AssertionError("US-010 — description line not found in forms-list.js")
