"""Per-pod, last-good Public form-number eligibility for engagement."""

import asyncio
import logging
import math
import os
import sys
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID

from database import SessionLocal
from models import PublicForm
from routes.forms import _apply_effective_date_filter, _safe_link_url

logger = logging.getLogger("engagement.public_cache")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
logger.propagate = False


def check_interval_seconds() -> float:
    try:
        minutes = float(os.environ.get("PUBLIC_ENGAGEMENT_CACHE_CHECK_MINUTES", "5"))
        if math.isfinite(minutes) and minutes > 0:
            return minutes * 60
    except ValueError:
        pass
    return 300


class PublicFormCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._forms: dict[str, tuple[UUID, bool]] = {}
        self._loaded = False
        self._failures = 0
        self._first_failure: datetime | None = None

    def resolve(self, number: str, metric: str) -> UUID | None:
        with self._lock:
            entry = self._forms.get(number)
            if (
                self._loaded
                and entry
                and (metric == "detail_view" or (metric == "link_click" and entry[1]))
            ):
                return entry[0]
            return None

    def check(self) -> None:
        try:
            with SessionLocal() as db:
                rows = db.query(
                    PublicForm.form_number,
                    PublicForm.form_id,
                    PublicForm.form_source,
                    PublicForm.form_source_url,
                ).filter(PublicForm.form_number.isnot(None))
                rows = _apply_effective_date_filter(rows).all()
            snapshot = {
                number: (UUID(str(form_id)), bool(_safe_link_url(source, url)))
                for number, form_id, source, url in rows
                if number
            }
        except Exception:
            with self._lock:
                self._failures += 1
                if self._first_failure is None:
                    self._first_failure = datetime.now(timezone.utc)
                failures = self._failures
                first = self._first_failure
            logger.warning(
                "public_cache_check_failed reason=read_failed streak=%d", failures
            )
            if failures == 20:
                logger.warning(
                    "Cache checks have failed 20 consecutive times since %s. "
                    "Engagement counts for newly eligible forms may be missing "
                    "on this pod; "
                    "stale forms may still be counted.",
                    first.isoformat(),
                )
            return
        with self._lock:
            if not self._loaded or snapshot != self._forms:
                self._forms = snapshot
            self._loaded = True
            self._failures = 0
            self._first_failure = None


cache = PublicFormCache()


async def run_checks() -> None:
    while True:
        await asyncio.to_thread(cache.check)
        await asyncio.sleep(check_interval_seconds())
