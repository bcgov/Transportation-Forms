"""US-006 source contracts only; these do not execute JS or browser behavior."""

from pathlib import Path
import re

FRONTEND = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND / relative_path).read_text(encoding="utf-8")


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    position = opening + 1
    while depth and position < len(source):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
        position += 1
    assert depth == 0
    return source[opening + 1 : position - 1]


def test_manager_role_detection_uses_validated_authorization_context():
    body = _function_body(
        _source("js/auth.js"), "export function isBusinessAreaManager()"
    )
    assert "_getAuthorizationContext()" in body
    assert "context?.roles.includes('business_area_manager') ?? false" in body


def test_manager_workflow_filters_exclude_archived_without_changing_other_roles():
    source = _source("js/views/forms-list.js")
    body = _function_body(source, "function _getVisibleFilterOptions()")
    assert "if (!canPresentFormWorkflowMetadata())" in body
    assert "option.category !== 'Workflow State'" in body
    assert (
        "isBusinessAreaManager() && !hasPermission('form:read_unpublished:any')" in body
    )
    assert "option.apiValue !== 'archived'" in body
    assert body.rstrip().endswith("return _FILTER_OPTIONS;")
    for state in ("draft", "pending_review", "published", "archived"):
        assert re.search(rf"key: 'ws:{state}'", source)


def test_retained_workflow_filters_use_current_visible_options():
    source = _source("js/views/forms-list.js")
    body = _function_body(source, "function _removeUnavailableWorkflowFilters()")
    assert "new Set(_getVisibleFilterOptions().map(option => option.key))" in body
    assert "chip => visibleFilterKeys.has(chip.key)" in body
    assert "_currentSkip = 0" in body
    refresh = _function_body(source, "function _handleFormsAuthorizationRefreshed()")
    assert "_removeUnavailableWorkflowFilters()" in refresh


def test_authorization_refresh_removes_stale_results_before_reloading():
    body = _function_body(
        _source("js/views/forms-list.js"),
        "function _handleFormsAuthorizationRefreshed()",
    )
    assert "_formsRequestController?.abort()" in body
    assert "_autocompleteRequestController?.abort()" in body
    assert "_dismissSearchSuggestions()" in body
    assert "hasPortalRoles() && hasPermission('form:read')" in body
    assert body.index("replaceChildren()") < body.index("loadForms(0)")


def test_authorization_refresh_resyncs_sidebar_and_clears_protected_audit_data():
    assert (
        "window.addEventListener('auth:authorization-refreshed', updateAuthUi)"
        in _source("js/auth.js")
    )
    assert (
        "window.addEventListener('auth:authorization-refreshed', clearAuditHistory)"
        in _source("js/views/form-audit-history.js")
    )


def test_editor_refresh_revalidates_actions_without_overwriting_unsaved_fields():
    body = _function_body(
        _source("js/views/forms-create.js"),
        "async function _handleFormAuthorizationRefreshed()",
    )
    assert body.index("_currentFormAvailableActions = []") < body.index("await fetch(")
    assert body.index("_setFormFieldsLocked(true)") < body.index("await fetch(")
    assert "form.available_actions" in body
    assert (
        "_setFormFieldsLocked(!_currentFormAvailableActions.includes('edit'))" in body
    )
    assert "controller.signal.aborted || _currentFormId !== formId" in body
    assert "response.status === 403 || response.status === 404" in body
    assert "_submitNeedsReload = true" in body
    assert "_loadedFormSnapshot === null" in body
    assert ".value =" not in body


def test_editor_discards_form_responses_after_navigation_or_reset():
    source = _source("js/views/forms-create.js")
    body = _function_body(source, "async function _loadFormForEdit(formId)")
    assert "signal: controller.signal" in body
    assert body.index("if (controller.signal.aborted) return") < body.index(
        "_currentFormAvailableActions ="
    )
    reset = _function_body(source, "export function resetFormState()")
    assert "_formRequestController?.abort()" in reset
    assert "window.addEventListener('app:route-changing'" in source


