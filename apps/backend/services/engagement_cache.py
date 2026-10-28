"""Per-pod, last-good Staff form eligibility for best-effort engagement."""

import asyncio
import logging
import math
import os
import sys
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlsplit
from uuid import UUID

from backend.database import SessionLocal
from backend.models import Form
from sqlalchemy.orm import Session

logger = logging.getLogger("engagement.staff_cache")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
logger.propagate = False


def check_interval_seconds() -> float:
    try:
        minutes = float(os.environ.get("STAFF_ENGAGEMENT_CACHE_CHECK_MINUTES", "5"))
        if math.isfinite(minutes) and minutes > 0:
            return minutes * 60
    except ValueError:
        pass
    return 300


def enabled_link(source: str | None, url: str | None) -> bool:
    if source != "URL" or not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url.strip())
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and not any(character.isspace() for character in parsed.netloc)
            and parsed.port != 0
        )
    except ValueError:
        return False


class StaffFormCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._forms: dict[UUID, bool] = {}
        self._loaded = False
        self._version = 0
        self._failures = 0
        self._first_failure: datetime | None = None

    def eligible(self, form_id: UUID, metric: str) -> bool:
        with self._lock:
            link = self._forms.get(form_id)
            return (
                self._loaded
                and link is not None
                and (metric == "detail_view" or (metric == "link_click" and link))
            )

    def committed(self, form: Form, db: Session | None = None) -> None:
        with self._lock:
            if db is not None:
                try:
                    db.refresh(form)
                except Exception:
                    logger.warning(
                        "staff_cache_commit_refresh_failed reason=read_failed"
                    )
                    return
            self._version += 1
            if form.deleted_at is not None:
                self._forms.pop(form.id, None)
            else:
                self._forms[form.id] = enabled_link(
                    form.form_source, form.form_source_url
                )

    def check(self) -> None:
        with self._lock:
            version = self._version
        try:
            with SessionLocal() as db:
                rows = (
                    db.query(Form.id, Form.form_source, Form.form_source_url)
                    .filter(Form.deleted_at.is_(None))
                    .all()
                )
            snapshot = {
                form_id: enabled_link(source, url) for form_id, source, url in rows
            }
        except Exception:
            with self._lock:
                self._failures += 1
                if self._first_failure is None:
                    self._first_failure = datetime.now(timezone.utc)
                failures = self._failures
                first = self._first_failure
            logger.warning(
                "staff_cache_check_failed reason=read_failed streak=%d", failures
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
            # A local form commit while reading wins over this older snapshot.
            if self._version == version and (
                not self._loaded or snapshot != self._forms
            ):
                self._forms = snapshot
            if self._version == version:
                self._loaded = True
            self._failures = 0
            self._first_failure = None


cache = StaffFormCache()


async def run_checks() -> None:
    while True:
        await asyncio.to_thread(cache.check)
        await asyncio.sleep(check_interval_seconds())
