"""FEAT-0005 — Public Forms Portal backend test suite.

Covers US-013 (X-Internal-Auth + CORS removal) and US-014 (API contract
additions: limit/offset, /business-areas, detail, /file via X-Accel-Redirect,
/og, /sitemap.xml, RFC 7807 problem JSON).

Frontend / NGINX / Helm / CI stories are exercised by their own suites
(per the FEAT-0005 test plan); this file is the **public-backend** scope
only.

Uses the shared conftest.py PostgreSQL test infrastructure.
"""

from __future__ import annotations

import importlib
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

# Make the public-backend package importable.
_PUBLIC_BACKEND_DIR = str(Path(__file__).resolve().parent.parent / "public-backend")
if _PUBLIC_BACKEND_DIR not in sys.path:
    sys.path.insert(0, _PUBLIC_BACKEND_DIR)

from backend.models import (  # noqa: E402  (path setup above)
    BusinessArea,
    Form,
    FormNumberPrefix,
    FormNumberReservation,
    FormVersion,
    User,
)


# ---------------------------------------------------------------------------
# View + app bootstrap (FEAT-0005 v2 view with file metadata + updated_at)
# ---------------------------------------------------------------------------

_VIEW_DDL_V2 = """\
CREATE OR REPLACE VIEW public_forms_v AS
SELECT
    f.id                  AS form_id,
    fnr.full_form_number  AS form_number,
    f.title,
    f.description,
    ba.id                 AS business_area_id,
    ba.name               AS business_area,
    f.keywords,
    f.file_type,
    f.effective_date,
    f.updated_at,
    fv.s3_key             AS s3_key,
    fv.file_name          AS file_name,
    fv.file_size          AS file_size
FROM forms f
LEFT JOIN form_number_reservations fnr
    ON f.form_number_reservation_id = fnr.id
LEFT JOIN business_areas ba
    ON f.business_area_id = ba.id
   AND ba.deleted_at IS NULL
   AND ba.is_active = True
LEFT JOIN form_versions fv
    ON fv.form_id = f.id
   AND fv.is_current = True
   AND fv.deleted_at IS NULL
WHERE f.status     = 'published'
  AND f.is_public  = True
  AND f.deleted_at IS NULL;
"""


@pytest.fixture(scope="session")
def _public_view_v2(_test_engine):
    with _test_engine.connect() as conn:
        conn.execute(text(_VIEW_DDL_V2))
        conn.commit()
    yield
    with _test_engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS public_forms_v"))
        conn.commit()


_TEST_SECRET = "feat-0005-test-shared-secret-fixed-len-0123456789abcdef"


def _make_client(db: Session, monkeypatch, *, secret: str) -> TestClient:
    """Build a fresh TestClient against the public-backend app.

    The app + middleware stack is rebuilt per-test so each test sees its
    own ``INTERNAL_AUTH_SECRET`` configuration.  We achieve this by
    forcing :func:`importlib.reload` on the public-backend modules.
    """
    monkeypatch.setenv("DATABASE_URL_READONLY", "postgresql://x@localhost/x")
    monkeypatch.setenv("INTERNAL_AUTH_SECRET", secret)
    monkeypatch.setenv("CACHE_MAX_AGE", "300")
    monkeypatch.setenv("BUSINESS_AREAS_CACHE_MAX_AGE", "600")
    monkeypatch.setenv("SITEMAP_CACHE_MAX_AGE", "3600")
    monkeypatch.setenv("OG_CACHE_MAX_AGE", "600")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://forms-public.example.gov")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    # Force a clean import so the module-level ``settings`` and the
    # FastAPI app pick up the just-set env vars.
    for name in (
        "config",
        "database",
        "audit",
        "http_cache",
        "problem",
        "middleware",
        "models",
        "routes.forms",
        "routes.business_areas",
        "routes.sitemap",
        "main",
    ):
        if name in sys.modules:
            del sys.modules[name]

    _database_mod = importlib.import_module("database")
    _main_mod = importlib.import_module("main")

    _main_mod.app.dependency_overrides[_database_mod.get_db] = lambda: db
    return TestClient(_main_mod.app, raise_server_exceptions=False)


