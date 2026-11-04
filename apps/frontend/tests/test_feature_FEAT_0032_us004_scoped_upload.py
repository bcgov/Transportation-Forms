from pathlib import Path

VIEWS = Path(__file__).resolve().parents[1] / "js" / "views"


def test_edit_upload_uses_form_scoped_route_and_create_upload_stays_unscoped():
    upload = (VIEWS / "file-upload.js").read_text(encoding="utf-8")
    editor = (VIEWS / "forms-create.js").read_text(encoding="utf-8")

    assert "setUploadFormId(null)" in editor
    assert "setUploadFormId(formId)" in editor
    assert "encodeURIComponent(_uploadFormId)" in upload
    assert "${API_BASE}/forms/upload" in upload
    assert "}/upload`" in upload
    assert "if (contextVersion !== _uploadContextVersion) return;" in upload
    assert "clearUploadState();" in upload
    before_snapshot = upload.split("const contextVersion = _uploadContextVersion;", 1)[
        0
    ]
    upload_start = before_snapshot.split("export async function uploadFile(file) {", 1)[
        1
    ]
    assert "_uploadContextVersion += 1;" in upload_start
