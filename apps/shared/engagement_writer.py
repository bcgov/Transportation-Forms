"""Shared, bounded persistence for anonymous daily engagement counts."""

from __future__ import annotations

import logging
import sys
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import BoundedSemaphore, Lock, Timer
from typing import Callable
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.pool import QueuePool

PCT = timezone(timedelta(hours=-7))
METRICS = frozenset({"download", "detail_view", "link_click"})
SOURCES = frozenset({"Staff", "Public"})
POOL_SIZE = 4
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
    "INSERT INTO daily_engagement_counts (form_id, metric, source, "
    "pct_day, count) "
    "VALUES (:form_id, :metric, :source, "
    ":pct_day, 1) "
    "ON CONFLICT (form_id, metric, source, pct_day) "
    "DO UPDATE SET count = daily_engagement_counts.count + 1"
)
ACCOUNT_CHECK = text(
    "SELECT NOT rolsuper AND pg_has_role(current_user, "
    "'daily_engagement_writer', 'member') "
    "FROM pg_roles WHERE rolname = current_user"
)

logger = logging.getLogger("engagement.daily_counts")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
logger.propagate = False


def pct_day() -> date:
    return datetime.now(timezone.utc).astimezone(PCT).date()


def validate_increment(form_id: UUID, metric: str, source: str) -> None:
    if (
        not isinstance(form_id, UUID)
        or metric not in METRICS
        or source not in SOURCES
    ):
        raise ValueError("Invalid daily engagement increment")


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


class WriterInitializing(Exception):
    pass


def create_writer_engine(
    analytics_url: str,
    application_url: str,
    ensure_driver: Callable[[str], str],
    engine_factory: Callable[..., Engine] = create_engine,
) -> Engine:
    writer_url = make_url(ensure_driver(analytics_url))
    app_url = make_url(ensure_driver(application_url))
    if not writer_url.username or writer_url.username == app_url.username:
        raise ValueError("Analytics must use a dedicated database account")
    engine = engine_factory(
        writer_url,
        poolclass=QueuePool,
        pool_size=POOL_SIZE,
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
                raise ValueError(
                    "Analytics account lacks the limited writer role"
                )
    except (ValueError, ArgumentError, DBAPIError):
        engine.dispose()
        raise
    return engine


class DailyCountWriter:
    def __init__(self, engine: Engine, summary: CountSummary) -> None:
        self.engine = engine
        self.summary = summary

    def increment(self, form_id: UUID, metric: str, source: str) -> None:
        validate_increment(form_id, metric, source)
        self._increment_for_day(form_id, metric, source, pct_day())

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
            self.summary.record("known_capacity")
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if stage == "acquire":
                reason = "known_unavailable"
            elif stage == "execute" and sqlstate == "55P03":
                reason = "known_lock_timeout"
            elif stage == "execute" and sqlstate == "57014":
                reason = "known_statement_timeout"
            elif stage == "execute" and sqlstate in {
                "42501",
                "23514",
                "22003",
                "23505",
            }:
                reason = "known_rejected"
            else:
                reason = (
                    "uncertain_commit"
                    if stage == "commit"
                    else "uncertain_execute"
                )
            self.summary.record(reason)
        else:
            self.summary.record("confirmed")


class CountDispatcher:
    """Reserve a slot before any analytics work is submitted."""

    def __init__(
        self, summary: CountSummary, capacity: int = POOL_SIZE
    ) -> None:
        self.summary = summary
        self._slots = BoundedSemaphore(capacity)
        self._executor = ThreadPoolExecutor(
            max_workers=capacity, thread_name_prefix="engagement"
        )

    def submit(
        self,
        record: Callable[[UUID, str, str, date], None],
        form_id: UUID,
        metric: str,
        source: str,
    ) -> Future[None] | None:
        validate_increment(form_id, metric, source)
        day = pct_day()
        if not self._slots.acquire(blocking=False):
            self.summary.record("known_capacity")
            return None
        try:
            future = self._executor.submit(
                self._run, record, form_id, metric, source, day
            )
        except RuntimeError:
            self._slots.release()
            self.summary.record("known_unavailable")
            return None
        future.add_done_callback(self._observe)
        return future

    def _run(
        self,
        record: Callable[[UUID, str, str, date], None],
        form_id: UUID,
        metric: str,
        source: str,
        day: date,
    ) -> None:
        try:
            record(form_id, metric, source, day)
        finally:
            self._slots.release()

    def _observe(self, future: Future[None]) -> None:
        error = future.exception()
        if error is not None:
            logger.error(
                "engagement_writer_unexpected error_type=%s",
                type(error).__name__,
            )
