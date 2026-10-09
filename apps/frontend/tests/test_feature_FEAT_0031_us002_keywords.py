"""Source contracts for the FEAT-0031 keyword widget before browser testing."""

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_enter_and_add_share_keyword_validation_without_submitting():
    widget = _source("js/views/keywords.js")
    form = _source("js/views/forms-create.js")

    assert "event.key === 'Enter'" in widget
    assert "event.preventDefault()" in widget
    assert "addKeyword();" in widget
    assert "clone.addEventListener('click', addKeyword);" in form
    assert "isComposing" not in widget


def test_keywords_validate_trimmed_casefolded_length_and_controls():
    widget = _source("js/views/keywords.js")

    assert "input.value.trim()" in widget
    assert "Array.from(keyword).length > 50" in widget
    assert "toLocaleLowerCase('en-US')" in widget
    assert "[\\x00-\\x1f\\x7f-\\x9f]" in widget
    assert "input.focus()" in widget


def test_keyword_controls_and_feedback_are_accessible_and_locked():
    widget = _source("js/views/keywords.js")
    form = _source("js/views/forms-create.js")
    html = _source("index.html")

    assert 'id="keywordFeedback"' in html
    assert 'role="status"' in html
    assert 'aria-label="Keyword status"' in html
    assert 'role="list" aria-label="Form keywords"' in html
    assert 'aria-describedby="keywordFeedback"' in html
    assert 'aria-label="Add keyword"' in html
    assert "data-keyword-index" in widget
    assert "document.createElement('button')" in widget
    assert "tag.setAttribute('role', 'listitem')" in widget
    assert "input.disabled" in widget
    assert "setKeywordsLocked(locked)" in form
    assert "!hasPermission('form:create')" in form
    assert "!hasPermission('form:edit')" in form


def test_unchanged_legacy_keywords_are_not_resubmitted_on_edit():
    form = _source("js/views/forms-create.js")

    assert "_loadedKeywords = getKeywords();" in form
    assert "JSON.stringify(getKeywords()) !==" in form
    assert "JSON.stringify(_loadedKeywords)" in form
