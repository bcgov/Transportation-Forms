from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.main import app


def test_upload_failure_does_not_expose_storage_error_details(caplog):
    token = TokenData(
        sub="00000000-0000-0000-0000-000000000001",
        email="staff@example.invalid",
        name="Staff User",
        roles=["staff"],
    )
    app.dependency_overrides[get_current_user] = lambda: token

    try:
        with patch(
            "backend.routes.forms.s3_service.upload_file",
            side_effect=RuntimeError("private-endpoint/internal-bucket"),
        ):
            response = TestClient(app).post(
                "/api/v1/forms/upload",
                files={"file": ("test.pdf", b"content", "application/pdf")},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 500
    assert response.json() == {"detail": "File upload failed"}
    assert "private-endpoint" not in response.text
    assert "internal-bucket" not in response.text
    assert "Form attachment upload failed" in caplog.text
    assert "private-endpoint" not in caplog.text
    assert "internal-bucket" not in caplog.text
