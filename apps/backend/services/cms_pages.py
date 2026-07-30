"""FEAT-0026 — Mini-CMS page service.

Implements the business logic for the public Forms Portal mini-CMS.  This
module owns slug validation, body sanitization, revision creation, audit
logging, and conflict detection.  Routes (``apps.backend.routes.cms_pages``)
are thin wrappers that translate service exceptions into HTTP responses.

Covers US-001 (create), US-002 (edit), US-003 (soft-delete / restore),
US-004 (slug change), US-005 (revision history & restore),
US-006 (reorder), US-008 (redirect management).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import (
    AuditLog,
    CmsPage,
    CmsPageRedirect,
    CmsPageRevision,
)
from backend.services.cms_reserved_slugs import is_reserved
from backend.services.cms_sanitizer import sanitize_html

# Slug must be lowercase alphanumerics separated by single hyphens; no
# leading/trailing/consecutive hyphens.  Length is enforced separately.
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Field-length bounds (mirrors model columns).
_TITLE_MAX = 120
_SLUG_MAX = 80
_META_MAX = 180
_BODY_MAX = 200_000  # 200 KB ceiling for body HTML to bound revision rows


# ---------------------------------------------------------------------------
# Domain exceptions — routes translate these to HTTP responses.
# ---------------------------------------------------------------------------


class CmsValidationError(ValueError):
    """Raised for client-fixable validation failures (HTTP 422)."""

    def __init__(self, message: str, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.field = field


class CmsSlugConflictError(ValueError):
    """Raised when the requested slug collides with another page/redirect (HTTP 409)."""

    def __init__(self, message: str, slug: str) -> None:
        super().__init__(message)
        self.slug = slug


class CmsNotFoundError(LookupError):
    """Raised when the referenced resource does not exist (HTTP 404)."""


class CmsConcurrencyError(RuntimeError):
    """Raised when an ``If-Match`` precondition fails (HTTP 412)."""


class CmsPreconditionRequiredError(RuntimeError):
    """Raised when a required ``If-Match`` header is missing (HTTP 428)."""


class CmsInvalidStateError(RuntimeError):
    """Raised when the requested operation conflicts with the current state (HTTP 409)."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _normalize_slug(raw: str) -> str:
    if raw is None:
        return ""
    return raw.strip().lower()


def _validate_slug(slug: str) -> None:
    if not slug:
        raise CmsValidationError("Slug is required.", field="slug")
    if len(slug) > _SLUG_MAX:
        raise CmsValidationError(
            f"Slug must be {_SLUG_MAX} characters or fewer.", field="slug"
        )
    if not _SLUG_RE.match(slug):
        raise CmsValidationError(
            "Slug must be lowercase alphanumerics separated by single hyphens.",
            field="slug",
        )
    if is_reserved(slug):
        raise CmsValidationError(
            f"Slug '{slug}' is reserved and cannot be used.", field="slug"
        )


def _validate_title(title: str) -> str:
    if title is None:
        raise CmsValidationError("Title is required.", field="title")
    trimmed = title.strip()
    if not trimmed:
        raise CmsValidationError("Title is required.", field="title")
    if len(trimmed) > _TITLE_MAX:
        raise CmsValidationError(
            f"Title must be {_TITLE_MAX} characters or fewer.", field="title"
        )
    return trimmed


def _validate_meta_description(meta: Optional[str]) -> Optional[str]:
    if meta is None:
        return None
    trimmed = meta.strip()
    if not trimmed:
        return None
    if len(trimmed) > _META_MAX:
        raise CmsValidationError(
            f"Meta description must be {_META_MAX} characters or fewer.",
            field="meta_description",
        )
    return trimmed


