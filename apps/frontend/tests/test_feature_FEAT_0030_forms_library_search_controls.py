"""Source-contract coverage for FEAT-0030 US-004 Forms library controls."""

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_forms_library_uses_approved_control_composition():
    html = _source("index.html")
    list_view = html.split('<div id="listView"', maxsplit=1)[1].split(
        '<div id="createView"', maxsplit=1
    )[0]

    assert "Forms library" in list_view
    assert "Search for forms and view their current details." in list_view
    assert 'class="forms-command-bar"' in list_view
    assert 'id="searchInput"' in list_view
    assert 'id="clearSearchButton"' in list_view
    assert 'id="filtersButton"' in list_view
    assert 'id="filtersMenu"' in list_view
    assert 'id="activeFilters"' in list_view
    assert 'id="resultsSummary"' in list_view
    assert 'id="pageSizeSelect"' in list_view
    assert 'id="sortOrder"' in list_view
    assert 'data-action="search-forms"' not in list_view
    assert 'id="filterComboboxInput"' not in list_view
    assert 'id="filterBusinessAreaInput"' not in list_view


def test_filters_menu_and_chips_use_safe_dynamic_dom_construction():
    forms_js = _source("js/views/forms-list.js")

    assert "getBusinessAreaOptions" in forms_js
    assert "function _renderFiltersMenu()" in forms_js
    assert "document.createElement('input')" in forms_js
    assert "checkbox.type = 'checkbox'" in forms_js
    assert "document.createTextNode(option.label)" in forms_js
    assert "function _renderActiveFilters()" in forms_js
    assert "removeButton.dataset.filterKey" in forms_js
    assert "removeButton.setAttribute('aria-label'" in forms_js
    assert "getElementById('selectedFilterChips')" not in forms_js
    assert "initFilterBusinessAreaCombobox" not in forms_js


def test_existing_query_sort_and_page_size_contract_is_preserved():
    forms_js = _source("js/views/forms-list.js")
    html = _source("index.html")

    assert "params.set('q', query)" in forms_js
    assert "params.append('business_area_ids', id)" in forms_js
    assert "params.append(opt.apiParam, opt.apiValue)" in forms_js
    assert "params.set('sort_field', sortField)" in forms_js
    assert "params.set('sort_order', sortDir)" in forms_js
    for value in ("24", "48", "96"):
        assert f'<option value="{value}"' in html
    for value in (
        "created_at:desc",
        "created_at:asc",
        "form_number:asc",
        "form_number:desc",
    ):
        assert f'<option value="{value}"' in html


def test_search_clear_and_latest_request_guards_are_wired():
    forms_js = _source("js/views/forms-list.js")

    assert "let _formsRequestController = null;" in forms_js
    assert "let _autocompleteRequestController = null;" in forms_js
    assert "_formsRequestController?.abort();" in forms_js
    assert "_autocompleteRequestController?.abort();" in forms_js
    assert "clearTimeout(_autocompleteDebounceTimer);" in forms_js
    assert "if (_isDismissingSearchSuggestions) return;" in forms_js
    assert 'data-action="clear-search"' not in forms_js
    assert "clearSearchButton" in forms_js
    assert "input.focus()" in forms_js
    assert "_currentSkip = 0;" in forms_js


def test_staff_viewer_filters_and_route_guard_remain_deny_by_default():
    forms_js = _source("js/views/forms-list.js")
    router_js = _source("js/router.js")
    staff_viewer_filter = (
        "o.category !== 'Workflow State' || "
        "o.key === 'ws:published'"
    )

    assert staff_viewer_filter in forms_js
    assert "if (path === ROUTES.FORMS_LIST)" in router_js
    assert "path === ROUTES.HOME || path === ROUTES.FORMS_LIST" in router_js
    assert "return hasPermission('form:read');" in router_js


def test_density_controls_are_present_for_us_005_activation():
    html = _source("index.html")

    assert html.count('data-density-view="list"') == 1
    assert html.count('data-density-view="grid"') == 1
    assert 'data-density-view="list" aria-pressed="true"' in html
    assert 'data-density-view="grid" aria-pressed="false"' in html


def test_obsolete_list_business_area_filter_code_is_removed():
    areas_js = _source("js/views/business-areas.js")

    assert "getBusinessAreaOptions" in areas_js
    assert "initFilterBusinessAreaCombobox" not in areas_js
    assert "filterBusinessAreaInput" not in areas_js
    assert "selectedBusinessAreaFilters" not in areas_js


def test_create_edit_business_area_combobox_exports_remain_available():
    areas_js = _source("js/views/business-areas.js")
    create_js = _source("js/views/forms-create.js")

    assert "export function selectBusinessArea(" in areas_js
    assert "export function closeBusinessAreaDropdown(" in areas_js
    assert "closeBusinessAreaDropdown" in create_js


def test_forms_state_is_invalidated_on_route_and_auth_changes():
    forms_js = _source("js/views/forms-list.js")

    assert "function _resetFormsListLifecycle()" in forms_js
    assert "window.addEventListener('app:route-changing'" in forms_js
    assert "window.addEventListener('auth:session-expired'" in forms_js
    assert "window.addEventListener('auth:session-started'" in forms_js
    assert "window.addEventListener('auth:session-cleared'" in forms_js
    assert "_selectedFilterChips = [];" in forms_js
    assert "_selectedBusinessAreaIds = [];" in forms_js


def test_forms_library_css_covers_responsive_and_focus_states():
    css = _source("css/main.css")

    assert ".forms-library" in css
    assert ".forms-command-bar" in css
    assert ".forms-filter-menu" in css
    assert ".forms-active-filters" in css
    assert ".forms-results-bar" in css
    assert ".forms-density-button:focus-visible" in css
    assert ".forms-search-suggestions:not([hidden])" in css
    assert "@media (max-width: 767.98px)" in css
    assert "@media (max-width: 575.98px)" in css
