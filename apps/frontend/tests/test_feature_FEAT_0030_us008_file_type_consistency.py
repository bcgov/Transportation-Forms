"""Regression contracts for FEAT-0030 US-008 source-type consistency."""

from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_forms_list_and_details_drawer_share_source_type_labels() -> None:
    utils = _source("js/utils.js")
    forms_list = _source("js/views/forms-list.js")
    drawer = _source("js/shared/form-details-drawer.js")
    drawer_label_assignment = (
        "elements.fileType.textContent = getFormSourceTypeLabel(form);"
    )

    assert "export function getFormSourceTypeLabel(form)" in utils
    assert "return 'Online form';" in utils
    assert "getFormSourceTypeLabel(form)" in forms_list
    assert drawer_label_assignment in drawer
