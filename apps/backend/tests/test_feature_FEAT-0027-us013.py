"""
FEAT-0027 — US-013 (Filter field dropdown opens on click).

Static assertions against the internal ``apps/frontend`` source tree. Mirrors the
FEAT-0027 batch-1 static-regression pattern and the US-012 sibling suite.
No browser is required.

Traceability (TC-US-013):
    AC1 / TC 13.1 — dropdown opens immediately on click (before any keystroke).
    AC2 / TC 13.2 — type-to-filter still narrows the list (same algorithm).
    AC3 / TC 13.3 — Enter / Space / ArrowDown open the closed dropdown.
    AC4 / TC 13.4 — selecting a multi-select chip keeps the dropdown open.
    AC5 / TC 13.5 — selecting a single-select (exclusive) chip closes it.
    AC6 / TC 13.6 — clicking outside the combobox closes the dropdown.
    AC7 / TC 13.7 — re-clicking the input reopens the dropdown.
    AC8 / TC 13.8 — ARIA combobox pattern incl. aria-activedescendant + groups.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APPS_DIR = Path(__file__).resolve().parents[2]
FRONTEND = APPS_DIR / "frontend"

FORMS_LIST_VIEW = FRONTEND / "js" / "views" / "forms-list.js"
INDEX_HTML = FRONTEND / "index.html"


def _read(path: Path) -> str:
    assert path.exists(), f"Missing frontend file: {path}"
    return path.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str:
    """Return the body of a ``function <name>(...) { ... }`` block."""
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
# AC1 / TC 13.1 — dropdown opens on click, before any keystroke
# ===========================================================================


class TestUS013OpensOnClick:
    def test_input_has_a_click_handler_that_opens_the_dropdown(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_initFilterCombobox")
        assert "input.addEventListener('click'" in fn, (
            "US-013 AC1 — the filter input must open its dropdown on click, "
            "independently of the focus handler"
        )
        assert "_openFilterDropdown()" in fn, "US-013 AC1 — click must call the open helper"

    def test_open_helper_renders_from_current_value_and_shows_dropdown(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_openFilterDropdown")
        assert "_renderFilterDropdown((input?.value || '').trim().toLowerCase())" in fn, (
            "US-013 AC1 — open must render the option list from the current input value"
        )
        assert "_setFilterDropdownVisible(true)" in fn


# ===========================================================================
# AC2 / TC 13.2 — type-to-filter still narrows the list (unchanged algorithm)
# ===========================================================================


class TestUS013TypeToFilterPreserved:
    def test_input_event_still_renders_the_filtered_dropdown(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_initFilterCombobox")
        assert "input.addEventListener('input'" in fn
        assert "_renderFilterDropdown(input.value.trim().toLowerCase())" in fn

    def test_matching_algorithm_is_unchanged(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFilterDropdown")
        assert "query && !opt.label.toLowerCase().includes(query)" in fn, (
            "US-013 AC2 / BR-02 — the case-insensitive substring match must not "
            "be regressed"
        )
        assert "selectedKeys.has(opt.key)" in fn, (
            "US-013 BR-01 — already-selected chips remain excluded from the list"
        )


# ===========================================================================
# AC3 / TC 13.3 — Enter / Space / ArrowDown open the closed dropdown
# ===========================================================================


class TestUS013KeyboardOpen:
    def test_keydown_opens_on_arrow_enter_and_space(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_initFilterCombobox")
        assert "e.key === 'ArrowDown'" in fn
        assert "e.key === 'ArrowUp'" in fn
        assert "e.key === 'Enter'" in fn
        assert "e.key === ' '" in fn
        assert "if (!isOpen) _openFilterDropdown();" in fn, (
            "US-013 AC3 — Arrow keys open the dropdown when it is closed"
        )
        assert fn.count("_openFilterDropdown()") >= 3, (
            "US-013 AC3 — Enter and Space must also open the closed dropdown"
        )

    def test_arrow_navigation_uses_active_descendant_helper(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_initFilterCombobox")
        assert "_moveFilterActiveOption(1)" in fn
        assert "_moveFilterActiveOption(-1)" in fn

    def test_enter_applies_the_highlighted_option_when_open(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_initFilterCombobox")
        assert "li[role=\"option\"].active" in fn, (
            "US-013 AC3 — Enter must resolve the highlighted option"
        )
        assert "_FILTER_OPTIONS.find(o => o.key === active.dataset.key)" in fn
        assert "_addFilterChip(opt)" in fn


# ===========================================================================
# AC4 / AC5 — multi-select keeps open, single-select closes
# ===========================================================================


class TestUS013SelectionOpenCloseSemantics:
    def test_multi_select_keeps_the_dropdown_open(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_addFilterChip")
        assert "if (opt.exclusive) {" in fn, (
            "US-013 AC4/AC5 — the open/close decision must branch on exclusivity"
        )
        assert "_setFilterDropdownVisible(true)" in fn, (
            "US-013 AC4 — a multi-select chip must leave the dropdown open"
        )

    def test_single_select_closes_the_dropdown(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_addFilterChip")
        assert "_closeFilterDropdown();" in fn, (
            "US-013 AC5 — an exclusive chip must close the dropdown"
        )

    def test_mutual_exclusivity_toast_preserved(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_addFilterChip")
        assert "showNotification(" in fn, (
            "US-013 AC5 — the existing mutual-exclusion toast must be preserved"
        )

    def test_option_click_stops_propagation_to_keep_multiselect_open(self):
        # Regression: _addFilterChip re-renders the dropdown, which detaches the
        # clicked <li>. If the click reaches the document click-outside handler,
        # `e.target.closest('#filterCombobox')` is null (detached node) and a
        # multi-select (AC4) dropdown is wrongly closed. The option handler must
        # stop propagation so the outside-close guard never fires on selection.
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFilterDropdown")
        assert "e.stopPropagation();" in fn, (
            "US-013 AC4 — option click must stopPropagation so the document "
            "click-outside handler cannot close a multi-select dropdown"
        )


# ===========================================================================
# AC6 / TC 13.6 — clicking outside the combobox closes the dropdown
# ===========================================================================


class TestUS013ClickOutsideCloses:
    def test_document_click_outside_combobox_closes(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_initFilterCombobox")
        assert "e.target.closest('#filterCombobox')" in fn, (
            "US-013 AC6 — a click outside the combobox must close the dropdown"
        )
        assert "_closeFilterDropdown();" in fn


# ===========================================================================
# AC7 / TC 13.7 — re-clicking the input reopens the dropdown
# ===========================================================================


class TestUS013ReopenOnClick:
    def test_click_handler_is_independent_of_focus(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_initFilterCombobox")
        assert "input.addEventListener('click'" in fn
        assert "input.addEventListener('focus'" in fn


# ===========================================================================
# AC8 / TC 13.8 — ARIA combobox pattern incl. aria-activedescendant + groups
# ===========================================================================


class TestUS013AriaComboboxPattern:
    def test_index_html_declares_the_combobox_role_and_controls(self):
        html = _read(INDEX_HTML)
        marker = html[html.index('id="filterComboboxInput"'):]
        marker = marker[: marker.index(">") + 1]
        assert 'role="combobox"' in marker, "US-013 AC8 — role=combobox required"
        assert 'aria-expanded="false"' in marker, "US-013 AC8 — initial aria-expanded"
        assert 'aria-controls="filterComboboxDropdown"' in marker, (
            "US-013 AC8 — aria-controls must point at the listbox"
        )
        assert 'aria-haspopup="listbox"' in marker
        assert 'aria-autocomplete="list"' in marker
        assert 'role="listbox"' in html, "US-013 AC8 — the popup must be a listbox"

    def test_category_headers_are_non_selectable_presentation(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFilterDropdown")
        assert "header.setAttribute('role', 'presentation')" in fn, (
            "US-013 AC8 — category headers must be presentational, not options"
        )

    def test_visibility_helper_toggles_aria_expanded(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_setFilterDropdownVisible")
        assert "input.setAttribute('aria-expanded', String(visible))" in fn, (
            "US-013 AC8 — aria-expanded must reflect the open/closed state"
        )
        assert "_clearFilterActiveOption()" in fn, (
            "US-013 AC8 — the active descendant must be cleared when closing"
        )

    def test_options_carry_ids_key_role_and_selected_state(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_renderFilterDropdown")
        assert "li.id = `filterCombobox-option-${optionIndex++}`" in fn, (
            "US-013 AC8 — each option needs a stable id for aria-activedescendant"
        )
        assert "li.setAttribute('role', 'option')" in fn
        assert "li.setAttribute('aria-selected', 'false')" in fn
        assert "li.dataset.key = opt.key" in fn

    def test_active_option_sets_aria_activedescendant(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_setFilterActiveOption")
        assert "input.setAttribute('aria-activedescendant', li.id)" in fn, (
            "US-013 AC8 — highlighting an option must update aria-activedescendant"
        )
        assert "li.setAttribute('aria-selected', 'true')" in fn

    def test_clear_active_removes_aria_activedescendant(self):
        fn = _extract_function(_read(FORMS_LIST_VIEW), "_clearFilterActiveOption")
        assert "input.removeAttribute('aria-activedescendant')" in fn


# ===========================================================================
# BR-01 — the Business Area filter (US-012) is a separate control
# ===========================================================================


class TestUS013ScopeGuard:
    def test_business_area_filter_is_a_distinct_combobox(self):
        src = _read(FORMS_LIST_VIEW)
        assert "initFilterBusinessAreaCombobox" in src
        assert "_initFilterCombobox()" in src
