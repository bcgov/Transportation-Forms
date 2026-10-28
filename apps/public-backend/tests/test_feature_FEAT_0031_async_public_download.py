"""Public file handoff never waits for an analytics connection or worker."""

from datetime import date, timedelta
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import ANY, Mock
from uuid import uuid4

from routes import forms as forms_route
from shared import engagement_writer


def test_slow_public_write_does_not_hold_download_or_queue_excess(
    public_client, monkeypatch
):
    form_id = uuid4()
    monkeypatch.setattr(
        forms_route,
        "_get_form_or_404",
        lambda _db, _number: SimpleNamespace(
            form_id=form_id, s3_key="uploads/test.pdf", file_name="test.pdf"
        ),
    )
    audit = Mock()
    monkeypatch.setattr(forms_route, "log_form_download", audit)
    summary = Mock()
    dispatcher = engagement_writer.CountDispatcher(summary, capacity=1)
    monkeypatch.setattr(forms_route, "dispatcher", dispatcher)
    day = date(2026, 10, 28)
    monkeypatch.setattr(engagement_writer, "pct_day", lambda: day)
    started, release, completed = Event(), Event(), Event()
    writes = []

    def slow_write(*args):
        started.set()
        try:
            assert release.wait(3)
            writes.append(args)
        finally:
            completed.set()

    monkeypatch.setattr(forms_route, "record_daily_engagement", slow_write)
    path = "/api/public/v1/forms/TEST/file"
    try:
        before = monotonic()
        first = public_client.get(path)
        assert monotonic() - before < 0.75
        assert first.status_code == 200
        assert (
            first.headers["x-accel-redirect"]
            == "/internal-s3/uploads/test.pdf"
        )
        assert started.wait(1)

        monkeypatch.setattr(
            engagement_writer, "pct_day", lambda: day + timedelta(days=1)
        )
        before = monotonic()
        second = public_client.get(path)
        assert monotonic() - before < 0.75
        assert second.status_code == 200
        summary.record.assert_called_once_with("known_capacity")
        audit.assert_called_with(ANY, form_number="TEST", filename="test.pdf")
        assert audit.call_count == 2
        assert writes == []

        release.set()
        assert completed.wait(2)
        assert writes == [(form_id, "download", "Public", day)]
    finally:
        release.set()
        dispatcher._executor.shutdown(wait=True)