def test_sidebar_requires_navigation_permission_without_blocking_forms_access():
    auth_ui = _function_body(_source("js/auth.js"), "export function updateAuthUi()")
    navigation_gate = "if (hasPortalRoles() && hasPermission('portal:navigation'))"
    _function_body(auth_ui, navigation_gate)
    assert re.search(
        r"setSidebarAvailability\(anyDestinationVisible\);\s*}\s*else\s*{"
        r"\s*hideSidebarDestinations\(\);\s*}",
        auth_ui,
    )
    hidden_sidebar = _function_body(auth_ui, "const hideSidebarDestinations = () =>")
    assert (
        "sidebarDestinationIds.forEach(linkId => "
        "setVisible(document.getElementById(linkId), false))"
    ) in hidden_sidebar
    assert "setVisible(sidebarToggleContainer, false)" in hidden_sidebar
    assert "setSidebarAvailability(false)" in hidden_sidebar

    route_guard = _function_body(
        _source("js/router.js"), "function _canAccessOperationalRoute(path)"
    )
    forms_access = _function_body(
        route_guard, "if (path === ROUTES.HOME || path === ROUTES.FORMS_LIST)"
    )
    assert forms_access.strip() == (
        "return !hasPortalRoles() || hasPermission('form:read');"
    )
    forms_view = _function_body(
        _source("js/views/forms-list.js"),
        "export async function showFormsListView(navigateFn)",
    )
    assert "loadForms();" in forms_view
    assert "portal:navigation" not in forms_view


def test_published_card_status_and_actions_have_no_client_action_fallback():
    source = _source("js/views/forms-list.js")
    card = _function_body(source, "export function displayForms(forms)")
    assert "const showWorkflowMetadata = canPresentFormWorkflowMetadata();" in card
    assert (
        '${showWorkflowMetadata ? `<span class="forms-result-card__status" '
        'data-status="${_escapeAttribute(form.status)}">'
        "${escapeHtml(_formatStatus(form.status))}</span>` : ''}"
    ) in card
    assert "${_renderFormActionButtons(form)}" in card

    actions = _function_body(source, "export function _renderFormActionButtons(form)")
    assert "const buttons = [];" in actions
    assert "const availableActions = new Set(form.available_actions);" in actions
    assert (
        "const canOpenEditor = availableActions.has('edit') "
        "|| (status === 'published' && availableActions.has('revert'));"
    ) in re.sub(r"\s+", " ", actions)
    action_gates = (
        ("if (canOpenEditor)", 'data-action="navigate"'),
        ("if (availableActions.has('submit_for_review'))", 'data-action="submit-form"'),
        ("if (availableActions.has('archive'))", 'data-action="archive-form"'),
        ("if (availableActions.has('restore'))", 'data-action="restore-form"'),
        ("if (availableActions.has('delete'))", 'data-action="delete-form"'),
    )
    for gate, action_attribute in action_gates:
        gated_button = _function_body(actions, gate)
        assert action_attribute in gated_button
        assert gated_button.count("buttons.push(") == 1
    assert actions.count("buttons.push(") == len(action_gates)
    assert actions.rstrip().endswith("return buttons.join('\\n');")


def test_draft_save_and_submit_visibility_uses_server_actions():
    buttons = _function_body(
        _source("js/views/forms-create.js"),
        "function _updateWorkflowButtons(status, "
        "availableActions = _currentFormAvailableActions)",
    )
    assert (
        "const actions = new Set("
        "Array.isArray(availableActions) ? availableActions : []);"
    ) in buttons
    assert buttons.index("el.style.display = 'none'") < buttons.index("const actions")
    draft = _function_body(buttons, "if (status === 'draft')")
    assert (
        "if (saveDraftBtn) saveDraftBtn.style.display = "
        "actions.has('edit') ? '' : 'none';"
    ) in draft
    submit = _function_body(
        draft, "if (submitForReviewBtn && actions.has('submit_for_review'))"
    )
    assert submit.strip() == "submitForReviewBtn.style.display = '';"


