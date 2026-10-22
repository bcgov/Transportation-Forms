"""US-007: identical persistence contract in separately packaged backends."""

import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from backend.services import daily_engagement as staff_writer
from sqlalchemy.exc import DBAPIError, TimeoutError


@pytest.fixture(params=["Staff", "Public"])
def writer_module(request, monkeypatch):
    if request.param == "Staff":
        return staff_writer
    monkeypatch.setenv("DATABASE_URL_READONLY", os.environ["DATABASE_URL"])
    path = Path(__file__).resolve().parents[2] / "public-backend"
    sys.path.insert(0, str(path))
    try:
        spec = importlib.util.spec_from_file_location(
            "us007_public_writer", path / "daily_engagement.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path))
    return module


@pytest.fixture
def writer(writer_module, monkeypatch):
    reasons = []
    monkeypatch.setattr(writer_module.summary, "record", reasons.append)
    connection = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    return writer_module.DailyCountWriter(engine), connection, reasons


@pytest.mark.parametrize(
    ("instant", "expected_day"),
    [
        (
            datetime(2026, 3, 8, 6, 59, 59, tzinfo=timezone.utc),
            datetime(2026, 3, 7).date(),
        ),
        (
            datetime(2026, 3, 8, 7, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 8).date(),
        ),
        (
            datetime(2026, 11, 1, 7, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 1).date(),
        ),
    ],
)
def test_single_atomic_statement_and_received_day(
    writer_module, writer, monkeypatch, instant, expected_day
):
    target, connection, reasons = writer

    class ReceiptTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(writer_module, "datetime", ReceiptTime)
    form_id = uuid4()
    target.increment(form_id, "detail_view", "Public")

    statement, params = connection.execute.call_args.args
    assert "ON CONFLICT (form_id, metric, source, pct_day) DO UPDATE" in str(statement)
    assert "daily_engagement_counts.count + 1" in str(statement)
    assert not any(
        identity in params for identity in ("email", "ip", "user_agent", "visitor_id")
    )
    assert params == {
        "form_id": form_id,
        "metric": "detail_view",
        "source": "Public",
        "pct_day": expected_day,
    }
    connection.commit.assert_called_once_with()
    assert reasons == ["confirmed"]


@pytest.mark.parametrize(
    ("stage", "sqlstate", "expected"),
    [
        ("execute", "55P03", "known_lock_timeout"),
        ("execute", "57014", "known_statement_timeout"),
        ("execute", "42501", "known_rejected"),
        ("execute", None, "uncertain_execute"),
        ("commit", None, "uncertain_commit"),
    ],
)
def test_write_failure_is_not_retried(writer, stage, sqlstate, expected):
    target, connection, reasons = writer
    cause = Exception("private details")
    cause.sqlstate = sqlstate
    error = DBAPIError("private statement", {}, cause)
    getattr(connection, stage).side_effect = error
    target.increment(uuid4(), "download", "Staff")
    assert connection.execute.call_count == 1
    assert reasons == [expected]


def test_pool_exhaustion_does_not_start_write(writer):
    target, connection, reasons = writer
    target.engine.connect.side_effect = TimeoutError("pool full")
    target.increment(uuid4(), "link_click", "Public")
    connection.execute.assert_not_called()
    assert reasons == ["known_capacity"]


def test_public_entry_captures_day_before_pool_initialization(
    writer_module, monkeypatch
):
    class ReceiptTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 8, 6, 59, 59, tzinfo=timezone.utc)

    monkeypatch.setattr(writer_module, "datetime", ReceiptTime)
    target = MagicMock()
    monkeypatch.setattr(writer_module, "get_writer", lambda: target)
    form_id = uuid4()
    writer_module.record_daily_engagement(form_id, "download", "Staff")
    target._increment_for_day.assert_called_once_with(
        form_id, "download", "Staff", datetime(2026, 3, 7).date()
    )


def test_invalid_metric_source_and_identifier_never_connect(writer):
    target, _, _ = writer
    for form_id, metric, source in (
        ("not-a-uuid", "download", "Staff"),
        (uuid4(), "unknown", "Public"),
        (uuid4(), "download", "Unknown"),
    ):
        with pytest.raises(ValueError):
            target.increment(form_id, metric, source)
    target.engine.connect.assert_not_called()


def test_summary_contains_only_fixed_counts(writer_module, monkeypatch):
    lines = []
    monkeypatch.setattr(writer_module.logger, "info", lambda *args: lines.append(args))
    summary = writer_module.CountSummary()
    summary.record("known_capacity")
    summary.record("uncertain_commit")
    summary.flush()
    assert len(lines) == 1
    message, attempts, counters = lines[0]
    assert message == "engagement_writer window_seconds=60 attempts=%d %s"
    assert attempts == 2
    assert "known_capacity=1" in counters
    assert "uncertain_commit=1" in counters
    assert all(reason + "=" in counters for reason in writer_module.REASONS)


def test_writer_refuses_main_account_or_non_member(writer_module, monkeypatch):
    application_url = (
        writer_module.DATABASE_URL
        if hasattr(writer_module, "DATABASE_URL")
        else writer_module.settings.DATABASE_URL_READONLY
    )
    monkeypatch.setenv("ANALYTICS_DATABASE_URL", application_url)
    with pytest.raises(ValueError, match="dedicated"):
        writer_module._writer_engine()

    monkeypatch.setenv(
        "ANALYTICS_DATABASE_URL",
        "postgresql://daily_writer:placeholder@localhost/counts",
    )
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = (
        False
    )
    monkeypatch.setattr(writer_module, "create_engine", lambda *args, **kwargs: engine)
    with pytest.raises(ValueError, match="limited writer role"):
        writer_module._writer_engine()
    engine.dispose.assert_called_once_with()


def test_writer_pool_has_fixed_ceiling_and_timeouts(writer_module, monkeypatch):
    monkeypatch.setenv(
        "ANALYTICS_DATABASE_URL",
        "postgresql://daily_writer:placeholder@localhost/counts",
    )
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = (
        True
    )
    captured = {}

    def engine_factory(url, **kwargs):
        captured.update(kwargs)
        return engine

    monkeypatch.setattr(writer_module, "create_engine", engine_factory)
    assert writer_module._writer_engine() is engine
    assert captured["pool_size"] == 4
    assert captured["max_overflow"] == 0
    assert captured["pool_timeout"] == 0
    assert captured["connect_args"]["connect_timeout"] == 2
    assert "lock_timeout=500ms" in captured["connect_args"]["options"]
    assert "statement_timeout=1500ms" in captured["connect_args"]["options"]


def test_initialization_contention_is_known_capacity_drop(writer_module, monkeypatch):
    monkeypatch.setattr(writer_module, "_writer", None)
    reasons = []
    monkeypatch.setattr(writer_module.summary, "record", reasons.append)
    assert writer_module._writer_lock.acquire(blocking=False)
    try:
        writer_module.record_daily_engagement(uuid4(), "download", "Staff")
    finally:
        writer_module._writer_lock.release()
    assert reasons == ["known_capacity"]
