"""Source contracts for FEAT-0030 US-007 denied callback destinations."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_registered_route_is_stored_then_guarded_after_callback() -> None:
    router = _source("js/router.js")
    unauthenticated_guard = router.split(
        "if (!isAuthenticated() && path !== ROUTES.CALLBACK)", maxsplit=1
    )[1].split("if (isAuthenticated() && !_canAccessOperationalRoute(path))", maxsplit=1)[
        0
    ]

    assert "_isRegisteredRoute(path)" in unauthenticated_guard
    assert "path !== ROUTES.HOME" in unauthenticated_guard
    assert "path !== ROUTES.CALLBACK" in unauthenticated_guard
    assert "sessionStorage.setItem('tf_return_url', path)" in unauthenticated_guard

    route_handler = router.split(
        "export async function routeHandler(path, params = {})", maxsplit=1
    )[1].split("export function initRouter()", maxsplit=1)[0]
    permission_guard = route_handler.index(
        "if (isAuthenticated() && !_canAccessOperationalRoute(path))"
    )
    route_dispatch = route_handler.index("// ── Route dispatch")

    assert permission_guard < route_dispatch
    assert "_currentRoute = 'not-found'" in route_handler[
        permission_guard:route_dispatch
    ]


def test_callback_consumes_only_safe_internal_registered_destination() -> None:
    auth = _source("js/auth.js")
    sanitizer = auth.split("function _getSafeInternalReturnUrl(value)", maxsplit=1)[
        1
    ].split("// ─── Exported auth API", maxsplit=1)[0]
    callback = auth.split(
        "export async function handleAuthCallback()", maxsplit=1
    )[1].split("export async function signOut()", maxsplit=1)[0]

    assert "value.startsWith('//')" in sanitizer
    assert "url.origin !== window.location.origin" in sanitizer
    assert "route !== ROUTES.HOME && route !== ROUTES.CALLBACK" in sanitizer
    assert "const returnUrl = _consumeStoredReturnUrl();" in callback
    assert "dest = _getSafeInternalReturnUrl(returnUrl) || dest;" in callback
    assert "window.dispatchEvent(new CustomEvent('auth:callback-complete'))" in callback