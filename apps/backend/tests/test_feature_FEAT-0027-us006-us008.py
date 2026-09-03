"""
FEAT-0027 — US-006 (Approvals View popup) + US-008 (Forms list Share + deep-link).

Static assertions against the internal `apps/frontend` source tree. Mirrors
the FEAT-0027 batch-1 static-regression pattern already established for
US-001..US-005. No browser is required.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APPS_DIR = Path(__file__).resolve().parents[2]
FRONTEND = APPS_DIR / "frontend"

SHARED_POPUP = FRONTEND / "js" / "shared" / "form-view-popup.js"
FORMS_LIST_VIEW = FRONTEND / "js" / "views" / "forms-list.js"
APPROVALS_VIEW = FRONTEND / "js" / "views" / "approvals.js"
ROUTER_JS = FRONTEND / "js" / "router.js"


def _read(path: Path) -> str:
    assert path.exists(), f"Missing frontend file: {path}"
    return path.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


# ===========================================================================
# US-006 — Approvals "View" popup
# ===========================================================================


class TestUS006ApprovalsViewButton:
    """AC1 — every Form Approval Request row exposes a "View" button that
    opens the shared popup component."""

    def test_form_approval_row_has_view_button(self):
        """AC1 — the Form Approval Requests section renders a View button."""
        src = _read(APPROVALS_VIEW)
        # The Form Approval Requests section must contain a button carrying
        # data-action="form-view" alongside the existing Approve / Reject
        # buttons.
        assert 'data-action="form-view"' in src, (
            "Form Approval Request rows must render a View button "
            "(data-action=\"form-view\") — US-006 AC1"
        )
        assert 'data-action="form-approve"' in src and 'data-action="form-reject"' in src, (
            "Existing inline Approve / Reject controls MUST remain — CC-BR-04"
        )

    def test_view_button_carries_row_context_attributes(self):
        """AC2 — the View button carries requester + submitted-at so the
        popup can render the Request Context section without a second fetch."""
        src = _read(APPROVALS_VIEW)
        assert 'data-requester=' in src, (
            "View button must expose data-requester — US-006 AC2"
        )
        assert 'data-submitted-at=' in src, (
            "View button must expose data-submitted-at — US-006 AC2"
        )

    def test_view_button_delegates_to_shared_popup_in_approvals_mode(self):
        """AC2 / BR-02 — the click handler opens the SHARED popup with
        mode='approvals' and forwards the row context."""
        src = _strip_js_comments(_read(APPROVALS_VIEW))
        # Match a call to openFormViewPopup(...) whose argument object contains
        # mode: 'approvals' and forwards requesterName + submittedAt.
        pattern = re.compile(
            r"openFormViewPopup\s*\(\s*\{[^}]*mode\s*:\s*['\"]approvals['\"][^}]*\}\s*\)",
            re.DOTALL,
        )
        assert pattern.search(src), (
            "Approvals view must open the shared popup with mode='approvals'"
        )

    def test_approvals_view_imports_shared_popup(self):
        """BR-02 — the approvals view MUST import the shared popup module
        rather than duplicating rendering logic."""
        src = _read(APPROVALS_VIEW)
        assert "from '../shared/form-view-popup.js'" in src, (
            "approvals.js must import the shared form-view-popup module"
        )


class TestUS006SharedPopupApprovalsMode:
    """AC2, AC3, AC5, AC6 — approvals mode composition."""

    def test_shared_popup_renders_request_context_in_approvals_mode(self):
        """AC2 — approvals mode renders a labelled Request Context section
        with Requester + Submitted date."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        assert "_renderRequestContextHtml" in src, (
            "Shared popup must render request-context section in approvals mode"
        )
        # The context section must expose test hooks for both fields.
        assert 'data-testid="request-context-requester"' in src, (
            "Request context must expose a Requester field — US-006 AC2"
        )
        assert 'data-testid="request-context-submitted-at"' in src, (
            "Request context must expose a Submitted date field — US-006 AC2"
        )

    def test_shared_popup_uses_same_approve_endpoint_as_inline(self):
        """AC3 / CC-BR-04 — the popup Approve button POSTs to the SAME
        endpoint used by the existing inline Approve control."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        assert "/staff/forms/${encodeURIComponent(formId)}/approve" in src, (
            "Popup Approve must POST to /staff/forms/<id>/approve — CC-BR-04"
        )
        # And it MUST be a POST.
        m = re.search(
            r"fetch\(\s*`\$\{API_BASE\}/staff/forms/\$\{encodeURIComponent\(formId\)\}/approve`\s*,\s*\{([^}]*)\}",
            src,
            re.DOTALL,
        )
        assert m and "method: 'POST'" in m.group(1), (
            "Popup Approve must be a POST — CC-BR-04"
        )

    def test_shared_popup_reject_reuses_existing_modal(self):
        """AC3 / CC-BR-04 — the popup Reject button dispatches to the SAME
        server flow (approvalsFormRejectModal) as the existing inline
        Reject control, rather than posting the reject directly."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        assert "approvalsFormRejectModal" in src, (
            "Popup Reject must reuse the existing Approvals Reject modal — CC-BR-04"
        )
        assert "form-view-popup:reject-request" in src, (
            "Popup Reject must hand the target formId back to approvals.js "
            "via the form-view-popup:reject-request event"
        )

    def test_approvals_view_wires_reject_bridge_event(self):
        """AC3 / CC-BR-04 — approvals.js listens for the reject-request event
        emitted by the shared popup so a single _actionFormId flows through
        the same server call as the inline Reject control."""
        src = _strip_js_comments(_read(APPROVALS_VIEW))
        assert "'form-view-popup:reject-request'" in src, (
            "approvals.js must listen for form-view-popup:reject-request "
            "so the popup and inline reject share one server flow — CC-BR-04"
        )
        assert "'form-view-popup:action-complete'" in src, (
            "approvals.js must listen for form-view-popup:action-complete "
            "so the list refresh mirrors the inline flow — CC-BR-04"
        )

    def test_approve_button_disabled_when_missing_permission(self):
        """AC5 — Approve button is disabled when the user lacks
        form:approve or form:review."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        # Approve render helper must check both permissions.
        m = re.search(
            r"function\s+_renderApproveButtonHtml\s*\(\s*form\s*\)\s*\{(.*?)\n\}\n",
            src,
            re.DOTALL,
        )
        assert m, "Approve render helper missing"
        body = m.group(1)
        assert "hasPermission('form:approve')" in body, (
            "Approve button gating must check form:approve — US-006 AC5"
        )
        assert "hasPermission('form:review')" in body, (
            "Approve button gating must check form:review — US-006 AC5"
        )
        assert "disabled" in body, (
            "Approve button must render the disabled attribute when gated"
        )

    def test_self_approve_soD_disables_approve_with_tooltip(self):
        """AC5 — when the requester equals the current user AND the user
        does NOT hold form:approve-self, the Approve button is disabled
        with the tooltip 'You cannot approve your own request'."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        assert "form:approve-self" in src, (
            "Popup must consult form:approve-self for self-approve SoD — AC5"
        )
        assert "You cannot approve your own request" in src, (
            "Self-approve disabled tooltip must be present — AC5"
        )
        # created_by.id comparison to current user id must exist
        assert "form.created_by?.id" in src or "created_by?.id" in src, (
            "Popup must compare form.created_by.id to the current user — AC5"
        )

    def test_reject_button_disabled_when_missing_permission(self):
        """AC6 — Reject button state matches existing inline control gating."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        m = re.search(
            r"function\s+_renderRejectButtonHtml\s*\(\s*form\s*\)\s*\{(.*?)\n\}\n",
            src,
            re.DOTALL,
        )
        assert m, "Reject render helper missing"
        body = m.group(1)
        assert "hasPermission('form:approve')" in body, (
            "Reject gating must check form:approve — US-006 AC6"
        )
        assert "disabled" in body

    def test_focus_returned_to_opener_on_close(self):
        """AC8 — closing the popup returns keyboard focus to the opener
        element (View button)."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        assert "hidden.bs.modal" in src, (
            "Popup must handle Bootstrap's hidden.bs.modal event — AC8"
        )
        assert "_openerElement" in src and ".focus(" in src, (
            "Popup must call opener.focus() on close — AC8"
        )


