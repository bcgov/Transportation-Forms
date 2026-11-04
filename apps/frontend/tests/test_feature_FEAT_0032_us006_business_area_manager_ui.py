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
        "const canEdit = _currentFormAvailableActions.includes('edit');" in body
    )
    assert re.search(
        r"const canChangeBusinessArea = "
        r"_currentFormAvailableActions\.includes\(\s*"
        r"'change_business_area',?\s*\);",
        body,
    )
    assert "_setFormFieldsLocked(!canEdit, !canChangeBusinessArea);" in body
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


def test_direct_editor_url_without_editor_action_redirects_with_toast():
    source = _source("js/views/forms-create.js")
    mapping = source.split("const EDITOR_ACTIONS_BY_STATUS = {", 1)[1].split("};", 1)[0]
    assert "draft: ['edit', 'submit_for_review', 'delete']" in mapping
    assert "published: ['archive', 'unpublish', 'revert']" in mapping
    assert "archived: ['restore']" in mapping
    assert "pending_review" not in mapping

    can_open = _function_body(source, "function _canOpenInEditor(status, availableActions)")
    assert "_forStatus(EDITOR_ACTIONS_BY_STATUS, status, [])" in can_open
    assert "availableActions.includes(action)" in can_open
    lookup = _function_body(source, "function _forStatus(table, status, fallback)")
    # Own-key lookup so unexpected statuses cannot resolve to prototype members.
    assert "Object.hasOwn(table, status) ? table[status] : fallback" in lookup

    leave = _function_body(source, "function _leaveUnavailableEditor()")
    assert leave.index("resetFormState()") < leave.index("showAlert(")
    assert "showAlert(EDITOR_UNAVAILABLE_MESSAGE, 'warning')" in leave
    assert leave.rstrip().endswith("_navigate(ROUTES.FORMS_LIST);")

    guard = "if (!_canOpenInEditor(form.status, _currentFormAvailableActions)) {"
    load = _function_body(source, "async function _loadFormForEdit(formId)")
    # The guard must run before any form content is written to the page.
    assert load.index(guard) < load.index("_populateFormFields(form);")
    assert load.index(guard) < load.index("_renderFormHeader(form);")
    assert "document.getElementById('title').value" not in load
    populate = _function_body(source, "function _populateFormFields(form)")
    assert "document.getElementById('title').value = form.title;" in populate
    assert "restoreUploadState(" in populate
    assert "_leaveUnavailableEditor();\n            return;" in load
    refresh = _function_body(source, "async function _handleFormAuthorizationRefreshed()")
    assert refresh.index(guard) < refresh.index("_currentFormStatus = form.status")


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
        "|| (status === 'published' && availableActions.has('unpublish')) "
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


def _workflow_button_table(source: str) -> str:
    return source.split("const WORKFLOW_BUTTONS_BY_STATUS = {", 1)[1].split("};", 1)[0]


def test_unpublish_without_revert_uses_the_unpublish_endpoint():
    source = _source("js/views/forms-create.js")
    assert (
        "published: { archiveFormBtn: ['archive'], "
        "unpublishFormBtn: ['unpublish', 'revert'] }"
    ) in _workflow_button_table(source)
    buttons = _function_body(
        source,
        "function _updateWorkflowButtons(status, "
        "availableActions = _currentFormAvailableActions)",
    )
    assert "revealingActions.some(action => actions.has(action))" in buttons

    opener = _function_body(source, "function _openFormUnpublishModal()")
    assert "_currentFormAvailableActions.includes('unpublish')" in opener
    assert "_currentFormAvailableActions.includes('revert')" in opener
    assert "confirm('Unpublish this form and return it to Draft status?')" in opener

    unpublish = _function_body(source, "async function _unpublishForm()")
    assert "/staff/forms/${_currentFormId}/unpublish" in unpublish
    assert "method: 'POST'" in unpublish
    assert "_navigate(ROUTES.FORMS_LIST);" in unpublish


def test_draft_save_and_submit_visibility_uses_server_actions():
    source = _source("js/views/forms-create.js")
    buttons = _function_body(
        source,
        "function _updateWorkflowButtons(status, "
        "availableActions = _currentFormAvailableActions)",
    )
    assert (
        "const actions = new Set("
        "Array.isArray(availableActions) ? availableActions : []);"
    ) in buttons
    hide_all = (
        "WORKFLOW_BUTTON_IDS.forEach(id => "
        "_setDisplayed(document.getElementById(id), false));"
    )
    assert buttons.index(hide_all) < buttons.index("const actions")
    assert (
        "_setDisplayed(saveDraftBtn, status === 'draft' && actions.has('edit'));"
    ) in buttons
    assert "_forStatus(WORKFLOW_BUTTONS_BY_STATUS, status, {})" in buttons
    table = _workflow_button_table(source)
    assert (
        "draft: { submitForReviewBtn: ['submit_for_review'], deleteFormBtn: ['delete'] }"
    ) in table
    assert "archived: { restoreFormBtn: ['restore'] }" in table
    assert "pending_review" not in table
    assert (
        "const WORKFLOW_BUTTON_IDS = "
        "Object.values(WORKFLOW_BUTTONS_BY_STATUS).flatMap(Object.keys);"
    ) in source
    display = _function_body(source, "function _setDisplayed(element, visible)")
    assert "if (element) element.style.display = visible ? '' : 'none';" in display


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
    assert "const isLocked = !_currentFormAvailableActions.includes('edit');" in load
    assert re.search(
        r"const isBusinessAreaLocked = "
        r"!_currentFormAvailableActions\.includes\(\s*"
        r"'change_business_area',?\s*\);",
        load,
    )
    assert "_setFormFieldsLocked(isLocked, isBusinessAreaLocked);" in load
    locking = _function_body(
        source,
        "function _setFormFieldsLocked(locked, businessAreaLocked = locked)",
    )
    assert "if (el) el.disabled = locked;" in locking
    assert "businessAreaInput.disabled = businessAreaLocked;" in locking
    assert "if (businessAreaLocked) closeBusinessAreaDropdown();" in locking
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
