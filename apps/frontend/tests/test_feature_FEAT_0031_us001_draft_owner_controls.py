"""Draft editing controls must match backend creator-only authorization."""

from pathlib import Path


VIEWS = Path(__file__).resolve().parents[1] / "js" / "views"


def test_draft_edit_controls_require_creator():
    forms_list = (VIEWS / "forms-list.js").read_text(encoding="utf-8")
    forms_create = (VIEWS / "forms-create.js").read_text(encoding="utf-8")

    assert "(status === 'draft' && isOwner)" in forms_list
    assert "status === 'published'" in forms_list
    assert "isOwner && hasPermission('form:edit')" in forms_create
    assert "_currentFormCreatedById !== getCurrentUser()?.id" in forms_create