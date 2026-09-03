"""Contract coverage for FEAT-0030 US-003 Staff portal sidebar."""

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_sidebar_replaces_dropdown_and_preserves_destination_contract():
    html = _source("index.html")
    expected_destinations = (
        ("approvalsLink", "/approvals", "Approvals"),
        ("manageFormsLink", "/forms", "Manage Forms"),
        ("createFormLink", "/create", "New Form"),
        ("reserveNumberLink", "/reserve", "Reserve Form Number"),
        ("myReservationsLink", "/my-reservations", "My Reservations"),
        ("rolesLink", "/roles", "Roles"),
        ("usersLink", "/users", "Users"),
        ("accessRequestsLink", "/access-requests", "Access Requests"),
        ("businessAreasLink", "/business-areas", "Business Areas"),
        ("prefixesLink", "/prefixes", "Prefixes"),
        ("cmsPagesLink", "/admin/cms/pages", "CMS Pages"),
        ("cmsRedirectsLink", "/admin/cms/redirects", "CMS Redirects"),
    )

    assert '<nav class="staff-sidebar" id="staffSidebar"' in html
    assert 'aria-label="Primary navigation"' in html
    assert 'id="navMenuToggle"' in html
    assert 'aria-controls="staffSidebar"' in html
    assert 'id="sidebarScrim"' in html
    assert 'id="navDropdownContainer"' not in html
    assert 'id="navAccordion"' not in html

    positions = []
    for link_id, route, label in expected_destinations:
        assert html.count(f'id="{link_id}"') == 1
        assert f'href="{route}" data-route="{route}"' in html
        positions.append(html.index(f'id="{link_id}"'))
        assert label in html

    assert positions == sorted(positions)
    assert "nav-count" not in html


def test_sidebar_controller_covers_responsive_and_accessible_state():
    sidebar_js = _source("js/sidebar.js")
    main_js = _source("js/main.js")

    assert "export function initSidebarNavigation()" in sidebar_js
    assert "export function setSidebarAvailability(available)" in sidebar_js
    assert "matchMedia('(max-width: 767.98px)')" in sidebar_js
    assert "aria-expanded" in sidebar_js
    assert "aria-hidden" in sidebar_js
    assert "inert" in sidebar_js
    assert "event.key === 'Escape'" in sidebar_js
    assert "sidebarScrim" in sidebar_js
    assert "requestAnimationFrame" in sidebar_js
    assert "sidebar?.contains(document.activeElement)" in sidebar_js
    assert "fetch(" not in sidebar_js
    assert "initSidebarNavigation();" in main_js


def test_auth_visibility_uses_existing_permissions_and_normalizes_groups():
    auth_js = _source("js/auth.js")

    for permission in (
        "form:read",
        "form:create",
        "form:approve",
        "form:review",
        "reservation:create",
        "reservation:read",
        "reservation:approve",
        "reservation:request_changes",
        "reservation:reject",
        "cms:manage",
    ):
        assert f"hasPermission('{permission}')" in auth_js

    assert "setSidebarAvailability(" in auth_js
    assert "updateSidebarGroups()" in auth_js
    assert "hasPermission('business_area:manage')" in auth_js
    assert (
        "hasPermission('business_area:create')"
        not in auth_js.split("export function updateAuthUi()", maxsplit=1)[1]
    )
    assert "navDropdownContainer" not in auth_js
    assert "formsAccordionItem" not in auth_js
    assert "reservationsAccordionItem" not in auth_js
    assert "adminAccordionItem" not in auth_js


def test_router_sets_one_accessible_current_destination():
    router_js = _source("js/router.js")
    update_navigation = router_js.split(
        "export function updateNavbar(user)", maxsplit=1
    )[1].split("// ─── Admin route guard", maxsplit=1)[0]

    assert "#staffSidebar .staff-sidebar__link" in update_navigation
    assert "removeAttribute('aria-current')" in update_navigation
    assert "setAttribute('aria-current', 'page')" in update_navigation
    assert "navbarColor01" not in update_navigation


def test_router_denies_hidden_operational_destinations_before_view_loading():
    auth_js = _source("js/auth.js")
    router_js = _source("js/router.js")

    assert "export function canReviewApprovals()" in auth_js
    assert "approvalsLink: canReviewApprovals()" in auth_js
    assert "function _canAccessOperationalRoute(path)" in router_js
    assert "path === ROUTES.FORMS_LIST" in router_js
    assert "if (path.startsWith('/forms/'))" in router_js
    assert "path === ROUTES.FORM_CREATE" in router_js
    assert "path === ROUTES.RESERVE" in router_js
    assert "path === ROUTES.MY_RESERVATIONS" in router_js
    assert "path === ROUTES.APPROVALS" in router_js
    guard_prefix = "if (isAuthenticated() && "
    guard_suffix = "!_canAccessOperationalRoute(path))"
    assert guard_prefix + guard_suffix in router_js
    assert "return canReviewApprovals();" in router_js


def test_sidebar_css_defines_desktop_mobile_and_focus_states():
    css = _source("css/main.css")

    assert ".staff-sidebar" in css
    assert "body.sidebar-available:not(.sidebar-collapsed) > .container" in css
    assert "body.sidebar-collapsed > .container" in css
    assert ".staff-sidebar__scrim" in css
    assert ".staff-sidebar__link:focus-visible" in css
    assert "@media (max-width: 767.98px)" in css
    assert ".staff-sidebar.is-open" in css
