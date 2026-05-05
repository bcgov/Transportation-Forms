"""FEAT-0004 — Public Read-Only Forms API test suite.

Covers US-001 (list forms), US-002 (CORS), US-003 (caching/ETag),
US-004 (infrastructure/hardening), and US-005 (DB view).

Uses the shared conftest.py PostgreSQL test infrastructure.  The
``public_forms_v`` database view is recreated in each test session
using ``Base.metadata.create_all`` on the view-backing raw SQL.
"""

import importlib
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

# Add public-backend to sys.path so its modules are importable.
_PUBLIC_BACKEND_DIR = str(Path(__file__).resolve().parent.parent / "public-backend")
if _PUBLIC_BACKEND_DIR not in sys.path:
    sys.path.insert(0, _PUBLIC_BACKEND_DIR)

from backend.models import BusinessArea, Form, FormNumberReservation, FormNumberPrefix, User

# ---------------------------------------------------------------------------
# View + app bootstrap helpers
# ---------------------------------------------------------------------------

_VIEW_DDL = """\
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
def _public_view(_test_engine):
    """Create the ``public_forms_v`` view once per session."""
    with _test_engine.connect() as conn:
        conn.execute(text(_VIEW_DDL))
        conn.commit()
    yield
    with _test_engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS public_forms_v"))
        conn.commit()


@pytest.fixture()
def public_client(db: Session, _public_view, monkeypatch):
    """TestClient wired to the public-backend FastAPI app.

    Overrides the public-backend ``get_db`` dependency to use the
    transactional test session.
    """
    monkeypatch.setenv("DATABASE_URL_READONLY", "postgresql://x@localhost/x")
    # FEAT-0005: CORS removed; INTERNAL_AUTH_SECRET left empty so the
    # middleware degrades to a no-op for these legacy FEAT-0004 tests.
    monkeypatch.setenv("INTERNAL_AUTH_SECRET", "")
    monkeypatch.setenv("CACHE_MAX_AGE", "300")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    # Must import AFTER env vars are set so Settings picks them up.
    _database_mod = importlib.import_module("database")
    _main_mod = importlib.import_module("main")
    public_get_db = _database_mod.get_db
    public_app = _main_mod.app

    public_app.dependency_overrides[public_get_db] = lambda: db
    yield TestClient(public_app, raise_server_exceptions=False)
    public_app.dependency_overrides.pop(public_get_db, None)


# ---------------------------------------------------------------------------
# Data factories (scoped to the forms/view context)
# ---------------------------------------------------------------------------

@pytest.fixture()
def _creator(db: Session) -> User:
    """A user to satisfy forms.created_by_id FK."""
    user = User(
        id=uuid.uuid4(),
        email=f"creator-{uuid.uuid4().hex[:6]}@example.com",
        first_name="Creator",
        last_name="Bot",
    )
    db.add(user)
    db.flush()
    return user


def _make_ba(db: Session, *, name: str, is_active: bool = True, deleted_at=None) -> BusinessArea:
    ba = BusinessArea(
        id=uuid.uuid4(),
        name=name,
        is_active=is_active,
        deleted_at=deleted_at,
    )
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
    form_number: str,
    full_form_number: str,
    reserved_by: User,
    status: str = "approved",
) -> FormNumberReservation:
    r = FormNumberReservation(
        id=uuid.uuid4(),
        prefix_id=prefix.id,
        form_number=form_number,
        full_form_number=full_form_number,
        numbering_method="auto_generated",
        status=status,
        reserved_by_id=reserved_by.id,
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
    status: str = "published",
    is_public: bool = True,
    deleted_at=None,
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
        deleted_at=deleted_at,
    )
    db.add(f)
    db.flush()
    return f


# ===================================================================
# US-001 — List publicly visible forms
# ===================================================================

class TestListPublicForms:
    """TC-US-001 test cases."""

    # TC-1.1
    def test_happy_path(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Form A")
        _make_form(db, creator=_creator, title="Form B")
        _make_form(db, creator=_creator, title="Form C")

        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

    # TC-1.2
    def test_response_field_structure(self, public_client, db, _creator):
        ba = _make_ba(db, name="Highway Safety")
        pfx = _make_prefix(db, prefix="H", creator=_creator)
        res = _make_reservation(db, prefix=pfx, form_number="0021",
                                full_form_number="H0021", reserved_by=_creator)
        _make_form(
            db, creator=_creator, title="Safety Inspection Report",
            description="Quarterly safety inspection", business_area=ba,
            reservation=res, keywords=["safety", "inspection"],
            file_type="pdf",
            effective_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )

        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["form_number"] == "H0021"
        assert item["title"] == "Safety Inspection Report"
        assert item["description"] == "Quarterly safety inspection"
        assert item["business_area"] == "Highway Safety"
        assert item["keywords"] == ["safety", "inspection"]
        assert item["file_type"] == "pdf"
        assert "2026-01-15" in item["effective_date"]

    # TC-1.3
    def test_search_matches_title(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Safety Report")
        _make_form(db, creator=_creator, title="Budget Summary")

        resp = public_client.get("/api/public/v1/forms?q=safety")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert "Safety" in resp.json()["items"][0]["title"]

    # TC-1.4
    def test_search_matches_description(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Form A",
                   description="Annual vehicle inspection procedures")

        resp = public_client.get("/api/public/v1/forms?q=vehicle")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    # TC-1.5
    def test_search_matches_keywords(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Form B",
                   keywords=["compliance", "regulation"])

        resp = public_client.get("/api/public/v1/forms?q=regulation")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    # TC-1.6
    def test_search_no_match(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Existing Form")

        resp = public_client.get("/api/public/v1/forms?q=xyznonexistent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    # TC-1.7
    def test_filter_by_business_area(self, public_client, db, _creator):
        ba1 = _make_ba(db, name="Highway Safety")
        ba2 = _make_ba(db, name="Vehicle Inspection")
        _make_form(db, creator=_creator, title="F1", business_area=ba1)
        _make_form(db, creator=_creator, title="F2", business_area=ba1)
        _make_form(db, creator=_creator, title="F3", business_area=ba2)

        resp = public_client.get("/api/public/v1/forms?f=Highway%20Safety")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    # TC-1.8
    def test_filter_case_insensitive(self, public_client, db, _creator):
        ba = _make_ba(db, name="Highway Safety")
        _make_form(db, creator=_creator, title="F1", business_area=ba)

        resp = public_client.get("/api/public/v1/forms?f=highway%20safety")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    # TC-1.9
    def test_sort_effective_date_asc(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="C",
                   effective_date=datetime(2026, 3, 1, tzinfo=timezone.utc))
        _make_form(db, creator=_creator, title="A",
                   effective_date=datetime(2026, 1, 15, tzinfo=timezone.utc))
        _make_form(db, creator=_creator, title="B",
                   effective_date=datetime(2026, 6, 20, tzinfo=timezone.utc))

        resp = public_client.get("/api/public/v1/forms?s=effective_date&o=asc")
        assert resp.status_code == 200
        dates = [i["effective_date"] for i in resp.json()["items"]]
        assert dates == sorted(dates)

    # TC-1.10
    def test_sort_effective_date_desc(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="C",
                   effective_date=datetime(2026, 3, 1, tzinfo=timezone.utc))
        _make_form(db, creator=_creator, title="A",
                   effective_date=datetime(2026, 1, 15, tzinfo=timezone.utc))
        _make_form(db, creator=_creator, title="B",
                   effective_date=datetime(2026, 6, 20, tzinfo=timezone.utc))

        resp = public_client.get("/api/public/v1/forms?s=effective_date&o=desc")
        assert resp.status_code == 200
        dates = [i["effective_date"] for i in resp.json()["items"]]
        assert dates == sorted(dates, reverse=True)

    # TC-1.11
    def test_sort_form_number_asc(self, public_client, db, _creator):
        pfx = _make_prefix(db, prefix="X", creator=_creator)
        for num, full in [("001", "A001"), ("002", "B002"), ("003", "C003")]:
            res = _make_reservation(db, prefix=pfx, form_number=num,
                                    full_form_number=full, reserved_by=_creator)
            _make_form(db, creator=_creator, title=f"Form {full}", reservation=res)

        resp = public_client.get("/api/public/v1/forms?s=form_number&o=asc")
        assert resp.status_code == 200
        numbers = [i["form_number"] for i in resp.json()["items"]]
        assert numbers == sorted(numbers)

    # TC-1.12
    def test_sort_title_desc(self, public_client, db, _creator):
        for t in ["Alpha Form", "Beta Form", "Gamma Form"]:
            _make_form(db, creator=_creator, title=t)

        resp = public_client.get("/api/public/v1/forms?s=title&o=desc")
        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert titles == ["Gamma Form", "Beta Form", "Alpha Form"]

    # TC-1.13
    def test_combined_search_filter_sort(self, public_client, db, _creator):
        ba = _make_ba(db, name="Highway Safety")
        _make_form(db, creator=_creator, title="Permit Alpha", business_area=ba)
        _make_form(db, creator=_creator, title="Permit Beta", business_area=ba)
        _make_form(db, creator=_creator, title="Budget Report", business_area=ba)
        ba2 = _make_ba(db, name="Other")
        _make_form(db, creator=_creator, title="Permit Gamma", business_area=ba2)

        resp = public_client.get(
            "/api/public/v1/forms?q=permit&f=Highway%20Safety&s=title&o=asc"
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        assert items[0]["title"] == "Permit Alpha"
        assert items[1]["title"] == "Permit Beta"

    # TC-1.14 — FEAT-0005: validation errors return 400 problem+json
    # (US-014 AC13) instead of FastAPI's default 422.
    def test_invalid_sort_field(self, public_client):
        resp = public_client.get("/api/public/v1/forms?s=created_by")
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")

    # TC-1.15
    def test_invalid_sort_order(self, public_client):
        resp = public_client.get("/api/public/v1/forms?o=random")
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")

    # TC-1.16
    def test_q_exceeds_max_length(self, public_client):
        long_q = "x" * 101
        resp = public_client.get(f"/api/public/v1/forms?q={long_q}")
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")

    # TC-1.17
    def test_draft_forms_excluded(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Draft Form", status="draft")
        _make_form(db, creator=_creator, title="Published Form", status="published")

        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Draft Form" not in titles
        assert "Published Form" in titles

    # TC-1.18
    def test_pending_review_excluded(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Pending Form", status="pending_review")

        resp = public_client.get("/api/public/v1/forms")
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Pending Form" not in titles

    # TC-1.19
    def test_archived_forms_excluded(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Archived Form", status="archived")

        resp = public_client.get("/api/public/v1/forms")
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Archived Form" not in titles

    # TC-1.20
    def test_non_public_excluded(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Private Form", is_public=False)

        resp = public_client.get("/api/public/v1/forms")
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Private Form" not in titles

    # TC-1.21
    def test_soft_deleted_excluded(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Deleted Form",
                   deleted_at=datetime(2026, 4, 1, tzinfo=timezone.utc))

        resp = public_client.get("/api/public/v1/forms")
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Deleted Form" not in titles

    # TC-1.22
    def test_empty_result(self, public_client):
        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    # TC-1.23
    def test_excludes_internal_identifiers(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Test Form")

        resp = public_client.get("/api/public/v1/forms")
        item = resp.json()["items"][0]
        # FEAT-0005: ``updated_at`` IS now exposed (powers the recently
        # updated feed); everything else internal stays hidden.
        forbidden = [
            "id", "form_id", "created_by_id", "form_number_reservation_id",
            "business_area_id", "is_public", "status", "deleted_at",
            "created_at", "form_source", "form_source_url",
            "form_attachment_url", "form_attachment_filename",
            "collects_personal_info",
            "s3_key",
        ]
        for key in forbidden:
            assert key not in item, f"Internal field '{key}' found in response"

    # TC-1.24
    def test_nonexistent_ba_filter(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Some Form")

        resp = public_client.get("/api/public/v1/forms?f=Nonexistent%20Division")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_form_without_reservation_has_null_form_number(
        self, public_client, db, _creator
    ):
        _make_form(db, creator=_creator, title="No Reservation Form")

        resp = public_client.get("/api/public/v1/forms")
        item = resp.json()["items"][0]
        assert item["form_number"] is None

    def test_form_with_inactive_ba_has_null_business_area(
        self, public_client, db, _creator
    ):
        ba = _make_ba(db, name="Inactive BA", is_active=False)
        _make_form(db, creator=_creator, title="Inactive BA Form", business_area=ba)

        resp = public_client.get("/api/public/v1/forms")
        item = resp.json()["items"][0]
        assert item["business_area"] is None

    def test_form_with_deleted_ba_has_null_business_area(
        self, public_client, db, _creator
    ):
        ba = _make_ba(db, name="Deleted BA",
                      deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _make_form(db, creator=_creator, title="Deleted BA Form", business_area=ba)

        resp = public_client.get("/api/public/v1/forms")
        item = resp.json()["items"][0]
        assert item["business_area"] is None

    def test_default_sort_title_asc(self, public_client, db, _creator):
        # FEAT-0005: default sort is now ``updated_at desc``; explicitly
        # request title-asc so this regression test keeps its original
        # intent (alphabetical ordering when asked for).
        for t in ["Zeta", "Alpha", "Mu"]:
            _make_form(db, creator=_creator, title=t)

        resp = public_client.get("/api/public/v1/forms?s=title&o=asc")
        titles = [i["title"] for i in resp.json()["items"]]
        assert titles == ["Alpha", "Mu", "Zeta"]

    def test_whitespace_only_q_treated_as_no_search(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Any Form")

        resp = public_client.get("/api/public/v1/forms?q=%20%20")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


# ===================================================================
# US-013 (FEAT-0005) — CORS removed; same-origin only
# (replaces former US-002 CORS allowlist tests)
# ===================================================================

class TestNoCORS:
    """FEAT-0005: ``CORSMiddleware`` was removed; verify no CORS headers
    are emitted regardless of Origin."""

    def test_get_emits_no_cors_headers(self, public_client):
        resp = public_client.get(
            "/api/public/v1/forms",
            headers={"Origin": "https://forms.example.gov"},
        )
        assert "access-control-allow-origin" not in resp.headers
        assert "access-control-allow-credentials" not in resp.headers
        assert "access-control-allow-methods" not in resp.headers

    def test_evil_origin_emits_no_cors_headers(self, public_client):
        resp = public_client.get(
            "/api/public/v1/forms",
            headers={"Origin": "https://evil.example.com"},
        )
        assert "access-control-allow-origin" not in resp.headers


# ===================================================================
# US-003 — Cache-Control and ETag/304
# ===================================================================

class TestCaching:
    """TC-US-003 test cases."""

    # TC-3.1
    def test_cache_control_header(self, public_client):
        resp = public_client.get("/api/public/v1/forms")
        assert "Cache-Control" in resp.headers
        cc = resp.headers["Cache-Control"]
        assert "public" in cc
        assert "max-age=300" in cc

    # TC-3.2
    def test_etag_header(self, public_client):
        resp = public_client.get("/api/public/v1/forms")
        assert "ETag" in resp.headers
        etag = resp.headers["ETag"]
        assert etag.startswith('"') and etag.endswith('"')

    # TC-3.3
    def test_304_when_etag_matches(self, public_client):
        resp1 = public_client.get("/api/public/v1/forms")
        etag = resp1.headers["ETag"]

        resp2 = public_client.get(
            "/api/public/v1/forms",
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304
        assert resp2.headers["ETag"] == etag

    # TC-3.4
    def test_200_when_etag_does_not_match(self, public_client):
        resp = public_client.get(
            "/api/public/v1/forms",
            headers={"If-None-Match": '"old-etag"'},
        )
        assert resp.status_code == 200
        assert "ETag" in resp.headers

    # TC-3.5
    def test_etag_varies_by_query_params(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Safety Form",
                   keywords=["safety"])
        _make_form(db, creator=_creator, title="Permit Form",
                   keywords=["permit"])

        r1 = public_client.get("/api/public/v1/forms?q=safety")
        r2 = public_client.get("/api/public/v1/forms?q=permit")
        assert r1.headers["ETag"] != r2.headers["ETag"]

    # TC-3.6
    def test_no_set_cookie(self, public_client):
        resp = public_client.get("/api/public/v1/forms")
        assert "set-cookie" not in resp.headers

    # TC-3.7
    def test_cache_control_public_directive(self, public_client):
        resp = public_client.get("/api/public/v1/forms")
        cc = resp.headers["Cache-Control"]
        assert "private" not in cc
        assert "no-store" not in cc
        assert "public" in cc


# ===================================================================
# US-004 — Service infrastructure and hardening
# ===================================================================

class TestInfrastructure:
    """TC-US-004 test cases."""

    # TC-4.1
    def test_liveness(self, public_client):
        resp = public_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    # TC-4.2
    def test_readiness_db_available(self, public_client):
        resp = public_client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    # TC-4.10
    def test_get_allowed(self, public_client):
        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code != 405

    # TC-4.11 — FEAT-0005: CORS removed → no preflight handler; OPTIONS
    # on a GET-only route returns 405 from the router.  This is correct
    # for a same-origin-only public surface.
    def test_options_returns_405(self, public_client):
        resp = public_client.options("/api/public/v1/forms")
        assert resp.status_code == 405

    # TC-4.12
    def test_post_returns_405(self, public_client):
        resp = public_client.post("/api/public/v1/forms")
        assert resp.status_code == 405

    # TC-4.13
    def test_put_returns_405(self, public_client):
        resp = public_client.put("/api/public/v1/forms")
        assert resp.status_code == 405

    # TC-4.14
    def test_patch_returns_405(self, public_client):
        resp = public_client.patch("/api/public/v1/forms")
        assert resp.status_code == 405

    # TC-4.15
    def test_delete_returns_405(self, public_client):
        resp = public_client.delete("/api/public/v1/forms")
        assert resp.status_code == 405

    def test_request_id_propagated(self, public_client):
        resp = public_client.get(
            "/api/public/v1/forms",
            headers={"X-Request-ID": "req-abc-123"},
        )
        assert resp.headers.get("X-Request-ID") == "req-abc-123"

    def test_request_id_generated(self, public_client):
        resp = public_client.get("/api/public/v1/forms")
        assert resp.headers.get("X-Request-ID")
        assert len(resp.headers["X-Request-ID"]) > 0

    def test_request_id_sanitised(self, public_client):
        resp = public_client.get(
            "/api/public/v1/forms",
            headers={"X-Request-ID": "evil<script>alert(1)</script>"},
        )
        # Should generate a new ID (original contains disallowed chars)
        rid = resp.headers.get("X-Request-ID", "")
        assert "<" not in rid
        assert ">" not in rid

    def test_request_id_truncated(self, public_client):
        long_id = "a" * 200
        resp = public_client.get(
            "/api/public/v1/forms",
            headers={"X-Request-ID": long_id},
        )
        rid = resp.headers.get("X-Request-ID", "")
        assert len(rid) <= 128


# ===================================================================
# US-005 — Database view public_forms_v
# ===================================================================

class TestDatabaseView:
    """TC-US-005 — verify the view semantics through the API."""

    def test_view_only_published_public_nondel(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Good", status="published", is_public=True)
        _make_form(db, creator=_creator, title="Draft", status="draft", is_public=True)
        _make_form(db, creator=_creator, title="Private", status="published", is_public=False)
        _make_form(db, creator=_creator, title="Deleted", status="published", is_public=True,
                   deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

        resp = public_client.get("/api/public/v1/forms")
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["title"] == "Good"

    def test_view_columns_exact(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="Column Check")

        resp = public_client.get("/api/public/v1/forms")
        item = resp.json()["items"][0]
        # FEAT-0005 added ``updated_at`` to the public projection;
        # internal columns (form_id, business_area_id, s3_key, file_name,
        # file_size) MUST remain hidden from clients.
        expected_keys = {"form_number", "title", "description", "business_area",
                         "keywords", "file_type", "effective_date", "updated_at"}
        assert set(item.keys()) == expected_keys

    def test_view_left_join_no_reservation(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="No Res")

        resp = public_client.get("/api/public/v1/forms")
        assert resp.json()["items"][0]["form_number"] is None

    def test_view_left_join_no_ba(self, public_client, db, _creator):
        _make_form(db, creator=_creator, title="No BA")

        resp = public_client.get("/api/public/v1/forms")
        assert resp.json()["items"][0]["business_area"] is None

    def test_view_inactive_ba_is_null(self, public_client, db, _creator):
        ba = _make_ba(db, name="Inactive", is_active=False)
        _make_form(db, creator=_creator, title="With Inactive BA", business_area=ba)

        resp = public_client.get("/api/public/v1/forms")
        assert resp.json()["items"][0]["business_area"] is None

    def test_view_deleted_ba_is_null(self, public_client, db, _creator):
        ba = _make_ba(db, name="Del BA",
                      deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _make_form(db, creator=_creator, title="With Del BA", business_area=ba)

        resp = public_client.get("/api/public/v1/forms")
        assert resp.json()["items"][0]["business_area"] is None
