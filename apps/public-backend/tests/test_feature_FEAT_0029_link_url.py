"""FEAT-0029 US-001 — Expose link-source destination URL in the public API.

Tier-1 backend regression tests (pytest) for TC-US-001.  They assert the new
``form_source`` / ``url`` projection on both the list and detail endpoints and
prove the URL scheme guard, additivity, and preserved behaviour.

Seed rows are inserted directly into the SQLite ``public_forms_v`` stand-in
table (see ``conftest.py``), mirroring the FEAT-0005/FEAT-0010 test pattern.

Run standalone::

    pytest apps/public-backend/tests/test_feature_FEAT_0029_link_url.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

LIST_URL = "/api/public/v1/forms"


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------


def _insert_form(
    db: Session,
    *,
    form_number: str,
    title: str = "Test Form",
    form_source: str | None = None,
    form_source_url: str | None = None,
    s3_key: str | None = None,
    file_name: str | None = None,
    file_type: str | None = None,
) -> str:
    """Insert a row directly into ``public_forms_v`` and return ``form_id``."""
    form_id = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO public_forms_v
                (form_id, form_number, title, form_source, form_source_url,
                 s3_key, file_name, file_type, effective_date, updated_at,
                 keywords)
            VALUES
                (:form_id, :form_number, :title, :form_source, :form_source_url,
                 :s3_key, :file_name, :file_type, :effective_date, :updated_at,
                 :keywords)
            """
        ),
        {
            "form_id": form_id,
            "form_number": form_number,
            "title": title,
            "form_source": form_source,
            "form_source_url": form_source_url,
            "s3_key": s3_key,
            "file_name": file_name,
            "file_type": file_type,
            # Past date so the FEAT-0010 effective-date filter keeps the row.
            "effective_date": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
            "keywords": "[]",
        },
    )
    db.commit()
    return form_id


def _item_by_number(payload: dict, form_number: str) -> dict:
    for item in payload["items"]:
        if item.get("form_number") == form_number:
            return item
    raise AssertionError(f"{form_number} not found in list payload")


# ===========================================================================
# TC1.2 — List exposes url for URL-source form (AC2)
# ===========================================================================


class TestListLinkSource:
    def test_url_source_https_exposes_url(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-URL-01",
            form_source="URL",
            form_source_url="https://example.gov.bc.ca/form",
        )
        resp = public_client.get(LIST_URL)
        assert resp.status_code == 200
        item = _item_by_number(resp.json(), "TF-URL-01")
        assert item["form_source"] == "URL"
        assert item["url"] == "https://example.gov.bc.ca/form"

    def test_url_source_http_exposes_url(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-URL-HTTP",
            form_source="URL",
            form_source_url="http://example.gov.bc.ca/form",
        )
        resp = public_client.get(LIST_URL)
        item = _item_by_number(resp.json(), "TF-URL-HTTP")
        assert item["url"] == "http://example.gov.bc.ca/form"

    # TC1.3 — downloadable form has url=null (AC3)
    def test_download_source_url_is_null(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-DL-01",
            form_source="Download",
            s3_key="uploads/a.pdf",
            file_name="a.pdf",
            file_type="pdf",
        )
        resp = public_client.get(LIST_URL)
        item = _item_by_number(resp.json(), "TF-DL-01")
        assert item["form_source"] == "Download"
        assert item["url"] is None
        assert item["file_type"] == "pdf"

    def test_legacy_null_source_url_is_null(self, public_client, db):
        _insert_form(db, form_number="TF-LEGACY", form_source=None)
        resp = public_client.get(LIST_URL)
        item = _item_by_number(resp.json(), "TF-LEGACY")
        assert item["form_source"] is None
        assert item["url"] is None


# ===========================================================================
# TC1.4 — Detail exposes url per source (AC4)
# ===========================================================================


