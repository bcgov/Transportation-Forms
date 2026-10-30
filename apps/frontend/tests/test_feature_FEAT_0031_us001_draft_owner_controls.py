"""Form actions are presented from the server's authorization result."""

from pathlib import Path


VIEWS = Path(__file__).resolve().parents[1] / "js" / "views"


def test_form_controls_use_server_authorized_actions():
    forms_list = (VIEWS / "forms-list.js").read_text(encoding="utf-8")
    forms_create = (VIEWS / "forms-create.js").read_text(encoding="utf-8")

    assert "new Set(form.available_actions)" in forms_list
    assert "availableActions.has('edit')" in forms_list
    assert "availableActions.has('submit_for_review')" in forms_list
    assert "availableActions.has('restore')" in forms_list
    assert "actions.has('edit')" in forms_create
    assert "actions.has('submit_for_review')" in forms_create
    assert "actions.has('restore')" in forms_create
    assert "_currentFormAvailableActions.includes('edit')" in forms_create


def test_business_area_manager_has_a_friendly_role_label():
    constants = (VIEWS.parent / "constants.js").read_text(encoding="utf-8")
    roles = (VIEWS / "admin" / "roles.js").read_text(encoding="utf-8")
    users = (VIEWS / "admin" / "users.js").read_text(encoding="utf-8")

    assert "['business_area_manager', 'Business Area Manager']" in constants
    assert "ROLE_DISPLAY_NAMES.get(role.name) || role.name" in roles
    assert "ROLE_DISPLAY_NAMES.get(role.name) || role.name" in users