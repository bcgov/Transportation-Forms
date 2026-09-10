"""Source contracts for FEAT-0030 US-012 Staff Forms sort options."""

from html.parser import HTMLParser
from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


class _SortOptionsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_sort_select = False
        self.current_option = None
        self.options = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "select" and attributes.get("id") == "sortOrder":
            self.in_sort_select = True
        elif tag == "option" and self.in_sort_select:
            self.current_option = {
                "value": attributes.get("value"),
                "selected": "selected" in attributes,
                "label": "",
            }

    def handle_data(self, data):
        if self.current_option is not None:
            self.current_option["label"] += data

    def handle_endtag(self, tag):
        if tag == "option" and self.current_option is not None:
            self.current_option["label"] = self.current_option["label"].strip()
            self.options.append(self.current_option)
            self.current_option = None
        elif tag == "select" and self.in_sort_select:
            self.in_sort_select = False


def _sort_options():
    parser = _SortOptionsParser()
    parser.feed(_source("index.html"))
    return parser.options


def test_sort_control_contains_exact_approved_options_in_order():
    assert [
        (option["value"], option["label"]) for option in _sort_options()
    ] == [
        ("suggested:desc", "Suggested"),
        ("title:asc", "Form Title A-Z"),
        ("title:desc", "Form Title Z-A"),
        ("form_number:asc", "Form Number A-Z"),
        ("form_number:desc", "Form Number Z-A"),
    ]


def test_suggested_is_the_only_selected_sort_option():
    assert [
        option["value"] for option in _sort_options() if option["selected"]
    ] == ["suggested:desc"]


def test_legacy_date_created_options_are_absent():
    options = _sort_options()

    assert all("Date Created" not in option["label"] for option in options)
    assert all(not option["value"].startswith("created_at:") for option in options)


def test_sort_source_declares_exact_allowlist_and_default():
    constants = _source("js/constants.js")

    assert "export const DEFAULT_FORMS_SORT = 'suggested:desc';" in constants
    for value in (
        "title:asc",
        "title:desc",
        "form_number:asc",
        "form_number:desc",
    ):
        assert f"'{value}'" in constants
    assert "created_at:" not in constants


def test_invalid_sort_state_is_normalized_before_request_serialization():
    forms_js = _source("js/views/forms-list.js")

    normalize_position = forms_js.index("const sortValue = _normalizeSortSelection")
    split_position = forms_js.index("const [sortField, sortDir] = sortValue.split")
    request_position = forms_js.index("params.set('sort_field', sortField)")

    assert "FORMS_SORT_OPTIONS.includes(candidate)" in forms_js
    assert "sortSelect.value = normalized" in forms_js
    assert normalize_position < split_position < request_position
    assert "created_at:asc" not in forms_js
    assert "created_at:desc" not in forms_js


def test_sort_change_uses_single_first_page_reload_path():
    forms_js = _source("js/views/forms-list.js")
    apply_filters = forms_js.split(
        "export function applyFilters()", maxsplit=1
    )[1].split("// ── Private helpers", maxsplit=1)[0]

    assert apply_filters.count("_currentSkip = 0;") == 1
    assert apply_filters.count("loadForms();") == 1
    assert (
        "getElementById('sortOrder')?.addEventListener('change', applyFilters)"
        in forms_js
    )