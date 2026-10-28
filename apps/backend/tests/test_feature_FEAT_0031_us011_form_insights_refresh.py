"""Regression coverage for live Form Insights statistics refreshes."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import DailyEngagementCount, Form, UserRole
from backend.services import engagement_stats

TODAY = date(2024, 3, 11)


@pytest.fixture
def refresh_setup(db, user_factory, role_factory, monkeypatch):
    user = user_factory()
    role = role_factory(name="insights_refresh", permissions=["form:stats"])
    db.add(UserRole(id=uuid4(), user_id=user.id, role_id=role.id))
    form = Form(
        id=uuid4(),
        title="Form Insights refresh",
        status="draft",
        is_public=False,
        form_source="URL",
        created_by_id=user_factory().id,
    )
    db.add(form)
    db.flush()
    monkeypatch.setattr(engagement_stats, "pct_today", lambda: TODAY)
    monkeypatch.setattr(
        engagement_stats, "mark_transaction_read_only", lambda _db: None
    )
    engagement_stats._cache.clear()
    monkeypatch.setattr(engagement_stats, "_cache_day", None)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        sub=str(user.id),
        email="refresh@example.test",
        name="Refresh tester",
        roles=["insights_refresh"],
    )
    try:
        yield TestClient(app), role, form
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        engagement_stats._cache.clear()


def _url(form, period="30d", *, refresh=False):
    url = f"/api/v1/staff/forms/{form.id}/stats?period={period}"
    return f"{url}&refresh=true" if refresh else url


def test_refresh_reaggregates_only_requested_cached_key(refresh_setup, db):
    client, _, form = refresh_setup
    count = DailyEngagementCount(
        form_id=form.id,
        metric="download",
        source="Staff",
        pct_day=TODAY - timedelta(days=1),
        count=2,
    )
    db.add(count)
    db.flush()

    original = client.get(_url(form))
    other_period = client.get(_url(form, "7d"))
    assert original.status_code == other_period.status_code == 200
    count.count = 5
    db.flush()

    assert client.get(_url(form)).json() == original.json()
    refreshed = client.get(_url(form, refresh=True))
    assert refreshed.status_code == 200
    assert refreshed.headers["cache-control"] == "private, no-store"
    assert refreshed.json() == {
        **original.json(),
        "totals": {
            **original.json()["totals"],
            "download": {"Staff": 5, "Public": 0},
        },
    }
    assert set(refreshed.json()) == {
        "period",
        "pct_day_cutoff",
        "data_through",
        "totals",
    }
    assert client.get(_url(form)).json() == refreshed.json()
    assert client.get(_url(form, "7d")).json() == other_period.json()
    refreshed_other_period = client.get(_url(form, "7d", refresh=True))
    assert refreshed_other_period.status_code == 200
    assert (
        refreshed_other_period.headers["cache-control"] == "private, no-store"
    )
    assert refreshed_other_period.json()["totals"]["download"]["Staff"] == 5
    assert client.get(_url(form, "7d")).json() == refreshed_other_period.json()


def test_refresh_checks_permission_and_auth_even_with_cached_result(
    refresh_setup, db
):
    client, role, form = refresh_setup
    assert client.get(_url(form)).status_code == 200

    role.permissions = []
    db.flush()
    denied = client.get(_url(form, refresh=True))
    assert denied.status_code == 403
    assert denied.json() == {
        "detail": "Insufficient permissions for this action"
    }
    assert "totals" not in denied.text

    app.dependency_overrides.pop(get_current_user)
    unauthenticated = client.get(_url(form, refresh=True))
    assert unauthenticated.status_code in (401, 403)
    assert "totals" not in unauthenticated.text


def test_refresh_checks_form_not_deleted_even_with_cached_result(
    refresh_setup, db
):
    client, _, form = refresh_setup
    assert client.get(_url(form)).status_code == 200
    form.deleted_at = datetime.now(timezone.utc)
    db.flush()

    deleted = client.get(_url(form, refresh=True))
    unknown = client.get(
        f"/api/v1/staff/forms/{uuid4()}/stats?period=1d&refresh=true"
    )
    malformed = client.get(
        "/api/v1/staff/forms/not-a-uuid/stats?period=1d&refresh=true"
    )
    for result in (deleted, unknown, malformed):
        assert result.status_code == 404
        assert result.json() == {"detail": "Statistics unavailable"}
        assert "totals" not in result.text


@pytest.mark.parametrize("period", ("x", "", "365d", "<script>"))
def test_refresh_preserves_invalid_period_behavior(refresh_setup, period):
    client, _, form = refresh_setup
    assert client.get(_url(form)).status_code == 200

    result = client.get(_url(form, period, refresh=True))
    assert result.status_code == 400
    assert result.json() == {"detail": "Invalid statistics period"}
    assert "totals" not in result.text
    if period:
        assert period not in result.text
