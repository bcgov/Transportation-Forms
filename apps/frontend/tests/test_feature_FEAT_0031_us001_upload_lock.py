"""Source contract for upload controls in read-only form views."""

from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1]


def test_locked_form_disables_upload_controls_and_handlers():
    form = (FRONTEND / "js/views/forms-create.js").read_text(encoding="utf-8")
    upload = (FRONTEND / "js/views/file-upload.js").read_text(encoding="utf-8")

    assert "fileInput.disabled = locked" in form
    assert "dropZone.tabIndex = locked ? -1 : 0" in form
    assert "dropZone.setAttribute('aria-disabled', String(locked))" in form
    assert "clearFileBtn.disabled = locked" in form
    assert "if (fileInput && !fileInput.disabled) fileInput.click();" in upload
    assert "if (document.getElementById('fileInput')?.disabled) return;" in upload