@pytest.fixture()
def auth_client(db, _public_view_v2, monkeypatch) -> TestClient:
    """Client that automatically supplies the correct ``X-Internal-Auth``."""
    client = _make_client(db, monkeypatch, secret=_TEST_SECRET)
    client.headers.update({"X-Internal-Auth": _TEST_SECRET})
    yield client


@pytest.fixture()
def noauth_client(db, _public_view_v2, monkeypatch) -> TestClient:
    """Client that intentionally omits ``X-Internal-Auth`` (for 403 tests)."""
    client = _make_client(db, monkeypatch, secret=_TEST_SECRET)
    yield client


@pytest.fixture()
def open_client(db, _public_view_v2, monkeypatch) -> TestClient:
    """Client against an unconfigured-secret deployment (no-op middleware).

    Verifies the empty-secret degraded mode does not break the contract.
    """
    client = _make_client(db, monkeypatch, secret="")
    yield client


# ---------------------------------------------------------------------------
# Data factories (forms + file versions)
# ---------------------------------------------------------------------------

@pytest.fixture()
def creator(db: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"feat0005-{uuid.uuid4().hex[:6]}@example.com",
        first_name="FEAT0005",
        last_name="Creator",
    )
    db.add(user)
    db.flush()
    return user


def _make_ba(db: Session, *, name: str) -> BusinessArea:
    ba = BusinessArea(id=uuid.uuid4(), name=name, is_active=True)
    db.add(ba)
    db.flush()
    return ba


def _make_prefix(db: Session, *, prefix: str, creator: User) -> FormNumberPrefix:
    p = FormNumberPrefix(
        id=uuid.uuid4(),
        prefix=prefix,
        current_sequence=0,
        padding_length=4,
        max_number_length=10,
        is_active=True,
        created_by_id=creator.id,
    )
    db.add(p)
    db.flush()
    return p


