"""FEAT-0026 — Reserved-slug registry for the mini-CMS.

This module is the single source of truth for slugs that must never be claimed
by a CMS page because they collide with first-class application routes,
infrastructure endpoints, or well-known protocol files.

Used by:

* ``apps.backend.services.cms_pages`` to reject reserved slugs at create/update.
* ``apps.backend.routes.cms_pages`` to expose the list to the admin UI so
  reservation can be surfaced client-side before submission (US-007).
"""

from __future__ import annotations

from typing import FrozenSet, List

# FEAT-0026 US-001 AC2 / US-007 AC1 — reserved slug registry.  Kept short and
# deliberate so failures are obvious; new application routes that need to be
# protected from collision must be added here in the same PR.
RESERVED_SLUGS: FrozenSet[str] = frozenset(
    {
        # Backend / API surfaces
        "api",
        "admin",
        "auth",
        "health",
        "internal-s3",
        # Public-facing portal sections handled by application routing
        "forms",
        # Static asset roots served outside the CMS
        "assets",
        "static",
        # Well-known files / SEO surfaces
        "robots.txt",
        "sitemap.xml",
        "favicon.ico",
    }
)


def is_reserved(slug: str) -> bool:
    """Return True when ``slug`` is reserved and cannot be used for a CMS page.

    Comparison is case-insensitive on the slug input.  Reserved entries are
    stored lowercase and slugs are always normalized to lowercase by the
    service layer before reaching the database.
    """
    if not slug:
        return False
    return slug.strip().lower() in RESERVED_SLUGS


def get_reserved_slugs() -> List[str]:
    """Return the reserved slugs as a deterministically sorted list.

    The sorted order makes the public JSON response stable so HTTP caches and
    ETags downstream are stable across calls.
    """
    return sorted(RESERVED_SLUGS)
