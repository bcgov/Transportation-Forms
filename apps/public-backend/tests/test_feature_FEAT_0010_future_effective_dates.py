"""FEAT-0010 — Filter Future Effective Dates from Public API.

Tests for US-001: Hide Future Effective Forms in Public API.

Covers all acceptance criteria defined in
plan/features/FEAT-0010-future-effective-dates/stories/US-001-hide-future-effective-forms.md

AC1  — Future-dated forms are hidden from list endpoints.
AC2  — Future-dated forms return 404 on detail and file endpoints.
AC3  — Present/past-dated forms are visible (200 OK).
AC4  — NULL effective_date forms are always visible (treated as active).

Run this suite standalone:
    pytest apps/public-backend/tests/ -v
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlalchemy import text
from sqlalchemy.orm import Session

# Import module under test at module level so it is already in sys.modules
# before any freeze_time decorator runs (prevents pydantic metaclass conflict).
from routes.forms import _today_vancouver  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FROZEN_NOW = "2026-05-15 17:00:00"  # UTC; Vancouver is UTC-7 → local 10:00
_FROZEN_VANCOUVER_DATE = "2026-05-15"  # date visible in America/Vancouver at that moment


def _insert_form(
    db: Session,
    *,
    form_number: str,
    title: str = "Test Form",
    effective_date: str | None,
    s3_key: str | None = "bucket/file.pdf",
    file_name: str | None = "file.pdf",
) -> str:
    """Insert a row directly into ``public_forms_v`` and return ``form_id``.

    ``effective_date`` should be an ISO date string (``'YYYY-MM-DD'``) or ``None``.
    It is converted to a Python ``datetime`` so that SQLAlchemy's pysqlite
    adapter serialises it with microseconds (``'YYYY-MM-DD HH:MM:SS.ffffff'``),
    matching how the ORM bind-parameter for the filter is serialised.  This
    avoids a lexicographic mismatch between ``'2026-05-16 00:00:00'`` (string)
    and ``'2026-05-16 00:00:00.000000'`` (datetime) that would cause future
    forms to pass the filter incorrectly.
    """
    form_id = str(uuid.uuid4())
    effective_dt: datetime | None = None
    if effective_date is not None:
        # Accept both 'YYYY-MM-DD' and 'YYYY-MM-DD HH:MM:SS'
        if len(effective_date) == 10:
            effective_dt = datetime(
                int(effective_date[:4]),
                int(effective_date[5:7]),
                int(effective_date[8:10]),
            )
        else:
            effective_dt = datetime.strptime(effective_date, "%Y-%m-%d %H:%M:%S")

    db.execute(
        text(
            """
            INSERT INTO public_forms_v
                (form_id, form_number, title, effective_date, s3_key, file_name, keywords)
            VALUES
                (:form_id, :form_number, :title, :effective_date, :s3_key, :file_name, :keywords)
            """
        ),
        {
            "form_id": form_id,
            "form_number": form_number,
            "title": title,
            "effective_date": effective_dt,
            "s3_key": s3_key,
            "file_name": file_name,
            "keywords": "[]",
        },
    )
    db.commit()  # commit so the request handler (in a worker thread) sees the row
    return form_id


# ---------------------------------------------------------------------------
# Unit tests for the helper functions (no HTTP layer)
# ---------------------------------------------------------------------------


class TestTodayVancouver:
    """Unit-test _today_vancouver() returns the date in America/Vancouver."""

    @freeze_time("2026-05-16 06:59:59", tz_offset=0)  # 2026-05-15 23:59:59 Vancouver (UTC-7)
    def test_returns_vancouver_date_not_utc_date(self):
        result = _today_vancouver()
        assert str(result) == "2026-05-15", (
            "At 06:59:59 UTC it is still May 15 in Vancouver (UTC-7), "
            f"but got {result}"
        )

    @freeze_time("2026-05-16 07:00:01", tz_offset=0)  # 2026-05-16 00:00:01 Vancouver (UTC-7)
    def test_rolls_over_at_vancouver_midnight(self):
        result = _today_vancouver()
        assert str(result) == "2026-05-16", (
            "At 07:00:01 UTC it is May 16 in Vancouver, "
            f"but got {result}"
        )


# ---------------------------------------------------------------------------
# AC1 — Future-dated forms hidden in list endpoint
# ---------------------------------------------------------------------------


class TestListEndpointEffectiveDateFilter:

    @freeze_time(_FROZEN_NOW)
    def test_future_form_excluded_from_list(self, public_client, db):
        """AC1: Form effective tomorrow must not appear in list results."""
        _insert_form(db, form_number="TF-FUTURE-01", effective_date="2026-05-16")  # tomorrow
        _insert_form(db, form_number="TF-TODAY-01", effective_date=_FROZEN_VANCOUVER_DATE)  # today

        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code == 200

        numbers = [item["form_number"] for item in resp.json()["items"]]
        assert "TF-FUTURE-01" not in numbers, "Future-dated form must not appear in list"
        assert "TF-TODAY-01" in numbers, "Today-dated form must appear in list"

    @freeze_time(_FROZEN_NOW)
    def test_past_form_included_in_list(self, public_client, db):
        """AC3: Form effective in the past must appear in list results."""
        _insert_form(db, form_number="TF-PAST-01", effective_date="2026-01-01")

        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code == 200

        numbers = [item["form_number"] for item in resp.json()["items"]]
        assert "TF-PAST-01" in numbers

    @freeze_time(_FROZEN_NOW)
    def test_null_effective_date_included_in_list(self, public_client, db):
        """AC4: Form with NULL effective_date must appear in list results."""
        _insert_form(db, form_number="TF-NULL-01", effective_date=None)

        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code == 200

        numbers = [item["form_number"] for item in resp.json()["items"]]
        assert "TF-NULL-01" in numbers

    @freeze_time(_FROZEN_NOW)
    def test_total_count_excludes_future_forms(self, public_client, db):
        """AC1: The ``total`` field in the list response must not include future forms."""
        _insert_form(db, form_number="TF-FUTURE-02", effective_date="2026-05-16")
        _insert_form(db, form_number="TF-VISIBLE-01", effective_date="2026-05-10")

        resp = public_client.get("/api/public/v1/forms")
        assert resp.status_code == 200

        data = resp.json()
        returned_numbers = {item["form_number"] for item in data["items"]}
        assert "TF-FUTURE-02" not in returned_numbers
        # total must equal the count of non-future forms returned
        assert data["total"] == len(data["items"])


# ---------------------------------------------------------------------------
# AC2 — Future-dated forms return 404 on detail and file endpoints
# ---------------------------------------------------------------------------


class TestDetailEndpointEffectiveDateFilter:

    @freeze_time(_FROZEN_NOW)
    def test_future_form_detail_returns_404(self, public_client, db):
        """AC2: GET /forms/{number} must return 404 for a future-dated form."""
        _insert_form(db, form_number="TF-FUTURE-D01", effective_date="2026-05-16")

        resp = public_client.get("/api/public/v1/forms/TF-FUTURE-D01")
        assert resp.status_code == 404

    @freeze_time(_FROZEN_NOW)
    def test_today_form_detail_returns_200(self, public_client, db):
        """AC3: GET /forms/{number} must return 200 for a form effective today."""
        _insert_form(db, form_number="TF-TODAY-D01", effective_date=_FROZEN_VANCOUVER_DATE)

        resp = public_client.get("/api/public/v1/forms/TF-TODAY-D01")
        assert resp.status_code == 200

    @freeze_time(_FROZEN_NOW)
    def test_past_form_detail_returns_200(self, public_client, db):
        """AC3: GET /forms/{number} must return 200 for a form effective in the past."""
        _insert_form(db, form_number="TF-PAST-D01", effective_date="2026-03-01")

        resp = public_client.get("/api/public/v1/forms/TF-PAST-D01")
        assert resp.status_code == 200

    @freeze_time(_FROZEN_NOW)
    def test_null_effective_date_detail_returns_200(self, public_client, db):
        """AC4: GET /forms/{number} must return 200 when effective_date is NULL."""
        _insert_form(db, form_number="TF-NULL-D01", effective_date=None)

        resp = public_client.get("/api/public/v1/forms/TF-NULL-D01")
        assert resp.status_code == 200


class TestFileEndpointEffectiveDateFilter:

    @freeze_time(_FROZEN_NOW)
    def test_future_form_file_returns_404(self, public_client, db):
        """AC2: GET /forms/{number}/file must return 404 for a future-dated form."""
        _insert_form(db, form_number="TF-FUTURE-F01", effective_date="2026-05-16")

        resp = public_client.get("/api/public/v1/forms/TF-FUTURE-F01/file")
        assert resp.status_code == 404

    @freeze_time(_FROZEN_NOW)
    def test_today_form_file_returns_200(self, public_client, db):
        """AC3: GET /forms/{number}/file must return 200 for a form effective today."""
        _insert_form(db, form_number="TF-TODAY-F01", effective_date=_FROZEN_VANCOUVER_DATE)

        # The endpoint issues X-Accel-Redirect — TestClient will not follow
        # the internal NGINX redirect, but the handler should return 200.
        resp = public_client.get("/api/public/v1/forms/TF-TODAY-F01/file")
        assert resp.status_code == 200
        assert "X-Accel-Redirect" in resp.headers

    @freeze_time(_FROZEN_NOW)
    def test_future_form_og_returns_404_html(self, public_client, db):
        """AC2: GET /forms/{number}/og must serve the 404 HTML page for future forms."""
        _insert_form(db, form_number="TF-FUTURE-OG01", effective_date="2026-05-16")

        resp = public_client.get("/api/public/v1/forms/TF-FUTURE-OG01/og")
        assert resp.status_code == 404
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Boundary — exact midnight boundary in Vancouver
# ---------------------------------------------------------------------------


class TestVancouverMidnightBoundary:

    @freeze_time("2026-05-16 07:00:00", tz_offset=0)  # exactly 00:00:00 Vancouver (UTC-7)
    def test_form_becomes_visible_exactly_at_vancouver_midnight(self, public_client, db):
        """AC3 boundary: form effective 2026-05-16 becomes visible at 00:00 Vancouver."""
        _insert_form(db, form_number="TF-BOUNDARY-01", effective_date="2026-05-16")

        resp = public_client.get("/api/public/v1/forms/TF-BOUNDARY-01")
        assert resp.status_code == 200, (
            "Form effective today must be visible at exactly 00:00 Vancouver"
        )

    @freeze_time("2026-05-16 06:59:59", tz_offset=0)  # 23:59:59 Vancouver (still May 15)
    def test_form_hidden_one_second_before_vancouver_midnight(self, public_client, db):
        """AC1 boundary: form effective 2026-05-16 is hidden at 23:59:59 Vancouver on May 15."""
        _insert_form(db, form_number="TF-BOUNDARY-02", effective_date="2026-05-16")

        resp = public_client.get("/api/public/v1/forms/TF-BOUNDARY-02")
        assert resp.status_code == 404, (
            "Form effective tomorrow must still return 404 at 23:59:59 Vancouver"
        )
