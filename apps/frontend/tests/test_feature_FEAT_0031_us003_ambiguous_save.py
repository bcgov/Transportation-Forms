"""An uncertain form update must not be retried with a stale version."""

from pathlib import Path


FORM_VIEW = (
    Path(__file__).resolve().parents[1] / "js" / "views" / "forms-create.js"
)


def test_submit_recovery_requires_reload_after_uncertain_save():
    source = FORM_VIEW.read_text(encoding="utf-8")
    submit = source.split("async function _submitFormForReview()", 1)[1].split(
        "async function _archiveForm()", 1
    )[0]

    assert "saveOutcomeUncertain = true;" in submit
    assert "if (update.status < 500) saveOutcomeUncertain = false;" in submit
    assert "if (saveOutcomeUncertain) _submitNeedsReload = true;" in submit
    assert "Save outcome could not be confirmed. Reload and reconcile before submitting again." in submit


def test_ordinary_edit_save_blocks_retry_when_response_is_lost():
    source = FORM_VIEW.read_text(encoding="utf-8")
    save = source.split("export async function handleFormSubmit(event)", 1)[1].split(
        "export function resetFormState()", 1
    )[0]

    assert save.index("let saveOutcomeUncertain = false;") < save.index("    try {")
    assert "saveOutcomeUncertain = true;" in save
    assert "if (response.status < 500) saveOutcomeUncertain = false;" in save
    assert "if (saveOutcomeUncertain) {\n            _submitNeedsReload = true;" in save
    assert "Save outcome could not be confirmed. Reload and reconcile before saving again." in save