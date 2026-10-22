"""Best-effort, bounded daily engagement count writer for the Public API."""

from __future__ import annotations

import atexit
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from threading import Lock, Timer
from uuid import UUID

from config import settings
from database import _ensure_psycopg_driver
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.pool import QueuePool

PCT = timezone(timedelta(hours=-7))
METRICS = frozenset({"download", "detail_view", "link_click"})
SOURCES = frozenset({"Staff", "Public"})
REASONS = (
    "confirmed",
    "known_capacity",
    "known_unavailable",
    "known_lock_timeout",
    "known_statement_timeout",
    "known_rejected",
    "uncertain_execute",
    "uncertain_commit",
)
INCREMENT = text(
    "INSERT INTO daily_engagement_counts (form_id, metric, source, pct_day, count) "
    "VALUES (:form_id, :metric, :source, :pct_day, 1) "
    "ON CONFLICT (form_id, metric, source, pct_day) "
    "DO UPDATE SET count = daily_engagement_counts.count + 1"
)
ACCOUNT_CHECK = text(
    "SELECT NOT rolsuper AND pg_has_role(current_user, 'daily_engagement_writer', 'member') "
    "FROM pg_roles WHERE rolname = current_user"
)

logger = logging.getLogger("engagement.daily_counts")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
logger.propagate = False


class CountSummary:
    """Emit at most one identity-free summary per 60-second activity window."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: Counter[str] = Counter()
        self._timer: Timer | None = None

    def record(self, reason: str) -> None:
        if reason not in REASONS:
            raise ValueError("Unknown writer outcome")
        with self._lock:
            self._counts[reason] += 1
            if self._timer is None:
                self._timer = Timer(60, self.flush)
                self._timer.daemon = True
                self._timer.start()

    def flush(self) -> None:
        with self._lock:
            counts = self._counts
            self._counts = Counter()
            self._timer = None
        if counts:
            logger.info(
                "engagement_writer window_seconds=60 attempts=%d %s",
                sum(counts.values()),
                " ".join(f"{reason}={counts[reason]}" for reason in REASONS),
            )


summary = CountSummary()
atexit.register(summary.flush)
_writer_lock = Lock()
_writer: DailyCountWriter | None = None


class WriterInitializing(Exception):
    pass


def _writer_engine() -> Engine:
    url = os.environ.get("ANALYTICS_DATABASE_URL")
    if not url:
        raise ValueError("ANALYTICS_DATABASE_URL is required")
    writer_url = make_url(_ensure_psycopg_driver(url))
    application_url = make_url(_ensure_psycopg_driver(settings.DATABASE_URL_READONLY))
    if not writer_url.username or writer_url.username == application_url.username:
        raise ValueError("Analytics must use a dedicated database account")
    engine = create_engine(
        writer_url,
        poolclass=QueuePool,
        pool_size=4,
        max_overflow=0,
        pool_timeout=0,
        connect_args={
            "connect_timeout": 2,
            "options": "-c lock_timeout=500ms -c statement_timeout=1500ms",
        },
    )
    try:
        with engine.connect() as connection:
            if connection.execute(ACCOUNT_CHECK).scalar() is not True:
                raise ValueError("Analytics account lacks the limited writer role")
    except (ValueError, ArgumentError, DBAPIError):
        engine.dispose()
        raise
    return engine


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


class DailyCountWriter:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def increment(self, form_id: UUID, metric: str, source: str) -> None:
        if (
            not isinstance(form_id, UUID)
            or metric not in METRICS
            or source not in SOURCES
        ):
            raise ValueError("Invalid daily engagement increment")
        day = datetime.now(timezone.utc).astimezone(PCT).date()
        self._increment_for_day(form_id, metric, source, day)

    def _increment_for_day(
        self, form_id: UUID, metric: str, source: str, day: date
    ) -> None:
        stage = "acquire"
        try:
            with self.engine.connect() as connection:
                stage = "execute"
                connection.execute(
                    INCREMENT,
                    {
                        "form_id": form_id,
                        "metric": metric,
                        "source": source,
                        "pct_day": day,
                    },
                )
                stage = "commit"
                connection.commit()
        except PoolTimeoutError:
            summary.record("known_capacity")
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if stage == "acquire":
                summary.record("known_unavailable")
            elif stage == "execute" and sqlstate == "55P03":
                summary.record("known_lock_timeout")
            elif stage == "execute" and sqlstate == "57014":
                summary.record("known_statement_timeout")
            elif stage == "execute" and sqlstate in {
                "42501",
                "23514",
                "22003",
                "23505",
            }:
                summary.record("known_rejected")
            else:
                summary.record(
                    "uncertain_commit" if stage == "commit" else "uncertain_execute"
                )
        else:
            summary.record("confirmed")


def record_daily_engagement(form_id: UUID, metric: str, source: str) -> None:
    """Call only after qualification; never pass request identity or timestamps."""
    if not isinstance(form_id, UUID) or metric not in METRICS or source not in SOURCES:
        raise ValueError("Invalid daily engagement increment")
    day = datetime.now(timezone.utc).astimezone(PCT).date()
    try:
        get_writer()._increment_for_day(form_id, metric, source, day)
    except WriterInitializing:
        summary.record("known_capacity")
    except (ValueError, ArgumentError, DBAPIError):
        summary.record("known_unavailable")
