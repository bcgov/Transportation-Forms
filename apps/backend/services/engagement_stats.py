"""Read-only daily engagement aggregates with per-pod, day-scoped caching."""

from collections import OrderedDict
from datetime import date, datetime, timedelta
from threading import Lock
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.models import DailyEngagementCount
from backend.services.daily_engagement import PCT

PERIOD_DAYS = {
    "1d": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "180d": 180,
    "1y": 365,
    "all": None,
}
METRICS = ("download", "detail_view", "link_click")
SOURCES = ("Staff", "Public")
CACHE_CAP = 1024

_cache: OrderedDict[tuple[UUID, str, date], dict] = OrderedDict()
_lock = Lock()


def mark_transaction_read_only(db: Session) -> None:
    """Prevent writes in the remainder of the authorized read transaction."""
    db.execute(text("SET TRANSACTION READ ONLY"))


def pct_today() -> date:
    return datetime.now(PCT).date()


def aggregate(
    db: Session,
    form_id: UUID,
    period: str,
    cutoff: date,
    refresh: bool = False,
) -> dict:
    """Read today's live count for 1d; cache completed-day aggregates."""
    with _lock:
        key = (form_id, period, cutoff)
        live_day = period == "1d"
        if not live_day and not refresh and key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

        # Old entries must never be returned on or after the next PCT midnight.
        for old_key in list(_cache):
            if old_key[2] != cutoff:
                del _cache[old_key]

        end_day = cutoff + timedelta(days=1) if live_day else cutoff
        query = db.query(
            DailyEngagementCount.metric,
            DailyEngagementCount.source,
            func.sum(DailyEngagementCount.count),
        ).filter(
            DailyEngagementCount.form_id == form_id,
            DailyEngagementCount.pct_day < end_day,
        )
        days = PERIOD_DAYS[period]
        if days is not None:
            query = query.filter(
                DailyEngagementCount.pct_day >= end_day - timedelta(days=days)
            )
        rows = query.group_by(
            DailyEngagementCount.metric, DailyEngagementCount.source
        ).all()

        totals = {
            metric: {source: 0 for source in SOURCES} for metric in METRICS
        }
        for metric, source, count in rows:
            totals[metric][source] = int(count)

        result = {
            "period": period,
            "pct_day_cutoff": datetime.combine(
                end_day, datetime.min.time(), PCT
            ).isoformat(),
            "data_through": (end_day - timedelta(days=1)).isoformat(),
            "totals": totals,
        }
        if not live_day:
            _cache[key] = result
            _cache.move_to_end(key)
            if len(_cache) > CACHE_CAP:
                _cache.popitem(last=False)
        return result
