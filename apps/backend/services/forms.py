"""Form management service - CRUD operations for forms.

Provides business logic for creating, reading, updating, deleting, and managing forms.
Includes audit logging, soft deletes, and version management.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from uuid import UUID, uuid7
from urllib.parse import urlsplit, urlunsplit
import logging
import re
from sqlalchemy.orm import Session
from sqlalchemy import and_, asc, case, desc, or_, text, func as sa_func
from sqlalchemy.exc import OperationalError

from backend.models import (
    BusinessArea,
    Form,
    FormWorkflow,
    AuditLog,
    FormActivityEvent,
    FormNumberReservation,
    FormVersion,
    User,
)
from backend.services import s3_service

logger = logging.getLogger(__name__)


def _utc_naive_now() -> datetime:
    """Return current UTC time as a naive ``datetime`` (no tzinfo).

    FEAT-0015: replaces ``datetime.utcnow()`` which is deprecated on
    Python 3.12+ but matches the historical naive-UTC value stored in the
    SQLAlchemy ``DateTime`` columns used here.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_effective_date(value: Optional[datetime]) -> Optional[datetime]:
    """Convert aware instants to naive UTC without shifting date-only inputs."""
    if value is None or value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


_ACTIVITY_FIELDS = (
    "title", "description", "is_public", "keywords", "business_area_id",
    "effective_date", "collects_personal_info", "form_source",
    "form_source_url", "form_attachment_url", "form_attachment_filename",
    "file_type", "form_number_reservation_id",
)
_OBJECT_KEY = re.compile(r"uploads/[A-Za-z0-9_./-]+")
_SENSITIVE_PAIR = re.compile(
    r"(?i)\b(token|secret|password|api[_-]?key|signature|credential)"
    r"\s*[:=]\s*[^\s,;&]+"
)
_EMBEDDED_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def _safe_text(value: str) -> str:
    """Remove embedded URL credentials/query strings and obvious secret pairs."""
    def clean_url(match: re.Match) -> str:
        url = match.group(0)
        try:
            parts = urlsplit(url)
            if not parts.hostname:
                return "[unavailable]"
            host = parts.hostname
            if ":" in host:
                host = f"[{host}]"
            if parts.port:
                host = f"{host}:{parts.port}"
            return urlunsplit((parts.scheme, host, parts.path, "", ""))
        except ValueError:
            return "[unavailable]"

    return _SENSITIVE_PAIR.sub("[redacted]", _EMBEDDED_URL.sub(clean_url, value))


def _activity_value(field: str, value: Any) -> Any:
    """Store JSON-safe historical values, never a signed attachment URL."""
    if isinstance(value, (UUID, datetime)):
        value = value.isoformat() if isinstance(value, datetime) else str(value)
    if field == "form_attachment_url":
        if value is None:
            return None
        if not isinstance(value, str):
            return "[unavailable]"
        try:
            path = urlsplit(value).path
        except ValueError:
            return "[unavailable]"
        match = _OBJECT_KEY.search(path)
        return (
            match.group(0) if match and (
                match.start() == 0 or path[match.start() - 1] == "/"
            ) else "[unavailable]"
        )
    if field == "form_source_url" and isinstance(value, str):
        try:
            parts = urlsplit(value)
            # A URL's user-info, query and fragment can all contain credentials.
            if parts.scheme not in ("http", "https") or not parts.hostname:
                return "[unavailable]"
            host = parts.hostname
            if ":" in host:
                host = f"[{host}]"
            if parts.port:
                host = f"{host}:{parts.port}"
            return urlunsplit((parts.scheme, host, parts.path, "", ""))
        except ValueError:
            return "[unavailable]"
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_safe_text(item) if isinstance(item, str) else item for item in value]
    return value


def _activity_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        field: _activity_value(field, values[field])
        for field in _ACTIVITY_FIELDS if field in values
    }


