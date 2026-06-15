"""Form management service - CRUD operations for forms.

Provides business logic for creating, reading, updating, deleting, and managing forms.
Includes audit logging, soft deletes, and version management.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, text, func as sa_func
from sqlalchemy.exc import OperationalError

from backend.models import (
    Form,
    FormWorkflow,
    AuditLog,
    FormNumberReservation,
    FormVersion,
)
from backend.services import s3_service


def _utc_naive_now() -> datetime:
    """Return current UTC time as a naive ``datetime`` (no tzinfo).

    FEAT-0015: replaces ``datetime.utcnow()`` which is deprecated on
    Python 3.12+ but matches the historical naive-UTC value stored in the
    SQLAlchemy ``DateTime`` columns used here.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
            effective_date=effective_date,
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
        db.commit()
        db.refresh(form)

        # Audit log
        audit_new_values = {
            "id": str(form.id),
            "title": title,
            "is_public": is_public,
            "form_source": form_source,
            "file_type": file_type,
            "collects_personal_info": form.collects_personal_info,
        }

        # Include reservation_id in audit log if provided (TASK-413)
        if form_number_reservation_id:
            audit_new_values["form_number_reservation_id"] = str(
                form_number_reservation_id
            )

        FormService._audit_log(
            db=db,
            entity_type="forms",
            entity_id=str(form.id),
            action="CREATE",
            user_id=created_by_id,
            new_values=audit_new_values,
        )

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
        limit: int = 25,
        q: Optional[str] = None,
        status: Optional[List[str]] = None,
        business_area_ids: Optional[List[UUID]] = None,
        form_source: Optional[List[str]] = None,
        is_public: Optional[bool] = None,
        sort_order: str = "desc",
        sort_field: str = "created_at",
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
            sort_field: created_at or form_number

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
            .filter(Form.deleted_at.is_(None))
        )

        search_active = False
        if q and q.strip():
            search_active = True
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
                        form_number_reservations.full_form_number
                            ILIKE :like_pattern ESCAPE :esc
                    )
                )""")  # noqa: E501
            ).params(search_query=q.strip(), like_pattern=like_pattern, esc="\\")

        # Apply filters
        if status:
            query = query.filter(Form.status.in_(status))

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

        # Sorting
        #
        # When a search is active, form-number matches are ranked first
        # (primary ORDER BY) regardless of the chosen sort_field, so that
        # an exact/partial form-number hit always appears above title-only
        # matches.  The user's sort_field is applied as secondary.
        if search_active:
            rank_expr = text("""
                CASE WHEN form_number_reservations.full_form_number
                          ILIKE :rank_pattern ESCAPE :esc
                     THEN 0 ELSE 1 END
            """).params(
                rank_pattern=like_pattern,
                esc="\\",
            )

            if sort_field == "form_number":
                sort_col = FormNumberReservation.full_form_number
                if sort_order.lower() == "asc":
                    query = query.order_by(rank_expr, asc(sort_col).nullslast())
                else:
                    query = query.order_by(rank_expr, desc(sort_col).nullslast())
            else:
                if sort_order.lower() == "asc":
                    query = query.order_by(rank_expr, asc(Form.created_at))
                else:
                    query = query.order_by(rank_expr, desc(Form.created_at))
        else:
            if sort_field == "form_number":
                sort_col = FormNumberReservation.full_form_number
                if sort_order.lower() == "asc":
                    query = query.order_by(asc(sort_col).nullslast())
                else:
                    query = query.order_by(desc(sort_col).nullslast())
            else:
                if sort_order.lower() == "asc":
                    query = query.order_by(asc(Form.created_at))
                else:
                    query = query.order_by(desc(Form.created_at))

        # Apply pagination
        forms = query.offset(skip).limit(limit).all()

        return forms, total

    @staticmethod
    def get_autocomplete_suggestions(
        db: Session,
        query_text: str,
        max_suggestions: int = 10,
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
                  AND f.title ILIKE :pattern ESCAPE '\\'

                UNION

                SELECT DISTINCT
                    jsonb_array_elements_text(
                        COALESCE(f.keywords::jsonb, '[]'::jsonb)
                    ) AS suggestion
                FROM forms f
                WHERE f.deleted_at IS NULL

                UNION

                SELECT DISTINCT fnr.full_form_number AS suggestion
                FROM form_number_reservations fnr
                JOIN forms f ON f.form_number_reservation_id = fnr.id
                WHERE f.deleted_at IS NULL
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
            },
        ).fetchall()

        return [row[0] for row in rows if row and row[0]]

    # =====================================================================
    # UPDATE OPERATIONS
    # =====================================================================

    @staticmethod
    def update_form(
        db: Session, form_id: UUID, updated_by_id: UUID, **kwargs
    ) -> Optional[Form]:
        """
        Update a form (all fields except status/version).

        Args:
            db: Database session
            form_id: Form UUID to update
            updated_by_id: UUID of user performing update
            **kwargs: Fields to update (title, description, is_public,
                     keywords, business_area_ids, effective_date)

        Returns:
            Updated Form object or None if not found
        """
        form = FormService.get_form_by_id(db, form_id)
        if not form:
            return None

        # Track old values for audit
        old_values = {
            "title": form.title,
            "description": form.description,
            "is_public": form.is_public,
            "keywords": form.keywords,
            "collects_personal_info": form.collects_personal_info,
        }

        # Update fields
        if "title" in kwargs:
            form.title = kwargs["title"]
        if "description" in kwargs:
            form.description = kwargs["description"]
        if "is_public" in kwargs:
            form.is_public = kwargs["is_public"]
        if "keywords" in kwargs:
            form.keywords = kwargs["keywords"]
        if "effective_date" in kwargs:
            form.effective_date = kwargs["effective_date"]
        if "collects_personal_info" in kwargs:
            form.collects_personal_info = kwargs["collects_personal_info"]
        # TASK-416: handle attachment field updates and S3 deletion
        if "form_source" in kwargs:
            form.form_source = kwargs["form_source"]
        if "form_source_url" in kwargs:
            form.form_source_url = kwargs["form_source_url"]
        if "form_attachment_url" in kwargs:
            old_url = form.form_attachment_url
            new_url = kwargs["form_attachment_url"]
            # Delete the old file from S3 whenever the URL changes (removed or replaced)
            if old_url and old_url != new_url:
                old_key = FormService._extract_s3_object_key(old_url)
                if old_key:
                    s3_service.delete_file(old_key)
            form.form_attachment_url = new_url
        if "form_attachment_filename" in kwargs:
            form.form_attachment_filename = kwargs["form_attachment_filename"]
        # FEAT-0002: file_type tracking
        if "file_type" in kwargs:
            form.file_type = kwargs["file_type"]

        # Handle business area updates
        if "business_area_id" in kwargs:
            form.business_area_id = kwargs["business_area_id"]

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
            & set(kwargs.keys())
        )
        if _attachment_fields_changed and form.status == "published":
            if form.form_source == "Download" and form.form_attachment_url:
                FormService._sync_form_version(db, form, updated_by_id)
            else:
                # Attachment cleared OR source switched away from Download →
                # retire any current FormVersion so /file returns 404 cleanly.
                FormService._retire_current_form_version(db, form)

        db.commit()
        db.refresh(form)

        # Audit log
        # Convert UUID values to strings for JSON serialization (PortableJSON/JSONB)
        audit_new_values = {
            k: str(v) if isinstance(v, UUID) else v
            for k, v in kwargs.items()
        }
        FormService._audit_log(
            db=db,
            entity_type="forms",
            entity_id=str(form.id),
            action="UPDATE",
            user_id=updated_by_id,
            old_values=old_values,
            new_values=audit_new_values,
        )

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
            form = query.first()
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

        # Sync FormVersion so public_forms_v can resolve the file for download.
        if to_status == "published":
            FormService._sync_form_version(db, form, triggered_by_id)

        db.commit()
        db.refresh(form)
        return form

    @staticmethod
    def submit_form_for_review(db: Session, form_id: UUID, user_id: UUID) -> Form:
        form = FormService._get_form_for_transition(db, form_id, lock=True)

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
        if str(form.created_by_id) == str(approver_id) and not allow_self_approve:
            raise FormWorkflowValidationError(
                "You cannot approve your own form submission."
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

        db.commit()
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
                {"id": str(form.business_area.id), "name": form.business_area.name}
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