class TestDetailLinkSource:
    def test_detail_url_source(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-DET-URL",
            form_source="URL",
            form_source_url="https://example.gov.bc.ca/detail",
        )
        resp = public_client.get(f"{LIST_URL}/TF-DET-URL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["form_source"] == "URL"
        assert body["url"] == "https://example.gov.bc.ca/detail"

    def test_detail_download_source(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-DET-DL",
            form_source="Download",
            s3_key="uploads/b.pdf",
            file_name="b.pdf",
            file_type="pdf",
        )
        resp = public_client.get(f"{LIST_URL}/TF-DET-DL")
        body = resp.json()
        assert body["url"] is None
        assert body["form_source"] == "Download"
        assert body["file"]["filename"] == "b.pdf"
        assert body["file"]["content_type"] == "pdf"


# ===========================================================================
# TC1.5 — Disallowed URL scheme is nulled (AC5)
# ===========================================================================


class TestUrlSchemeGuard:
    _UNSAFE = [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "file:///etc/passwd",
        "//evil.example.com/path",
        "ftp://example.com/file",
        "  javascript:alert(1)  ",
    ]

    def test_unsafe_schemes_nulled_in_list_and_detail(self, public_client, db):
        for i, bad in enumerate(self._UNSAFE):
            number = f"TF-BAD-{i}"
            _insert_form(
                db,
                form_number=number,
                form_source="URL",
                form_source_url=bad,
            )
            list_item = _item_by_number(public_client.get(LIST_URL).json(), number)
            assert list_item["url"] is None, f"{bad!r} leaked in list"
            detail = public_client.get(f"{LIST_URL}/{number}").json()
            assert detail["url"] is None, f"{bad!r} leaked in detail"

    def test_no_unsafe_value_in_raw_body(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-BAD-JS",
            form_source="URL",
            form_source_url="javascript:alert(1)",
        )
        resp = public_client.get(LIST_URL)
        assert b"javascript:" not in resp.content


# ===========================================================================
# TC1.6 — Blank or missing destination is nulled (AC6)
# ===========================================================================


class TestBlankDestination:
    def test_blank_and_whitespace_and_missing(self, public_client, db):
        _insert_form(db, form_number="TF-BLANK", form_source="URL", form_source_url="")
        _insert_form(db, form_number="TF-WS", form_source="URL", form_source_url="   ")
        _insert_form(
            db, form_number="TF-NONE", form_source="URL", form_source_url=None
        )
        payload = public_client.get(LIST_URL).json()
        for number in ("TF-BLANK", "TF-WS", "TF-NONE"):
            item = _item_by_number(payload, number)
            assert item["url"] is None
            assert item["form_source"] == "URL"


# ===========================================================================
# TC1.7 — No internal identifiers or S3 key leak (AC7)
# ===========================================================================


class TestNoInternalLeak:
    def test_no_internal_fields_in_responses(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-LEAK",
            form_source="URL",
            form_source_url="https://example.gov.bc.ca/x",
            s3_key="uploads/secret.pdf",
        )
        list_body = public_client.get(LIST_URL).content
        detail_body = public_client.get(f"{LIST_URL}/TF-LEAK").content
        for needle in (b"form_id", b"business_area_id", b"s3_key", b"secret.pdf"):
            assert needle not in list_body
            assert needle not in detail_body


# ===========================================================================
# TC1.9 — File endpoint still 404 for link forms (AC9)
# ===========================================================================


class TestFileEndpointUnchanged:
    def test_link_form_file_returns_404(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-LINK-FILE",
            form_source="URL",
            form_source_url="https://example.gov.bc.ca/x",
        )
        resp = public_client.get(f"{LIST_URL}/TF-LINK-FILE/file")
        assert resp.status_code == 404
        # No redirect to the destination is performed by the backend.
        assert "x-accel-redirect" not in {k.lower() for k in resp.headers}


# ===========================================================================
# TC1.8 — ETag / conditional response preserved with the new field (AC8, E6)
# ===========================================================================


class TestEtagPreserved:
    def test_etag_304_after_field_added(self, public_client, db):
        _insert_form(
            db,
            form_number="TF-ETAG",
            form_source="URL",
            form_source_url="https://example.gov.bc.ca/x",
        )
        first = public_client.get(LIST_URL)
        etag = first.headers.get("ETag")
        assert etag
        second = public_client.get(LIST_URL, headers={"If-None-Match": etag})
        assert second.status_code == 304
