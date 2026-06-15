"""Tests for attachment download bug fixes.

Covers three root causes:
  RC-1  public_forms_v resolves file metadata from form_versions, but
        _sync_form_version was never called on publish → 404 on download.
  RC-2  Detail page showed the Download button even for URL-source forms
        (frontend-only change, not tested here).
  RC-3  Admin frontend navigated to a raw S3 key instead of a pre-signed URL.
        The new GET /forms/{id}/file endpoint is tested here.
"""

import uuid
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from backend.models import AuditLog, Form, FormVersion
from backend.services import s3_service
from backend.services.forms import FormService
from backend.services.s3_service import S3ObjectNotFound


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_download_form(db, creator_id, *, s3_key="uploads/test.pdf", status="draft"):
    form = Form(
        id=uuid.uuid4(),
        title="Attachment Form",
        description="Form with a file attachment",
        status=status,
        is_public=True,
        keywords=[],
        created_by_id=creator_id,
        form_source="Download",
        form_attachment_url=s3_key,
        form_attachment_filename="test.pdf",
        file_type="pdf",
    )
    db.add(form)
    db.flush()
    return form


def _make_url_form(db, creator_id):
    form = Form(
        id=uuid.uuid4(),
        title="URL Form",
        description="Form that links to an external URL",
        status="draft",
        is_public=True,
        keywords=[],
        created_by_id=creator_id,
        form_source="URL",
        form_attachment_url=None,
    )
    db.add(form)
    db.flush()
    return form


# ---------------------------------------------------------------------------
# RC-1a: s3_service.get_object_size — unit tests
# ---------------------------------------------------------------------------

class TestGetObjectSize:
    @patch("backend.services.s3_service._get_s3_client")
    def test_returns_content_length_on_success(self, mock_get_client):
        """get_object_size returns the ContentLength reported by head_object."""
        mock_client = mock_get_client.return_value
        mock_client.head_object.return_value = {"ContentLength": 98765}

        result = s3_service.get_object_size("uploads/some.pdf")

        assert result == 98765
        mock_client.head_object.assert_called_once()

    @patch("backend.services.s3_service._get_s3_client")
    def test_returns_zero_on_client_error(self, mock_get_client):
        """get_object_size returns 0 (not an exception) when the object is missing."""
        mock_client = mock_get_client.return_value
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )

        result = s3_service.get_object_size("uploads/missing.pdf")

        assert result == 0

    @patch("backend.services.s3_service._get_s3_client")
    def test_returns_zero_when_content_length_absent(self, mock_get_client):
        """get_object_size returns 0 when head_object omits ContentLength."""
        mock_client = mock_get_client.return_value
        mock_client.head_object.return_value = {}  # no ContentLength key

        result = s3_service.get_object_size("uploads/some.pdf")

        assert result == 0


# ---------------------------------------------------------------------------
# RC-1b: FormService._sync_form_version — integration tests (DB required)
# ---------------------------------------------------------------------------

