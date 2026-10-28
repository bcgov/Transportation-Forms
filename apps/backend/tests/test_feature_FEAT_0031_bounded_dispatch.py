"""Bounded admission and receipt-day behavior for all engagement writes."""

from datetime import date
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest

from shared import engagement_writer


def test_excess_write_is_dropped_before_submission_and_slot_is_released(
    monkeypatch,
):
    received = date(2026, 10, 28)
    monkeypatch.setattr(engagement_writer, "pct_day", lambda: received)
    summary = Mock()
    dispatcher = engagement_writer.CountDispatcher(summary, capacity=1)
    entered = Event()
    release = Event()
    writes = []

    def record(form_id, metric, source, day):
        entered.set()
        assert release.wait(2)
        writes.append((form_id, metric, source, day))

    form_id = uuid4()
    try:
        first = dispatcher.submit(record, form_id, "download", "Staff")
        assert first is not None
        assert entered.wait(1)
        assert (
            dispatcher.submit(record, form_id, "detail_view", "Staff") is None
        )
        summary.record.assert_called_once_with("known_capacity")
        assert len(writes) == 0
        release.set()
        first.result(timeout=2)
        next_write = dispatcher.submit(record, form_id, "link_click", "Public")
        assert next_write is not None
        next_write.result(timeout=2)
        assert writes == [
            (form_id, "download", "Staff", received),
            (form_id, "link_click", "Public", received),
        ]
    finally:
        release.set()
        dispatcher._executor.shutdown(wait=True)


def test_day_is_fixed_at_admission_even_when_worker_starts_later(monkeypatch):
    day = date(2026, 3, 7)
    monkeypatch.setattr(engagement_writer, "pct_day", lambda: day)
    dispatcher = engagement_writer.CountDispatcher(Mock(), capacity=1)
    entered = Event()
    release = Event()
    seen = []

    def record(*args):
        entered.set()
        assert release.wait(2)
        seen.append(args[-1])

    try:
        future = dispatcher.submit(record, uuid4(), "download", "Staff")
        assert future is not None
        assert entered.wait(1)
        monkeypatch.setattr(
            engagement_writer, "pct_day", lambda: date(2026, 3, 8)
        )
        release.set()
        future.result(timeout=2)
        assert seen == [day]
    finally:
        release.set()
        dispatcher._executor.shutdown(wait=True)


def test_invalid_increment_never_enters_worker():
    dispatcher = engagement_writer.CountDispatcher(Mock(), capacity=1)
    record = Mock()
    try:
        with pytest.raises(
            ValueError, match="Invalid daily engagement increment"
        ):
            dispatcher.submit(record, uuid4(), "unknown", "Public")
        record.assert_not_called()
    finally:
        dispatcher._executor.shutdown(wait=True)
