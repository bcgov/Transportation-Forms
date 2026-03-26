"""Form management service - CRUD operations for forms.

Provides business logic for creating, reading, updating, deleting, and managing forms.
Includes audit logging, soft deletes, and version management.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, asc, text
from sqlalchemy.exc import OperationalError

from backend.models import (
    Form,
    FormBusinessArea,
    FormWorkflow,
    BusinessArea,
    AuditLog,
    FormNumberReservation,
)
from backend.config import settings
from backend.services import minio_service


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
        "pending_review": ["approved", "draft"],
        "approved": ["published"],
        "published": ["archived", "draft"],
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
        business_area_ids: Optional[List[UUID]],
        created_by_id: UUID,
        effective_date: Optional[datetime] = None,
        form_source: Optional[str] = None,
        form_source_url: Optional[str] = None,
        form_attachment_url: Optional[str] = None,
        form_attachment_filename: Optional[str] = None,
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
            business_area_ids: List of associated business area IDs
            created_by_id: UUID of user creating the form
            effective_date: When the form becomes effective
            form_source: 'URL' or 'DOWNLOAD' (or None)
            form_source_url: Source URL when form_source == 'URL'
            form_attachment_url: MinIO object URL when form_source == 'DOWNLOAD'
            form_attachment_filename: Original filename of uploaded attachment
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
            form_source=form_source,
            form_source_url=form_source_url,
            form_attachment_url=form_attachment_url,
            form_attachment_filename=form_attachment_filename,
            form_number_reservation_id=form_number_reservation_id,
            collects_personal_info=collects_personal_info or "No",
        )

        # Associate business areas
        if business_area_ids:
            business_areas = (
                db.query(BusinessArea)
                .filter(
                    BusinessArea.id.in_(business_area_ids),
                    BusinessArea.deleted_at.is_(None),
                )
                .all()
            )

            if len(business_areas) != len(business_area_ids):
                raise ValueError("One or more business areas do not exist")

            for ba in business_areas:
                form_ba = FormBusinessArea(business_area=ba)
                form.business_areas.append(form_ba)

        db.add(form)
        db.commit()
        db.refresh(form)

        # Audit log
        audit_new_values = {
            "id": str(form.id),
            "title": title,
            "is_public": is_public,
            "form_source": form_source,
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
    def list_forms(
        db: Session,
        skip: int = 0,
        limit: int = 25,
        q: Optional[str] = None,
        status: Optional[str] = None,
        business_area_ids: Optional[List[UUID]] = None,
        form_source: Optional[str] = None,
        is_public: Optional[bool] = None,
        sort_order: str = "desc",
    ) -> tuple[List[Form], int]:
        """
        List forms with filters and pagination.

        Args:
            db: Database session
            skip: Number of records to skip
            limit: Max records to return
            q: Full-text search query
            status: Filter by status (draft, pending_review, approved, published, archived)
            business_area_ids: Optional list of business area IDs (match any)
            form_source: Filter by source ('Link' or 'Download')
            is_public: Filter by public status
            sort_order: asc or desc

        Returns:
            Tuple of (list of Form objects, total count)
        """
        query = db.query(Form).filter(Form.deleted_at.is_(None))

        if q and q.strip():
            query = query.filter(text("""
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
                    """)).params(search_query=q.strip())  # noqa: E501

        # Apply filters
        if status:
            query = query.filter(Form.status == status)

        if business_area_ids:
            query = query.join(
                FormBusinessArea,
                and_(
                    FormBusinessArea.form_id == Form.id,
                    FormBusinessArea.deleted_at.is_(None),
                ),
            ).filter(FormBusinessArea.business_area_id.in_(business_area_ids))

        if form_source:
            normalized_source = "URL" if form_source.lower() == "link" else "Download"
            query = query.filter(Form.form_source == normalized_source)

        if is_public is not None:
            query = query.filter(Form.is_public == is_public)

        query = query.distinct()

        # Count total
        total = query.count()

        sort_column = Form.created_at

        if sort_order.lower() == "asc":
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(desc(sort_column))

        # Apply pagination
        forms = query.offset(skip).limit(limit).all()

        return forms, total

    @staticmethod
    def get_autocomplete_suggestions(
        db: Session,
        query_text: str,
        max_suggestions: int = 10,
    ) -> List[str]:
        """Get autocomplete suggestions from form titles and keywords."""
        normalized_query = (query_text or "").strip()
        if len(normalized_query) < 2:
            return []

        sql = text("""
            SELECT suggestion
            FROM (
                SELECT DISTINCT f.title AS suggestion
                FROM forms f
                WHERE f.deleted_at IS NULL
                  AND f.title ILIKE :pattern

                UNION

                SELECT DISTINCT
                    jsonb_array_elements_text(
                        COALESCE(f.keywords::jsonb, '[]'::jsonb)
                    ) AS suggestion
                FROM forms f
                WHERE f.deleted_at IS NULL
            ) s
            WHERE s.suggestion ILIKE :pattern
            ORDER BY s.suggestion ASC
            LIMIT :max_suggestions
            """)  # noqa: E501

        rows = db.execute(
            sql,
            {
                "pattern": f"%{normalized_query}%",
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
        # TASK-416: handle attachment field updates and MinIO deletion
        if "form_source" in kwargs:
            form.form_source = kwargs["form_source"]
        if "form_source_url" in kwargs:
            form.form_source_url = kwargs["form_source_url"]
        if "form_attachment_url" in kwargs:
            old_url = form.form_attachment_url
            new_url = kwargs["form_attachment_url"]
            # Delete the old file from MinIO whenever the URL changes (removed or replaced)
            if old_url and old_url != new_url:
                old_key = FormService._extract_minio_object_key(old_url)
                if old_key:
                    minio_service.delete_file(old_key)
            form.form_attachment_url = new_url
        if "form_attachment_filename" in kwargs:
            form.form_attachment_filename = kwargs["form_attachment_filename"]

        # Handle business area updates
        if "business_area_ids" in kwargs:
            form.business_areas.clear()
            business_area_ids = kwargs["business_area_ids"]
            if business_area_ids:
                business_areas = (
                    db.query(BusinessArea)
                    .filter(
                        BusinessArea.id.in_(business_area_ids),
                        BusinessArea.deleted_at.is_(None),
                    )
                    .all()
                )
                for ba in business_areas:
                    form_ba = FormBusinessArea(business_area=ba)
                    form.business_areas.append(form_ba)

        db.commit()
        db.refresh(form)

        # Audit log
        FormService._audit_log(
            db=db,
            entity_type="forms",
            entity_id=str(form.id),
            action="UPDATE",
            user_id=updated_by_id,
            old_values=old_values,
            new_values=kwargs,
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

        form.deleted_at = datetime.utcnow()
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
    def approve_form(db: Session, form_id: UUID, approver_id: UUID) -> Form:
        form = FormService._get_form_for_transition(db, form_id, lock=True)

        if FormService._is_separation_of_duties_enforced(db) and str(
            form.created_by_id
        ) == str(approver_id):
            raise FormWorkflowValidationError(
                "You cannot approve your own form submission."
            )

        return FormService._transition_form_status(
            db,
            form,
            action="approve",
            to_status="approved",
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
    def _extract_minio_object_key(url: str) -> Optional[str]:
        """Extract the MinIO object key from a full public URL."""
        if not url:
            return None
        prefix = f"{settings.MINIO_PUBLIC_URL}/{settings.MINIO_BUCKET}/"
        if url.startswith(prefix):
            return url[len(prefix) :]
        # Fallback: look for the 'uploads/' path segment used by all stored objects
        import re

        match = re.search(r"(uploads/[^?#]+)", url)
        return match.group(1) if match else None

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
            "business_areas": [
                {"id": str(ba.business_area.id), "name": ba.business_area.name}
                for ba in form.business_areas
                if not ba.deleted_at
            ],
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