def _validate_body_html(body_html: str) -> str:
    if body_html is None or not body_html.strip():
        raise CmsValidationError("Body is required.", field="body_html")
    if len(body_html) > _BODY_MAX:
        raise CmsValidationError(
            f"Body must be {_BODY_MAX} characters or fewer.", field="body_html"
        )
    sanitized = sanitize_html(body_html)
    # If sanitization stripped every meaningful element treat the input as
    # empty so authors can't bypass the "body required" rule by submitting
    # only disallowed markup.
    if not sanitized.strip():
        raise CmsValidationError(
            "Body did not contain any allowed content.", field="body_html"
        )
    return sanitized


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CmsPageService:
    """Business logic for mini-CMS pages (FEAT-0026)."""

    # =====================================================================
    # CREATE (US-001)
    # =====================================================================

    @staticmethod
    def create_page(
        db: Session,
        *,
        title: str,
        slug: str,
        body_html: str,
        meta_description: Optional[str] = None,
        show_in_nav: bool = True,
        created_by_id: UUID,
    ) -> CmsPage:
        """Create a CMS page, its initial revision, and an audit log entry.

        All writes occur in a single transaction.  Raises
        :class:`CmsValidationError` (422) or :class:`CmsSlugConflictError`
        (409) before any DB write happens.
        """
        # 1) Validate inputs.  Order matters — we validate the slug *before*
        # touching the database so reserved/format errors short-circuit.
        normalized_slug = _normalize_slug(slug)
        _validate_slug(normalized_slug)
        clean_title = _validate_title(title)
        clean_meta = _validate_meta_description(meta_description)
        clean_body = _validate_body_html(body_html)

        # 2) Check slug collision against active pages.
        existing_page = (
            db.query(CmsPage)
            .filter(
                func.lower(CmsPage.slug) == normalized_slug,
                CmsPage.deleted_at.is_(None),
            )
            .first()
        )
        if existing_page is not None:
            raise CmsSlugConflictError(
                f"A page with slug '{normalized_slug}' already exists.",
                slug=normalized_slug,
            )

        # 3) Check slug collision against active redirects.  A redirect
        # pointing at this slug would shadow the new page, so we reject.
        existing_redirect = (
            db.query(CmsPageRedirect)
            .filter(func.lower(CmsPageRedirect.from_slug) == normalized_slug)
            .first()
        )
        if existing_redirect is not None:
            raise CmsSlugConflictError(
                f"Slug '{normalized_slug}' is in use by an existing redirect.",
                slug=normalized_slug,
            )

        # 4) Compute nav_order — append at the end of the visible nav.
        max_order = (
            db.query(func.max(CmsPage.nav_order))
            .filter(CmsPage.deleted_at.is_(None))
            .scalar()
        )
        next_order = (max_order or 0) + 1 if show_in_nav else None

        # 5) Persist page + initial revision + audit log in one transaction.
        page = CmsPage(
            slug=normalized_slug,
            title=clean_title,
            meta_description=clean_meta,
            body_html=clean_body,
            show_in_nav=show_in_nav,
            nav_order=next_order,
            created_by_id=created_by_id,
            updated_by_id=created_by_id,
        )
        db.add(page)
        db.flush()  # allocate page.id for the revision/audit FK

        revision = CmsPageRevision(
            page_id=page.id,
            title=clean_title,
            slug=normalized_slug,
            meta_description=clean_meta,
            body_html=clean_body,
            edited_by_id=created_by_id,
        )
        db.add(revision)

        audit = AuditLog(
            entity_type="cms_pages",
            entity_id=str(page.id),
            action="cms_page.created",
            user_id=created_by_id,
            new_values={
                "slug": normalized_slug,
                "title": clean_title,
                "meta_description": clean_meta,
                "show_in_nav": show_in_nav,
                "nav_order": next_order,
                # Body intentionally omitted — large, and full revision row
                # already captures the content.
            },
            description=f"Created CMS page '{normalized_slug}'",
        )
        db.add(audit)

        db.commit()
        db.refresh(page)
        return page

    # =====================================================================
    # READ helpers used by tests / future stories
    # =====================================================================

    @staticmethod
    def get_active_by_slug(db: Session, slug: str) -> Optional[CmsPage]:
        """Return the active (non-deleted) page for ``slug`` or None."""
        normalized = _normalize_slug(slug)
        if not normalized:
            return None
        return (
            db.query(CmsPage)
            .filter(
                func.lower(CmsPage.slug) == normalized,
                CmsPage.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def slug_in_use(db: Session, slug: str) -> bool:
        """Return True when the slug collides with a page OR a redirect."""
        normalized = _normalize_slug(slug)
        if not normalized:
            return False
        return (
            db.query(CmsPage.id)
            .filter(
                func.lower(CmsPage.slug) == normalized,
                CmsPage.deleted_at.is_(None),
            )
            .union_all(
                db.query(CmsPageRedirect.id).filter(
                    func.lower(CmsPageRedirect.from_slug) == normalized
                )
            )
            .first()
            is not None
        )

    # =====================================================================
    # ETag helpers (CC-BR-03 / CC-BR-13)
    # =====================================================================

    @staticmethod
    def page_etag(page: CmsPage) -> str:
        """Compute a strong ETag from the page's ``updated_at``.

        Deterministic across processes so revalidation works after redeploy.
        """
        stamp = page.updated_at.isoformat() if page.updated_at else "0"
        digest = hashlib.sha256(
            f"cms:{page.id}:{stamp}".encode("utf-8")
        ).hexdigest()[:32]
        return f'"{digest}"'

    @staticmethod
    def _check_if_match(page: CmsPage, if_match: Optional[str]) -> None:
        """Enforce the ``If-Match`` precondition against the page ETag.

        Raises :class:`CmsPreconditionRequiredError` (428) when the header
        is missing and :class:`CmsConcurrencyError` (412) when it mismatches.
        """
        if not if_match or not if_match.strip():
            raise CmsPreconditionRequiredError(
                "If-Match header is required for this operation."
            )
        current = CmsPageService.page_etag(page)
        # Support comma-separated lists and the ``*`` wildcard so clients
        # that echo multiple prior ETags still validate.
        candidates = {tok.strip() for tok in if_match.split(",") if tok.strip()}
        if current in candidates or "*" in candidates:
            return
        raise CmsConcurrencyError(
            "The page has changed since it was loaded. Reload and retry."
        )

    @staticmethod
    def list_etag(db: Session) -> str:
        """Compute the list-level ETag used by reorder + navbar payloads.

        Combines the max ``updated_at`` across active pages with the row
        count so add/delete operations that share a second still invalidate.
        """
        row = (
            db.query(
                func.max(CmsPage.updated_at),
                func.count(CmsPage.id),
            )
            .filter(CmsPage.deleted_at.is_(None))
            .one()
        )
        max_updated, count = row
        stamp = max_updated.isoformat() if max_updated else "0"
        digest = hashlib.sha256(
            f"cms-list:{stamp}:{count}".encode("utf-8")
        ).hexdigest()[:32]
        return f'"{digest}"'

    @staticmethod
    def nav_etag(db: Session) -> str:
        """Compute the ETag for the public navbar payload."""
        row = (
            db.query(
                func.max(CmsPage.updated_at),
                func.count(CmsPage.id),
            )
            .filter(
                CmsPage.deleted_at.is_(None),
                CmsPage.show_in_nav.is_(True),
            )
            .one()
        )
        max_updated, count = row
        stamp = max_updated.isoformat() if max_updated else "0"
        digest = hashlib.sha256(
            f"cms-nav:{stamp}:{count}".encode("utf-8")
        ).hexdigest()[:32]
        return f'"{digest}"'

    # =====================================================================
    # READ / list / get (admin)
    # =====================================================================

    @staticmethod
    def list_pages(
        db: Session, *, include_deleted: bool = False, search: Optional[str] = None
    ) -> List[CmsPage]:
        """Return all pages (active by default) ordered for the admin list."""
        query = db.query(CmsPage)
        if include_deleted:
            query = query.filter(CmsPage.deleted_at.isnot(None)).order_by(
                CmsPage.deleted_at.desc()
            )
        else:
            query = query.filter(CmsPage.deleted_at.is_(None)).order_by(
                CmsPage.nav_order.asc().nullslast(),
                CmsPage.created_at.asc(),
            )
        if search:
            like = f"%{search.strip().lower()}%"
            query = query.filter(
                func.lower(CmsPage.title).like(like)
                | func.lower(CmsPage.slug).like(like)
            )
        return query.all()

    @staticmethod
    def get_page(
        db: Session, page_id: UUID, *, include_deleted: bool = False
    ) -> CmsPage:
        """Return the page by id or raise :class:`CmsNotFoundError`."""
        query = db.query(CmsPage).filter(CmsPage.id == page_id)
        if not include_deleted:
            query = query.filter(CmsPage.deleted_at.is_(None))
        page = query.first()
        if page is None:
            raise CmsNotFoundError(f"Page {page_id} not found.")
        return page

    # =====================================================================
    # UPDATE (US-002 + US-004 slug side-effects)
    # =====================================================================

    @staticmethod
    def update_page(
        db: Session,
        page_id: UUID,
        *,
        title: Optional[str] = None,
        slug: Optional[str] = None,
        body_html: Optional[str] = None,
        meta_description: Optional[str] = None,
        show_in_nav: Optional[bool] = None,
        if_match: Optional[str],
        updated_by_id: UUID,
    ) -> Tuple[CmsPage, List[str]]:
        """Update a page and return ``(page, changed_fields)``.

        - Enforces the ``If-Match`` precondition (US-002 AC3/AC4).
        - Normalizes + sanitizes inputs; runs slug validation (US-004).
        - Inserts a revision row when any field changed (US-002 BR-02).
        - When slug changes, rewrites redirects for a single-hop invariant
          (US-004 AC2) and removes any self-redirect that would result
          (US-004 AC3).
        - Emits ``cms_page.updated`` + optional ``cms_page.slug_changed``
          + ``cms_redirect.deleted`` audit events.
        """
        page = CmsPageService.get_page(db, page_id)
        CmsPageService._check_if_match(page, if_match)

        proposed: dict = {}
        if title is not None:
            proposed["title"] = _validate_title(title)
        if meta_description is not None:
            proposed["meta_description"] = _validate_meta_description(
                meta_description
            )
        if body_html is not None:
            proposed["body_html"] = _validate_body_html(body_html)
        if show_in_nav is not None:
            proposed["show_in_nav"] = bool(show_in_nav)
        if slug is not None:
            proposed["slug"] = _normalize_slug(slug)
            _validate_slug(proposed["slug"])

        old_slug = page.slug
        new_slug = proposed.get("slug", old_slug)

        # Detect slug collision only when it is actually changing (case
        # sensitive comparison happens on the normalized value).
        if slug is not None and new_slug != old_slug:
            existing_page = (
                db.query(CmsPage)
                .filter(
                    func.lower(CmsPage.slug) == new_slug,
                    CmsPage.deleted_at.is_(None),
                    CmsPage.id != page.id,
                )
                .first()
            )
            if existing_page is not None:
                raise CmsSlugConflictError(
                    f"A page with slug '{new_slug}' already exists.",
                    slug=new_slug,
                )
            # Redirect collision: allowed only when the redirect currently
            # points at this same page (that redirect will be cleaned up).
            colliding_redirect = (
                db.query(CmsPageRedirect)
                .filter(func.lower(CmsPageRedirect.from_slug) == new_slug)
                .first()
            )
            if (
                colliding_redirect is not None
                and colliding_redirect.to_page_id != page.id
            ):
                raise CmsSlugConflictError(
                    f"Slug '{new_slug}' is in use by an existing redirect.",
                    slug=new_slug,
                )

        # Compute the actual change set by comparing to current row state.
        changed_fields: List[str] = []
        candidate = {
            "title": proposed.get("title", page.title),
            "slug": proposed.get("slug", page.slug),
            "meta_description": proposed.get(
                "meta_description", page.meta_description
            ),
            "body_html": proposed.get("body_html", page.body_html),
            "show_in_nav": proposed.get("show_in_nav", bool(page.show_in_nav)),
        }
        for field, new_val in candidate.items():
            if new_val != getattr(page, field):
                changed_fields.append(field)

        # No-op save — return without writing (US-002 AC2).
        if not changed_fields:
            return page, []

        # Apply changes.
        for field, new_val in candidate.items():
            setattr(page, field, new_val)

        # `show_in_nav` toggle preserves nav_order (CC-BR-08 / US-006 AC5).

        page.updated_by_id = updated_by_id
        # Force updated_at bump — SQLAlchemy ``onupdate`` uses server-side
        # ``func.now()`` at flush time but we want the audit log timestamp to
        # match, so we set it explicitly here to keep tests deterministic.
        page.updated_at = datetime.utcnow()
        db.flush()

        # Slug change side effects (US-004).
        slug_changed = "slug" in changed_fields
        if slug_changed:
            _rewrite_redirects_for_slug_change(
                db,
                page=page,
                old_slug=old_slug,
                new_slug=new_slug,
                actor=updated_by_id,
            )

        # Revision row (CC-BR-02).
        revision = CmsPageRevision(
            page_id=page.id,
            title=page.title,
            slug=page.slug,
            meta_description=page.meta_description,
            body_html=page.body_html,
            edited_by_id=updated_by_id,
        )
        db.add(revision)

        # Audit events.
        db.add(
            AuditLog(
                entity_type="cms_pages",
                entity_id=str(page.id),
                action="cms_page.updated",
                user_id=updated_by_id,
                new_values={
                    "changed_fields": changed_fields,
                    "slug": page.slug,
                },
                description=f"Updated CMS page '{page.slug}'",
            )
        )
        if slug_changed:
            db.add(
                AuditLog(
                    entity_type="cms_pages",
                    entity_id=str(page.id),
                    action="cms_page.slug_changed",
                    user_id=updated_by_id,
                    old_values={"slug": old_slug},
                    new_values={"slug": page.slug},
                    description=(
                        f"Slug changed from '{old_slug}' to '{page.slug}'"
                    ),
                )
            )

        db.commit()
        db.refresh(page)
        return page, changed_fields

    # =====================================================================
    # SOFT-DELETE / RESTORE (US-003)
    # =====================================================================

    @staticmethod
    def soft_delete_page(
        db: Session,
        page_id: UUID,
        *,
        if_match: Optional[str],
        actor_id: UUID,
    ) -> CmsPage:
        """Soft-delete an active page and clear its ``nav_order``."""
        page = CmsPageService.get_page(db, page_id)  # 404 if already deleted
        CmsPageService._check_if_match(page, if_match)
        page.deleted_at = datetime.utcnow()
        page.nav_order = None
        page.updated_by_id = actor_id
        page.updated_at = datetime.utcnow()
        db.add(
            AuditLog(
                entity_type="cms_pages",
                entity_id=str(page.id),
                action="cms_page.deleted",
                user_id=actor_id,
                old_values={"slug": page.slug},
                description=f"Soft-deleted CMS page '{page.slug}'",
            )
        )
        db.commit()
        db.refresh(page)
        return page

    @staticmethod
    def restore_page(
        db: Session,
        page_id: UUID,
        *,
        if_match: Optional[str],
        actor_id: UUID,
        alternate_slug: Optional[str] = None,
    ) -> CmsPage:
        """Restore a soft-deleted page, optionally renaming to avoid collisions."""
        page = (
            db.query(CmsPage)
            .filter(CmsPage.id == page_id, CmsPage.deleted_at.isnot(None))
            .first()
        )
        if page is None:
            # Already active → 409 per US-003 AC8.
            active = (
                db.query(CmsPage)
                .filter(CmsPage.id == page_id, CmsPage.deleted_at.is_(None))
                .first()
            )
            if active is not None:
                raise CmsInvalidStateError("Page is not deleted.")
            raise CmsNotFoundError(f"Page {page_id} not found.")

        CmsPageService._check_if_match(page, if_match)

        # Slug collision check against active rows.
        active_collision = (
            db.query(CmsPage)
            .filter(
                func.lower(CmsPage.slug) == page.slug,
                CmsPage.deleted_at.is_(None),
                CmsPage.id != page.id,
            )
            .first()
        )
        redirect_collision = (
            db.query(CmsPageRedirect)
            .filter(func.lower(CmsPageRedirect.from_slug) == page.slug)
            .first()
        )
        needs_rename = active_collision is not None or (
            redirect_collision is not None
            and redirect_collision.to_page_id != page.id
        )
        if needs_rename and not alternate_slug:
            raise CmsSlugConflictError(
                "Slug is already in use; provide an alternate_slug to restore.",
                slug=page.slug,
            )

        old_slug = page.slug
        if alternate_slug:
            normalized = _normalize_slug(alternate_slug)
            _validate_slug(normalized)
            # Reject when alternate slug also collides.
            other = (
                db.query(CmsPage)
                .filter(
                    func.lower(CmsPage.slug) == normalized,
                    CmsPage.deleted_at.is_(None),
                    CmsPage.id != page.id,
                )
                .first()
            )
            if other is not None:
                raise CmsSlugConflictError(
                    f"A page with slug '{normalized}' already exists.",
                    slug=normalized,
                )
            colliding_redirect = (
                db.query(CmsPageRedirect)
                .filter(func.lower(CmsPageRedirect.from_slug) == normalized)
                .first()
            )
            if (
                colliding_redirect is not None
                and colliding_redirect.to_page_id != page.id
            ):
                raise CmsSlugConflictError(
                    f"Slug '{normalized}' is in use by an existing redirect.",
                    slug=normalized,
                )
            page.slug = normalized

        page.deleted_at = None
        max_order = (
            db.query(func.max(CmsPage.nav_order))
            .filter(CmsPage.deleted_at.is_(None))
            .scalar()
        )
        page.nav_order = (max_order or 0) + 1 if page.show_in_nav else None
        page.updated_by_id = actor_id
        page.updated_at = datetime.utcnow()
        db.flush()

        slug_changed = page.slug != old_slug
        if slug_changed:
            _rewrite_redirects_for_slug_change(
                db,
                page=page,
                old_slug=old_slug,
                new_slug=page.slug,
                actor=actor_id,
            )

        db.add(
            AuditLog(
                entity_type="cms_pages",
                entity_id=str(page.id),
                action="cms_page.restored",
                user_id=actor_id,
                new_values={"slug": page.slug},
                description=f"Restored CMS page '{page.slug}'",
            )
        )
        if slug_changed:
            db.add(
                AuditLog(
                    entity_type="cms_pages",
                    entity_id=str(page.id),
                    action="cms_page.slug_changed",
                    user_id=actor_id,
                    old_values={"slug": old_slug},
                    new_values={"slug": page.slug},
                    description=(
                        f"Slug changed on restore: '{old_slug}' → '{page.slug}'"
                    ),
                )
            )
        db.commit()
        db.refresh(page)
        return page

    # =====================================================================
    # REORDER (US-006)
    # =====================================================================

    @staticmethod
    def reorder_pages(
        db: Session,
        *,
        ordered_ids: List[UUID],
        if_match: Optional[str],
        actor_id: UUID,
    ) -> List[CmsPage]:
        """Assign sequential ``nav_order`` values from the supplied list.

        Validates payload against every non-deleted page id and rejects
        unknown / soft-deleted / duplicate ids (US-006 AC2).  Requires a
        list-level ``If-Match`` derived from :meth:`list_etag`.
        """
        if if_match is None or not if_match.strip():
            raise CmsPreconditionRequiredError(
                "If-Match header is required for reorder."
            )
        current_list_etag = CmsPageService.list_etag(db)
        candidates = {
            tok.strip() for tok in if_match.split(",") if tok.strip()
        }
        if current_list_etag not in candidates and "*" not in candidates:
            raise CmsConcurrencyError(
                "The page list has changed since it was loaded. Reload and retry."
            )

        if not isinstance(ordered_ids, list):
            raise CmsValidationError("ordered_ids must be a list.", field="ordered_ids")
        # Reject duplicates.
        if len(ordered_ids) != len(set(ordered_ids)):
            raise CmsValidationError(
                "ordered_ids contains duplicates.", field="ordered_ids"
            )

        active_pages = (
            db.query(CmsPage)
            .filter(CmsPage.deleted_at.is_(None))
            .all()
        )
        active_ids = {page.id for page in active_pages}
        supplied_ids = set(ordered_ids)

        if supplied_ids != active_ids:
            raise CmsValidationError(
                "ordered_ids must enumerate every non-deleted page exactly once.",
                field="ordered_ids",
            )

        pages_by_id = {page.id: page for page in active_pages}
        before_order = [
            str(p.id)
            for p in sorted(
                active_pages,
                key=lambda p: (
                    p.nav_order if p.nav_order is not None else 10_000_000,
                    p.created_at,
                ),
            )
        ]

        for idx, pid in enumerate(ordered_ids, start=1):
            pages_by_id[pid].nav_order = idx
        db.flush()

        db.add(
            AuditLog(
                entity_type="cms_pages",
                entity_id="*",
                action="cms_page.reordered",
                user_id=actor_id,
                old_values={"before": before_order},
                new_values={"after": [str(p) for p in ordered_ids]},
                description="Reordered CMS pages",
            )
        )
        db.commit()
        return sorted(
            active_pages,
            key=lambda p: p.nav_order if p.nav_order is not None else 0,
        )

    # =====================================================================
    # REVISIONS (US-005)
    # =====================================================================

    @staticmethod
    def list_revisions(db: Session, page_id: UUID) -> List[CmsPageRevision]:
        """Return all revisions for the page ordered newest first."""
        # Ensure the page exists (allow soft-deleted for restore workflow).
        exists = (
            db.query(CmsPage.id).filter(CmsPage.id == page_id).first()
        )
        if exists is None:
            raise CmsNotFoundError(f"Page {page_id} not found.")
        return (
            db.query(CmsPageRevision)
            .filter(CmsPageRevision.page_id == page_id)
            .order_by(CmsPageRevision.edited_at.desc())
            .all()
        )

    @staticmethod
    def restore_revision(
        db: Session,
        page_id: UUID,
        revision_id: UUID,
        *,
        if_match: Optional[str],
        actor_id: UUID,
    ) -> Tuple[CmsPage, List[str]]:
        """Restore the fields of a prior revision onto the page."""
        page = (
            db.query(CmsPage).filter(CmsPage.id == page_id).first()
        )
        if page is None:
            raise CmsNotFoundError(f"Page {page_id} not found.")

        revision = (
            db.query(CmsPageRevision)
            .filter(
                CmsPageRevision.id == revision_id,
                CmsPageRevision.page_id == page.id,
            )
            .first()
        )
        if revision is None:
            raise CmsNotFoundError(
                f"Revision {revision_id} not found for page {page_id}."
            )
        CmsPageService._check_if_match(page, if_match)

        # Re-sanitize the historical body against the current allow-list
        # (US-005 BR-02 defense-in-depth).
        clean_body = sanitize_html(revision.body_html)
        if not clean_body.strip():
            # Historical body no longer contains any allowed content —
            # keep original to preserve behaviour.
            clean_body = revision.body_html

        # Validate slug against the current allow-list / reserved list.
        _validate_slug(revision.slug)

        old_slug = page.slug
        was_deleted = page.deleted_at is not None
        # Slug collision checks (excluding this page).
        if revision.slug != page.slug:
            other = (
                db.query(CmsPage)
                .filter(
                    func.lower(CmsPage.slug) == revision.slug,
                    CmsPage.deleted_at.is_(None),
                    CmsPage.id != page.id,
                )
                .first()
            )
            if other is not None:
                raise CmsSlugConflictError(
                    f"A page with slug '{revision.slug}' already exists.",
                    slug=revision.slug,
                )
            colliding_redirect = (
                db.query(CmsPageRedirect)
                .filter(
                    func.lower(CmsPageRedirect.from_slug) == revision.slug
                )
                .first()
            )
            if (
                colliding_redirect is not None
                and colliding_redirect.to_page_id != page.id
            ):
                raise CmsSlugConflictError(
                    f"Slug '{revision.slug}' is in use by an existing redirect.",
                    slug=revision.slug,
                )

        # Diff before applying.
        candidate = {
            "title": revision.title,
            "slug": revision.slug,
            "meta_description": revision.meta_description,
            "body_html": clean_body,
        }
        changed_fields = [
            f for f, v in candidate.items() if v != getattr(page, f)
        ]
        if was_deleted:
            # Implicit un-delete (US-005 AC6).
            page.deleted_at = None
            max_order = (
                db.query(func.max(CmsPage.nav_order))
                .filter(CmsPage.deleted_at.is_(None))
                .scalar()
            )
            page.nav_order = (
                (max_order or 0) + 1 if page.show_in_nav else None
            )

        if not changed_fields and not was_deleted:
            return page, []

        for field, val in candidate.items():
            setattr(page, field, val)
        page.updated_by_id = actor_id
        page.updated_at = datetime.utcnow()
        db.flush()

        slug_changed = "slug" in changed_fields
        if slug_changed:
            _rewrite_redirects_for_slug_change(
                db,
                page=page,
                old_slug=old_slug,
                new_slug=page.slug,
                actor=actor_id,
            )

        # Append a new revision snapshotting the post-restore state.
        new_rev = CmsPageRevision(
            page_id=page.id,
            title=page.title,
            slug=page.slug,
            meta_description=page.meta_description,
            body_html=page.body_html,
            edited_by_id=actor_id,
        )
        db.add(new_rev)

        # Audit events.
        db.add(
            AuditLog(
                entity_type="cms_pages",
                entity_id=str(page.id),
                action="cms_page.revision_restored",
                user_id=actor_id,
                new_values={
                    "source_revision_id": str(revision.id),
                    "slug": page.slug,
                },
                description=(
                    f"Restored revision {revision.id} onto page '{page.slug}'"
                ),
            )
        )
        if changed_fields:
            db.add(
                AuditLog(
                    entity_type="cms_pages",
                    entity_id=str(page.id),
                    action="cms_page.updated",
                    user_id=actor_id,
                    new_values={"changed_fields": changed_fields},
                    description=(
                        f"Updated CMS page '{page.slug}' via revision restore"
                    ),
                )
            )
        if slug_changed:
            db.add(
                AuditLog(
                    entity_type="cms_pages",
                    entity_id=str(page.id),
                    action="cms_page.slug_changed",
                    user_id=actor_id,
                    old_values={"slug": old_slug},
                    new_values={"slug": page.slug},
                    description=(
                        f"Slug changed via revision restore: "
                        f"'{old_slug}' → '{page.slug}'"
                    ),
                )
            )
        if was_deleted:
            db.add(
                AuditLog(
                    entity_type="cms_pages",
                    entity_id=str(page.id),
                    action="cms_page.restored",
                    user_id=actor_id,
                    description=(
                        f"Restored soft-deleted CMS page '{page.slug}' via "
                        "revision restore"
                    ),
                )
            )
        db.commit()
        db.refresh(page)
        return page, changed_fields

    # =====================================================================
    # REDIRECTS (US-008)
    # =====================================================================

    @staticmethod
    def list_redirects(db: Session) -> List[CmsPageRedirect]:
        return (
            db.query(CmsPageRedirect)
            .order_by(CmsPageRedirect.created_at.desc())
            .all()
        )

    @staticmethod
    def delete_redirect(
        db: Session,
        redirect_id: UUID,
        *,
        actor_id: UUID,
    ) -> None:
        """Hard-delete a redirect row (CC-BR-05 / US-008)."""
        redirect = (
            db.query(CmsPageRedirect)
            .filter(CmsPageRedirect.id == redirect_id)
            .first()
        )
        if redirect is None:
            raise CmsNotFoundError(f"Redirect {redirect_id} not found.")
        db.delete(redirect)
        db.add(
            AuditLog(
                entity_type="cms_page_redirects",
                entity_id=str(redirect.id),
                action="cms_redirect.deleted",
                user_id=actor_id,
                old_values={
                    "from_slug": redirect.from_slug,
                    "to_page_id": str(redirect.to_page_id),
                },
                description=(
                    f"Deleted redirect '{redirect.from_slug}' → "
                    f"page {redirect.to_page_id}"
                ),
            )
        )
        db.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rewrite_redirects_for_slug_change(
    db: Session,
    *,
    page: CmsPage,
    old_slug: str,
    new_slug: str,
    actor: UUID,
) -> None:
    """Maintain the single-hop redirect invariant on slug change (US-004).

    - Existing redirects targeting this page are preserved (their
      ``from_slug`` continues to resolve to the current page in one hop).
    - Any redirect whose ``from_slug`` equals the new slug (which can only
      exist when we are renaming the page back to a prior name) is
      hard-deleted and audited so the resolver does not produce a
      self-redirect (US-004 AC3).
    - A new redirect row ``(from_slug=old_slug, to_page_id=page.id)`` is
      inserted.
    """
    # 1) Remove any redirect whose from_slug == new_slug (must belong to us).
    self_redirect = (
        db.query(CmsPageRedirect)
        .filter(func.lower(CmsPageRedirect.from_slug) == new_slug)
        .first()
    )
    if self_redirect is not None and self_redirect.to_page_id == page.id:
        db.add(
            AuditLog(
                entity_type="cms_page_redirects",
                entity_id=str(self_redirect.id),
                action="cms_redirect.deleted",
                user_id=actor,
                old_values={
                    "from_slug": self_redirect.from_slug,
                    "to_page_id": str(self_redirect.to_page_id),
                },
                description=(
                    "Auto-deleted self-redirect on slug rename "
                    f"(from_slug='{self_redirect.from_slug}')"
                ),
            )
        )
        db.delete(self_redirect)
        db.flush()

    # 2) Insert the new redirect for the old slug (unless a row already
    # exists from a prior rename cycle).
    existing = (
        db.query(CmsPageRedirect)
        .filter(func.lower(CmsPageRedirect.from_slug) == old_slug)
        .first()
    )
    if existing is None:
        db.add(
            CmsPageRedirect(
                from_slug=old_slug,
                to_page_id=page.id,
            )
        )
        db.flush()
    else:
        # Point any pre-existing row at us (defensive — normally already ours).
        existing.to_page_id = page.id
        db.flush()
