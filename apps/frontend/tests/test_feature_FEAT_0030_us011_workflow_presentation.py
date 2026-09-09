"""Source contracts for FEAT-0030 US-011 workflow presentation permissions."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_one_fail_closed_effective_permission_decision_is_shared() -> None:
    auth = _source("js/auth.js")
    forms = _source("js/views/forms-list.js")
    drawer = _source("js/shared/form-details-drawer.js")

    assert "export function canPresentFormWorkflowMetadata()" in auth
    assert "return hasPermission('form:edit');" in auth
    assert "canPresentFormWorkflowMetadata" in forms
    assert "canPresentFormWorkflowMetadata" in drawer
    assert "isStaffViewerOnly" not in forms


def test_no_edit_filter_options_omit_the_complete_workflow_group() -> None:
    forms = _source("js/views/forms-list.js")

    assert "if (!canPresentFormWorkflowMetadata())" in forms
    assert "option => option.category !== 'Workflow State'" in forms
    assert "o.key === 'ws:published'" not in forms


def test_stale_filters_are_pruned_before_request_serialization() -> None:
    forms = _source("js/views/forms-list.js")

    assert "function _removeUnavailableWorkflowFilters()" in forms
    assert "chip.category !== 'Workflow State'" in forms
    assert (
        "const workflowSelectionRemoved = "
        "_removeUnavailableWorkflowFilters();"
    ) in forms
    assert (
        "const requestedPage = workflowSelectionRemoved ? 0 : requestedSkip;"
    ) in forms
    assert forms.index("_removeUnavailableWorkflowFilters();") < forms.index(
        "_selectedFilterChips.forEach(chip =>"
    )


def test_permission_refresh_preserves_unrelated_state() -> None:
    forms = _source("js/views/forms-list.js")

    assert "function _handleFormsAuthorizationRefreshed()" in forms
    assert (
        "window.addEventListener('auth:authorization-refreshed', "
        "_handleFormsAuthorizationRefreshed);"
    ) in forms
    assert (
        "window.addEventListener('auth:authorization-refreshed', "
        "_resetFormsListLifecycle);"
    ) not in forms
    assert "statusElement.remove()" in forms


def test_card_status_markup_is_emitted_only_for_edit_capable_users() -> None:
    forms = _source("js/views/forms-list.js")

    assert (
        "const showWorkflowMetadata = canPresentFormWorkflowMetadata();"
    ) in forms
    assert "${showWorkflowMetadata ? `" in forms
    assert 'class="forms-result-card__status"' in forms


def test_drawer_hides_the_status_term_and_definition_by_default() -> None:
    html = _source("index.html")
    drawer = _source("js/shared/form-details-drawer.js")

    assert '<dt id="formDetailsStatusTerm" hidden>Status</dt>' in html
    assert '<dd id="formDetailsStatusDefinition" hidden>' in html
    assert (
        "const showWorkflowMetadata = canPresentFormWorkflowMetadata();"
    ) in drawer
    assert "elements.statusTerm.hidden = !showWorkflowMetadata;" in drawer
    assert (
        "elements.statusDefinition.hidden = !showWorkflowMetadata;"
    ) in drawer
    assert "elements.status.textContent = showWorkflowMetadata" in drawer
