"""Source contracts for FEAT-0030 US-008 responsive form-details drawer."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]
DRAWER_PATH = FRONTEND_DIR / "js" / "shared" / "form-details-drawer.js"
OBSOLETE_POPUP_PATH = FRONTEND_DIR / "js" / "shared" / "form-view-popup.js"


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_one_shared_drawer_serves_forms_approvals_and_deep_links() -> None:
    forms = _source("js/views/forms-list.js")
    approvals = _source("js/views/approvals.js")
    router = _source("js/router.js")

    assert "openFormDetailsDrawer" in forms
    assert "from '../shared/form-details-drawer.js'" in forms
    assert "openFormDetailsDrawer" in approvals
    assert "mode: 'approvals'" in approvals
    assert "openFormDetailsDrawer" in router
    assert "./shared/form-details-drawer.js" in router


def test_drawer_markup_replaces_only_the_form_details_modal() -> None:
    html = _source("index.html")

    assert 'id="formDetailsDrawer" role="dialog" aria-modal="true"' in html
    assert 'aria-labelledby="formDetailsDrawerLabel"' in html
    assert 'id="formDetailsScrim"' in html
    assert 'id="formModal"' not in html
    assert 'id="reservationViewModal"' in html
    assert 'id="approvalsFormRejectModal"' in html


def test_drawer_renders_only_approved_form_metadata() -> None:
    html = _source("index.html")
    drawer_markup = html.split('id="formDetailsDrawer"', maxsplit=1)[1].split(
        "</aside>", maxsplit=1
    )[0]

    for label in (
        "Status",
        "Business Area",
        "File Type",
        "Public",
        "Form Requires Personal Information",
        "Last updated",
        "Description",
    ):
        assert label in drawer_markup
    for excluded in ("Owner", "Keywords", "Effective Date", "Created"):
        assert excluded not in drawer_markup
    assert "form_source_url" not in drawer_markup
    assert "form_attachment_filename" not in drawer_markup


def test_dynamic_text_uses_text_content_and_description_preserves_lines() -> None:
    drawer = _source("js/shared/form-details-drawer.js")
    css = _source("css/main.css")

    assert "elements.number.textContent" in drawer
    assert "elements.title.textContent" in drawer
    assert "elements.description.textContent" in drawer
    assert "elements.contactNoteText.textContent" in drawer
    assert ".form-details-drawer__description p" in css
    assert "white-space: pre-wrap" in css


def test_source_actions_are_download_form_link_or_absent() -> None:
    drawer = _source("js/shared/form-details-drawer.js")

    assert "form.form_source === 'Download'" in drawer
    assert "form.form_attachment_url" in drawer
    assert "form.form_attachment_filename" in drawer
    assert "Download'" in drawer
    assert "form.form_source === 'URL' && _isSafeHttpUrl(form.form_source_url)" in drawer
    assert "Form link'" in drawer
    assert "url.protocol === 'http:' || url.protocol === 'https:'" in drawer
    assert "link.target = '_blank'" in drawer
    assert "link.rel = 'noopener noreferrer'" in drawer


def test_forms_actions_reuse_the_existing_policy_and_handlers() -> None:
    drawer = _source("js/shared/form-details-drawer.js")
    forms = _source("js/views/forms-list.js")

    assert "await import('../views/forms-list.js')" in drawer
    assert "_renderFormActionButtons(form)" in drawer
    assert "handleFormWorkflowAction(workflowButton)" in drawer
    assert "export function _renderFormActionButtons(form)" in forms
    assert "export async function handleFormWorkflowAction(actionElement)" in forms
    assert "FORM_WORKFLOW_STATES.has(status)" in forms
    assert "typeof creatorId !== 'string' || !UUID_PATTERN.test(creatorId)" in forms


def test_approvals_actions_retain_permissions_self_denial_and_bridge() -> None:
    drawer = _source("js/shared/form-details-drawer.js")
    approvals = _source("js/views/approvals.js")

    assert "export function getFormApprovalActionState(creatorId)" in drawer
    assert "hasPermission('form:approve')" in drawer
    assert "hasPermission('form:review')" in drawer
    assert "hasPermission('form:approve-self')" in drawer
    assert "You cannot approve your own request" in drawer
    assert "/staff/forms/${encodeURIComponent(formId)}/approve" in drawer
    assert "form-details-drawer:reject-request" in drawer
    assert "'form-details-drawer:reject-request'" in approvals
    assert "approvalsFormRejectModal" in drawer


def test_share_and_deep_link_close_follow_stable_url_contract() -> None:
    drawer = _source("js/shared/form-details-drawer.js")
    forms = _source("js/views/forms-list.js")

    assert "`${window.location.origin}/forms/${encodeURIComponent(formId)}`" in drawer
    assert "navigator.clipboard.writeText(url)" in drawer
    assert "Unable to copy link. Please copy manually" in drawer
    assert "window.history.replaceState({}, '', '/forms')" in drawer
    assert "window.history" not in forms.split(
        "async function _viewForm", maxsplit=1
    )[1].split("async function _deleteForm", maxsplit=1)[0]


def test_deep_link_denials_do_not_show_a_loading_drawer() -> None:
    drawer = _source("js/shared/form-details-drawer.js")
    router = _source("js/router.js")

    assert "if (!_openedFromDeepLink)" in drawer
    assert "if (_openedFromDeepLink) _showDrawer()" in drawer
    assert "if (path.startsWith('/forms/'))" in router
    assert "showNotification(DEEPLINK_DENIED_TOAST, 'warning')" in router
    assert "Form not found or you don't have permission to view it." in drawer


def test_approvals_inline_and_drawer_share_action_state_and_pending_guard() -> None:
    approvals = _source("js/views/approvals.js")

    assert "getFormApprovalActionState(f.submitted_by_id)" in approvals
    assert "actionState.canApprove" in approvals
    assert "actionState.canDecide" in approvals
    assert "_pendingFormDecisions.has(formId)" in approvals
    assert "_pendingFormDecisions.delete(formId)" in approvals
    assert "_pendingApprovalRequests.has(formId)" in _source(
        "js/shared/form-details-drawer.js"
    )
    assert "_pendingApprovalRequests.delete(formId)" in _source(
        "js/shared/form-details-drawer.js"
    )


def test_malformed_ownership_identifiers_fail_closed() -> None:
    drawer = _source("js/shared/form-details-drawer.js")
    forms = _source("js/views/forms-list.js")

    assert "const UUID_PATTERN" in drawer
    assert "UUID_PATTERN.test(currentUserId)" in drawer
    assert "UUID_PATTERN.test(creatorId)" in drawer
    assert "const UUID_PATTERN" in forms
    assert "UUID_PATTERN.test(userId)" in forms
    assert "UUID_PATTERN.test(creatorId)" in forms


def test_drawer_fails_closed_for_races_and_authorization_changes() -> None:
    drawer = _source("js/shared/form-details-drawer.js")

    assert "_formRequestController?.abort()" in drawer
    assert "drawerGeneration !== _drawerGeneration" in drawer
    assert "signal," in drawer
    assert "auth:session-expired', _resetDrawerLifecycle" in drawer
    assert "auth:session-cleared', _resetDrawerLifecycle" in drawer
    assert "auth:authorization-refreshed', _resetDrawerLifecycle" in drawer
    assert "_clearDrawerContent()" in drawer


def test_drawer_dismissal_focus_and_responsive_contracts_exist() -> None:
    drawer = _source("js/shared/form-details-drawer.js")
    css = _source("css/main.css")

    assert "scrim.addEventListener('click', () => _closeDrawer())" in drawer
    assert "document.getElementById('closeFormDetailsDrawer')?.focus()" in drawer
    assert "event.key === 'Escape'" in drawer
    assert "event.key !== 'Tab'" in drawer
    assert "focusTarget?.focus()" in drawer
    assert "element.inert = true" in drawer
    assert "width: min(460px, 100vw)" in css
    assert "@media (max-width: 575.98px)" in css
    assert "width: 100vw" in css
    assert "overflow-wrap: anywhere" in css


def test_obsolete_popup_module_is_removed() -> None:
    assert DRAWER_PATH.exists()
    assert not OBSOLETE_POPUP_PATH.exists()
