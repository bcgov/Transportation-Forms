"""Staff configuration for the shared anonymous daily-count writer."""

from __future__ import annotations

import atexit
import os
from datetime import date, datetime, timezone
from threading import Lock
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError, DBAPIError

from backend.database import DATABASE_URL, _ensure_psycopg_driver
from shared.engagement_writer import (
    PCT,
    METRICS as METRICS,
    SOURCES as SOURCES,
    REASONS as REASONS,
    CountDispatcher,
    CountSummary,
    DailyCountWriter as SharedDailyCountWriter,
    WriterInitializing,
    create_writer_engine,
    logger as logger,
    validate_increment,
)

__all__ = (
    "PCT",
    "METRICS",
    "SOURCES",
    "REASONS",
    "CountDispatcher",
    "CountSummary",
    "DailyCountWriter",
    "WriterInitializing",
    "dispatcher",
    "get_writer",
    "logger",
    "record_daily_engagement",
)

summary = CountSummary()
atexit.register(summary.flush)
dispatcher = CountDispatcher(summary)
_writer_lock = Lock()
_writer: DailyCountWriter | None = None


class DailyCountWriter(SharedDailyCountWriter):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine, summary)


def _writer_engine() -> Engine:
    url = os.environ.get("ANALYTICS_DATABASE_URL")
    if not url:
        raise ValueError("ANALYTICS_DATABASE_URL is required")
    if DATABASE_URL is None:
        raise ValueError("DATABASE_URL is required")
    return create_writer_engine(
        url, DATABASE_URL, _ensure_psycopg_driver, create_engine
    )


def get_writer() -> DailyCountWriter:
    global _writer
    if _writer is not None:
        return _writer
    if not _writer_lock.acquire(blocking=False):
        raise WriterInitializing
    try:
        if _writer is None:
            _writer = DailyCountWriter(_writer_engine())
        return _writer
    finally:
        _writer_lock.release()


def record_daily_engagement(
    form_id: UUID, metric: str, source: str, received_day: date | None = None
) -> None:
    """Keep the PCT receipt day even if a bounded worker starts later."""
    validate_increment(form_id, metric, source)
    day = received_day or datetime.now(timezone.utc).astimezone(PCT).date()
    try:
        get_writer()._increment_for_day(form_id, metric, source, day)
    except WriterInitializing:
        summary.record("known_capacity")
    except (ValueError, ArgumentError, DBAPIError):
        summary.record("known_unavailable")
