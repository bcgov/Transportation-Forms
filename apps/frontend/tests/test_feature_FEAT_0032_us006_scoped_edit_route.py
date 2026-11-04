"""Source contracts for the scoped manager edit-route entry point."""

from pathlib import Path

ROUTER = Path(__file__).resolve().parents[1] / "js" / "router.js"


def _route_guard(source: str, condition: str) -> str:
    return source.split(condition, 1)[1].split("\n  }", 1)[0].strip()


def test_edit_route_accepts_scoped_manager_or_existing_edit_permission() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    guard = _route_guard(source, "if (path.startsWith('/edit/')) {")
    assert " ".join(guard.split()) == (
        "return hasPermission('form:edit') || "
        "hasPermission('form:edit:own') || "
        "hasPermission('form:edit:business_area') || "
        "hasPermission('form:edit:any') || "
        "hasPermission('form:approve');"
    )
    assert "if (!hasValidAuthorizationContext())" in source


def test_scoped_edit_permission_does_not_grant_other_operational_routes() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    protected_routes = {
        "if (path === ROUTES.FORM_CREATE) {": "form:create",
        "if (path === ROUTES.RESERVE) {": "reservation:create",
        "if (path === ROUTES.MY_RESERVATIONS) {": "reservation:read",
    }
    for condition, permission in protected_routes.items():
        guard = _route_guard(source, condition)
        assert guard == f"return hasPermission('{permission}');"
