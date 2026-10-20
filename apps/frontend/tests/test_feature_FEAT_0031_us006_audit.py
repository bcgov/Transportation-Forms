"""Source contracts for permission-gated form audit presentation."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def test_audit_only_mounts_for_edit_with_both_permissions():
    form = source("js/views/forms-create.js")
    audit = source("js/views/form-audit-history.js")
    html = source("index.html")

    assert "loadAuditHistory(formId);" in form
    assert "clearAuditHistory();" in form
    assert "if (!hasPermission('form:audit') || !hasPermission('form:edit')) return;" in audit
    assert '<div id="auditHistoryMount"></div>' in html
    assert "Audit History" not in html


def test_audit_history_has_bounded_pagination_and_safe_rendering():
    audit = source("js/views/form-audit-history.js")

    assert "url.searchParams.set('limit', '10')" in audit
    assert "url.searchParams.set('cursor', cursor)" in audit
    assert "getJson(url.toString())" in audit
    assert "list.append(item)" in audit
    assert "more.hidden = !nextCursor" in audit
    assert "summary.append(actor, document.createTextNode" in audit
    assert "node.textContent =" in audit
    assert "time.dateTime = date.toISOString()" in audit
    assert "const shifted = new Date(date.getTime() - 7 * 60 * 60 * 1000)" in audit
    assert "details.setAttribute('aria-label'" in audit
    assert "trigger.isConnected && trigger.focus()" in audit


def test_audit_loading_and_errors_clear_protected_values():
    audit = source("js/views/form-audit-history.js")

    assert "ticket !== generation" in audit
    assert "document.getElementById('auditLastEdited').replaceChildren()" in audit
    assert "document.getElementById('auditHistoryList').replaceChildren()" in audit
    assert "No audit history" in audit
    assert "Audit history unavailable." in audit
    assert "Unable to load audit history." in audit
    assert "Retry audit history" in audit
