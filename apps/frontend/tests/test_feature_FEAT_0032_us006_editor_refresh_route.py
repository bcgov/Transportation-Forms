"""Source contracts for preserving an authorized editor on context refresh."""

from pathlib import Path
import re

ROUTER = Path(__file__).resolve().parents[1] / "js" / "router.js"


def _refresh_listener() -> str:
    source = ROUTER.read_text(encoding="utf-8")
    match = re.search(
        r"window\.addEventListener\('auth:authorization-refreshed', \(\) => \{"
        r"(.*?)\n  \}\);",
        source,
        re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def test_refresh_preserves_only_a_mounted_authorized_editor() -> None:
    body = _refresh_listener()
    assert "currentPath.startsWith('/edit/')" in body
    assert "document.getElementById('createView')?.style.display === 'block'" in body
    assert "if (editorOpen && _canAccessOperationalRoute(currentPath))" in body
    assert re.search(r"\{\s*updateNavbar\(\);\s*return;\s*\}", body)


def test_other_or_denied_routes_still_reenter_the_authorization_guards() -> None:
    body = _refresh_listener()
    assert body.rstrip().endswith("routeHandler(currentPath);")
    assert body.index("_canAccessOperationalRoute(currentPath)") < body.index(
        "routeHandler(currentPath);"
    )
    assert "resetFormState" not in body
    assert "showEditView" not in body


def test_session_expiry_navigation_handles_route_failures() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    assert "void navigateTo(ROUTES.HOME).catch(() => {" in source
    assert (
        "Unable to return to the Forms page. Refresh the page and try again."
        in source
    )
