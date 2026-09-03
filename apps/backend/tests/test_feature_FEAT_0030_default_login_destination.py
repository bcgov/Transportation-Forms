"""Regression coverage for FEAT-0030 US-001 default staff landing."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi.testclient import TestClient


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_successful_callback_defaults_to_forms_for_every_role():
    auth_source = _source("js/auth.js")
    callback_source = auth_source.split(
        "export async function handleAuthCallback()", maxsplit=1
    )[1].split("export async function signOut()", maxsplit=1)[0]

    assert "let dest = ROUTES.FORMS_LIST;" in callback_source
    assert "hasPortalRoles()" not in callback_source
    assert "_getSafeInternalReturnUrl(returnUrl)" in callback_source
    assert "_consumeStoredReturnUrl()" in callback_source


def test_failed_callback_clears_session_and_stale_return_destination():
    auth_source = _source("js/auth.js")
    callback_source = auth_source.split(
        "export async function handleAuthCallback()", maxsplit=1
    )[1].split("export async function signOut()", maxsplit=1)[0]

    missing_parameters_branch = callback_source.split("if (!code || !state)", maxsplit=1)[
        1
    ].split("try {", maxsplit=1)[0]
    failure_branch = callback_source.rsplit("} catch (_error) {", maxsplit=1)[1]

    for branch in (missing_parameters_branch, failure_branch):
        assert "_clearAuthSession();" in branch
        assert "_removeStoredReturnUrl();" in branch
        assert "ROUTES.FORMS_LIST" not in branch


def test_dashboard_is_a_terminal_not_found_route():
    router_source = _source("js/router.js")
    route_handler_source = router_source.split(
        "export async function routeHandler(path, params = {})", maxsplit=1
    )[1].split("export function initRouter()", maxsplit=1)[0]

    route_existence_check = route_handler_source.index("if (!_isRegisteredRoute(path))")
    unauthenticated_guard = route_handler_source.index(
        "if (!isAuthenticated() && path !== ROUTES.CALLBACK)"
    )

    assert route_existence_check < unauthenticated_guard
    assert "route !== ROUTES.DASHBOARD" in router_source
    assert "const dynamicPrefixes" in router_source
    assert "showNotFoundView" in router_source
    assert "./views/dashboard.js" not in router_source
    assert "navigateTo(ROUTES.FORMS_LIST);" in router_source


def test_dashboard_markup_and_navigation_are_removed():
    html = _source("index.html")

    assert 'href="/dashboard"' not in html
    assert 'data-route="/dashboard"' not in html
    assert 'id="dashboardLink"' not in html
    assert 'id="dashboardView"' not in html
    assert 'id="notFoundView"' in html


def test_frontend_server_serves_forms_and_callback_but_not_dashboard():
    spec = spec_from_file_location("staff_frontend_app", FRONTEND_DIR / "app.py")
    assert spec and spec.loader
    frontend_app = module_from_spec(spec)
    spec.loader.exec_module(frontend_app)

    with TestClient(frontend_app.app) as client:
        assert client.get("/forms").status_code == 200
        assert client.get("/callback").status_code == 200
        dashboard_response = client.get("/dashboard")
        unknown_response = client.get("/page-that-does-not-exist")

    for response in (dashboard_response, unknown_response):
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")
        assert 'id="notFoundView"' in response.text


def test_caddy_serves_known_routes_normally_and_unknown_routes_with_404_shell():
    caddy_source = _source("Caddyfile")

    assert "handle /api/*" in caddy_source
    assert "handle /auth/*" in caddy_source
    assert "handle /static/*" in caddy_source
    assert "@spa_routes {" in caddy_source
    assert "\t\tpath / /callback /forms" in caddy_source
    assert "/forms/*" in caddy_source
    assert "/reservations/*" in caddy_source
    assert "/admin/cms/pages/*" in caddy_source

    spa_handler = caddy_source.split("handle @spa_routes", maxsplit=1)[1].split(
        "handle {", maxsplit=1
    )[0]
    unknown_handler = caddy_source.rsplit("handle {", maxsplit=1)[1]

    assert "rewrite * /index.html" in spa_handler
    assert "status 404" not in spa_handler
    assert "rewrite * /index.html" in unknown_handler
    assert "status 404" in unknown_handler


def test_frontend_gateway_logs_exclude_authentication_secrets():
    caddy_source = _source("Caddyfile")
    coraza_source = _source("coraza.conf")

    assert "SecRuleEngine On" in coraza_source
    assert "SecAuditEngine RelevantOnly" in coraza_source
    assert "SecAuditLogParts AKZ" in coraza_source

    audit_parts = coraza_source.split("SecAuditLogParts ", maxsplit=1)[1].splitlines()[0]
    assert not set(audit_parts).intersection("BCDEFIJH")

    assert "format filter" in caddy_source
    assert "request>uri query" in caddy_source
    for query_parameter in ("code", "state", "session_state"):
        assert f"replace {query_parameter} REDACTED" in caddy_source