class TestSyncFormVersion:
    @pytest.mark.integration
    @patch("backend.services.s3_service.get_object_size", return_value=12345)
    def test_creates_form_version_row_on_first_publish(self, mock_size, db, user_factory):
        """Publishing a Download-source form creates a is_current FormVersion row."""
        creator = user_factory(email="sync-publish-creator@example.com")
        reviewer = user_factory(email="sync-publish-reviewer@example.com")
        form = _make_download_form(db, creator.id)

        # Drive _sync_form_version via the service layer.
        # Reviewer uses allow_self_approve=False (default) — different user, so valid.
        FormService.submit_form_for_review(db, form.id, creator.id)
        FormService.approve_form(db, form.id, reviewer.id)

        fv = (
            db.query(FormVersion)
            .filter(
                FormVersion.form_id == form.id,
                FormVersion.is_current.is_(True),
                FormVersion.deleted_at.is_(None),
            )
            .one_or_none()
        )
        assert fv is not None
        assert fv.s3_key == "uploads/test.pdf"
        assert fv.file_name == "test.pdf"
        assert fv.file_size == 12345
        assert fv.file_type == "pdf"
        assert str(fv.uploaded_by_id) == str(reviewer.id)

    @pytest.mark.integration
    @patch("backend.services.s3_service.get_object_size", return_value=999)
    def test_reactivates_existing_version_on_republish_same_key(self, mock_size, db, user_factory):
        """Re-publishing with the same S3 key reactivates the row, no duplicate."""
        creator = user_factory(email="sync-republish-creator@example.com")
        reviewer = user_factory(email="sync-republish-reviewer@example.com")
        form = _make_download_form(db, creator.id)

        # First publish
        FormService.submit_form_for_review(db, form.id, creator.id)
        FormService.approve_form(db, form.id, reviewer.id)

        # Unpublish (archive) then restore to published state.
        FormService.archive_form(db, form.id, reviewer.id)
        FormService.restore_form(db, form.id, reviewer.id)

        versions = (
            db.query(FormVersion)
            .filter(
                FormVersion.form_id == form.id,
                FormVersion.deleted_at.is_(None),
            )
            .all()
        )
        current_versions = [v for v in versions if v.is_current]

        # Exactly one current version; no extra rows for the same s3_key.
        assert len(current_versions) == 1
        assert current_versions[0].s3_key == "uploads/test.pdf"

    @pytest.mark.integration
    @patch("backend.services.s3_service.get_object_size", return_value=0)
    def test_sync_is_noop_for_url_source_form(self, mock_size, db, user_factory):
        """_sync_form_version does nothing for URL-source forms."""
        creator = user_factory(email="sync-url-creator@example.com")
        reviewer = user_factory(email="sync-url-reviewer@example.com")
        form = _make_url_form(db, creator.id)

        FormService.submit_form_for_review(db, form.id, creator.id)
        FormService.approve_form(db, form.id, reviewer.id)

        count = (
            db.query(FormVersion)
            .filter(FormVersion.form_id == form.id)
            .count()
        )
        assert count == 0


# ---------------------------------------------------------------------------
# RC-3: GET /api/v1/forms/{id}/file — endpoint tests (streaming proxy)
# ---------------------------------------------------------------------------
#
# SECURITY CONTRACT under test (FEAT-0005 US-004 AC14, US-012 BR-001):
#   The streaming endpoint MUST NOT leak the S3 hostname, bucket name,
#   object key, or any pre-signed URL into any response header or body.
#   The admin browser only ever sees opaque attachment bytes.

_FORBIDDEN_DISCLOSURES = (
    b"s3.example.com",
    b"amazonaws",
    b"X-Amz-",
    b"AWSAccessKeyId",
    b"Signature=",
    b"Expires=",
    b"uploads/",
)


def _assert_no_s3_leakage(resp):
    """Fail if any response header/body contains S3-identifying material."""
    for needle in _FORBIDDEN_DISCLOSURES:
        for name, value in resp.headers.items():
            assert needle.decode().lower() not in value.lower(), (
                f"S3 disclosure {needle!r} leaked in header {name}: {value!r}"
            )
        assert needle not in resp.content, (
            f"S3 disclosure {needle!r} leaked into response body"
        )