def _record_form_activity(
    db: Session, form: "Form", user_id: Optional[UUID], event_name: str,
    old: Optional[Dict[str, Any]] = None,
    new: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> None:
    """Stage required history in the caller's form-write transaction."""
    try:
        if user_id is None:
            label = "System"
        else:
            actor = db.query(User).filter(User.id == user_id).first()
            if actor is None:
                raise RuntimeError("Audit actor unavailable")
            label = " ".join(
                part.strip() for part in (actor.first_name, actor.last_name)
                if part and part.strip()
            ) or (actor.email.strip() if actor.email else "")
        if not label:
            raise RuntimeError("Audit actor unavailable")
        label = _safe_text(label)
        old_values = _activity_values(old or {})
        new_values = _activity_values(new or {})
        changed = [
            key for key in _ACTIVITY_FIELDS
            if key in old_values or key in new_values
        ]
        if event_name not in ("Form created", "Form saved"):
            changed = ["status"]
            old_values = {"status": (old or {}).get("status")}
            new_values = {"status": (new or {}).get("status")}
            if (old or {}).get("created_by_id") != (new or {}).get("created_by_id"):
                changed.append("created_by_id")
                old_values["created_by_id"] = (old or {}).get("created_by_id")
                new_values["created_by_id"] = (new or {}).get("created_by_id")
        db.add(FormActivityEvent(
            id=uuid7(), occurred_at=_utc_naive_now(),
            form_id=form.id, event_name=event_name, actor_label=label,
            changed_fields=changed, old_values=old_values, new_values=new_values,
            reason=_safe_text(reason.strip()) if reason and reason.strip() else None,
        ))
        db.flush()
    except Exception:
        db.rollback()
        raise


class FormWorkflowValidationError(ValueError):
    """Raised when a workflow transition request is invalid (HTTP 400)."""


class FormWorkflowConflictError(ValueError):
    """Raised for workflow conflicts (HTTP 409)."""


class FormNotFoundError(ValueError):
    """Raised when a form cannot be found (HTTP 404)."""


class FormService:
    """Service class for form management operations."""

    VALID_TRANSITIONS = {
        "draft": ["pending_review"],
        "pending_review": ["published", "draft"],
        "published": ["archived", "draft"],  # FEAT-0016: "draft" added for revert
        "archived": ["published"],
    }

    @staticmethod
    def _require_active_business_area(db: Session, business_area_id: Optional[UUID]) -> None:
        if not business_area_id or not db.query(BusinessArea.id).filter(
            BusinessArea.id == business_area_id,
            BusinessArea.deleted_at.is_(None),
        ).with_for_update().first():
            raise FormWorkflowValidationError("Select an active Business Area.")

    @staticmethod
    def _normalize_newlines(value: Optional[str]) -> Optional[str]:
        """FEAT-0027 US-011: normalise CRLF/CR line endings to LF before persistence.

        Preserves the user's line/paragraph structure verbatim (no stripping or
        collapsing) so Save is idempotent for already-normalised text.
        """
        if value is None:
            return None
        return value.replace("\r\n", "\n").replace("\r", "\n")


    # =====================================================================
    # CREATE OPERATIONS
    # =====================================================================

    @staticmethod
    def create_form(
        db: Session,
        title: str,
        description: Optional[str],
        is_public: bool,
        keywords: Optional[List[str]],
        business_area_id: Optional[UUID],
        created_by_id: UUID,
        effective_date: Optional[datetime] = None,
        form_source: Optional[str] = None,
        form_source_url: Optional[str] = None,
        form_attachment_url: Optional[str] = None,
        form_attachment_filename: Optional[str] = None,
        file_type: Optional[str] = None,
        form_number_reservation_id: Optional[UUID] = None,
        collects_personal_info: Optional[str] = None,
    ) -> Form:
        """
        Create a new form.

        Args:
            db: Database session
            title: Form title
            description: Form description
            is_public: Whether form is publicly visible
            keywords: List of search keywords
            business_area_id: Associated business area ID
            created_by_id: UUID of user creating the form
            effective_date: When the form becomes effective
            form_source: 'URL' or 'DOWNLOAD' (or None)
            form_source_url: Source URL when form_source == 'URL'
            form_attachment_url: S3 object key when form_source == 'DOWNLOAD'
            form_attachment_filename: Original filename of uploaded attachment
            file_type: Short file-type label derived from MIME (FEAT-0002)
            form_number_reservation_id: UUID of approved reservation (TASK-413)
            collects_personal_info: Whether form collects personal information

        Returns:
            Created Form object

        Raises:
            ValueError: If validation fails or reservation is invalid
        """
        # Validate description is provided (required per TASK-110C)
        if not description or not description.strip():
            raise ValueError("description is required")

        FormService._require_active_business_area(db, business_area_id)

        # FEAT-0027 US-011: normalise newlines (\r\n, \r -> \n) before persistence
        description = FormService._normalize_newlines(description)

        # TASK-413: Validate and link form number reservation
        if form_number_reservation_id:
            reservation = (
                db.query(FormNumberReservation)
                .filter(
                    FormNumberReservation.id == form_number_reservation_id,
                    FormNumberReservation.deleted_at.is_(None),
                )
                .first()
            )

            if not reservation:
                raise ValueError(f"Reservation {form_number_reservation_id} not found")

            if reservation.status != "approved":
                raise ValueError(
                    f"Reservation must be approved, current status: {reservation.status}"
                )

            # Check if this reservation is already used by another form
            existing_form = (
                db.query(Form)
                .filter(
                    Form.form_number_reservation_id == form_number_reservation_id,
                    Form.deleted_at.is_(None),
                )
                .first()
            )

            if existing_form:
                raise ValueError("Reservation is already used by another form")

        # Create the form
        form = Form(
            title=title,
            description=description,
            is_public=is_public,
            keywords=keywords or [],
            created_by_id=created_by_id,
            effective_date=_normalize_effective_date(effective_date),
            status="draft",
            current_version=0,
            business_area_id=business_area_id,
            form_source=form_source,
            form_source_url=form_source_url,
            form_attachment_url=form_attachment_url,
            form_attachment_filename=form_attachment_filename,
            file_type=file_type,
            form_number_reservation_id=form_number_reservation_id,
            collects_personal_info=collects_personal_info or "No",
        )

        db.add(form)
        db.flush()
        values = {field: getattr(form, field) for field in _ACTIVITY_FIELDS}
        _record_form_activity(
            db, form, created_by_id, "Form created", new=values,
        )
        db.add(AuditLog(
            entity_type="forms", entity_id=str(form.id), action="CREATE",
            user_id=created_by_id, new_values=_activity_values(values),
        ))
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(form)

        return form

    # =====================================================================
    # READ OPERATIONS
    # =====================================================================

    @staticmethod
    def get_form_by_id(db: Session, form_id: UUID) -> Optional[Form]:
        """
        Get a form by ID (excluding soft-deleted).

        Args:
            db: Database session
            form_id: Form UUID

        Returns:
            Form object or None if not found
        """
        return (
            db.query(Form).filter(Form.id == form_id, Form.deleted_at.is_(None)).first()
        )

    @staticmethod
    def _escape_like(value: str) -> str:
        """Escape LIKE/ILIKE wildcard characters in user input.

        Prevents ``%`` and ``_`` from being interpreted as wildcards.
        Uses backslash as the escape character (PostgreSQL default).
        """
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def list_forms(
        db: Session,
        skip: int = 0,
        limit: int = 24,
        q: Optional[str] = None,
        status: Optional[List[str]] = None,
        business_area_ids: Optional[List[UUID]] = None,
        form_source: Optional[List[str]] = None,
        is_public: Optional[bool] = None,
        sort_order: str = "desc",
        sort_field: str = "suggested",
        unpublished_area_ids: Optional[set[UUID]] = None,
        allow_unpublished_any: bool = False,
    ) -> tuple[List[Form], int]:
        """
        List forms with filters and pagination.

        Args:
            db: Database session
            skip: Number of records to skip
            limit: Max records to return
            q: Full-text search query (matches title/description/keywords OR form number)
            status: Filter by status list (OR logic within)
            business_area_ids: Optional list of business area IDs (match any)
            form_source: Filter by source list (OR logic within)
            is_public: Filter by public status
            sort_order: asc or desc
            sort_field: suggested, title, or form_number
            unpublished_area_ids: Active areas allowed for scoped unpublished reads.
            allow_unpublished_any: Whether all unpublished forms are readable.

        Returns:
            Tuple of (list of Form objects, total count)
        """
        # Always LEFT JOIN form_number_reservations for search/sort access
        query = (
            db.query(Form)
            .outerjoin(
                FormNumberReservation,
                Form.form_number_reservation_id == FormNumberReservation.id,
            )
            .outerjoin(
                BusinessArea,
                (Form.business_area_id == BusinessArea.id)
                & (BusinessArea.deleted_at.is_(None)),
            )
            .filter(Form.deleted_at.is_(None))
        )

        if q and q.strip():
            escaped_q = FormService._escape_like(q.strip())
            like_pattern = f"%{escaped_q}%"

            # Full-text search OR form number ILIKE
            # Outer parens required so OR doesn't bypass other WHERE filters
            query = query.filter(
                text("""(
                    (
                        COALESCE(
                            forms.search_vector,
                            setweight(to_tsvector('english',
                                coalesce(forms.title, '')), 'A') ||
                            setweight(to_tsvector('english',
                                coalesce(forms.description, '')), 'B') ||
                            setweight(to_tsvector('english',
                                coalesce(forms.keywords::text, '')), 'C') ||
                            setweight(to_tsvector('english',
                                coalesce(forms.form_source, '')), 'D') ||
                            setweight(to_tsvector('english',
                                coalesce(forms.form_source_url, '')), 'D')
                        ) @@ plainto_tsquery('english', :search_query)
                    )
                        OR
                        (
                            -- Keep Business Area matches at keyword weight; no promotion.
                            setweight(
                                to_tsvector('english',
                                    coalesce(business_areas.name, '')), 'C'
                            ) @@ plainto_tsquery('english', :search_query)
                        )
                    OR
                    (
                        form_number_reservations.full_form_number
                            ILIKE :like_pattern ESCAPE :esc
                    )
                )""")  # noqa: E501
            ).params(search_query=q.strip(), like_pattern=like_pattern, esc="\\")

        # Apply filters
        if status:
            query = query.filter(Form.status.in_(status))

        if unpublished_area_ids is not None or allow_unpublished_any:
            visibility_filters = [Form.status == "published"]
            if allow_unpublished_any:
                visibility_filters.append(
                    Form.status.in_(["draft", "pending_review", "archived"])
                )
            elif unpublished_area_ids:
                visibility_filters.append(
                    and_(
                        Form.status.in_(["draft", "pending_review"]),
                        Form.business_area_id.in_(unpublished_area_ids),
                    )
                )
            query = query.filter(or_(*visibility_filters))

        if business_area_ids:
            query = query.filter(Form.business_area_id.in_(business_area_ids))

        if form_source:
            normalized_sources = [
                "URL" if s.lower() == "link" else "Download" for s in form_source
            ]
            query = query.filter(Form.form_source.in_(normalized_sources))

        if is_public is not None:
            query = query.filter(Form.is_public == is_public)

        # Count total (no DISTINCT needed — LEFT JOIN is 1:1 via FK)
        total = query.count()

        allowed_sort_orders = {
            "suggested": {"desc"},
            "title": {"asc", "desc"},
            "form_number": {"asc", "desc"},
        }
        normalized_sort_order = sort_order.lower()
        if normalized_sort_order not in allowed_sort_orders.get(sort_field, set()):
            raise ValueError("Unsupported Forms sort field and order")

        if sort_field == "suggested":
            query = query.order_by(desc(Form.created_at), asc(Form.id))
        elif sort_field == "title":
            title_whitespace = sa_func.concat(" \t\n\r\f\v", sa_func.chr(160))
            title_sort_key = case(
                (sa_func.btrim(Form.title, title_whitespace) == "", None),
                else_=Form.title,
            ).collate("forms_title_en_natural_ci")
            title_order = (
                asc(title_sort_key).nullslast()
                if normalized_sort_order == "asc"
                else desc(title_sort_key).nullslast()
            )
            query = query.order_by(
                title_order,
                desc(Form.created_at),
                asc(Form.id),
            )
        else:
            form_number_sort_key = FormNumberReservation.full_form_number
            form_number_order = (
                asc(form_number_sort_key).nullslast()
                if normalized_sort_order == "asc"
                else desc(form_number_sort_key).nullslast()
            )
            query = query.order_by(form_number_order, asc(Form.id))

        # Apply pagination
        forms = query.offset(skip).limit(limit).all()

        return forms, total

    @staticmethod
    def get_autocomplete_suggestions(
        db: Session,
        query_text: str,
        max_suggestions: int = 10,
        published_only: bool = False,
    ) -> List[str]:
        """Get autocomplete suggestions from form titles, keywords, and form numbers."""
        normalized_query = (query_text or "").strip()
        if len(normalized_query) < 2:
            return []

        escaped_q = FormService._escape_like(normalized_query)
        like_pattern = f"%{escaped_q}%"

        sql = text("""
            SELECT suggestion
            FROM (
                SELECT DISTINCT f.title AS suggestion
                FROM forms f
                WHERE f.deleted_at IS NULL
                                    AND (:published_only = FALSE OR f.status = 'published')
                  AND f.title ILIKE :pattern ESCAPE '\\'

                UNION

                SELECT DISTINCT
                    jsonb_array_elements_text(
                        COALESCE(f.keywords::jsonb, '[]'::jsonb)
                    ) AS suggestion
                FROM forms f
                WHERE f.deleted_at IS NULL
                                    AND (:published_only = FALSE OR f.status = 'published')

                UNION

                SELECT DISTINCT fnr.full_form_number AS suggestion
                FROM form_number_reservations fnr
                JOIN forms f ON f.form_number_reservation_id = fnr.id
                WHERE f.deleted_at IS NULL
                                    AND (:published_only = FALSE OR f.status = 'published')
                  AND fnr.full_form_number ILIKE :pattern ESCAPE '\\'
            ) s
            WHERE s.suggestion ILIKE :pattern ESCAPE '\\'
            ORDER BY s.suggestion ASC
            LIMIT :max_suggestions
            """)  # noqa: E501

        rows = db.execute(
            sql,
            {
                "pattern": like_pattern,
                "max_suggestions": min(max(max_suggestions, 1), 10),
                "published_only": published_only,
            },
        ).fetchall()

        return [row[0] for row in rows if row and row[0]]

    # =====================================================================
    # UPDATE OPERATIONS
    # =====================================================================

    @staticmethod
    def update_form(
        db: Session,
        form_id: UUID,
        updated_by_id: UUID,
        expected_version: Optional[int] = None,
        allow_non_owner_draft: bool = False,
        **kwargs,
    ) -> Optional[Form]:
        """
        Update a form's content and advance its version without changing status.

        Args:
            db: Database session
            form_id: Form UUID to update
            updated_by_id: UUID of user performing update
            **kwargs: Fields to update (title, description, is_public,
                     keywords, business_area_ids, effective_date)

        Returns:
            Updated Form object or None if not found
        """
        form = db.query(Form).filter(
            Form.id == form_id, Form.deleted_at.is_(None)
        ).with_for_update().populate_existing().first()
        if not form:
            return None

        if form.status == "draft" and (
            form.created_by_id != updated_by_id and not allow_non_owner_draft
        ):
            raise PermissionError("Only the form creator can edit this draft")
        if form.status == "pending_review":
            raise PermissionError(
                "Form cannot be edited while it is in Pending Review state"
            )
        if expected_version is not None and form.current_version != expected_version:
            raise FormWorkflowConflictError(
                "Form version changed; reload and reconcile before saving"
            )

        FormService._require_active_business_area(
            db, kwargs.get("business_area_id", form.business_area_id)
        )

        old_values = {field: getattr(form, field) for field in _ACTIVITY_FIELDS}
        old_values["effective_date"] = _normalize_effective_date(
            old_values["effective_date"]
        )

        # Update fields
        if "title" in kwargs:
            form.title = kwargs["title"]
        if "description" in kwargs:
            form.description = FormService._normalize_newlines(kwargs["description"])
        if "is_public" in kwargs:
            form.is_public = kwargs["is_public"]
        if "keywords" in kwargs:
            form.keywords = kwargs["keywords"]
        if "effective_date" in kwargs:
            form.effective_date = _normalize_effective_date(kwargs["effective_date"])
        if "collects_personal_info" in kwargs:
            form.collects_personal_info = kwargs["collects_personal_info"]
        # TASK-416: handle attachment field updates and S3 deletion
        if "form_source" in kwargs:
            form.form_source = kwargs["form_source"]
        if "form_source_url" in kwargs:
            form.form_source_url = kwargs["form_source_url"]
        if "form_attachment_url" in kwargs:
            form.form_attachment_url = kwargs["form_attachment_url"]
        if "form_attachment_filename" in kwargs:
            form.form_attachment_filename = kwargs["form_attachment_filename"]
        # FEAT-0002: file_type tracking
        if "file_type" in kwargs:
            form.file_type = kwargs["file_type"]

        # Handle business area updates
        if "business_area_id" in kwargs:
            form.business_area_id = kwargs["business_area_id"]

        new_values = {field: getattr(form, field) for field in _ACTIVITY_FIELDS}
        changed_fields = [
            field for field in _ACTIVITY_FIELDS
            if old_values[field] != new_values[field]
        ]
        if not changed_fields:
            return form
        form.current_version += 1

        # FEAT-0005 BUGFIX (2026-06-11): when the attachment changes on an
        # already-published form, the `form_versions` row that backs the
        # ``public_forms_v`` database view becomes stale (its s3_key now
        # points at the deleted S3 object).  The public download endpoint
        # then resolves a key that no longer exists → NGINX returns 404.
        #
        # Re-sync the current FormVersion so the public-portal download
        # path always reflects the latest attachment.  No-op when the form
        # is not published or when the attachment field was not part of
        # this update.
        _attachment_fields_changed = bool(
            {"form_attachment_url", "form_source", "form_attachment_filename", "file_type"}
            & set(changed_fields)
        )
        if _attachment_fields_changed and form.status == "published":
            if form.form_source == "Download" and form.form_attachment_url:
                FormService._sync_form_version(db, form, updated_by_id)
            else:
                # Attachment cleared OR source switched away from Download →
                # retire any current FormVersion so /file returns 404 cleanly.
                FormService._retire_current_form_version(db, form)

        before = {field: old_values[field] for field in changed_fields}
        after = {field: new_values[field] for field in changed_fields}
        _record_form_activity(
            db, form, updated_by_id, "Form saved", old=before, new=after,
        )
        db.add(AuditLog(
            entity_type="forms", entity_id=str(form.id), action="UPDATE",
            user_id=updated_by_id,
            old_values=_activity_values(before), new_values=_activity_values(after),
        ))
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(form)
        # External cleanup cannot be part of the database transaction. Do not
        # delete the old object until both the form and required audit are durable.
        if "form_attachment_url" in changed_fields and old_values["form_attachment_url"]:
            old_key = FormService._extract_s3_object_key(old_values["form_attachment_url"])
            if old_key:
                try:
                    s3_service.delete_file(old_key)
                except Exception:
                    # Retain orphaned storage rather than report a committed save as failed.
                    logger.warning("Superseded form attachment cleanup failed")

        return form

    # =====================================================================
    # DELETE OPERATIONS
    # =====================================================================

    @staticmethod
    def delete_form(db: Session, form_id: UUID, deleted_by_id: UUID) -> bool:
        """
        Soft delete a form (set deleted_at).

        Args:
            db: Database session
            form_id: Form UUID to delete
            deleted_by_id: UUID of user performing delete

        Returns:
            True if deleted, False if not found
        """
        form = FormService.get_form_by_id(db, form_id)
        if not form:
            return False

        form.deleted_at = _utc_naive_now()
        db.commit()

        # Audit log
        FormService._audit_log(
            db=db,
            entity_type="forms",
            entity_id=str(form.id),
            action="DELETE",
            user_id=deleted_by_id,
            old_values={"status": form.status},
            new_values={"deleted_at": form.deleted_at.isoformat()},
        )

        return True

    @staticmethod
    def _get_form_for_transition(db: Session, form_id: UUID, lock: bool = True) -> Form:
        query = db.query(Form).filter(
            Form.id == form_id,
            Form.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update(nowait=True)

        try:
            form = query.populate_existing().first()
        except OperationalError as exc:
            raise FormWorkflowConflictError(
                "Form status was changed by another user; unable to acquire lock"
            ) from exc

        if not form:
            raise FormNotFoundError("Form not found")

        return form

    @staticmethod
    def _validate_workflow_transition(current_status: str, target_status: str) -> None:
        if current_status == target_status:
            raise FormWorkflowValidationError(
                f"Form is already in '{target_status}' state"
            )

        allowed = FormService.VALID_TRANSITIONS.get(current_status, [])
        if target_status not in allowed:
            raise FormWorkflowValidationError(
                f"Invalid transition from '{current_status}' to '{target_status}'"
            )

    @staticmethod
    def _is_separation_of_duties_enforced(db: Session) -> bool:
        """Read DB-level setting; defaults to off when undefined."""
        try:
            value = db.execute(
                text("SELECT current_setting('app.enforce_separation_of_duties', true)")
            ).scalar()
        except Exception:
            return False

        if value is None:
            return False

        return str(value).strip().lower() in {"1", "true", "on", "yes"}

    @staticmethod
    def _transition_form_status(
        db: Session,
        form: Form,
        *,
        action: str,
        to_status: str,
        triggered_by_id: UUID,
        reason_notes: Optional[str] = None,
    ) -> Form:
        from_status = form.status
        FormService._validate_workflow_transition(from_status, to_status)

        workflow = FormWorkflow(
            form_id=form.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            triggered_by_id=triggered_by_id,
            reason_notes=reason_notes,
        )
        db.add(workflow)
        db.flush()

        form.status = to_status
        db.flush()

        db.add(
            AuditLog(
                entity_type="forms",
                entity_id=str(form.id),
                action="WORKFLOW_TRANSITION",
                user_id=triggered_by_id,
                old_values={"status": from_status},
                new_values={
                    "status": to_status,
                    "action": action,
                    "reason_notes": reason_notes,
                },
            )
        )
        # BR-007 is an allowlist: legacy unpublish is a valid transition, but
        # is not one of the approved user-facing activity event types.
        included_events = {
            "submit": "Form submitted", "approve": "Form approved",
            "reject": "Form rejected", "request_changes": "Changes requested",
            "publish": "Form published", "archive": "Form archived",
            "restore": "Form restored",
        }
        if action in included_events:
            _record_form_activity(
                db, form, triggered_by_id, included_events[action],
                old={"status": from_status}, new={"status": to_status},
                reason=reason_notes,
            )

        # Sync FormVersion so public_forms_v can resolve the file for download.
        if to_status == "published":
            try:
                FormService._sync_form_version(db, form, triggered_by_id)
            except Exception:
                db.rollback()
                raise

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(form)
        return form

    @staticmethod
    def submit_form_for_review(
        db: Session, form_id: UUID, user_id: UUID, expected_version: Optional[int] = None
    ) -> Form:
        form = FormService._get_form_for_transition(db, form_id, lock=True)
        if expected_version is not None and form.current_version != expected_version:
            raise FormWorkflowConflictError(
                "Form version changed; reload and reconcile before submitting"
            )
        FormService._require_active_business_area(db, form.business_area_id)

        if form.form_number_reservation_id:
            reservation = (
                db.query(FormNumberReservation)
                .filter(
                    FormNumberReservation.id == form.form_number_reservation_id,
                    FormNumberReservation.deleted_at.is_(None),
                )
                .first()
            )

            if not reservation or reservation.status != "approved":
                raise FormWorkflowConflictError(
                    "Form number reservation must be approved before submission"
                )

        return FormService._transition_form_status(
            db,
            form,
            action="submit",
            to_status="pending_review",
            triggered_by_id=user_id,
        )

    @staticmethod
    def approve_form(
        db: Session,
        form_id: UUID,
        approver_id: UUID,
        allow_self_approve: bool = False,
    ) -> Form:
        form = FormService._get_form_for_transition(db, form_id, lock=True)

        # BR-002: Separation of duties.
        # Bypassed only when the caller explicitly holds form:approve-self (FEAT-0007).
        is_creator = str(form.created_by_id) == str(approver_id)
        if is_creator and not allow_self_approve:
            raise FormWorkflowValidationError(
                "You cannot approve your own form submission."
            )

        latest_submit = (
            db.query(FormWorkflow)
            .filter(
                FormWorkflow.form_id == form.id,
                FormWorkflow.action == "submit",
                FormWorkflow.deleted_at.is_(None),
            )
            .order_by(desc(FormWorkflow.created_at))
            .first()
        )
        is_latest_submitter = latest_submit is not None and str(
            latest_submit.triggered_by_id
        ) == str(approver_id)
        if is_latest_submitter and not allow_self_approve:
            raise FormWorkflowValidationError(
                "You cannot approve a form you most recently submitted."
            )

        return FormService._transition_form_status(
            db,
            form,
            action="approve",
            to_status="published",
            triggered_by_id=approver_id,
        )

    @staticmethod
    def reject_form(
        db: Session, form_id: UUID, reviewer_id: UUID, reason_notes: str
    ) -> Form:
        if not reason_notes or not reason_notes.strip():
            raise FormWorkflowValidationError(
                "Rejection reason (reason_notes) is required"
            )

        form = FormService._get_form_for_transition(db, form_id, lock=True)
        return FormService._transition_form_status(
            db,
            form,
            action="reject",
            to_status="draft",
            triggered_by_id=reviewer_id,
            reason_notes=reason_notes.strip(),
        )

    @staticmethod
    def publish_form(db: Session, form_id: UUID, user_id: UUID) -> Form:
        form = FormService._get_form_for_transition(db, form_id, lock=True)
        return FormService._transition_form_status(
            db,
            form,
            action="publish",
            to_status="published",
            triggered_by_id=user_id,
        )

    @staticmethod
    def unpublish_form(db: Session, form_id: UUID, user_id: UUID) -> Form:
        form = FormService._get_form_for_transition(db, form_id, lock=True)
        return FormService._transition_form_status(
            db,
            form,
            action="unpublish",
            to_status="draft",
            triggered_by_id=user_id,
        )

    @staticmethod
    def revert_form_to_draft(
        db: Session,
        form_id: UUID,
        reverting_user_id: UUID,
        reason_notes: str,
    ) -> Form:
        """Revert a Published form to Draft (FEAT-0016).

        The reverting user becomes the new owner. Both the prior and new
        ``created_by_id`` values are written to the AuditLog entry so that
        AC7 / CONFLICT-03 (ownership-change audit trail) is satisfied.

        Args:
            db: Database session.
            form_id: UUID of the form to revert.
            reverting_user_id: UUID of the staff user performing the revert.
            reason_notes: Mandatory non-blank justification for the revert.

        Returns:
            Updated Form object in Draft state.

        Raises:
            FormWorkflowValidationError: Reason is blank, or the form is not
                in Published state.
            FormNotFoundError: Form does not exist or has been soft-deleted.
            FormWorkflowConflictError: Row lock could not be acquired.
        """
        if not reason_notes or not reason_notes.strip():
            raise FormWorkflowValidationError(
                "Revert reason (reason_notes) is required"
            )

        form = FormService._get_form_for_transition(db, form_id, lock=True)
        from_status = form.status

        # AC4: only Published forms may be reverted; pending_review → draft is
        # a valid generic transition (reject flow) but must NOT be reachable here.
        if from_status != "published":
            raise FormWorkflowValidationError(
                f"Invalid transition from '{from_status}' to 'draft': "
                "revert is only permitted for Published forms"
            )

        prior_owner_id = form.created_by_id
        cleaned_reason = reason_notes.strip()

        workflow = FormWorkflow(
            form_id=form.id,
            action="revert",
            from_status=from_status,
            to_status="draft",
            triggered_by_id=reverting_user_id,
            reason_notes=cleaned_reason,
        )
        db.add(workflow)
        db.flush()

        form.status = "draft"
        form.created_by_id = reverting_user_id
        db.flush()

        db.add(
            AuditLog(
                entity_type="forms",
                entity_id=str(form.id),
                action="WORKFLOW_TRANSITION",
                user_id=reverting_user_id,
                old_values={
                    "status": from_status,
                    "created_by_id": str(prior_owner_id),
                },
                new_values={
                    "status": "draft",
                    "action": "revert",
                    "reason_notes": cleaned_reason,
                    "created_by_id": str(reverting_user_id),
                },
            )
        )
        _record_form_activity(
            db, form, reverting_user_id, "Form reverted",
            old={"status": from_status, "created_by_id": str(prior_owner_id)},
            new={"status": "draft", "created_by_id": str(reverting_user_id)},
            reason=cleaned_reason,
        )
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(form)
        return form

    @staticmethod
    def archive_form(
        db: Session,
        form_id: UUID,
        archived_by_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> Optional[Form]:
        """
        Archive a form (change status to archived).

        Args:
            db: Database session
            form_id: Form UUID to archive
            archived_by_id: UUID of user archiving form

        Returns:
            Archived Form object or None if not found
        """
        actor_id = user_id or archived_by_id
        if actor_id is None:
            raise FormWorkflowValidationError("A user_id is required")

        form = FormService._get_form_for_transition(db, form_id, lock=True)
        return FormService._transition_form_status(
            db,
            form,
            action="archive",
            to_status="archived",
            triggered_by_id=actor_id,
        )

    @staticmethod
    def restore_form(db: Session, form_id: UUID, user_id: UUID) -> Form:
        """
        Unarchive a form (change status back to published).

        Args:
            db: Database session
            form_id: Form UUID to unarchive
            unarchived_by_id: UUID of user unarchiving form

        Returns:
            Unarchived Form object or None if not found
        """
        form = FormService._get_form_for_transition(db, form_id, lock=True)
        return FormService._transition_form_status(
            db,
            form,
            action="restore",
            to_status="published",
            triggered_by_id=user_id,
        )

    @staticmethod
    def unarchive_form(
        db: Session, form_id: UUID, unarchived_by_id: UUID
    ) -> Optional[Form]:
        """Backward-compatible alias for restore_form."""
        return FormService.restore_form(
            db=db, form_id=form_id, user_id=unarchived_by_id
        )

    @staticmethod
    def get_workflow_history(db: Session, form_id: UUID) -> List[FormWorkflow]:
        """Return workflow history ordered by newest first."""
        form = FormService.get_form_by_id(db, form_id)
        if not form:
            raise FormNotFoundError("Form not found")

        return (
            db.query(FormWorkflow)
            .filter(
                FormWorkflow.form_id == form_id,
                FormWorkflow.deleted_at.is_(None),
            )
            .order_by(desc(FormWorkflow.created_at))
            .all()
        )

    # =====================================================================
    # HELPER METHODS
    # =====================================================================

    @staticmethod
    def _extract_s3_object_key(url: str) -> Optional[str]:
        """Extract the S3 object key from the stored attachment reference.

        New records store the object key directly; legacy records may store
        a full MinIO URL that requires parsing.
        """
        if not url:
            return None
        if url.startswith("uploads/"):
            return url  # new format: value IS the object key
        # Fallback: extract key from legacy full-URL format still present in existing DB rows
        import re

        match = re.search(r"(uploads/[^?#]+)", url)
        return match.group(1) if match else None

    @staticmethod
    def _sync_form_version(db: Session, form: Form, uploaded_by_id: UUID) -> None:
        """Create or reactivate a ``form_versions`` row when a form is published.

        The ``public_forms_v`` DB view resolves file metadata from
        ``form_versions`` (``is_current = True``), not from
        ``forms.form_attachment_url``.  This method bridges that gap by
        ensuring a current ``FormVersion`` row always exists for any
        ``Download``-source form when it enters the ``published`` state.

        Edge-cases handled:
        * First publish          → insert a new ``FormVersion`` row.
        * Re-publish, same file  → reactivate the existing row (avoids the
                                   ``s3_key`` unique-constraint violation).
        * Re-publish, new file   → retire the old current row, insert fresh.
        * Non-Download forms     → no-op (form_source != 'Download').
        """
        if form.form_source != "Download" or not form.form_attachment_url:
            return

        object_key = FormService._extract_s3_object_key(form.form_attachment_url)
        if not object_key:
            return

        # If a FormVersion with this exact S3 key already exists for this form,
        # simply re-flag it as current to avoid the unique-constraint on s3_key.
        existing_fv = (
            db.query(FormVersion)
            .filter(
                FormVersion.form_id == form.id,
                FormVersion.s3_key == object_key,
                FormVersion.deleted_at.is_(None),
            )
            .first()
        )

        if existing_fv:
            # Retire any *other* current version for this form.
            db.query(FormVersion).filter(
                FormVersion.form_id == form.id,
                FormVersion.s3_key != object_key,
                FormVersion.is_current.is_(True),
                FormVersion.deleted_at.is_(None),
            ).update({"is_current": False}, synchronize_session=False)

            existing_fv.is_current = True
            existing_fv.file_name = form.form_attachment_filename or object_key.split("/")[-1]
            existing_fv.file_type = form.file_type or existing_fv.file_type or "unknown"
            existing_fv.file_size = s3_service.get_object_size(object_key)
            existing_fv.uploaded_by_id = uploaded_by_id
            db.flush()
            return

        # Retire any existing current version before inserting the new one.
        db.query(FormVersion).filter(
            FormVersion.form_id == form.id,
            FormVersion.is_current.is_(True),
            FormVersion.deleted_at.is_(None),
        ).update({"is_current": False}, synchronize_session=False)

        max_ver = (
            db.query(sa_func.max(FormVersion.version_number))
            .filter(FormVersion.form_id == form.id)
            .scalar()
        ) or 0

        file_size = s3_service.get_object_size(object_key)
        fv = FormVersion(
            form_id=form.id,
            version_number=max_ver + 1,
            s3_key=object_key,
            file_name=form.form_attachment_filename or object_key.split("/")[-1],
            file_size=file_size,
            file_type=form.file_type or "unknown",
            is_current=True,
            uploaded_by_id=uploaded_by_id,
        )
        db.add(fv)
        db.flush()

    @staticmethod
    def _retire_current_form_version(db: Session, form: Form) -> None:
        """Mark every current ``FormVersion`` for ``form`` as no longer current.

        Used when a published form's attachment is *removed* (or its
        ``form_source`` changes away from ``Download``) so that the
        ``public_forms_v`` DB view stops resolving a stale ``s3_key``.

        This is a soft retire (``is_current = False``).  The history row is
        retained for auditability; the public download endpoint will then
        return 404 (no attached file) for the form.
        """
        db.query(FormVersion).filter(
            FormVersion.form_id == form.id,
            FormVersion.is_current.is_(True),
            FormVersion.deleted_at.is_(None),
        ).update({"is_current": False}, synchronize_session=False)
        db.flush()

    @staticmethod
    def _audit_log(
        db: Session,
        entity_type: str,
        entity_id: str,
        action: str,
        user_id: UUID,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create an audit log entry."""
        try:
            audit_entry = AuditLog(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                user_id=user_id,
                old_values=old_values,
                new_values=new_values,
            )
            db.add(audit_entry)
            db.commit()
        except Exception:
            db.rollback()
            # Don't let audit logging failures break the app
            pass

    @staticmethod
    def get_form_with_details(db: Session, form_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get a form with all related details (business areas, versions, workflow).

        Args:
            db: Database session
            form_id: Form UUID

        Returns:
            Dictionary with form details or None
        """
        form = FormService.get_form_by_id(db, form_id)
        if not form:
            return None

        reservation = form.form_number_reservation

        return {
            "id": str(form.id),
            "title": form.title,
            "description": form.description,
            "status": form.status,
            "is_public": form.is_public,
            "current_version": form.current_version,
            "keywords": form.keywords,
            "business_area": (
                {
                    "id": str(form.business_area.id),
                    "name": form.business_area.name,
                    "mailbox": form.business_area.mailbox or None,
                }
                if form.business_area else None
            ),
            "created_by": {
                "id": str(form.created_by.id),
                "email": form.created_by.email,
            },
            "effective_date": (
                form.effective_date.isoformat() if form.effective_date else None
            ),
            # TASK-110C fields
            "form_source": form.form_source,
            "form_source_url": form.form_source_url,
            "form_attachment_url": form.form_attachment_url,
            "form_attachment_filename": form.form_attachment_filename,
            # FEAT-0002: file type label
            "file_type": form.file_type,
            # Personal information field
            "collects_personal_info": form.collects_personal_info,
            # TASK-413 fields
            "form_number_reservation_id": (
                str(form.form_number_reservation_id)
                if form.form_number_reservation_id
                else None
            ),
            "form_number": reservation.form_number if reservation else None,
            "full_form_number": reservation.full_form_number if reservation else None,
            "created_at": form.created_at.isoformat(),
            "updated_at": form.updated_at.isoformat(),
        }
