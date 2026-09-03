"""Contract coverage for FEAT-0030 US-004 Forms library controls."""

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_denied_route_invalidates_previously_rendered_forms_data():
    router_js = _source("js/router.js")
    forms_list_js = _source("js/views/forms-list.js")
    operational_guard = "if (isAuthenticated() && " "!_canAccessOperationalRoute(path))"

    denied_guard = router_js.split(operational_guard, maxsplit=1)[1].split(
        "// ── Admin guard", maxsplit=1
    )[0]

    assert "app:route-changing" in denied_guard
    assert "path: 'denied'" in denied_guard
    assert "window.addEventListener('app:route-changing'" in forms_list_js
    assert "_resetFormsListLifecycle();" in forms_list_js
    assert "list.replaceChildren();" in forms_list_js
    assert "_updateResultsSummary(0);" in forms_list_js
    assert "paginationContainer.hidden = true" in forms_list_js
    assert "paginationSummary.textContent = " "'Showing 0-0 of 0'" in forms_list_js


def test_forms_responses_are_bounded_and_attribute_values_are_encoded():
    forms_list_js = _source("js/views/forms-list.js")

    assert "function _normalizeFormItem(item)" in forms_list_js
    assert ".map(_normalizeFormItem)" in forms_list_js
    assert "MAX_FORM_DESCRIPTION_LENGTH" in forms_list_js
    assert "MAX_FORM_URL_LENGTH" in forms_list_js
    assert "function _escapeAttribute(value)" in forms_list_js
    assert "&quot;" in forms_list_js
    assert "&#39;" in forms_list_js
    assert "ALLOWED_PAGE_SIZES.has(requestedLimit)" in forms_list_js


def test_business_areas_and_autocomplete_have_canonical_dismissible_state():
    html = _source("index.html")
    forms_list_js = _source("js/views/forms-list.js")
    business_areas_js = _source("js/views/business-areas.js")

    suggestions_markup = (
        'id="searchSuggestions" ' 'class="dropdown-menu forms-search-suggestions"'
    )

    assert suggestions_markup in html
    assert 'role="listbox" hidden' in html
    assert "const areasById = new Map();" in business_areas_js
    assert "if (!areasById.has(area.id))" in business_areas_js
    assert "function _dismissSearchSuggestions()" in forms_list_js
    assert "_autocompleteRequestController?.abort();" in forms_list_js
    assert (
        "document.activeElement !== document.getElementById('searchInput')"
        in forms_list_js
    )
    assert "e.key === 'Tab'" in forms_list_js
    assert "addEventListener('focusout'" in forms_list_js
    assert "signal.aborted || error.name === 'AbortError'" in forms_list_js
    assert "signal.aborted || error.name === " "'AbortError'" in business_areas_js


def test_removed_business_area_selections_reload_canonical_results():
    forms_list_js = _source("js/views/forms-list.js")
    business_areas_js = _source("js/views/business-areas.js")

    assert "let _formsLifecycleGeneration = 0;" in forms_list_js
    assert "_formsLifecycleGeneration += 1;" in forms_list_js
    assert (
        "lifecycleGeneration !== _formsLifecycleGeneration || !loaded" in forms_list_js
    )
    assert "selectedAreaIdsBeforeLoad" in forms_list_js
    assert "const selectionChanged" in forms_list_js
    assert "if (selectionChanged) loadForms();" in forms_list_js
    load_function = business_areas_js.split(
        "export async function loadBusinessAreas()", maxsplit=1
    )[1].split("// ── Form combobox", maxsplit=1)[0]
    invalid_nonempty_guard = (
        "areas.length > 0 && normalizedAreas.length === 0"
    )
    assert "_businessAreaOptions = [];" not in load_function
    assert "if (!Array.isArray(payload))" in load_function
    assert invalid_nonempty_guard in load_function
