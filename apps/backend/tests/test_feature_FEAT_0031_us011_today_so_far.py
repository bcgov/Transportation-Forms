"""US-011: today's live fixed-PCT engagement counts."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import DailyEngagementCount, Form, UserRole
from backend.services import engagement_stats

TODAY = date(2024, 3, 11)


@pytest.fixture
def today_stats(db, user_factory, role_factory, monkeypatch):
    user = user_factory()
    role = role_factory(name="today_stats", permissions=["form:stats"])
    db.add(UserRole(id=uuid4(), user_id=user.id, role_id=role.id))
    form = Form(
        id=uuid4(),
        title="Today's statistics",
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
        email="today@example.test",
        name="Today tester",
        roles=["today_stats"],
    )
    try:
        yield TestClient(app), form
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        engagement_stats._cache.clear()


def _url(form, period="1d", *, refresh=False):
    url = f"/api/v1/staff/forms/{form.id}/stats?period={period}"
    return f"{url}&refresh=true" if refresh else url


def _count(db, form, metric, source, day, amount):
    count = DailyEngagementCount(
        form_id=form.id,
        metric=metric,
        source=source,
        pct_day=day,
        count=amount,
    )
    db.add(count)
    db.flush()
    return count


def test_one_day_shape_cutoff_and_only_today_counts(today_stats, db):
    client, form = today_stats
    _count(db, form, "download", "Staff", TODAY - timedelta(days=1), 9)
    _count(db, form, "download", "Staff", TODAY, 2)
    _count(db, form, "link_click", "Public", TODAY, 3)
    _count(db, form, "download", "Staff", TODAY + timedelta(days=1), 11)
    _count(db, form, "link_click", "Public", TODAY + timedelta(days=1), 12)

    response = client.get(_url(form))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "period": "1d",
        "pct_day_cutoff": "2024-03-12T00:00:00-07:00",
        "data_through": "2024-03-11",
        "totals": {
            "download": {"Staff": 2, "Public": 0},
            "detail_view": {"Staff": 0, "Public": 0},
            "link_click": {"Staff": 0, "Public": 3},
        },
    }


def test_one_day_rereads_db_on_every_request_even_without_refresh(
    today_stats, db
):
    client, form = today_stats
    count = _count(db, form, "detail_view", "Staff", TODAY, 1)
    reads = []

    def count_reads(_conn, _cursor, statement, _params, _context, _many):
        if (
            statement.lstrip().lower().startswith("select")
            and "daily_engagement_counts" in statement.lower()
        ):
            reads.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count_reads)
    try:
        first = client.get(_url(form))
        assert first.status_code == 200
        assert first.json()["totals"]["detail_view"]["Staff"] == 1
        assert len(reads) == 1

        count.count = 2
        db.flush()
        second = client.get(_url(form))
        assert second.status_code == 200
        assert second.json()["totals"]["detail_view"]["Staff"] == 2
        assert len(reads) == 2

        count.count = 3
        db.flush()
        refreshed = client.get(_url(form, refresh=True))
        assert refreshed.status_code == 200
        assert refreshed.json()["totals"]["detail_view"]["Staff"] == 3
        assert len(reads) == 3

        unchanged = client.get(_url(form))
        assert unchanged.status_code == 200
        assert unchanged.json() == refreshed.json()
        assert len(reads) == 4
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count_reads)


def test_one_day_rolls_over_at_next_fixed_pct_date(
    today_stats, db, monkeypatch
):
    client, form = today_stats
    _count(db, form, "download", "Staff", TODAY, 2)
    _count(db, form, "download", "Staff", TODAY + timedelta(days=1), 5)

    before = client.get(_url(form))
    assert before.status_code == 200
    assert before.json()["totals"]["download"]["Staff"] == 2
    monkeypatch.setattr(
        engagement_stats, "pct_today", lambda: TODAY + timedelta(days=1)
    )

    after = client.get(_url(form))

    assert after.status_code == 200
    assert after.json()["period"] == "1d"
    assert after.json()["pct_day_cutoff"] == "2024-03-13T00:00:00-07:00"
    assert after.json()["data_through"] == "2024-03-12"
    assert after.json()["totals"]["download"]["Staff"] == 5


def test_seven_days_and_default_remain_completed_day_cached_windows(
    today_stats, db
):
    client, form = today_stats
    _count(db, form, "download", "Staff", TODAY - timedelta(days=31), 20)
    older = _count(db, form, "download", "Staff", TODAY - timedelta(days=8), 4)
    recent = _count(
        db, form, "download", "Staff", TODAY - timedelta(days=1), 2
    )
    _count(db, form, "download", "Staff", TODAY, 10)

    week = client.get(_url(form, "7d"))
    default = client.get(f"/api/v1/staff/forms/{form.id}/stats")

    assert week.status_code == default.status_code == 200
    assert week.json()["period"] == "7d"
    assert default.json()["period"] == "30d"
    for response in (week, default):
        assert response.json()["pct_day_cutoff"] == (
            "2024-03-11T00:00:00-07:00"
        )
        assert response.json()["data_through"] == "2024-03-10"
    assert week.json()["totals"]["download"]["Staff"] == 2
    assert default.json()["totals"]["download"]["Staff"] == 6

    recent.count = 3
    older.count = 5
    db.flush()
    assert client.get(_url(form, "7d")).json() == week.json()
    assert client.get(f"/api/v1/staff/forms/{form.id}/stats").json() == (
        default.json()
    )