# ===========================================================================
# US-008 — Share button + deep-link inbound
# ===========================================================================


class TestUS008ShareButton:
    """AC2..AC5 / BR-01..BR-04 — Share button behaviour."""

    def test_shared_popup_renders_share_button(self):
        """AC2 — the popup renders a Share button in every entry point."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        assert 'data-action="form-view-share"' in src, (
            "Popup must render a Share button — US-008 AC2"
        )
        assert 'aria-label="Share"' in src, (
            "Share button must expose an aria-label (AC12 / CC-BR-06)"
        )

    def test_share_url_shape_is_forms_slash_uuid(self):
        """AC3 / BR-01 — Share copies `${origin}/forms/<form_uuid>` with
        NO query string."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        m = re.search(
            r"function\s+_buildDeepLinkUrl\s*\(\s*formId\s*\)\s*\{(.*?)\n\}\n",
            src,
            re.DOTALL,
        )
        assert m, "_buildDeepLinkUrl missing"
        body = m.group(1)
        assert "window.location.origin" in body, (
            "Deep-link URL must be built from window.location.origin — BR-01"
        )
        assert "/forms/${encodeURIComponent(formId)}" in body, (
            "Deep-link URL shape must be `/forms/<form_uuid>` — BR-01"
        )
        # BR-01 — no query string, no hash-fragment shape
        assert "?" not in body, "Share URL MUST NOT contain a query string — BR-01"
        assert "#" not in body, "Share URL MUST NOT contain a hash — BR-01"

    def test_share_uses_navigator_clipboard(self):
        """AC4 — Share uses the Clipboard API and shows a success toast."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        assert "navigator.clipboard" in src, (
            "Share must use navigator.clipboard.writeText — AC4"
        )
        assert "'Link copied to clipboard'" in src, (
            "Share must show 'Link copied to clipboard' toast — AC4"
        )

    def test_share_manual_copy_fallback(self):
        """AC5 — clipboard-denied path shows the URL inline and does not
        surface a console exception."""
        src = _strip_js_comments(_read(SHARED_POPUP))
        assert "_showManualCopyFallback" in src, (
            "Popup must expose a manual-copy fallback when clipboard is denied — AC5"
        )
        assert "Unable to copy link" in src, (
            "Manual-copy toast must include the 'Unable to copy link' wording — AC5"
        )
        # AC5 — no `throw` inside the share handler that would surface an
        # exception in the console.
        m = re.search(
            r"async\s+function\s+_handleShare\s*\([^)]*\)\s*\{(.*?)\n\}\n",
            src,
            re.DOTALL,
        )
        assert m, "_handleShare missing"
        assert "throw" not in m.group(1), (
            "Share handler must not surface an uncaught exception — AC5"
        )

    def test_forms_list_view_click_does_not_push_state(self):
        """AC1 — clicking a Forms list View button MUST NOT update the
        browser URL."""
        src = _strip_js_comments(_read(FORMS_LIST_VIEW))
        # Isolate _viewForm — it must not call pushState / replaceState /
        # window.history.
        m = re.search(
            r"async\s+function\s+_viewForm\s*\([^)]*\)\s*\{(.*?)\n\}\n",
            src,
            re.DOTALL,
        )
        assert m, "_viewForm missing"
        body = m.group(1)
        assert "pushState" not in body and "replaceState" not in body, (
            "_viewForm MUST NOT push a new URL when opening the popup — AC1"
        )


class TestUS008DeepLinkRouter:
    """AC6..AC9 — inbound `/forms/<uuid>` routing."""

    def test_router_registers_forms_slash_uuid_handler(self):
        """AC6 — router must recognise the deep-link path."""
        src = _strip_js_comments(_read(ROUTER_JS))
        assert "path.startsWith('/forms/')" in src, (
            "Router must handle `/forms/<uuid>` — US-008 AC6"
        )
        assert "openFormViewPopup" in src, (
            "Deep-link route must open the shared popup — US-008 AC6"
        )

    def test_router_uses_uuid_shape_guard(self):
        """AC7/AC8 — invalid UUID collapses into the same denied toast as
        403 / 404, so the branches are indistinguishable client-side."""
        src = _strip_js_comments(_read(ROUTER_JS))
        assert "_isUuidLike" in src, (
            "Router must apply a UUID shape check before hitting the API "
            "so malformed IDs surface the SAME toast as 403 / 404 — AC7/AC8"
        )

    def test_router_uses_shared_denied_toast_constant(self):
        """CC-BR-05 — the router surfaces the SAME wording exported by the
        shared popup module, so failure branches cannot diverge."""
        src = _strip_js_comments(_read(ROUTER_JS))
        assert "DEEPLINK_DENIED_TOAST" in src, (
            "Router must import the shared DEEPLINK_DENIED_TOAST constant "
            "so failure wording cannot diverge — CC-BR-05"
        )
        shared = _strip_js_comments(_read(SHARED_POPUP))
        assert (
            "Form not found or you don't have permission to view it."
            in shared
        ), "Shared popup must define the CC-BR-05 canonical denied wording"

    def test_router_stashes_return_url_when_unauthenticated(self):
        """AC9 — an unauthenticated hit on `/forms/<uuid>` stores the target
        path so the app can resume after login."""
        src = _strip_js_comments(_read(ROUTER_JS))
        # The routeHandler unauthenticated guard shows the welcome view — a
        # unique enough anchor to isolate it from navigateTo's guard.
        m = re.search(
            r"if\s*\(\s*!isAuthenticated\(\)\s*&&\s*path\s*!==\s*ROUTES\.CALLBACK\s*\)"
            r"\s*\{(?P<body>[\s\S]*?showWelcomeView[\s\S]*?)\n\s{2}\}",
            src,
        )
        assert m, "Unauthenticated guard in routeHandler missing"
        body = m.group("body")
        assert "sessionStorage.setItem('tf_return_url'" in body, (
            "Router must remember the deep-link target for post-login resume — AC9"
        )
        assert "_isRegisteredRoute(path)" in body, (
            "Return-url stash must remain scoped to registered routes — AC9"
        )
        assert "path !== ROUTES.HOME" in body
        assert "path !== ROUTES.CALLBACK" in body

    def test_router_resumes_at_return_url_on_callback_complete(self):
        """AC9 — after the OIDC callback completes, the app resumes at the
        stored deep-link URL rather than being forced to the dashboard."""
        src = _strip_js_comments(_read(ROUTER_JS))
        m = re.search(
            r"addEventListener\(\s*'auth:callback-complete'\s*,\s*\(\s*\)\s*=>\s*\{(.*?)\}\)",
            src,
            re.DOTALL,
        )
        assert m, "auth:callback-complete handler missing"
        body = m.group(1)
        assert "routeHandler(" in body, (
            "callback-complete must be able to route to the return URL — AC9"
        )


class TestUS008AndUS006SharedComponent:
    """Regression risk from 04-test-plan: Forms-list and Approvals must use
    the SAME popup component — no divergence."""

    def test_forms_list_delegates_to_shared_popup(self):
        src = _strip_js_comments(_read(FORMS_LIST_VIEW))
        assert "from '../shared/form-view-popup.js'" in src, (
            "forms-list.js must import the shared popup component — BR-02"
        )
        assert "openFormViewPopup" in src, (
            "forms-list.js must call openFormViewPopup — BR-02"
        )

    def test_forms_list_no_longer_inlines_form_details_markup(self):
        """After the refactor the inline Form Details HTML must be gone —
        prevents future divergence between the two entry points."""
        src = _read(FORMS_LIST_VIEW)
        # The inline dl.row block that used to live in _viewForm — a
        # unique-enough label to guarantee we spot a regression.
        assert "Does this form collect personal info?" not in src, (
            "Inline popup markup MUST live in the shared component only — BR-02"
        )
