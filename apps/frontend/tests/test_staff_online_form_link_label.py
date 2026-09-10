"""Regression contracts for staff-facing online form link labels."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_staff_hyperlink_actions_use_online_form_label() -> None:
    forms_list = _source("js/views/forms-list.js")
    drawer = _source("js/shared/form-details-drawer.js")

    assert 'aria-hidden="true"></i> Online Form</a>' in forms_list
    assert 'aria-hidden="true"></i> Online Form\'' in drawer
    assert 'aria-hidden="true"></i> Form Link</a>' not in forms_list
    assert 'aria-hidden="true"></i> Form link\'' not in drawer


def test_staff_hyperlink_action_behavior_is_unchanged() -> None:
    forms_list = _source("js/views/forms-list.js")
    drawer = _source("js/shared/form-details-drawer.js")

    assert 'href="${href}" target="_blank" rel="noopener noreferrer"' in forms_list
    assert 'data-action="open-form-link"' in forms_list
    assert "link.href = form.form_source_url.trim()" in drawer
    assert "link.target = '_blank'" in drawer
    assert "link.rel = 'noopener noreferrer'" in drawer