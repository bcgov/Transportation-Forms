"""FEAT-0002: Integration / API tests for file_type persistence and retrieval.

Covers:
- TC1.10: file_type persisted on form creation (Download source)
- TC1.11: file_type null for URL-source forms
- TC1.12: file_type updated when attachment replaced
- TC1.13: file_type cleared when attachment removed
- TC1.14: Pre-existing records have null file_type
- TC2.1:  GET /forms returns file_type for attached forms
- TC2.2:  GET /forms returns null file_type for URL-source forms
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData


@pytest.fixture()
def ft_client(db, user_factory):
    """TestClient wired for file_type integration tests."""
    user = user_factory(email="ft_user@example.com")
    token = TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        roles=["staff"],
        token_type="access",
        permissions=["form:read", "form:create", "form:edit"],
    )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token

    client = TestClient(app)
    yield client

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _create_download_form(client, *, file_type="pdf", title="Download Form"):
    """Create a form with form_source='Download' and a given file_type."""
    return client.post(
        "/api/v1/forms",
        json={
            "title": title,
            "description": "Form with file attachment.",
            "is_public": False,
            "form_source": "Download",
            "form_attachment_url": "uploads/fake-key.pdf",
            "form_attachment_filename": "test.pdf",
            "file_type": file_type,
        },
    )


def _create_url_form(client, *, title="URL Form"):
    """Create a form with form_source='URL' (no attachment)."""
    return client.post(
        "/api/v1/forms",
        json={
            "title": title,
            "description": "Form with URL source.",
            "is_public": True,
            "form_source": "URL",
            "form_source_url": "https://example.com/form.pdf",
        },
    )


# ── TC1.10: file_type persisted on create ──────────────────────────────────────


@pytest.mark.integration
def test_create_download_form_stores_file_type(ft_client):
    """TC1.10: file_type = 'pdf' is persisted on create with Download source."""
    resp = _create_download_form(ft_client, file_type="pdf")
    assert resp.status_code == 201
    data = resp.json()
    assert data["file_type"] == "pdf"


@pytest.mark.integration
def test_create_download_form_stores_unknown_file_type(ft_client):
    """file_type = 'unknown' is accepted and stored."""
    resp = _create_download_form(ft_client, file_type="unknown")
    assert resp.status_code == 201
    assert resp.json()["file_type"] == "unknown"


# ── TC1.11: file_type null for URL-source forms ───────────────────────────────


@pytest.mark.integration
def test_create_url_form_has_null_file_type(ft_client):
    """TC1.11: URL-source form stores file_type = null."""
    resp = _create_url_form(ft_client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["file_type"] is None


@pytest.mark.integration
def test_url_form_ignores_supplied_file_type(ft_client):
    """TC1.18: file_type supplied for a URL-source form is discarded."""
    resp = ft_client.post(
        "/api/v1/forms",
        json={
            "title": "URL Form With File Type",
            "description": "Should ignore file_type.",
            "is_public": False,
            "form_source": "URL",
            "form_source_url": "https://example.com/form.pdf",
            "file_type": "pdf",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["file_type"] is None


# ── TC1.12: file_type updated when attachment replaced ─────────────────────────


@pytest.mark.integration
def test_update_form_replaces_file_type(ft_client):
    """TC1.12: Replacing the attachment updates file_type."""
    create_resp = _create_download_form(ft_client, file_type="pdf")
    assert create_resp.status_code == 201
    form_id = create_resp.json()["id"]

    update_resp = ft_client.put(
        f"/api/v1/forms/{form_id}",
        json={
            "form_attachment_url": "uploads/new-key.docx",
            "form_attachment_filename": "report.docx",
            "file_type": "docx",
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["file_type"] == "docx"


# ── TC1.13: file_type cleared when attachment removed ──────────────────────────


@pytest.mark.integration
def test_update_form_clears_file_type_on_attachment_removal(ft_client):
    """TC1.13: Removing attachment sets file_type to null."""
    create_resp = _create_download_form(ft_client, file_type="pdf")
    assert create_resp.status_code == 201
    form_id = create_resp.json()["id"]

    update_resp = ft_client.put(
        f"/api/v1/forms/{form_id}",
        json={
            "form_source": "URL",
            "form_source_url": "https://example.com",
            "form_attachment_url": None,
            "form_attachment_filename": None,
            "file_type": None,
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["file_type"] is None


# ── TC1.14: Existing records have null file_type ───────────────────────────────


@pytest.mark.integration
def test_existing_form_without_file_type_returns_null(ft_client):
    """TC1.14: Form created without file_type field still returns null."""
    resp = ft_client.post(
        "/api/v1/forms",
        json={
            "title": "Legacy Form",
            "description": "Created before FEAT-0002.",
            "is_public": True,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["file_type"] is None


# ── TC2.1–TC2.2: GET /forms list returns file_type ────────────────────────────


@pytest.mark.integration
def test_list_forms_includes_file_type(ft_client):
    """TC2.1: GET /forms returns file_type for forms with attachment."""
    _create_download_form(ft_client, file_type="xlsx", title="Excel Form")
    resp = ft_client.get("/api/v1/forms")
    assert resp.status_code == 200
    items = resp.json()["items"]
    excel_form = next(f for f in items if f["title"] == "Excel Form")
    assert excel_form["file_type"] == "xlsx"


@pytest.mark.integration
def test_list_forms_null_file_type_for_url_source(ft_client):
    """TC2.2: GET /forms returns null file_type for URL-source forms."""
    _create_url_form(ft_client, title="URL Only Form")
    resp = ft_client.get("/api/v1/forms")
    assert resp.status_code == 200
    items = resp.json()["items"]
    url_form = next(f for f in items if f["title"] == "URL Only Form")
    assert url_form["file_type"] is None


# ── TC2.1 variant: GET /forms/{id} returns file_type ──────────────────────────


@pytest.mark.integration
def test_get_single_form_includes_file_type(ft_client):
    """GET /forms/{id} returns file_type for a specific form."""
    create_resp = _create_download_form(ft_client, file_type="csv")
    form_id = create_resp.json()["id"]

    detail_resp = ft_client.get(f"/api/v1/forms/{form_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["file_type"] == "csv"
