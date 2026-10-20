"""Contracts for protected audit detail comparisons."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def test_each_changed_field_has_a_centered_two_column_comparison():
    audit = source("js/views/form-audit-history.js")
    css = source("css/main.css")

    assert "field.className = 'form-audit__field';" in audit
    assert "title.textContent = fieldLabel(change.field);" in audit
    assert "comparison.className = 'form-audit__comparison';" in audit
    assert "comparisonColumn('Previous', valueNode(change.old_value))" in audit
    assert "comparisonColumn('New', valueNode(change.new_value))" in audit
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert "text-align: center;" in css
    assert "text-transform: capitalize;" in css


def test_keywords_show_only_removed_and_added_values_as_text():
    audit = source("js/views/form-audit-history.js")

    assert "if (change.field === 'keywords')" in audit
    assert "before.filter(keyword => !afterSet.has(keyword))" in audit
    assert "after.filter(keyword => !beforeSet.has(keyword))" in audit
    assert "comparisonColumn('Removed', keywordList(removed))" in audit
    assert "comparisonColumn('Added', keywordList(added))" in audit
    assert "item.textContent = keyword;" in audit
    assert "if (!keywords.length) return valueNode('None');" in audit
    assert "Invalid keyword audit values" in audit
