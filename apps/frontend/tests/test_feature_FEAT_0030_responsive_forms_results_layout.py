"""Source-contract coverage for FEAT-0030 US-005 Forms results layout."""

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_results_use_semantic_ordered_cards_and_functional_density_controls():
    html = _source("index.html")
    list_view = html.split('<div id="listView"', maxsplit=1)[1].split(
        '<div id="createView"', maxsplit=1
    )[0]

    assert '<ol id="formsList" class="forms-results-list"' in list_view
    assert 'data-density-view="list" aria-pressed="true"' in list_view
    assert 'data-density-view="grid" aria-pressed="false"' in list_view
    assert 'aria-disabled="true"' not in list_view
    assert 'aria-label="Grid view"' in list_view


def test_normalized_results_retain_approved_metadata():
    forms_js = _source("js/views/forms-list.js")

    assert "business_area: businessArea" in forms_js
    assert "name: _boundedString(businessArea.name" in forms_js
    assert "updated_at: _boundedString(item.updated_at" in forms_js
    assert "form.business_area?.name" in forms_js
    assert "_formatUpdatedDate(form.updated_at)" in forms_js
    assert "Created:" not in forms_js


def test_cards_preserve_existing_source_and_workflow_handlers():
    forms_js = _source("js/views/forms-list.js")

    assert "_renderFormSourceType(form)" in forms_js
    assert "_renderFormSourceButton(form)" in forms_js
    assert "_renderFormActionButtons(form)" in forms_js
    assert 'data-action="view-form"' in forms_js
    assert "openFormDetailsDrawer" in forms_js
    assert "downloadFormAttachment" in forms_js
    assert "_isSafeHttpUrl" in forms_js
    assert "Open details for form ${_escapeAttribute(" in forms_js
    assert "from form number" in forms_js


def test_details_drawer_rejects_unsafe_external_source_urls():
    drawer_js = _source("js/shared/form-details-drawer.js")
    guarded_url_branch = (
        "form.form_source === 'URL' && "
        "_isSafeHttpUrl(form.form_source_url)"
    )
    assert guarded_url_branch in drawer_js
    assert "function _isSafeHttpUrl(value)" in drawer_js
    assert "url.protocol === 'http:'" in drawer_js
    assert "url.protocol === 'https:'" in drawer_js
    assert "link.href = form.form_source_url.trim()" in drawer_js
    assert "link.rel = 'noopener noreferrer'" in drawer_js


def test_list_view_shim_awaits_preference_restoration():
    list_js = _source("js/views/list.js")

    assert "export async function showListView()" in list_js
    assert "await showFormsListView();" in list_js


def test_action_visibility_remains_fail_closed_and_state_aware():
    forms_js = _source("js/views/forms-list.js")
    fail_closed_guard = (
        "if (!isKnownStatus || !user || "
        "!Array.isArray(user.permissions))"
    )

    assert "FORM_WORKFLOW_STATES.has(status)" in forms_js
    assert fail_closed_guard in forms_js
    assert "status === 'draft' && isOwner" in forms_js
    assert "status === 'published'" in forms_js
    assert "hasPermission('form:archive')" in forms_js
    assert "status === 'archived'" in forms_js
    assert "hasPermission('form:approve')" in forms_js
    assert "status === 'draft' && hasPermission('form:delete')" in forms_js
    assert 'aria-label="Edit form ${formLabel}"' in forms_js
    assert 'aria-label="Delete form ${formLabel}"' in forms_js


def test_layout_preference_is_per_user_bounded_and_storage_safe():
    forms_js = _source("js/views/forms-list.js")
    preference_generation = "++_layoutPreferenceGeneration"
    current_preference = (
        "generation === _layoutPreferenceGeneration && storageKey"
    )

    assert "RESULTS_LAYOUT_STORAGE_PREFIX" in forms_js
    assert "crypto.subtle.digest('SHA-256'" in forms_js
    assert "localStorage.getItem(storageKey)" in forms_js
    assert "localStorage.setItem(storageKey, layout)" in forms_js
    assert "RESULTS_LAYOUTS.has" in forms_js
    assert preference_generation in forms_js
    assert current_preference in forms_js
    assert "catch (_error)" in forms_js
    assert "user.email" not in forms_js
    assert "user.name" not in forms_js


def test_results_layout_css_covers_list_grid_mobile_and_focus():
    css = _source("css/main.css")

    assert ".forms-results-list" in css
    assert '.forms-results-list[data-layout="grid"]' in css
    assert ".forms-result-card" in css
    assert ".forms-result-card__business-area" in css
    assert ".forms-result-card__status" in css
    assert "@media (max-width: 620px)" in css
    assert "grid-template-columns: 1fr;" in css
    assert ".forms-density-control" in css
    assert ".forms-result-card a:focus-visible" in css
    assert (
        '.forms-results-list[data-layout="grid"] .forms-list__source-btn'
        in css
    )
    assert "@media (min-width: 768px) and (max-width: 991.98px)" in css
    assert "overflow-wrap: anywhere;" in css


def test_grid_metadata_and_non_card_states_follow_mockup_alignment():
    css = _source("css/main.css")

    assert (
        '.forms-results-list[data-layout="grid"] '
        ".forms-result-card__number"
        in css
    )
    assert "grid-row: 1;" in css
    assert "align-items: start;" in css
    assert "justify-self: start;" in css
    assert "text-align: left;" in css
    assert (
        '.forms-results-list[data-layout="grid"] > .empty-state'
        in css
    )
    assert (
        '.forms-results-list[data-layout="grid"] > .spinner-container'
        in css
    )
    assert "grid-column: 1 / -1;" in css


def test_results_loading_and_view_lifecycle_remain_semantic_and_stale_safe():
    forms_js = _source("js/views/forms-list.js")
    lifecycle_guard = (
        "if (lifecycleGeneration !== "
        "_formsLifecycleGeneration) return;"
    )

    assert '<li class="spinner-container">' in forms_js
    assert "showSpinner('#formsList'" not in forms_js
    assert "lifecycleGeneration = _formsLifecycleGeneration" in forms_js
    assert lifecycle_guard in forms_js
