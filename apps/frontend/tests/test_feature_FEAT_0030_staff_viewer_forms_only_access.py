"""Source contracts for FEAT-0030 US-007 Staff Viewer Forms-only access."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_navigation_is_hidden_before_and_after_permission_resolution() -> None:
    html = _source("index.html")
    auth = _source("js/auth.js")

    assert 'id="sidebarToggleContainer" hidden style="display:none;"' in html
    assert 'id="staffSidebar" aria-label="Primary navigation"' in html
    assert "aria-hidden=\"true\" hidden inert" in html
    assert "hasPortalRoles() && hasPermission('portal:navigation')" in auth
    assert "setSidebarAvailability(false);" in auth


def test_staff_viewer_classification_is_case_insensitive_and_shared() -> None:
    authorization = _source("js/authorization-context.js")
    auth = _source("js/auth.js")
    forms = _source("js/views/forms-list.js")

    assert "export function isStaffViewerOnly()" in auth
    assert ".trim().toLowerCase()" in authorization
    assert "context?.roles.length === 1 && context.roles[0] === 'staff_viewer'" in auth
    assert "isStaffViewerOnly," in forms
    assert "if (isStaffViewerOnly() || hasNoRoles)" in forms


def test_unavailable_sidebar_clears_all_layout_and_focus_state() -> None:
    sidebar = _source("js/sidebar.js")
    css = _source("css/main.css")

    assert "_available && !isMobile && !isVisible" in sidebar
    assert "document.documentElement.style.removeProperty('--staff-sidebar-top')" in sidebar
    assert "window.cancelAnimationFrame(_sidebarTopFrame)" in sidebar
    assert "document.activeElement.blur()" in sidebar
    assert "body:not(.sidebar-available) > .container" in css
    assert "max-width: none" in css


def test_route_guards_cover_dynamic_routes_before_view_imports() -> None:
    router = _source("js/router.js")
    operational_guard = router.split(
        "function _canAccessOperationalRoute(path)", maxsplit=1
    )[1].split("// ─── Core route handler", maxsplit=1)[0]
    admin_denial = router.split("if (!isAllowed)", maxsplit=1)[1].split(
        "// ── Route dispatch", maxsplit=1
    )[0]

    assert "path.startsWith('/edit/')" in operational_guard
    assert "hasPermission('form:edit')" in operational_guard
    assert "path.startsWith('/reservations/')" in operational_guard
    assert "hasPermission('reservation:read')" in operational_guard
    assert "isAdminUser()" not in operational_guard
    assert "hasValidAuthorizationContext()" in operational_guard
    assert "_currentRoute = 'not-found'" in admin_denial
    assert "replaceState" not in admin_denial
    assert "await routeHandler(ROUTES.HOME)" not in admin_denial


def test_malformed_authorization_context_grants_no_client_access() -> None:
    authorization = _source("js/authorization-context.js")
    auth = _source("js/auth.js")
    router = _source("js/router.js")

    assert "!Array.isArray(user.roles) || !Array.isArray(user.permissions)" in authorization
    assert "new Set(roles).size !== roles.length" in authorization
    assert "new Set(permissions).size !== permissions.length" in authorization
    assert "roles.length === 0 && permissions.length > 0" in authorization
    assert "parseAuthorizationContext(getCurrentUser())" in auth
    assert "return context?.permissions.includes(permission) ?? false" in auth
    assert "if (!hasValidAuthorizationContext())" in router
    assert "path === ROUTES.HOME || path === ROUTES.FORMS_LIST" in router


def test_refresh_reloads_authorization_and_invalidates_sensitive_ui() -> None:
    auth = _source("js/auth.js")
    refresh = _source("js/token-refresh.js")
    router = _source("js/router.js")
    forms = _source("js/views/forms-list.js")
    drawer = _source("js/shared/form-details-drawer.js")

    assert "fetch(`${API_BASE}/auth/me`" in refresh
    assert "parseAuthorizationContext(user)" in refresh
    assert "setCurrentUser(user)" in refresh
    assert "auth:authorization-refreshed" in refresh
    assert "auth:authorization-refreshed', updateAuthUi" in auth
    assert "auth:authorization-refreshed', () =>" in router
    assert "auth:authorization-refreshed', _resetFormsListLifecycle" in forms
    assert "_formRequestController?.abort()" in drawer
    assert "drawerGeneration !== _drawerGeneration" in drawer
    assert "auth:authorization-refreshed', _resetDrawerLifecycle" in drawer
    assert "_clearDrawerContent()" in drawer


def test_reservation_popup_is_invalidated_on_route_and_auth_changes() -> None:
    popup = _source("js/shared/reservation-view-popup.js")

    assert "_reservationRequestController?.abort()" in popup
    assert "signal," in popup
    assert "popupGeneration !== _popupGeneration" in popup
    assert "app:route-changing', _resetPopupLifecycle" in popup
    assert "auth:session-cleared', _resetPopupLifecycle" in popup
    assert "auth:authorization-refreshed', _resetPopupLifecycle" in popup
    assert "body.replaceChildren()" in popup
    assert "footer.replaceChildren()" in popup


def test_no_role_view_does_not_request_protected_forms_data() -> None:
    forms = _source("js/views/forms-list.js")
    no_role_branch = forms.split("const hasNoRoles = !hasPortalRoles();", maxsplit=1)[1]
    no_role_branch = no_role_branch.split("await _restoreResultsLayoutPreference();", maxsplit=1)[0]

    assert "requestAccessPanel.style.display = hasNoRoles ? 'flex' : 'none'" in no_role_branch
    assert "formsLibraryContent.hidden = hasNoRoles" in no_role_branch
    assert "if (hasNoRoles) return;" in no_role_branch
    assert "loadForms()" not in no_role_branch
    assert "loadBusinessAreas()" not in no_role_branch