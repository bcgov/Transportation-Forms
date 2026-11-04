import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import UserRole


def test_upload_failure_does_not_expose_storage_error_details(
    caplog, db, user_factory, role_factory
):
    user = user_factory()
    role = role_factory(
        name=f"upload_{uuid.uuid4().hex}", permissions=["form:create"]
    )
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()
    token = TokenData(
        sub=str(user.id),
        email=user.email,
        name="Staff User",
        roles=[role.name],
    )
    app.dependency_overrides[get_current_user] = lambda: token
    app.dependency_overrides[get_db] = lambda: db

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
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 500
    assert response.json() == {"detail": "File upload failed"}
    assert "private-endpoint" not in response.text
    assert "internal-bucket" not in response.text
    assert "Form attachment upload failed" in caplog.text
    assert "private-endpoint" not in caplog.text
    assert "internal-bucket" not in caplog.text
