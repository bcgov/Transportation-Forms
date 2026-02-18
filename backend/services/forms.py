"""Form management service - CRUD operations for forms.

Provides business logic for creating, reading, updating, deleting, and managing forms.
Includes audit logging, soft deletes, and version management.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc, func

from backend.models import (
    Form, FormBusinessArea, FormVersion, FormWorkflow, 
    BusinessArea, User, AuditLog
)


class FormService:
    """Service class for form management operations."""
    
    # =====================================================================
    # CREATE OPERATIONS
    # =====================================================================
    
    @staticmethod
    def create_form(
        db: Session,
        title: str,
        description: Optional[str],
        category: str,
        is_public: bool,
        keywords: Optional[List[str]],
        business_area_ids: Optional[List[UUID]],
        created_by_id: UUID,
        effective_date: Optional[datetime] = None,
    ) -> Form:
        """
        Create a new form.
        
        Args:
            db: Database session
            title: Form title
            description: Form description
            category: Form category
            is_public: Whether form is publicly visible
            keywords: List of search keywords
            business_area_ids: List of associated business area IDs
            created_by_id: UUID of user creating the form
            effective_date: When the form becomes effective
            
        Returns:
            Created Form object
            
        Raises:
            ValueError: If business areas don't exist
        """
        # Create the form
        form = Form(
            title=title,
            description=description,
            category=category,
            is_public=is_public,
            keywords=keywords or [],
            created_by_id=created_by_id,
            effective_date=effective_date,
            status='draft',
            current_version=0,
        )
        
        # Associate business areas
        if business_area_ids:
            business_areas = db.query(BusinessArea).filter(
                BusinessArea.id.in_(business_area_ids),
                BusinessArea.deleted_at.is_(None)
            ).all()
            
            if len(business_areas) != len(business_area_ids):
                raise ValueError("One or more business areas do not exist")
            
            for ba in business_areas:
                form_ba = FormBusinessArea(business_area=ba)
                form.business_areas.append(form_ba)
        
        db.add(form)
        db.commit()
        db.refresh(form)
        
        # Audit log
        FormService._audit_log(
            db=db,
            entity_type="forms",
            entity_id=str(form.id),
            action="CREATE",
            user_id=created_by_id,
            new_values={
                "id": str(form.id),
                "title": title,
                "category": category,
                "is_public": is_public,
            }
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
        return db.query(Form).filter(
            Form.id == form_id,
            Form.deleted_at.is_(None)
        ).first()
    
    @staticmethod
    def list_forms(
        db: Session,
        skip: int = 0,
        limit: int = 20,
        category: Optional[str] = None,
        status: Optional[str] = None,
        is_public: Optional[bool] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[List[Form], int]:
        """
        List forms with filters and pagination.
        
        Args:
            db: Database session
            skip: Number of records to skip
            limit: Max records to return (max 100)
            category: Filter by category
            status: Filter by status (draft, pending_review, approved, published, archived)
            is_public: Filter by public status
            sort_by: Field to sort by (created_at, updated_at, title)
            sort_order: asc or desc
            
        Returns:
            Tuple of (list of Form objects, total count)
        """
        query = db.query(Form).filter(Form.deleted_at.is_(None))
        
        # Apply filters
        if category:
            query = query.filter(Form.category == category)
        if status:
            query = query.filter(Form.status == status)
        if is_public is not None:
            query = query.filter(Form.is_public == is_public)
        
        # Count total
        total = query.count()
        
        # Apply sorting
        if sort_by == "title":
            sort_column = Form.title
        elif sort_by == "updated_at":
            sort_column = Form.updated_at
        else:
            sort_column = Form.created_at
        
        if sort_order.lower() == "asc":
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(desc(sort_column))
        
        # Apply pagination
        limit = min(limit, 100)  # Max 100 per request
        forms = query.offset(skip).limit(limit).all()
        
        return forms, total
    
    # =====================================================================
    # UPDATE OPERATIONS
    # =====================================================================
    
    @staticmethod
    def update_form(
        db: Session,
        form_id: UUID,
        updated_by_id: UUID,
        **kwargs
    ) -> Optional[Form]:
        """
        Update a form (all fields except status/version).
        
        Args:
            db: Database session
            form_id: Form UUID to update
            updated_by_id: UUID of user performing update
            **kwargs: Fields to update (title, description, category, is_public, 
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
            "category": form.category,
            "is_public": form.is_public,
            "keywords": form.keywords,
        }
        
        # Update fields
        if "title" in kwargs:
            form.title = kwargs["title"]
        if "description" in kwargs:
            form.description = kwargs["description"]
        if "category" in kwargs:
            form.category = kwargs["category"]
        if "is_public" in kwargs:
            form.is_public = kwargs["is_public"]
        if "keywords" in kwargs:
            form.keywords = kwargs["keywords"]
        if "effective_date" in kwargs:
            form.effective_date = kwargs["effective_date"]
        
        # Handle business area updates
        if "business_area_ids" in kwargs:
            form.business_areas.clear()
            business_area_ids = kwargs["business_area_ids"]
            if business_area_ids:
                business_areas = db.query(BusinessArea).filter(
                    BusinessArea.id.in_(business_area_ids),
                    BusinessArea.deleted_at.is_(None)
                ).all()
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
            new_values=kwargs
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
            new_values={"deleted_at": form.deleted_at.isoformat()}
        )
        
        return True
    
    @staticmethod
    def archive_form(db: Session, form_id: UUID, archived_by_id: UUID) -> Optional[Form]:
        """
        Archive a form (change status to archived).
        
        Args:
            db: Database session
            form_id: Form UUID to archive
            archived_by_id: UUID of user archiving form
            
        Returns:
            Archived Form object or None if not found
        """
        form = FormService.get_form_by_id(db, form_id)
        if not form:
            return None
        
        old_status = form.status
        form.status = 'archived'
        db.commit()
        db.refresh(form)
        
        # Log workflow change
        workflow = FormWorkflow(
            form_id=form.id,
            action='archive',
            from_status=old_status,
            to_status='archived',
            triggered_by_id=archived_by_id,
        )
        db.add(workflow)
        db.commit()
        
        # Audit log
        FormService._audit_log(
            db=db,
            entity_type="forms",
            entity_id=str(form.id),
            action="UPDATE",
            user_id=archived_by_id,
            old_values={"status": old_status},
            new_values={"status": "archived"}
        )
        
        return form
    
    @staticmethod
    def unarchive_form(db: Session, form_id: UUID, unarchived_by_id: UUID) -> Optional[Form]:
        """
        Unarchive a form (change status back to published).
        
        Args:
            db: Database session
            form_id: Form UUID to unarchive
            unarchived_by_id: UUID of user unarchiving form
            
        Returns:
            Unarchived Form object or None if not found
        """
        form = FormService.get_form_by_id(db, form_id)
        if not form or form.status != 'archived':
            return None
        
        old_status = form.status
        form.status = 'published'
        db.commit()
        db.refresh(form)
        
        # Log workflow change
        workflow = FormWorkflow(
            form_id=form.id,
            action='unarchive',
            from_status=old_status,
            to_status='published',
            triggered_by_id=unarchived_by_id,
        )
        db.add(workflow)
        db.commit()
        
        # Audit log
        FormService._audit_log(
            db=db,
            entity_type="forms",
            entity_id=str(form.id),
            action="UPDATE",
            user_id=unarchived_by_id,
            old_values={"status": old_status},
            new_values={"status": "published"}
        )
        
        return form
    
    # =====================================================================
    # HELPER METHODS
    # =====================================================================
    
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
        
        return {
            "id": str(form.id),
            "title": form.title,
            "description": form.description,
            "category": form.category,
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
                "email": form.created_by.email
            },
            "effective_date": form.effective_date.isoformat() if form.effective_date else None,
            "created_at": form.created_at.isoformat(),
            "updated_at": form.updated_at.isoformat(),
        }
