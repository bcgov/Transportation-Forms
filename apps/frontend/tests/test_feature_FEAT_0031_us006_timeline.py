"""Source contracts for the value-free, mockup-inspired audit timeline."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def test_unnumbered_timeline_keeps_absolute_pct_and_cursor_order():
    audit = source("js/views/form-audit-history.js")
    css = source("css/main.css")

    assert '<ul id="auditHistoryList" class="form-audit__timeline"' in audit
    assert 'document.createElement(\'li\')' in audit
    assert "list.append(item)" in audit
    assert "time.dateTime = date.toISOString()" in audit
    assert "PCT" in audit
    assert ".form-audit__timeline {" in css
    assert "list-style: none;" in css
    assert ".form-audit__event:not(:last-child)::after" in css
    assert "--audit-time-column: 82px;" in css


def test_inline_link_opens_protected_modal_without_exposing_values_in_rows():
    audit = source("js/views/form-audit-history.js")

    assert "const details = document.createElement('a');" in audit
    assert "details.href = '#auditDetailModal';" in audit
    assert "summary.append(document.createTextNode(' '), details);" in audit
    assert "event.preventDefault();" in audit
    assert "openDetails(detail.dataset.auditDetail, detail);" in audit
    assert "trigger.isConnected && trigger.focus()" in audit
    assert "event.old_values" not in audit
    assert "event.new_values" not in audit


def test_event_summaries_use_field_names_and_event_type_without_values():
    audit = source("js/views/form-audit-history.js")

    assert "event.changed_fields.every(field => sourceFields.has(field))" in audit
    assert "sourceOnly ? 'Form source updated' : 'Form details saved'" in audit
    assert "'Form submitted': 'submitted the saved form for review'" in audit
    assert "'Form approved': 'approved the form'" in audit
    assert "Changed fields: ${fields}" in audit
    assert "fieldNames(event.changed_fields)" in audit
    assert "actor.textContent = event.actor_label;" in audit
    assert "fieldLabel(field).toLowerCase().replace(/\\burl\\b/g, 'URL')" in audit
