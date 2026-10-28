"""Slow aggregates must not block other keys or overwrite newer refreshes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend.services import engagement_stats

TODAY = date(2026, 10, 28)


@pytest.fixture(autouse=True)
def clear_stats_cache(monkeypatch):
    monkeypatch.setattr(engagement_stats, "_cache_day", None)
    engagement_stats._cache.clear()
    engagement_stats._pending.clear()
    yield
    engagement_stats._cache.clear()
    engagement_stats._pending.clear()


def database(read):
    db = Mock()
    query = db.query.return_value
    query.filter.return_value = query
    query.group_by.return_value = query
    query.all.side_effect = read
    return db


def rows(count):
    return [("download", "Staff", count)]


def test_slow_query_for_other_form_does_not_block_cached_hit():
    cached_form, slow_form = uuid4(), uuid4()
    engagement_stats.aggregate(
        database(lambda: rows(1)), cached_form, "7d", TODAY
    )
    entered, release = Event(), Event()

    def slow_read():
        entered.set()
        assert release.wait(2)
        return rows(2)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(
                engagement_stats.aggregate,
                database(slow_read),
                slow_form,
                "7d",
                TODAY,
            )
            assert entered.wait(1)
            hit = pool.submit(
                engagement_stats.aggregate,
                database(lambda: pytest.fail("cached key queried")),
                cached_form,
                "7d",
                TODAY,
            )
            assert hit.result(timeout=1)["totals"]["download"]["Staff"] == 1
            release.set()
            assert slow.result(timeout=2)["totals"]["download"]["Staff"] == 2
    finally:
        release.set()


def test_older_refresh_cannot_publish_after_newer_refresh():
    form_id = uuid4()
    entered, release = Event(), Event()

    def old_read():
        entered.set()
        assert release.wait(2)
        return rows(1)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(
                engagement_stats.aggregate,
                database(old_read),
                form_id,
                "7d",
                TODAY,
                True,
            )
            assert entered.wait(1)
            newest = engagement_stats.aggregate(
                database(lambda: rows(3)), form_id, "7d", TODAY, refresh=True
            )
            release.set()
            assert old.result(timeout=2)["totals"]["download"]["Staff"] == 1
        assert newest["totals"]["download"]["Staff"] == 3
        cached = engagement_stats.aggregate(
            database(lambda: pytest.fail("newest key queried")),
            form_id,
            "7d",
            TODAY,
        )
        assert cached == newest
    finally:
        release.set()


def test_previous_day_query_cannot_repopulate_cache_after_rollover():
    form_id = uuid4()
    entered, release = Event(), Event()

    def yesterday_read():
        entered.set()
        assert release.wait(2)
        return rows(1)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            yesterday = pool.submit(
                engagement_stats.aggregate,
                database(yesterday_read),
                form_id,
                "7d",
                TODAY,
            )
            assert entered.wait(1)
            next_day = TODAY + timedelta(days=1)
            today = engagement_stats.aggregate(
                database(lambda: rows(2)), form_id, "7d", next_day
            )
            release.set()
            yesterday.result(timeout=2)
        assert (
            engagement_stats.aggregate(
                database(lambda: pytest.fail("new day queried")),
                form_id,
                "7d",
                next_day,
            )
            == today
        )
        assert all(key[2] == next_day for key in engagement_stats._cache)
    finally:
        release.set()
