from pathlib import Path

import pytest


FRONTEND_INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


@pytest.mark.integration
class TestFrontendAdminVisibilityAndGuards:
    def test_admin_navbar_links_exist_and_hidden_by_default(self):
        html = FRONTEND_INDEX.read_text(encoding="utf-8")

        assert 'id="rolesLink"' in html
        assert 'id="usersLink"' in html
        assert 'id="accessRequestsLink"' in html
        assert 'href="/roles"' in html
        assert 'data-route="/roles"' in html

    def test_route_guard_blocks_non_admin_direct_navigation(self):
        js = (FRONTEND_INDEX.parent / "js" / "router.js").read_text(encoding="utf-8")

        assert "export function isAdminRoute(path)" in js
        assert "path === ROUTES.ROLES" in js
        assert "path === ROUTES.USERS" in js
        assert "path === ROUTES.ACCESS_REQUESTS" in js
        assert "if (isAuthenticated() && isAdminRoute(path) && !isAdminUser())" in js
        assert "window.history.replaceState({}, '', ROUTES.HOME);" in js

    def test_route_handler_supports_admin_pages_and_detail_routes(self):
        js = (FRONTEND_INDEX.parent / "js" / "router.js").read_text(encoding="utf-8")

        assert "path === ROUTES.ROLES" in js
        assert "path.startsWith('/roles/')" in js
        assert "path === ROUTES.USERS" in js
        assert "path.startsWith('/users/')" in js
        assert "path === ROUTES.ACCESS_REQUESTS" in js

    def test_request_access_panel_and_actions_exist(self):
        html = FRONTEND_INDEX.read_text(encoding="utf-8")
        admin_js = (FRONTEND_INDEX.parent / "js" / "views" / "admin" / "access-requests.js").read_text(encoding="utf-8")

        assert 'id="requestAccessPanel"' in html
        assert 'id="requestAccessBtn"' in html
        assert "function loadRequestAccessState()" in admin_js
        assert "function submitAccessRequest()" in admin_js
        assert "`${API_BASE}/access-requests/me`" in admin_js
        assert "`${API_BASE}/access-requests`" in admin_js

    def test_request_access_panel_has_no_d_flex_static_class(self):
        """Ensure requestAccessPanel does not carry a Bootstrap d-flex class.

        Bootstrap 5.3 compiles d-flex to `display: flex !important` which
        outranks any inline `style="display:none"` set by JS, causing the
        panel to always be visible regardless of user roles (BUG 1).
        """
        html = FRONTEND_INDEX.read_text(encoding="utf-8")

        # Find the requestAccessPanel element definition
        import re
        match = re.search(r'id="requestAccessPanel"[^>]*>', html)
        assert match, "requestAccessPanel element not found"
        element_tag = match.group(0)
        # The static class list must NOT contain any Bootstrap display utility
        assert "d-flex" not in element_tag, (
            "requestAccessPanel must not carry 'd-flex' — Bootstrap !important "
            "overrides JS style.display='none' and makes the panel permanently visible"
        )