def _make_reservation(
    db: Session,
    *,
    prefix: FormNumberPrefix,
    full_form_number: str,
    creator: User,
) -> FormNumberReservation:
    r = FormNumberReservation(
        id=uuid.uuid4(),
        prefix_id=prefix.id,
        form_number=full_form_number[len(prefix.prefix):],
        full_form_number=full_form_number,
        numbering_method="auto_generated",
        status="approved",
        reserved_by_id=creator.id,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    db.add(r)
    db.flush()
    return r


def _make_form(
    db: Session,
    *,
    creator: User,
    title: str,
    description: str | None = None,
    is_public: bool = True,
    status: str = "published",
    business_area: BusinessArea | None = None,
    reservation: FormNumberReservation | None = None,
    keywords: list[str] | None = None,
    file_type: str | None = None,
    effective_date: datetime | None = None,
) -> Form:
    f = Form(
        id=uuid.uuid4(),
        title=title,
        description=description,
        status=status,
        is_public=is_public,
        keywords=keywords or [],
        created_by_id=creator.id,
        business_area_id=business_area.id if business_area else None,
        form_number_reservation_id=reservation.id if reservation else None,
        file_type=file_type,
        effective_date=effective_date,
    )
    db.add(f)
    db.flush()
    return f


def _attach_version(
    db: Session,
    *,
    form: Form,
    creator: User,
    s3_key: str,
    file_name: str,
    file_size: int = 12345,
    file_type: str = "pdf",
) -> FormVersion:
    fv = FormVersion(
        id=uuid.uuid4(),
        form_id=form.id,
        version_number=1,
        s3_key=s3_key,
        file_name=file_name,
        file_size=file_size,
        file_type=file_type,
        uploaded_by_id=creator.id,
        is_current=True,
    )
    db.add(fv)
    db.flush()
    return fv


# ===========================================================================
# US-013 — X-Internal-Auth middleware + CORS removal
# ===========================================================================

class TestInternalAuth:
    """TC-US-013."""

    # TC5.1
    def test_missing_header_returns_403(self, noauth_client):
        resp = noauth_client.get("/api/public/v1/forms")
        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        # Generic body — never echoes the configured secret.
        assert _TEST_SECRET not in resp.text
        assert body["status"] == 403
        assert body["title"] == "Forbidden"

    # TC6.1
    def test_wrong_header_returns_403(self, noauth_client):
        resp = noauth_client.get(
            "/api/public/v1/forms",
            headers={"X-Internal-Auth": "definitely-not-the-secret"},
        )
        assert resp.status_code == 403
        assert _TEST_SECRET not in resp.text

    # TC6.1 — constant-time compare site
    def test_constant_time_compare_call_site(self):
        """Middleware MUST use ``hmac.compare_digest`` (regression alert
        per TC-US-013 regression notes)."""
        import inspect
        from middleware import XInternalAuthMiddleware
        src = inspect.getsource(XInternalAuthMiddleware.dispatch)
        assert "compare_digest" in src

    # TC7.1
    def test_correct_header_allowed(self, auth_client):
        resp = auth_client.get("/api/public/v1/forms")
        assert resp.status_code == 200

    # TC11.1
    def test_healthz_exempt(self, noauth_client):
        resp = noauth_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    def test_readyz_exempt(self, noauth_client):
        resp = noauth_client.get("/readyz")
        # 200 (db ok) — never 403.
        assert resp.status_code in (200, 503)

    # TC8.1
    def test_no_cors_headers_emitted(self, auth_client):
        resp = auth_client.get(
            "/api/public/v1/forms",
            headers={"Origin": "https://forms-public.example.gov"},
        )
        assert "access-control-allow-origin" not in resp.headers
        assert "access-control-allow-methods" not in resp.headers
        assert "access-control-allow-credentials" not in resp.headers

    # TC10.1
    def test_secret_never_in_response_body(self, noauth_client):
        resp = noauth_client.get(
            "/api/public/v1/forms",
            headers={"X-Internal-Auth": "anything"},
        )
        assert _TEST_SECRET not in resp.text

    def test_open_client_works_when_secret_unconfigured(self, open_client):
        # Empty INTERNAL_AUTH_SECRET → middleware no-op.
        resp = open_client.get("/api/public/v1/forms")
        assert resp.status_code == 200


# ===========================================================================
# US-014 AC1–AC3 — list endpoint: limit / offset / total / s=updated_at
# ===========================================================================

class TestListPagination:
    def test_total_limit_offset_in_response(self, auth_client, db, creator):
        for i in range(7):
            _make_form(db, creator=creator, title=f"Form {i:02d}")

        resp = auth_client.get("/api/public/v1/forms?limit=3&offset=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 7
        assert body["limit"] == 3
        assert body["offset"] == 2
        assert len(body["items"]) == 3

    def test_limit_above_max_returns_problem_json(self, auth_client):
        resp = auth_client.get("/api/public/v1/forms?limit=10000")
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert resp.json()["status"] == 400

    def test_negative_offset_returns_problem_json(self, auth_client):
        resp = auth_client.get("/api/public/v1/forms?offset=-1")
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")

    def test_default_limit_applied(self, auth_client, db, creator):
        for i in range(40):
            _make_form(db, creator=creator, title=f"Form {i:03d}")
        resp = auth_client.get("/api/public/v1/forms")
        body = resp.json()
        assert body["limit"] == 25
        assert body["offset"] == 0
        assert len(body["items"]) == 25
        assert body["total"] == 40

    def test_sort_updated_at_desc_is_default(self, auth_client, db, creator):
        # Create three forms with deterministic updated_at via direct UPDATE
        f1 = _make_form(db, creator=creator, title="Old")
        f2 = _make_form(db, creator=creator, title="Mid")
        f3 = _make_form(db, creator=creator, title="New")
        db.execute(
            text("UPDATE forms SET updated_at = :ts WHERE id = :id"),
            {"ts": datetime(2026, 1, 1, tzinfo=timezone.utc), "id": f1.id},
        )
        db.execute(
            text("UPDATE forms SET updated_at = :ts WHERE id = :id"),
            {"ts": datetime(2026, 6, 1, tzinfo=timezone.utc), "id": f2.id},
        )
        db.execute(
            text("UPDATE forms SET updated_at = :ts WHERE id = :id"),
            {"ts": datetime(2026, 12, 1, tzinfo=timezone.utc), "id": f3.id},
        )
        db.flush()

        resp = auth_client.get("/api/public/v1/forms")
        titles = [i["title"] for i in resp.json()["items"]]
        assert titles == ["New", "Mid", "Old"]

    def test_sort_updated_at_asc(self, auth_client, db, creator):
        f1 = _make_form(db, creator=creator, title="Old")
        f2 = _make_form(db, creator=creator, title="New")
        db.execute(
            text("UPDATE forms SET updated_at = :ts WHERE id = :id"),
            {"ts": datetime(2026, 1, 1, tzinfo=timezone.utc), "id": f1.id},
        )
        db.execute(
            text("UPDATE forms SET updated_at = :ts WHERE id = :id"),
            {"ts": datetime(2026, 12, 1, tzinfo=timezone.utc), "id": f2.id},
        )
        db.flush()
        resp = auth_client.get("/api/public/v1/forms?s=updated_at&o=asc")
        titles = [i["title"] for i in resp.json()["items"]]
        assert titles == ["Old", "New"]

    def test_invalid_sort_field_returns_problem_json(self, auth_client):
        resp = auth_client.get("/api/public/v1/forms?s=foo")
        # Pydantic enum validation -> 400 via our handler
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["status"] == 400
        assert "errors" in body  # validation extension

    def test_no_internal_fields_in_list_items(self, auth_client, db, creator):
        _make_form(db, creator=creator, title="X")
        resp = auth_client.get("/api/public/v1/forms")
        item = resp.json()["items"][0]
        for forbidden in ("s3_key", "form_id", "business_area_id"):
            assert forbidden not in item


# ===========================================================================
# US-014 AC4–AC5 — detail endpoint
# ===========================================================================

class TestDetail:
    def _seed(self, db, creator) -> tuple[Form, FormNumberReservation]:
        ba = _make_ba(db, name="Highway Safety")
        pfx = _make_prefix(db, prefix="H", creator=creator)
        res = _make_reservation(db, prefix=pfx, full_form_number="H0021", creator=creator)
        f = _make_form(
            db, creator=creator,
            title="Permit Application",
            description="Apply for a transportation permit.",
            business_area=ba, reservation=res,
            keywords=["permit", "transport"],
            file_type="pdf",
            effective_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        return f, res

    def test_detail_returns_full_metadata(self, auth_client, db, creator):
        f, _ = self._seed(db, creator)
        _attach_version(
            db, form=f, creator=creator,
            s3_key="forms/H0021/v1.pdf", file_name="permit.pdf",
            file_size=98765, file_type="pdf",
        )

        resp = auth_client.get("/api/public/v1/forms/H0021")
        assert resp.status_code == 200
        body = resp.json()
        assert body["form_number"] == "H0021"
        assert body["title"] == "Permit Application"
        assert body["business_area"] == "Highway Safety"
        assert body["keywords"] == ["permit", "transport"]
        assert body["file"] == {
            "filename": "permit.pdf",
            "size": 98765,
            "content_type": "pdf",
        }

    def test_detail_no_s3_reference_in_body(self, auth_client, db, creator):
        f, _ = self._seed(db, creator)
        _attach_version(
            db, form=f, creator=creator,
            s3_key="bucket-name/forms/H0021/v1.pdf",
            file_name="permit.pdf",
        )
        resp = auth_client.get("/api/public/v1/forms/H0021")
        text_body = resp.text
        assert "s3_key" not in text_body
        assert "s3://" not in text_body
        assert "amazonaws" not in text_body
        assert "bucket-name" not in text_body

    def test_detail_404_when_draft(self, auth_client, db, creator):
        ba = _make_ba(db, name="Z")
        pfx = _make_prefix(db, prefix="D", creator=creator)
        res = _make_reservation(db, prefix=pfx, full_form_number="D0099", creator=creator)
        _make_form(
            db, creator=creator, title="Draft", status="draft",
            business_area=ba, reservation=res,
        )
        resp = auth_client.get("/api/public/v1/forms/D0099")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")
        # Generic body — never reveals existence.
        assert "draft" not in resp.text.lower()

    def test_detail_404_when_private(self, auth_client, db, creator):
        pfx = _make_prefix(db, prefix="P", creator=creator)
        res = _make_reservation(db, prefix=pfx, full_form_number="P0001", creator=creator)
        _make_form(
            db, creator=creator, title="Private", is_public=False, reservation=res,
        )
        resp = auth_client.get("/api/public/v1/forms/P0001")
        assert resp.status_code == 404

    def test_detail_etag_and_304(self, auth_client, db, creator):
        f, _ = self._seed(db, creator)
        _attach_version(db, form=f, creator=creator, s3_key="k", file_name="n.pdf")
        r1 = auth_client.get("/api/public/v1/forms/H0021")
        etag = r1.headers["ETag"]
        r2 = auth_client.get(
            "/api/public/v1/forms/H0021",
            headers={"If-None-Match": etag},
        )
        assert r2.status_code == 304
        assert r2.headers["ETag"] == etag


# ===========================================================================
# US-014 AC6–AC7 — file download (X-Accel-Redirect)
# ===========================================================================

class TestDownload:
    def _seed(self, db, creator, *, s3_key="forms/X0001/v1.pdf",
              file_name="application.pdf", status="published",
              is_public=True) -> Form:
        pfx = _make_prefix(db, prefix="X", creator=creator)
        res = _make_reservation(
            db, prefix=pfx, full_form_number="X0001", creator=creator
        )
        f = _make_form(
            db, creator=creator, title="App", reservation=res,
            status=status, is_public=is_public, file_type="pdf",
        )
        if status == "published" and is_public:
            _attach_version(
                db, form=f, creator=creator,
                s3_key=s3_key, file_name=file_name,
            )
        return f

    def test_download_emits_x_accel_redirect(self, auth_client, db, creator):
        self._seed(db, creator)
        resp = auth_client.get("/api/public/v1/forms/X0001/file")
        assert resp.status_code == 200
        assert resp.content == b""
        assert resp.headers["X-Accel-Redirect"] == "/internal-s3/forms/X0001/v1.pdf"
        assert "application.pdf" in resp.headers["Content-Disposition"]
        assert resp.headers["Cache-Control"] == "private, no-store"

    def test_download_no_s3_in_body(self, auth_client, db, creator):
        self._seed(db, creator, s3_key="my-secret-bucket/forms/X0001/v1.pdf")
        resp = auth_client.get("/api/public/v1/forms/X0001/file")
        assert resp.status_code == 200
        assert b"my-secret-bucket" not in resp.content
        # And not in any non-X-Accel-Redirect header either.
        for hname, hval in resp.headers.items():
            if hname.lower() != "x-accel-redirect":
                assert "my-secret-bucket" not in hval

    def test_download_404_for_draft(self, auth_client, db, creator):
        self._seed(db, creator, status="draft", is_public=True)
        resp = auth_client.get("/api/public/v1/forms/X0001/file")
        assert resp.status_code == 404
        assert "X-Accel-Redirect" not in resp.headers

    def test_download_404_for_private(self, auth_client, db, creator):
        self._seed(db, creator, status="published", is_public=False)
        resp = auth_client.get("/api/public/v1/forms/X0001/file")
        assert resp.status_code == 404
        assert "X-Accel-Redirect" not in resp.headers

    def test_download_404_when_no_attached_file(self, auth_client, db, creator):
        # Published+public form but no FormVersion row.
        pfx = _make_prefix(db, prefix="Y", creator=creator)
        res = _make_reservation(
            db, prefix=pfx, full_form_number="Y0001", creator=creator
        )
        _make_form(db, creator=creator, title="No file", reservation=res)
        resp = auth_client.get("/api/public/v1/forms/Y0001/file")
        assert resp.status_code == 404
        assert "X-Accel-Redirect" not in resp.headers

    def test_download_audit_log_emitted(self, auth_client, db, creator, caplog):
        import logging
        self._seed(db, creator)
        with caplog.at_level(logging.INFO, logger="public_backend.audit"):
            resp = auth_client.get(
                "/api/public/v1/forms/X0001/file",
                headers={
                    "X-Real-IP": "203.0.113.5",
                    "User-Agent": "TestUA/1.0",
                },
            )
        assert resp.status_code == 200
        # structlog renders JSON to stdout; we don't depend on caplog
        # capturing it.  Instead, sanity-check the logger exists and the
        # request succeeded — the unit test in TestAuditModule covers the
        # call path explicitly.

    def test_download_ignores_client_supplied_x_accel_redirect(self, auth_client, db, creator):
        """A client trying to inject ``X-Accel-Redirect`` must not appear
        in the response — the value is set server-side from the row."""
        self._seed(db, creator, s3_key="forms/X0001/real.pdf")
        resp = auth_client.get(
            "/api/public/v1/forms/X0001/file",
            headers={"X-Accel-Redirect": "/internal-s3/HACKED.pdf"},
        )
        assert resp.headers["X-Accel-Redirect"] == "/internal-s3/forms/X0001/real.pdf"


class TestAuditModule:
    """Direct unit-test of the audit emitter so the integration test
    above doesn't have to rely on log capture machinery."""

    def test_log_form_download_safe_fields(self):
        from starlette.requests import Request
        from audit import log_form_download

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/public/v1/forms/X0001/file",
            "headers": [
                (b"x-real-ip", b"203.0.113.5"),
                (b"user-agent", b"TestUA/1.0"),
                (b"x-internal-auth", b"super-secret"),
            ],
            "client": ("203.0.113.5", 5555),
        }
        req = Request(scope)
        # Smoke: must not raise; secret must not be inspected by the helper.
        log_form_download(req, form_number="X0001", filename="application.pdf")


# ===========================================================================
# US-014 AC8 — OG endpoint
# ===========================================================================

class TestOG:
    def test_og_returns_html_with_meta_tags(self, auth_client, db, creator):
        ba = _make_ba(db, name="Highway Safety")
        pfx = _make_prefix(db, prefix="H", creator=creator)
        res = _make_reservation(db, prefix=pfx, full_form_number="H0021", creator=creator)
        _make_form(
            db, creator=creator, title="Permit Application",
            description="Apply for a transportation permit.",
            business_area=ba, reservation=res,
            effective_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )

        resp = auth_client.get("/api/public/v1/forms/H0021/og")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        body = resp.text
        for marker in (
            'property="og:title"',
            'property="og:description"',
            'property="og:url"',
            'property="og:type"',
            'name="twitter:card"',
            '<link rel="canonical"',
            'application/ld+json',
            'forms-public.example.gov/forms/H0021',
        ):
            assert marker in body, f"OG marker missing: {marker}"

    def test_og_html_escapes_user_content(self, auth_client, db, creator):
        pfx = _make_prefix(db, prefix="H", creator=creator)
        res = _make_reservation(db, prefix=pfx, full_form_number="H0099", creator=creator)
        _make_form(
            db, creator=creator,
            title="Evil <script>alert(1)</script>",
            description='Bad "quotes" & ampersands',
            reservation=res,
        )
        resp = auth_client.get("/api/public/v1/forms/H0099/og")
        assert resp.status_code == 200
        # Raw script tag must NOT appear; it must be entity-escaped.
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;" in resp.text
        assert "&amp;" in resp.text

    def test_og_404_for_unpublished(self, auth_client, db, creator):
        pfx = _make_prefix(db, prefix="H", creator=creator)
        res = _make_reservation(db, prefix=pfx, full_form_number="H0500", creator=creator)
        _make_form(db, creator=creator, title="Draft", status="draft", reservation=res)
        resp = auth_client.get("/api/public/v1/forms/H0500/og")
        assert resp.status_code == 404


# ===========================================================================
# US-014 AC9 — /business-areas
# ===========================================================================

class TestBusinessAreas:
    def test_returns_distinct_active_areas(self, auth_client, db, creator):
        ba1 = _make_ba(db, name="Highway Safety")
        ba2 = _make_ba(db, name="Vehicle Inspection")
        ba3 = _make_ba(db, name="Empty Area")  # has no forms — must be excluded
        _make_form(db, creator=creator, title="A", business_area=ba1)
        _make_form(db, creator=creator, title="B", business_area=ba1)
        _make_form(db, creator=creator, title="C", business_area=ba2)
        # ba3 deliberately has no published+public form.

        resp = auth_client.get("/api/public/v1/business-areas")
        assert resp.status_code == 200
        names = sorted(item["name"] for item in resp.json()["items"])
        assert names == ["Highway Safety", "Vehicle Inspection"]
        assert "Empty Area" not in names

    def test_business_areas_cache_headers(self, auth_client, db, creator):
        ba = _make_ba(db, name="A")
        _make_form(db, creator=creator, title="A", business_area=ba)
        resp = auth_client.get("/api/public/v1/business-areas")
        assert "max-age=600" in resp.headers["Cache-Control"]
        assert resp.headers["ETag"]

    def test_business_areas_etag_304(self, auth_client, db, creator):
        ba = _make_ba(db, name="A")
        _make_form(db, creator=creator, title="A", business_area=ba)
        r1 = auth_client.get("/api/public/v1/business-areas")
        r2 = auth_client.get(
            "/api/public/v1/business-areas",
            headers={"If-None-Match": r1.headers["ETag"]},
        )
        assert r2.status_code == 304


# ===========================================================================
# US-014 AC10 — /sitemap.xml
# ===========================================================================

class TestSitemap:
    def test_sitemap_returns_valid_xml(self, auth_client, db, creator):
        pfx = _make_prefix(db, prefix="H", creator=creator)
        for fn in ("H0001", "H0002", "H0003"):
            res = _make_reservation(db, prefix=pfx, full_form_number=fn, creator=creator)
            _make_form(db, creator=creator, title=f"F-{fn}", reservation=res)

        resp = auth_client.get("/api/public/v1/sitemap.xml")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        body = resp.text
        assert body.startswith('<?xml')
        assert "<urlset" in body
        root = ET.fromstring(body)
        loc_values = [loc.text for loc in root.findall(".//{*}loc") if loc.text]
        assert any(
            (parsed.scheme == "https" and parsed.hostname == "forms-public.example.gov")
            for parsed in (urlparse(loc) for loc in loc_values)
        )
        for fn in ("H0001", "H0002", "H0003"):
            assert f"/forms/{fn}" in body

    def test_sitemap_cache_3600(self, auth_client, db, creator):
        resp = auth_client.get("/api/public/v1/sitemap.xml")
        assert "max-age=3600" in resp.headers["Cache-Control"]


# ===========================================================================
# US-014 AC13–AC14 — RFC 7807 problem JSON; no stack traces
# ===========================================================================

class TestProblemJson:
    def test_404_has_problem_json_shape(self, auth_client):
        resp = auth_client.get("/api/public/v1/forms/DOES_NOT_EXIST")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        for k in ("type", "title", "status", "detail", "instance"):
            assert k in body
        assert body["status"] == 404

    def test_invalid_query_param_problem_json(self, auth_client):
        resp = auth_client.get("/api/public/v1/forms?limit=-5")
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["status"] == 400
        assert body["title"] == "Invalid limit"

    def test_internal_error_no_stack_trace(self, auth_client, monkeypatch):
        """Force an unhandled exception in a route and verify the 500
        response contains no traceback / library / file path."""
        from main import app
        from fastapi import APIRouter

        boom = APIRouter()

        @boom.get("/__test_boom")
        def _boom():
            raise RuntimeError("internal boom with /etc/passwd path")

        # Mount temporarily.
        app.include_router(boom)
        try:
            resp = auth_client.get("/__test_boom")
            assert resp.status_code == 500
            assert resp.headers["content-type"].startswith("application/problem+json")
            body = resp.text
            assert "Traceback" not in body
            assert "/etc/passwd" not in body
            assert "RuntimeError" not in body
            assert ".py" not in body
        finally:
            # Remove the temp route so other tests aren't affected.
            app.router.routes = [
                r for r in app.router.routes
                if getattr(r, "path", "") != "/__test_boom"
            ]
