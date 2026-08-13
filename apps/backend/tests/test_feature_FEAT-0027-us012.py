"""
FEAT-0027 — US-012 (Business Area filter dropdown opens on click).

Static assertions against the internal ``apps/frontend`` source tree. Mirrors the
FEAT-0027 batch-1 static-regression pattern established for US-001..US-011.
No browser is required.

Traceability (TC-US-012):
    AC1 / TC 12.1 — dropdown opens immediately on click (before any keystroke).
    AC2 / TC 12.2 — type-to-filter still narrows the list (same algorithm).
    AC3 / TC 12.3 — Enter / Space / ArrowDown open the closed dropdown.
    AC4 / TC 12.4 — selecting an option closes the dropdown.
    AC5 / TC 12.5 — clicking outside the combobox closes the dropdown.
    AC6 / TC 12.6 — re-clicking the input reopens the dropdown.
    AC7 / TC 12.7 — ARIA combobox pattern incl. aria-activedescendant.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APPS_DIR = Path(__file__).resolve().parents[2]
FRONTEND = APPS_DIR / "frontend"

BUSINESS_AREAS_VIEW = FRONTEND / "js" / "views" / "business-areas.js"
INDEX_HTML = FRONTEND / "index.html"


def _read(path: Path) -> str:
    assert path.exists(), f"Missing frontend file: {path}"
    return path.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str:
    """Return the body of a ``function <name>(...) { ... }`` block.

    Matches both ``function name(`` and ``export function name(`` because the
    search token is a substring of both.
    """
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
# AC1 / TC 12.1 — dropdown opens on click, before any keystroke
# ===========================================================================


class TestUS012OpensOnClick:
    def test_input_has_a_click_handler_that_opens_the_dropdown(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "initFilterBusinessAreaCombobox")
        assert "input.addEventListener('click'" in fn, (
            "US-012 AC1 — the filter input must open its dropdown on click, "
            "independently of the focus handler"
        )
        assert "_openFilterBusinessAreaDropdown()" in fn, (
            "US-012 AC1 — click must call the open helper"
        )

    def test_open_helper_renders_unfiltered_and_makes_dropdown_visible(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "_openFilterBusinessAreaDropdown")
        # Opens with the current (possibly empty) query so all options show
        # when nothing has been typed yet (AC1 — unfiltered on open).
        assert "renderFilterBusinessAreaDropdown((input?.value || '').toLowerCase())" in fn, (
            "US-012 AC1 — open must render the option list from the current input value"
        )
        assert "_setFilterBusinessAreaDropdownVisible(true)" in fn, (
            "US-012 AC1 — open must make the dropdown visible"
        )


# ===========================================================================
# AC2 / TC 12.2 — type-to-filter still narrows the list (unchanged algorithm)
# ===========================================================================


class TestUS012TypeToFilterPreserved:
    def test_input_event_still_renders_the_filtered_dropdown(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "initFilterBusinessAreaCombobox")
        assert "input.addEventListener('input'" in fn, (
            "US-012 AC2 / BR-02 — typing must keep re-rendering the dropdown"
        )
        assert "renderFilterBusinessAreaDropdown(input.value.toLowerCase())" in fn

    def test_matching_algorithm_is_unchanged(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "renderFilterBusinessAreaDropdown")
        assert "o.label.toLowerCase().includes(query)" in fn, (
            "US-012 AC2 / BR-02 — the case-insensitive substring match must not "
            "be regressed"
        )
        assert "!_selectedBusinessAreaFilters.includes(o.id)" in fn, (
            "US-012 BR-01 — already-selected areas remain excluded from the list"
        )


# ===========================================================================
# AC3 / TC 12.3 — Enter / Space / ArrowDown open the closed dropdown
# ===========================================================================


class TestUS012KeyboardOpen:
    def test_keydown_opens_on_arrow_enter_and_space(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "initFilterBusinessAreaCombobox")
        assert "e.key === 'ArrowDown'" in fn
        assert "e.key === 'ArrowUp'" in fn
        assert "e.key === 'Enter'" in fn
        assert "e.key === ' '" in fn
        # Each opening branch guards on the closed state and calls the open helper.
        assert "if (!isOpen) _openFilterBusinessAreaDropdown();" in fn, (
            "US-012 AC3 — Arrow keys open the dropdown when it is closed"
        )
        assert fn.count("_openFilterBusinessAreaDropdown()") >= 3, (
            "US-012 AC3 — Enter and Space must also open the closed dropdown"
        )

    def test_arrow_navigation_uses_active_descendant_helper(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "initFilterBusinessAreaCombobox")
        assert "_moveFilterActiveOption(1)" in fn
        assert "_moveFilterActiveOption(-1)" in fn

    def test_enter_applies_the_highlighted_option_when_open(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "initFilterBusinessAreaCombobox")
        assert "li[role=\"option\"].active" in fn, (
            "US-012 AC3/AC4 — Enter must resolve the highlighted option"
        )
        assert "addBusinessAreaFilter(active.dataset.id)" in fn


# ===========================================================================
# AC4 / TC 12.4 — selecting an option closes the dropdown
# ===========================================================================


class TestUS012SelectionCloses:
    def test_add_filter_closes_the_dropdown(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "addBusinessAreaFilter")
        assert "closeFilterBusinessAreaDropdown()" in fn, (
            "US-012 AC4 — applying a filter must close the dropdown"
        )

    def test_close_sets_aria_expanded_false(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "_setFilterBusinessAreaDropdownVisible")
        assert "aria-expanded" in fn and "String(visible)" in fn, (
            "US-012 AC4 — closing must reflect aria-expanded=\"false\""
        )


# ===========================================================================
# AC5 / TC 12.5 — clicking outside the combobox closes the dropdown
# ===========================================================================


class TestUS012ClickOutsideCloses:
    def test_document_click_outside_combobox_closes(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "initFilterBusinessAreaCombobox")
        assert "e.target.closest('#filterBusinessAreaCombobox')" in fn, (
            "US-012 AC5 — a click outside the combobox must close the dropdown"
        )
        assert "closeFilterBusinessAreaDropdown();" in fn


# ===========================================================================
# AC6 / TC 12.6 — re-clicking the input reopens the dropdown
# ===========================================================================


class TestUS012ReopenOnClick:
    def test_click_handler_is_independent_of_focus(self):
        """A dedicated click handler reopens the dropdown even when the input
        already holds focus (e.g. after Escape), which a focus-only handler
        would miss."""
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "initFilterBusinessAreaCombobox")
        assert "input.addEventListener('click'" in fn
        assert "input.addEventListener('focus'" in fn


# ===========================================================================
# AC7 / TC 12.7 — ARIA combobox pattern incl. aria-activedescendant
# ===========================================================================


class TestUS012AriaComboboxPattern:
    def test_index_html_declares_the_combobox_role_and_controls(self):
        html = _read(INDEX_HTML)
        # The filter input carries the editable-combobox ARIA contract.
        marker = html[html.index('id="filterBusinessAreaInput"'):]
        marker = marker[: marker.index(">") + 1]
        assert 'role="combobox"' in marker, "US-012 AC7 — role=combobox required"
        assert 'aria-expanded="false"' in marker, "US-012 AC7 — initial aria-expanded"
        assert 'aria-controls="filterBusinessAreaDropdown"' in marker, (
            "US-012 AC7 — aria-controls must point at the listbox"
        )
        assert 'aria-haspopup="listbox"' in marker
        assert 'aria-autocomplete="list"' in marker
        assert 'role="listbox"' in html, "US-012 AC7 — the popup must be a listbox"

    def test_visibility_helper_toggles_aria_expanded(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "_setFilterBusinessAreaDropdownVisible")
        assert "input.setAttribute('aria-expanded', String(visible))" in fn, (
            "US-012 AC7 — aria-expanded must reflect the open/closed state"
        )
        assert "_clearFilterActiveOption()" in fn, (
            "US-012 AC7 — the active descendant must be cleared when closing"
        )

    def test_options_carry_ids_role_and_selected_state(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "renderFilterBusinessAreaDropdown")
        assert "li.id = `filterBusinessArea-option-${index}`" in fn, (
            "US-012 AC7 — each option needs a stable id for aria-activedescendant"
        )
        assert "li.setAttribute('role', 'option')" in fn
        assert "li.setAttribute('aria-selected', 'false')" in fn

    def test_active_option_sets_aria_activedescendant(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "_setFilterActiveOption")
        assert "input.setAttribute('aria-activedescendant', li.id)" in fn, (
            "US-012 AC7 — highlighting an option must update aria-activedescendant"
        )
        assert "li.setAttribute('aria-selected', 'true')" in fn

    def test_clear_active_removes_aria_activedescendant(self):
        fn = _extract_function(_read(BUSINESS_AREAS_VIEW), "_clearFilterActiveOption")
        assert "input.removeAttribute('aria-activedescendant')" in fn


# ===========================================================================
# BR-01 — interaction-only change: the form-modal combobox is untouched
# ===========================================================================


class TestUS012ScopeGuard:
    def test_form_modal_combobox_still_uses_its_own_init(self):
        """The form combobox (initBusinessAreaCombobox) is a separate control and
        must not be affected by this filter-only change."""
        src = _read(BUSINESS_AREAS_VIEW)
        assert "export function initBusinessAreaCombobox(" in src
        assert "export function initFilterBusinessAreaCombobox(" in src
