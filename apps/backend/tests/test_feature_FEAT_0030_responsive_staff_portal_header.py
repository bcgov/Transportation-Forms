"""Contract coverage for FEAT-0030 US-002 Staff portal header."""

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_header_uses_existing_bootstrap_hooks_and_accessible_identity():
    html = _source("index.html")

    assert 'class="staff-header"' in html
    assert html.count('aria-label="Transportation Forms home"') == 2
    assert (
        'alt="Government of British Columbia, '
        'Ministry of Transportation and Transit"' in html
    )
    assert 'id="navMenuToggle"' in html
    assert 'id="authDropdown"' in html
    auth_dropdown_tag = html.split('id="authDropdown"', maxsplit=1)[1].split(
        ">", maxsplit=1
    )[0]
    nav_toggle_tag = html.split('id="navMenuToggle"', maxsplit=1)[1].split(
        ">", maxsplit=1
    )[0]
    assert 'data-bs-toggle="dropdown"' in auth_dropdown_tag
    assert 'data-bs-toggle="dropdown"' not in nav_toggle_tag
    assert 'aria-controls="staffSidebar"' in nav_toggle_tag
    assert 'data-action="sign-out"' in html


def test_authenticated_controls_are_hidden_by_default():
    html = _source("index.html")

    assert 'id="sidebarToggleContainer" hidden style="display:none;"' in html
    assert 'id="staffSidebar" aria-label="Primary navigation"' in html
    assert 'aria-hidden="true" hidden inert' in html
    assert 'id="authDropdownContainer" hidden style="display:none;"' in html
    assert 'id="authUserRole" hidden' in html


def test_header_contains_inert_bookmarks_and_no_role_preview():
    html = _source("index.html")

    assert 'id="bookmarksPlaceholder" type="button"' in html
    bookmarks_markup = html.split('id="bookmarksPlaceholder"', maxsplit=1)[1]
    bookmarks_tag = bookmarks_markup.split(">", maxsplit=1)[0]
    assert "href=" not in bookmarks_tag
    assert "data-route=" not in bookmarks_tag
    assert "data-action=" not in bookmarks_tag
    assert "role-preview" not in html
    assert "data-preview-role" not in html


def test_header_css_is_responsive_and_not_fixed():
    css = _source("css/main.css")
    header_styles = css.split(".staff-header {", maxsplit=1)[1]
    header_rule = header_styles.split("}", maxsplit=1)[0]

    assert "position: relative" in header_rule
    assert "position: fixed" not in header_rule
    assert "position: sticky" not in header_rule
    assert 'grid-template-areas: "navigation brand account";' in css
    assert '"brand brand brand"' in css
    assert '"navigation title account"' in css
    assert "@media (max-width: 767.98px)" in css


def test_auth_ui_safely_renders_identity_and_admin_only_role():
    auth_js = _source("js/auth.js")
    update_ui = auth_js.split("export function updateAuthUi()", maxsplit=1)[1]

    assert "typeof user?.name === 'string'" in update_ui
    assert "rawDisplayName.slice(0, 100) || 'Signed in'" in update_ui
    assert "authUserDisplay.textContent = displayName" in update_ui
    assert "authUserInitials.textContent = initials" in update_ui
    assert "authUserRole.textContent = isAdmin ? 'Admin' : ''" in update_ui
    assert "authUserDisplay.innerHTML" not in update_ui
    assert "user?.email" not in update_ui


def test_navigation_visibility_uses_existing_granular_permissions():
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

    for link_id in (
        "approvalsLink",
        "manageFormsLink",
        "createFormLink",
        "reserveNumberLink",
        "myReservationsLink",
    ):
        assert f"{link_id}:" in auth_js


def test_header_does_not_hard_code_mockup_user_identity():
    html = _source("index.html")

    assert "Raghu Mohindru" not in html
    assert ">RM<" not in html