def test_loaded_draft_fields_unlock_only_from_server_edit_action():
    source = _source("js/views/forms-create.js")
    load = _function_body(source, "async function _loadFormForEdit(formId)")
    assert load.index("_setFormFieldsLocked(true)") < load.index("await fetch(")
    assert re.search(
        r"_currentFormAvailableActions = Array\.isArray\(form\.available_actions\)"
        r"\s*\? form\.available_actions\s*: \[\];",
        load,
    )
    assert load.index("_currentFormAvailableActions =") < load.index(
        "_updateWorkflowButtons(form.status, _currentFormAvailableActions);"
    )
    assert re.search(
        r"const isLocked = !_currentFormAvailableActions\.includes\('edit'\);"
        r"\s*_setFormFieldsLocked\(isLocked\);",
        load,
    )
    locking = _function_body(source, "function _setFormFieldsLocked(locked)")
    assert "if (el) el.disabled = locked;" in locking
    assert "if (fileInput) fileInput.disabled = locked;" in locking
    assert "setKeywordsLocked(locked);" in locking


def test_both_details_triggers_use_shared_default_drawer_without_role_override():
    source = _source("js/views/forms-list.js")
    card = _function_body(source, "export function displayForms(forms)")
    triggers = re.findall(
        r'<button class="forms-result-card__(?:number|view)"(.*?)>', card, re.S
    )
    assert len(triggers) == 2
    for attributes in triggers:
        assert 'type="button"' in attributes
        assert 'data-action="view-form"' in attributes
        assert 'data-form-id="${_escapeAttribute(form.id)}"' in attributes
        assert "data-route=" not in attributes

    listeners = _function_body(source, "function _initListViewEvents()")
    assert "formsList.addEventListener('click', _handleFormsListClick);" in listeners
    click = _function_body(source, "function _handleFormsListClick(e)")
    assert "const viewBtn = e.target.closest('[data-action=\"view-form\"]');" in click
    assert _function_body(click, "if (viewBtn)").strip() == (
        "_viewForm(viewBtn.dataset.formId, viewBtn);"
    )
    view = _function_body(
        source, "async function _viewForm(formId, openerElement = null)"
    )
    assert re.sub(r"\s+", " ", view).strip() == (
        "await openFormDetailsDrawer({ formId, mode: 'default', openerElement, });"
    )

    workflow = _function_body(
        _source("js/shared/form-details-drawer.js"),
        "async function _renderWorkflowActions(container, form, drawerGeneration)",
    )
    approvals = _function_body(workflow, "if (_currentMode === 'approvals')")
    assert (
        "${_renderApproveButtonHtml(form)}${_renderRejectButtonHtml(form)}" in approvals
    )
    assert approvals.rstrip().endswith("return;")
    default_actions = workflow[workflow.index("const { _renderFormActionButtons }") :]
    assert "container.innerHTML = _renderFormActionButtons(form);" in default_actions
    assert "container.hidden = !container.childElementCount;" in default_actions
    assert workflow.count("container.innerHTML =") == 2


def test_initial_audit_load_clears_and_permission_gates_before_render_or_fetch():
    load = _function_body(
        _source("js/views/form-audit-history.js"),
        "export function loadAuditHistory(id)",
    )
    gate = "if (!hasPermission('form:audit') || !hasPermission('form:edit')) return;"
    assert load[: load.index("formId = id;")].strip() == (
        "clearAuditHistory();\n    " + gate
    )
    assert (
        load.index(gate)
        < load.index("host.innerHTML =")
        < load.index("void loadInitial();")
    )


def test_index_and_shared_drawer_have_no_insights_or_audit_sections():
    shell = re.sub(
        r'<div id="auditHistoryMount">\s*</div>', "", _source("index.html"), count=1
    )
    for source in (
        shell,
        _source("js/shared/form-details-drawer.js"),
    ):
        assert not re.search(
            r"form[\s_-]*insights|audit[\s_-]*history|loadAuditHistory", source, re.I
        )
