"""FEAT-0005 — Public Forms Portal: download endpoint regression tests.

Covers ``GET /api/public/v1/forms/{form_number}/file`` end-to-end:

* The response carries an ``X-Accel-Redirect`` header pointing under the
  ``/internal-s3/`` prefix and the body is empty (US-004 AC1, AC14).
* ``Content-Disposition`` is ``attachment;`` with both ASCII fallback
  and the RFC-6266 UTF-8 form so non-ASCII filenames survive (US-004 AC6).
* The redirect target is URL-encoded so S3 keys containing spaces or
  other URL-unsafe characters do not silently truncate at NGINX
  (FEAT-0005 BUGFIX 2026-06-11 — Bug B).
* No S3 hostname, bucket name, or pre-signed URL appears in any body
  byte (US-004 AC14, US-012 BR-001).
* ``Cache-Control: private, no-store`` is always set (US-004 AC6).
* 404 is returned for unknown form numbers, for forms without an
  attached file, and for forms with no ``file_name`` — never a 500
  that would disclose the database / S3 internals (US-014 AC5).

Run standalone::

    pytest apps/public-backend/tests/test_feature_FEAT_0005_public_download.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Constants enforcing the FEAT-0005 security contract.  Any of these strings
# appearing in a response body / header value is treated as a leak.
# ---------------------------------------------------------------------------

_INTERNAL_S3_PREFIX = "/internal-s3/"

# Snippets a leaking response would contain.  The test harness only asserts
# that none of these surface — it does not require any of them to be present.
_S3_DISCLOSURES = (
    b"s3.example.com",
    b"amazonaws",
    b"X-Amz-",
    b"AWSAccessKeyId",
    b"Signature=",
    b"Expires=",
    # The full bucket name is project-specific; we sample the most common
    # disclosure shapes only.
)


def _insert_form(
    db: Session,
    *,
    form_number: str,
    title: str = "Test Form",
    s3_key: str | None = "uploads/abc.pdf",
    file_name: str | None = "abc.pdf",
    file_type: str | None = "pdf",
) -> str:
    """Insert a row directly into ``public_forms_v`` and return ``form_id``."""
    form_id = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO public_forms_v
                (form_id, form_number, title, s3_key, file_name, file_type,
                 effective_date, updated_at, keywords)
            VALUES
                (:form_id, :form_number, :title, :s3_key, :file_name, :file_type,
                 :effective_date, :updated_at, :keywords)
            """
        ),
        {
            "form_id": form_id,
            "form_number": form_number,
            "title": title,
            "s3_key": s3_key,
            "file_name": file_name,
            "file_type": file_type,
            # Use a date well in the past so the FEAT-0010 effective-date
            # filter does not hide the row.
            "effective_date": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
            "keywords": "[]",
        },
    )
    db.commit()
    return form_id


