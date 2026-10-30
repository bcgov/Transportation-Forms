"""FEAT-0032 regression: list cards must render server-authorized actions.

The forms list normalizes API items before rendering. If the normalizer drops
``available_actions`` every card renders an empty action group, and Published
forms must still expose an Edit entry point to the editor's Unpublish control.
"""

import re
from pathlib import Path

VIEWS = Path(__file__).resolve().parents[1] / "js" / "views"


def _forms_list_source() -> str:
    return (VIEWS / "forms-list.js").read_text(encoding="utf-8")


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    next_function = re.search(r"\n(?:export )?function ", source[start + 1 :])
    end = start + 1 + next_function.start() if next_function else len(source)
    return source[start:end]


def test_normalizer_preserves_available_actions():
    body = _function_body(_forms_list_source(), "function _normalizeFormItem(item)")

    assert (
        "available_actions: _normalizeAvailableActions(item.available_actions)" in body
    )


def test_available_actions_are_limited_to_known_action_names():
    source = _forms_list_source()
    body = _function_body(source, "function _normalizeAvailableActions(actions)")
    known = re.search(r"KNOWN_FORM_ACTIONS = new Set\(\[(.*?)\]\)", source, re.S)

    assert "Array.isArray(actions)" in body
    assert "typeof action === 'string'" in body
    assert "KNOWN_FORM_ACTIONS.has(action)" in body
    assert known is not None
    for action in (
        "edit",
        "submit_for_review",
        "archive",
        "restore",
        "delete",
        "unpublish",
        "revert",
    ):
        assert f"'{action}'" in known.group(1)


def test_list_items_are_normalized_before_rendering():
    assert ".map(_normalizeFormItem)" in _forms_list_source()


def test_published_card_offers_edit_entry_point_when_revert_is_available():
    body = _function_body(
        _forms_list_source(), "export function _renderFormActionButtons(form)"
    )

    assert "availableActions.has('edit')" in body
    assert "status === 'published' && availableActions.has('revert')" in body
    assert "if (canOpenEditor)" in body
    assert 'data-route="/edit/${id}"' in body
    assert "availableActions.has('archive')" in body
