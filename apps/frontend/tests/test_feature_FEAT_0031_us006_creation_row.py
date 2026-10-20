"""Creation activity is a timeline entry without change details."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def test_creation_row_omits_changed_field_summary_and_details_link():
    audit = (FRONTEND / "js/views/form-audit-history.js").read_text(encoding="utf-8")

    assert "summary: 'created this form as a draft.'" in audit
    assert "if (event.event_name !== 'Form created' && event.event_name !== 'Form submitted') {" in audit
    assert "fieldsNote" not in audit
    assert "Initial fields:" not in audit


def test_non_creation_details_remain_inline_and_protected():
    audit = (FRONTEND / "js/views/form-audit-history.js").read_text(encoding="utf-8")

    assert "const details = document.createElement('a');" in audit
    assert "summary.append(document.createTextNode(' '), details);" in audit
    assert "openDetails(detail.dataset.auditDetail, detail);" in audit
