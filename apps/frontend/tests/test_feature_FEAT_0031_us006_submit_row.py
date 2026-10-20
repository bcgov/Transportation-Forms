"""Submitting changes workflow state without exposing a detail link."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def test_submission_keeps_history_summary_but_has_no_details_link():
    audit = (FRONTEND / "js/views/form-audit-history.js").read_text(encoding="utf-8")

    assert "'Form submitted': 'Submitted for review'" in audit
    assert "'Form submitted': 'submitted the saved form for review'" in audit
    assert "if (event.event_name !== 'Form created' && event.event_name !== 'Form submitted') {" in audit
    assert "summary.append(document.createTextNode(' '), details);" in audit
