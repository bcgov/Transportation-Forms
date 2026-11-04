"""FEAT-0032 US-005: admin user-detail Business Area Manager area selection.

Source-contract checks for the role-assignment UI. Browser behaviour
(TC-005.1/TC-005.2) is verified with Playwright after deployment.
"""

import re
from pathlib import Path

USERS_JS = Path(__file__).resolve().parents[1] / "js" / "views" / "admin" / "users.js"


def _source() -> str:
    return USERS_JS.read_text(encoding="utf-8")


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    next_function = re.search(
        r"\n(?:export )?(?:async )?function ", source[start + 1 :]
    )
    end = start + 1 + next_function.start() if next_function else len(source)
    return source[start:end]


def test_active_business_areas_are_loaded_from_active_only_endpoint():
    body = _function_body(_source(), "async function _fetchActiveBusinessAreas()")

    assert "`${API_BASE}/business-areas`" in body
    assert "return null" in body


def test_selection_is_an_accessible_required_checkbox_group():
    body = _function_body(_source(), "function _renderBusinessAreaSelection(")

    assert '<fieldset id="userBusinessAreasFieldset"' in body
    assert "<legend" in body
    assert "(required)" in body
    assert 'aria-describedby="userBusinessAreasHelp userBusinessAreasError"' in body
    assert 'role="alert"' in body
    assert 'class="form-check-input user-business-area-checkbox"' in body
    assert "${visible ? '' : 'hidden'}" in body


def test_existing_contact_areas_are_locked_and_selected():
    body = _function_body(_source(), "function _renderBusinessAreaSelection(")

    assert "isExisting ? 'checked disabled' : ''" in body
    assert "(existing contact)" in body
    assert "Removing the role does not remove contacts" in body


def test_area_names_and_ids_are_escaped():
    body = _function_body(_source(), "function _renderBusinessAreaSelection(")

    assert "escapeHtml(area.id)" in body
    assert "escapeHtml(area.name)" in body


def test_selection_visibility_follows_business_area_manager_checkbox():
    source = _source()
    detail = _function_body(source, "export async function loadUserDetail(userId)")

    assert 'data-role-name="${escapeHtml(role.name)}"' in detail
    assert "input.dataset.roleName === BUSINESS_AREA_MANAGER_ROLE" in detail
    assert "_toggleBusinessAreaSelection(input.checked)" in detail
    assert "user.contact_business_areas" in detail


def test_save_requires_an_area_and_sends_ids_only_with_the_role():
    body = _function_body(_source(), "export async function saveUserRoles()")

    assert "if (managerSelected) {" in body
    assert ".user-business-area-checkbox:checked" in body
    assert "if (!selectedAreaIds.length) {" in body
    assert "_setBusinessAreaError(BUSINESS_AREA_REQUIRED_MESSAGE);" in body
    required_branch = body[body.index("if (!selectedAreaIds.length) {") :]
    assert required_branch.index("return;") < required_branch.index("fetch(")
    assert "payload.business_area_ids = selectedAreaIds;" in body
    assert "body: JSON.stringify(payload)" in body
