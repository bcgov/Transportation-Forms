"""Source-contract coverage for FEAT-0030 US-009 search clearing."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_forms_search_uses_one_custom_clear_control():
    html = _source("index.html")
    list_view = html.split('<div id="listView"', maxsplit=1)[1].split(
        '<div id="createView"', maxsplit=1
    )[0]

    assert 'id="searchInput" type="text"' in list_view
    assert list_view.count('id="clearSearchButton"') == 1
    assert 'aria-label="Clear search"' in list_view


def test_empty_input_reloads_first_page_without_search_parameter():
    forms_js = _source("js/views/forms-list.js")

    assert "if (query.length === 0) searchForms();" in forms_js
    assert "export function searchForms()" in forms_js
    assert "_currentSkip = 0;" in forms_js
    assert "if (query) params.set('q', query);" in forms_js


def test_clear_button_keeps_focus_and_uses_existing_request_guards():
    forms_js = _source("js/views/forms-list.js")

    assert "input.value = '';" in forms_js
    assert "_dismissSearchSuggestions();" in forms_js
    assert "input.focus();" in forms_js
    assert "_formsRequestController?.abort();" in forms_js
    assert "if (signal.aborted) return;" in forms_js