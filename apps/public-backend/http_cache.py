"""Shared HTTP-cache helpers (ETag computation + conditional 304).

Centralising this avoids drift across the list/detail/business-areas/og
routers and keeps the ETag-stability contract (US-014 AC11) under a
single tested implementation.
"""

from __future__ import annotations

import hashlib
from typing import Optional


def compute_etag(body: bytes) -> str:
    """Return a quoted strong ETag (first 32 hex chars of SHA-256)."""
    digest = hashlib.sha256(body).hexdigest()[:32]
    return f'"{digest}"'


def etag_matches(if_none_match: Optional[str], etag: str) -> bool:
    """True iff the client's ``If-None-Match`` header matches ``etag``.

    Supports comma-separated ETag lists and the wildcard ``*``.
    """
    if not if_none_match:
        return False
    candidates = [t.strip() for t in if_none_match.split(",") if t.strip()]
    return etag in candidates or "*" in candidates
