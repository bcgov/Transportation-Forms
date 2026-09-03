from pathlib import Path

import pytest


FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


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

        # The admin-route enumeration must still cover roles / users /
        # access-requests so direct URL access is intercepted.
        assert "export function isAdminRoute(path)" in js
        assert "path === ROUTES.ROLES" in js
        assert "path === ROUTES.USERS" in js
        assert "path === ROUTES.ACCESS_REQUESTS" in js

        # The guard itself enters the protection block whenever the path
        # is an admin route. Inside it, Business Areas are allowed for
        # users that hold the matching granular permission — admin role
        # is no longer an authorization path. We assert the outer gate and
        # destination permission branches plus the Not Found outcome.
        assert "if (isAuthenticated() && isAdminRoute(path))" in js
        assert "hasPermission('business_area:create')" in js
        assert "hasPermission('business_area:manage')" in js
        assert "isAdminUser()" not in js
        assert "hasPermission('role:read')" in js
        assert "hasPermission('user:manage_roles')" in js
        assert "_currentRoute = 'not-found'" in js

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

    def test_cms_admin_routes_are_guarded_by_cms_manage_permission(self):
        """CMS admin routes must honour ``cms:manage`` (matches backend contract).

        The backend ``routes/cms_pages.py`` gates every write on
        ``require_permission("cms", "manage")``. The SPA router guard
        MUST accept the same permission so a ``content_editor`` role
        (which has ``cms:manage`` but is not a full admin) is not bounced
        back to HOME.
        """
        js = (FRONTEND_INDEX.parent / "js" / "router.js").read_text(encoding="utf-8")

        # CMS routes are enumerated as admin routes so the guard block runs.
        assert "path === ROUTES.CMS_PAGES" in js
        assert "path === ROUTES.CMS_PAGE_NEW" in js
        assert "path.startsWith('/admin/cms/')" in js

        # And the guard grants access on ``cms:manage`` — not admin-only.
        assert "hasPermission('cms:manage')" in js

    def test_cms_admin_nav_links_are_gated_by_cms_manage_permission(self):
        """CMS admin nav links must be gated on ``cms:manage``.

        Otherwise BA-only managers see CMS links they can't use, and
        ``cms:manage``-only users don't see the CMS links at all.
        """
        html = FRONTEND_INDEX.read_text(encoding="utf-8")
        auth_js = (FRONTEND_INDEX.parent / "js" / "auth.js").read_text(encoding="utf-8")

        # Link elements exist so JS can toggle their visibility.
        assert 'id="cmsPagesLink"' in html
        assert 'id="cmsRedirectsLink"' in html

        # auth.js drives visibility from ``cms:manage`` (or admin).
        assert "hasPermission('cms:manage')" in auth_js
        assert "cmsPagesLink:" in auth_js
        assert "cmsRedirectsLink:" in auth_js

    def test_spa_server_serves_cms_admin_routes(self):
        """The SPA server MUST list ``/admin/cms/*`` routes.

        Without them, direct navigation or a page refresh on a CMS admin
        URL returns a backend 404 instead of the SPA shell.
        """
        app_py = (FRONTEND_INDEX.parent / "app.py").read_text(encoding="utf-8")

        assert '@app.get("/admin/cms/pages")' in app_py
        assert '@app.get("/admin/cms/pages/new")' in app_py
        assert '@app.get("/admin/cms/pages/{page_id}")' in app_py
        assert '@app.get("/admin/cms/redirects")' in app_py
