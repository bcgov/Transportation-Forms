"""US-003: Edit Form submits, while Approvals owns review actions."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def test_edit_form_has_no_approval_controls_or_reject_modal():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    view = (FRONTEND / "js/views/forms-create.js").read_text(encoding="utf-8")

    for control in ("approvePublishBtn", "rejectFormBtn", "formRejectModal"):
        assert f'id="{control}"' not in html
        assert control not in view
    assert 'id="approvalsFormRejectModal"' in html


def test_submit_success_shows_feedback_then_returns_to_forms_list():
    view = (FRONTEND / "js/views/forms-create.js").read_text(encoding="utf-8")
    success = view.split("function _markSubmitted() {", 1)[1].split("\n}", 1)[0]

    assert "_updateWorkflowButtons(_currentFormStatus)" in success
    assert "_showSubmitMessage('Form submitted for review successfully.'" in success
    assert "showAlert('Form submitted for review successfully.', 'success')" in success
    assert "setTimeout(() => _navigate(ROUTES.FORMS_LIST), 1500)" in success
    assert view.count("_markSubmitted();") == 2