def _assert_no_s3_leakage(resp) -> None:
    """Fail if any S3-identifying material appears in headers or body."""
    for needle in _S3_DISCLOSURES:
        for name, value in resp.headers.items():
            assert needle.decode().lower() not in value.lower(), (
                f"S3 disclosure {needle!r} leaked in header {name}: {value!r}"
            )
        assert needle not in resp.content, (
            f"S3 disclosure {needle!r} leaked into response body"
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestDownloadHappyPath:

    def test_returns_x_accel_redirect_with_empty_body(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-OK-01",
            s3_key="uploads/abc.pdf",
            file_name="abc.pdf",
        )

        resp = public_client.get("/api/public/v1/forms/TF-OK-01/file")

        assert resp.status_code == 200
        assert resp.content == b""
        target = resp.headers.get("x-accel-redirect", "")
        assert target.startswith(_INTERNAL_S3_PREFIX), (
            f"X-Accel-Redirect must be under {_INTERNAL_S3_PREFIX}: {target!r}"
        )
        assert target == _INTERNAL_S3_PREFIX + "uploads/abc.pdf"

    def test_content_disposition_attachment_with_filename(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-OK-02",
            s3_key="uploads/report.pdf",
            file_name="Quarterly Report Q1.pdf",
        )

        resp = public_client.get("/api/public/v1/forms/TF-OK-02/file")

        assert resp.status_code == 200
        cd = resp.headers["content-disposition"]
        assert cd.startswith("attachment;"), cd
        # ASCII fallback present (space allowed in quoted form).
        assert 'filename="Quarterly Report Q1.pdf"' in cd, cd
        # UTF-8 RFC-6266 form present so non-ASCII filenames survive.
        assert "filename*=UTF-8''" in cd, cd

    def test_cache_control_private_no_store(self, public_client, db):
        _insert_form(db, form_number="TF-OK-03")

        resp = public_client.get("/api/public/v1/forms/TF-OK-03/file")

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "private, no-store"


# ---------------------------------------------------------------------------
# Bug B — X-Accel-Redirect target must be URL-encoded
# ---------------------------------------------------------------------------


class TestRedirectTargetEncoding:
    """The X-Accel-Redirect value must be a valid URI even when the S3 key
    contains characters that would otherwise truncate the header at NGINX."""

    def test_spaces_in_key_are_percent_encoded(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-ENC-01",
            s3_key="uploads/Provincial Land Tax 2025.pdf",
            file_name="Provincial Land Tax 2025.pdf",
        )

        resp = public_client.get("/api/public/v1/forms/TF-ENC-01/file")

        assert resp.status_code == 200
        target = resp.headers["x-accel-redirect"]
        # Slashes preserved, spaces percent-encoded.
        assert target == (
            _INTERNAL_S3_PREFIX + "uploads/Provincial%20Land%20Tax%202025.pdf"
        )
        # No literal space — would truncate at NGINX otherwise.
        assert " " not in target

    def test_unicode_in_key_is_percent_encoded(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-ENC-02",
            s3_key="uploads/règlement.pdf",
            file_name="règlement.pdf",
        )

        resp = public_client.get("/api/public/v1/forms/TF-ENC-02/file")

        assert resp.status_code == 200
        target = resp.headers["x-accel-redirect"]
        # 'è' (U+00E8) encodes to %C3%A8 in UTF-8.
        assert "%C3%A8" in target
        # No raw non-ASCII byte in the header value.
        assert all(ord(c) < 128 for c in target)

    def test_leading_slash_in_key_is_stripped(self, public_client, db):
        """The route strips a leading slash on the key before encoding so
        we never get a doubled separator (``/internal-s3//uploads/...``)."""
        _insert_form(
            db,
            form_number="TF-ENC-03",
            s3_key="/uploads/x.pdf",
            file_name="x.pdf",
        )

        resp = public_client.get("/api/public/v1/forms/TF-ENC-03/file")

        assert resp.status_code == 200
        assert resp.headers["x-accel-redirect"] == _INTERNAL_S3_PREFIX + "uploads/x.pdf"


# ---------------------------------------------------------------------------
# S3 disclosure assertions (US-004 AC14, US-012 BR-001)
# ---------------------------------------------------------------------------


class TestNoS3LeakageInResponse:

    def test_happy_path_body_and_headers_clean(self, public_client, db):
        _insert_form(db, form_number="TF-SEC-01")

        resp = public_client.get("/api/public/v1/forms/TF-SEC-01/file")
        assert resp.status_code == 200
        _assert_no_s3_leakage(resp)

    def test_404_body_does_not_disclose_s3(self, public_client, db):
        # No form inserted → 404 path.
        resp = public_client.get("/api/public/v1/forms/UNKNOWN-99/file")
        assert resp.status_code == 404
        _assert_no_s3_leakage(resp)


# ---------------------------------------------------------------------------
# 404 / error contracts (US-014 AC5)
# ---------------------------------------------------------------------------


class TestDownload404Contracts:

    def test_404_for_unknown_form_number(self, public_client):
        resp = public_client.get("/api/public/v1/forms/UNKNOWN-99/file")
        assert resp.status_code == 404
        # RFC-7807 problem+json shape.
        assert "application/problem+json" in resp.headers.get("content-type", "")
        body = resp.json()
        assert body["status"] == 404
        assert body["title"] == "Not Found"

    def test_404_when_s3_key_is_null(self, public_client, db):
        """Form is published but has no attached file → 404."""
        _insert_form(db, form_number="TF-NOFILE-01", s3_key=None, file_name=None)

        resp = public_client.get("/api/public/v1/forms/TF-NOFILE-01/file")
        assert resp.status_code == 404
        assert "x-accel-redirect" not in {k.lower() for k in resp.headers.keys()}

    def test_404_when_file_name_is_null(self, public_client, db):
        """Half-populated row — must still 404 rather than 500/leak."""
        _insert_form(
            db, form_number="TF-NOFILE-02", s3_key="uploads/x.pdf", file_name=None
        )

        resp = public_client.get("/api/public/v1/forms/TF-NOFILE-02/file")
        assert resp.status_code == 404
