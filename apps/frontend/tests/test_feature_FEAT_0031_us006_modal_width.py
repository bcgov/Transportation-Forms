"""Audit details use a wider modal without overriding mobile sizing."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def test_audit_modal_sets_only_bootstrap_max_width():
    css = (FRONTEND / "css/main.css").read_text(encoding="utf-8")
    audit = (FRONTEND / "js/views/form-audit-history.js").read_text(encoding="utf-8")

    assert "#auditDetailModal {\n    --bs-modal-width: 800px;\n}" in css
    assert "width: calc(100% - var(--bs-modal-margin) - var(--bs-modal-margin));" in css
    assert '<div class="modal fade" id="auditDetailModal"' in audit
    assert '<div class="modal-dialog modal-dialog-scrollable">' in audit