class TestStreamFormAttachment:
    """Admin-side streaming proxy: GET /api/v1/forms/{id}/file."""

    @patch("backend.routes.forms.s3_service.stream_object")
    def test_streams_bytes_for_download_form(
        self, mock_stream, client, db, admin_user
    ):
        """Endpoint streams raw bytes with attachment Content-Disposition."""
        mock_stream.return_value = iter([b"%PDF-1.4 admin-bytes"])
        form = _make_download_form(db, admin_user.id)

        resp = client.get(
            f"/api/v1/forms/{form.id}/file",
            headers={"Authorization": "Bearer admin"},
        )

        assert resp.status_code == 200
        assert resp.content == b"%PDF-1.4 admin-bytes"
        assert resp.headers["content-type"].startswith("application/pdf")
        assert resp.headers["content-disposition"].startswith("attachment;")
        assert 'filename="test.pdf"' in resp.headers["content-disposition"]
        assert resp.headers["cache-control"] == "private, no-store"
        assert resp.headers.get("x-content-type-options") == "nosniff"
        # stream_object must be invoked with the object key, never a URL.
        called_key = mock_stream.call_args.args[0]
        assert called_key == "uploads/test.pdf"

    @patch("backend.routes.forms.s3_service.stream_object")
    def test_no_s3_url_in_response(self, mock_stream, client, db, admin_user):
        """Response must not contain any S3-identifying material."""
        mock_stream.return_value = iter([b"binary-payload"])
        form = _make_download_form(db, admin_user.id)

        resp = client.get(
            f"/api/v1/forms/{form.id}/file",
            headers={"Authorization": "Bearer admin"},
        )

        assert resp.status_code == 200
        _assert_no_s3_leakage(resp)

    @patch("backend.routes.forms.s3_service.stream_object")
    def test_audit_log_row_written(self, mock_stream, client, db, admin_user):
        """A successful download creates an AuditLog row tagged FORM_DOWNLOAD."""
        mock_stream.return_value = iter([b"abc"])
        form = _make_download_form(db, admin_user.id)
        form_id = form.id

        before = db.query(AuditLog).filter(AuditLog.action == "FORM_DOWNLOAD").count()

        resp = client.get(
            f"/api/v1/forms/{form_id}/file",
            headers={"Authorization": "Bearer admin"},
        )
        assert resp.status_code == 200

        # The route uses its own DB session — make sure our session sees it.
        db.expire_all()
        rows = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "FORM_DOWNLOAD",
                AuditLog.entity_type == "forms",
                AuditLog.entity_id == str(form_id),
            )
            .all()
        )
        assert len(rows) >= 1
        latest = rows[-1]
        assert latest.new_values.get("filename") == "test.pdf"
        assert (
            db.query(AuditLog).filter(AuditLog.action == "FORM_DOWNLOAD").count()
            == before + 1
        )

    @patch("backend.routes.forms.s3_service.stream_object")
    def test_returns_404_when_object_missing_in_s3(
        self, mock_stream, client, db, admin_user
    ):
        """If the underlying S3 object is missing, the endpoint returns 404."""
        mock_stream.side_effect = S3ObjectNotFound()
        form = _make_download_form(db, admin_user.id)

        resp = client.get(
            f"/api/v1/forms/{form.id}/file",
            headers={"Authorization": "Bearer admin"},
        )
        assert resp.status_code == 404
        # Error body must not name the key either.
        _assert_no_s3_leakage(resp)

    @patch("backend.routes.forms.s3_service.stream_object")
    def test_returns_502_when_other_s3_error_happens(
        self, mock_stream, client, db, admin_user
    ):
        """If S3 raises an unexpected error, the endpoint returns 502 Bad Gateway without leaking details."""
        mock_stream.side_effect = Exception("Some arbitrary error")
        form = _make_download_form(db, admin_user.id)

        resp = client.get(
            f"/api/v1/forms/{form.id}/file",
            headers={"Authorization": "Bearer admin"},
        )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "Could not retrieve attachment"
        _assert_no_s3_leakage(resp)

    def test_returns_404_for_url_source_form(self, client, db, admin_user):
        """Endpoint returns 404 when the form has no S3 attachment."""
        form = _make_url_form(db, admin_user.id)

        resp = client.get(
            f"/api/v1/forms/{form.id}/file",
            headers={"Authorization": "Bearer admin"},
        )
        assert resp.status_code == 404

    def test_returns_403_without_form_read_permission(self, client, db, admin_user):
        """Endpoint returns 403 when the token lacks form:read."""
        form = _make_download_form(db, admin_user.id)

        from fastapi import Request
        from backend.auth.dependencies import get_current_user
        from backend.auth.jwt_handler import TokenData
        from backend.main import app as fastapi_app

        def _noperm_user(request: Request) -> TokenData:
            return TokenData(
                sub=str(admin_user.id),
                email="noperm@example.com",
                name="No Perm",
                roles=[],
                token_type="access",
                permissions=[],
            )

        fastapi_app.dependency_overrides[get_current_user] = _noperm_user
        try:
            from fastapi.testclient import TestClient
            tc = TestClient(fastapi_app)
            resp = tc.get(f"/api/v1/forms/{form.id}/file")
        finally:
            fastapi_app.dependency_overrides.pop(get_current_user, None)

        assert resp.status_code == 403

    def test_returns_404_for_unknown_form_id(self, client):
        """Endpoint returns 404 for a non-existent form ID."""
        resp = client.get(
            f"/api/v1/forms/{uuid.uuid4()}/file",
            headers={"Authorization": "Bearer admin"},
        )
        assert resp.status_code == 404

    def test_returns_400_for_invalid_form_id(self, client):
        """Endpoint returns 400 for a non-UUID form ID."""
        resp = client.get(
            "/api/v1/forms/not-a-uuid/file",
            headers={"Authorization": "Bearer admin"},
        )
        assert resp.status_code == 400
