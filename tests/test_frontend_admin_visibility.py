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
        assert 'id="rolesLink" href="/roles" onclick="navigateTo(event, \'/roles\')" style="display:none;"' in html
        assert 'id="usersLink" href="/users" onclick="navigateTo(event, \'/users\')" style="display:none;"' in html
        assert 'id="accessRequestsLink" href="/access-requests" onclick="navigateTo(event, \'/access-requests\')" style="display:none;"' in html

    def test_route_guard_blocks_non_admin_direct_navigation(self):
        html = FRONTEND_INDEX.read_text(encoding="utf-8")

        assert "function isAdminRoute(path)" in html
        assert "path === '/roles'" in html
        assert "path === '/users'" in html
        assert "path === '/access-requests'" in html
        assert "if (isAuthenticated() && isAdminRoute(path) && !isAdminUser())" in html
        assert "window.history.replaceState({}, '', '/');" in html

    def test_route_handler_supports_admin_pages_and_detail_routes(self):
        html = FRONTEND_INDEX.read_text(encoding="utf-8")

        assert "else if (path === '/roles')" in html
        assert "else if (path.startsWith('/roles/'))" in html
        assert "else if (path === '/users')" in html
        assert "else if (path.startsWith('/users/'))" in html
        assert "else if (path === '/access-requests' || path.startsWith('/access-requests/'))" in html

    def test_request_access_panel_and_actions_exist(self):
        html = FRONTEND_INDEX.read_text(encoding="utf-8")

        assert 'id="requestAccessPanel"' in html
        assert 'id="requestAccessBtn"' in html
        assert "function loadRequestAccessState()" in html
        assert "function submitAccessRequest()" in html
        assert "`${API_BASE}/access-requests/me`" in html
        assert "`${API_BASE}/access-requests`" in html

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
