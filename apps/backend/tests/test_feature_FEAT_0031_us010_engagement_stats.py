"""US-010: authorized, complete-day engagement statistics."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import DailyEngagementCount, Form, UserRole
from backend.services import engagement_stats

PCT = timezone(timedelta(hours=-7))
TODAY = date(2024, 3, 11)
PERIODS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "180d": 180, "1y": 365}


@pytest.fixture
def stats_setup(db, user_factory, role_factory, monkeypatch):
    user = user_factory()
    role = role_factory(name="stats_only", permissions=["form:stats"])
    db.add(UserRole(id=uuid4(), user_id=user.id, role_id=role.id))
    form = Form(
        id=uuid4(),
        title="Private draft",
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
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        sub=str(user.id),
        email="test@example.test",
        name="Tester",
        roles=["stats_only"],
    )
    yield TestClient(app), user, role, form
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    engagement_stats._cache.clear()


def _url(form, period="1d"):
    return f"/api/v1/staff/forms/{form.id}/stats?period={period}"


def _count(db, form, metric, source, day, amount):
    db.add(
        DailyEngagementCount(
            form_id=form.id,
            metric=metric,
            source=source,
            pct_day=day,
            count=amount,
        )
    )
    db.flush()


def test_stats_only_access_and_exactly_six_zero_totals(stats_setup):
    client, _, _, form = stats_setup
    response = client.get(_url(form))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "period": "1d",
        "pct_day_cutoff": "2024-03-11T00:00:00-07:00",
        "data_through": "2024-03-10",
        "totals": {
            "download": {"Staff": 0, "Public": 0},
            "detail_view": {"Staff": 0, "Public": 0},
            "link_click": {"Staff": 0, "Public": 0},
        },
    }
    assert "collection_start" not in response.json()


def test_permission_grant_and_revoke_apply_even_to_cached_results(
    stats_setup, db
):
    client, _, role, form = stats_setup
    assert client.get(_url(form)).status_code == 200
    role.permissions = []
    db.flush()
    denied = client.get(_url(form))
    assert denied.status_code == 403
    assert denied.json() == {
        "detail": "Insufficient permissions for this action"
    }
    role.permissions = ["form:stats"]
    db.flush()
    assert client.get(_url(form)).status_code == 200


def test_unauthenticated_and_invalid_period_expose_no_totals(stats_setup):
    client, _, _, form = stats_setup
    for value in ("x", "", "365d", "<script>", "A" * 5000):
        result = client.get(_url(form, value))
        assert result.status_code == 400
        if value:
            assert value not in result.text
        assert "totals" not in result.text
    app.dependency_overrides.pop(get_current_user)
    result = client.get(_url(form))
    assert result.status_code in (401, 403)
    assert "totals" not in result.text


@pytest.mark.parametrize(("period", "days"), PERIODS.items())
def test_each_finite_period_includes_only_previous_complete_days(
    stats_setup, db, period, days
):
    client, _, _, form = stats_setup
    _count(db, form, "download", "Staff", TODAY - timedelta(days=days + 1), 8)
    if days != 1:
        _count(db, form, "download", "Staff", TODAY - timedelta(days=days), 2)
    _count(db, form, "download", "Staff", TODAY - timedelta(days=1), 3)
    _count(db, form, "download", "Staff", TODAY, 10)
    result = client.get(_url(form, period))
    assert result.status_code == 200
    assert result.json()["totals"]["download"]["Staff"] == (
        3 if days == 1 else 5
    )


def test_all_time_sums_every_retained_day_without_start_metadata(
    stats_setup, db
):
    client, _, _, form = stats_setup
    _count(db, form, "link_click", "Public", TODAY - timedelta(days=600), 4)
    _count(db, form, "link_click", "Public", TODAY - timedelta(days=1), 2)
    _count(db, form, "link_click", "Public", TODAY, 7)
    all_time = client.get(_url(form, "all"))
    year = client.get(_url(form, "1y"))
    assert all_time.status_code == 200
    assert all_time.json()["totals"]["link_click"]["Public"] == 6
    assert "collection_start" not in all_time.json()
    assert year.json()["totals"]["link_click"]["Public"] == 2


def test_six_independent_metric_source_sums(stats_setup, db):
    client, _, _, form = stats_setup
    for metric_index, metric in enumerate(engagement_stats.METRICS):
        for source_index, source in enumerate(engagement_stats.SOURCES):
            _count(
                db,
                form,
                metric,
                source,
                TODAY - timedelta(days=2),
                metric_index * 2 + source_index + 1,
            )
            _count(db, form, metric, source, TODAY - timedelta(days=1), 10)
    totals = client.get(_url(form, "7d")).json()["totals"]
    assert totals == {
        metric: {
            source: 11 + metric_index * 2 + source_index
            for source_index, source in enumerate(engagement_stats.SOURCES)
        }
        for metric_index, metric in enumerate(engagement_stats.METRICS)
    }


def test_unknown_deleted_and_cached_deleted_are_equally_unavailable(
    stats_setup, db
):
    client, _, _, form = stats_setup
    assert client.get(_url(form)).status_code == 200
    form.deleted_at = datetime.now(timezone.utc)
    db.flush()
    deleted = client.get(_url(form))
    unknown = client.get(f"/api/v1/staff/forms/{uuid4()}/stats?period=1d")
    invalid = client.get("/api/v1/staff/forms/not-a-uuid/stats?period=1d")
    assert (
        deleted.status_code
        == unknown.status_code
        == invalid.status_code
        == 404
    )
    assert (
        deleted.json()
        == unknown.json()
        == invalid.json()
        == {"detail": "Statistics unavailable"}
    )


def test_cache_reuses_aggregate_across_users_and_recalculates_at_midnight(
    stats_setup, db, monkeypatch, user_factory
):
    client, _, role, form = stats_setup
    second_user = user_factory()
    db.add(UserRole(id=uuid4(), user_id=second_user.id, role_id=role.id))
    db.flush()
    _count(db, form, "download", "Staff", TODAY - timedelta(days=1), 1)
    reads = []

    def count_reads(_conn, _cursor, statement, _params, _context, _many):
        if (
            statement.lstrip().lower().startswith("select")
            and "daily_engagement_counts" in statement.lower()
        ):
            reads.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count_reads)
    try:
        first = client.get(_url(form)).json()
        _count(db, form, "download", "Staff", TODAY, 2)
        app.dependency_overrides[get_current_user] = lambda: TokenData(
            sub=str(second_user.id),
            email="second@example.test",
            name="Second",
            roles=["stats_only"],
        )
        assert client.get(_url(form)).json() == first
        assert len(reads) == 1
        monkeypatch.setattr(
            engagement_stats, "pct_today", lambda: TODAY + timedelta(days=1)
        )
        next_day = client.get(_url(form)).json()
        assert next_day["totals"]["download"]["Staff"] == 2
        assert next_day["pct_day_cutoff"] == "2024-03-12T00:00:00-07:00"
        assert len(reads) == 2
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count_reads)


def test_lru_eviction_recalculates_from_counts(stats_setup, db, monkeypatch):
    client, _, _, form = stats_setup
    monkeypatch.setattr(engagement_stats, "CACHE_CAP", 2)
    first = client.get(_url(form, "1d")).json()
    client.get(_url(form, "7d"))
    client.get(_url(form, "30d"))
    assert len(engagement_stats._cache) == 2
    assert client.get(_url(form, "1d")).json() == first
    engagement_stats._cache.clear()
    assert client.get(_url(form, "1d")).json() == first


def test_database_failure_is_unavailable_not_bad_request(
    stats_setup, db, monkeypatch
):
    client, _, _, form = stats_setup
    rollback = Mock()
    monkeypatch.setattr(db, "rollback", rollback)

    def unavailable(*_args):
        raise OperationalError(
            "SELECT", {}, Exception("private connection data")
        )

    monkeypatch.setattr(engagement_stats, "aggregate", unavailable)
    result = client.get(_url(form))
    assert result.status_code == 503
    assert result.json() == {"detail": "Statistics temporarily unavailable"}
    assert "private connection data" not in result.text
    rollback.assert_called_once()


def test_statistics_connection_is_read_only(_test_engine):
    with Session(_test_engine) as reader:
        reader.execute(text("SELECT 1"))
        engagement_stats.mark_transaction_read_only(reader)
        assert (
            reader.execute(text("SHOW transaction_read_only")).scalar_one()
            == "on"
        )


def test_fixed_pct_day_boundary():
    assert datetime(2024, 3, 11, 6, 59, tzinfo=timezone.utc).astimezone(
        PCT
    ).date() == date(2024, 3, 10)
    assert (
        datetime(2024, 3, 11, 7, 0, tzinfo=timezone.utc).astimezone(PCT).date()
        == TODAY
    )
