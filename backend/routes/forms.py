"""Form management API endpoints.

Provides RESTful endpoints for form CRUD operations with proper validation,
error handling, and authorization checks.
"""

from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.services.forms import FormService
from backend.models import Form

# ============================================================================
# Pydantic Models (Request/Response)
# ============================================================================

class BusinessAreaRef(BaseModel):
    """Reference to a business area."""
    id: str
    name: str


class FormCreateRequest(BaseModel):
    """Request model for creating a form."""
    title: str = Field(..., min_length=1, max_length=255, description="Form title")
    description: Optional[str] = Field(None, max_length=2000, description="Form description")
    category: str = Field(..., min_length=1, max_length=100, description="Form category")
    is_public: bool = Field(default=False, description="Whether form is publicly visible")
    keywords: Optional[List[str]] = Field(default=None, description="Search keywords")
    business_area_ids: Optional[List[str]] = Field(default=None, description="Associated business area IDs")
    effective_date: Optional[datetime] = Field(None, description="When form becomes effective")


class FormUpdateRequest(BaseModel):
    """Request model for updating a form."""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    is_public: Optional[bool] = None
    keywords: Optional[List[str]] = None
    business_area_ids: Optional[List[str]] = None
    effective_date: Optional[datetime] = None


class FormResponse(BaseModel):
    """Response model for form details."""
    id: str
    title: str
    description: Optional[str]
    category: str
    status: str
    is_public: bool
    current_version: int
    keywords: List[str]
    business_areas: List[BusinessAreaRef]
    created_by: Dict[str, str]
    effective_date: Optional[str]
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


class FormListResponse(BaseModel):
    """Response model for form list."""
    total: int
    skip: int
    limit: int
    items: List[FormResponse]


class FormListItem(BaseModel):
    """List item for form summaries."""
    id: str
    title: str
    category: str
    status: str
    is_public: bool
    created_at: str
    updated_at: str


# ============================================================================
# Router Setup
# ============================================================================

router = APIRouter(
    prefix="/forms",
    tags=["Forms"],
    responses={
        404: {"description": "Form not found"},
        422: {"description": "Validation error"},
    }
)


# ============================================================================
# CRUD ENDPOINTS
# ============================================================================

@router.post("", response_model=FormResponse, status_code=status.HTTP_201_CREATED)
async def create_form(
    request: FormCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormResponse:
    """
    Create a new form.
    
    - **title**: Form title (required, 1-255 chars)
    - **description**: Optional form description
    - **category**: Form category (required)
    - **is_public**: Whether form is publicly visible
    - **keywords**: List of search keywords
    - **business_area_ids**: Associated business areas
    - **effective_date**: When form becomes effective
    """
    try:
        # Convert string UUIDs to UUID objects
        business_area_ids = None
        if request.business_area_ids:
            business_area_ids = [UUID(ba_id) for ba_id in request.business_area_ids]
        
        form = FormService.create_form(
            db=db,
            title=request.title,
            description=request.description,
            category=request.category,
            is_public=request.is_public,
            keywords=request.keywords,
            business_area_ids=business_area_ids,
            created_by_id=UUID(current_user.sub),
            effective_date=request.effective_date,
        )
        
        return FormResponse(**FormService.get_form_with_details(db, form.id))
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create form"
        )


@router.get("/{form_id}", response_model=FormResponse)
async def get_form(
    form_id: str,
    db: Session = Depends(get_db),
) -> FormResponse:
    """Get a form by ID."""
    try:
        form_uuid = UUID(form_id)
        form_data = FormService.get_form_with_details(db, form_uuid)
        
        if not form_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Form not found"
            )
        
        return FormResponse(**form_data)
    
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid form ID format"
        )


@router.put("/{form_id}", response_model=FormResponse)
async def update_form(
    form_id: str,
    request: FormUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormResponse:
    """
    Update a form (all fields except status and version).
    
    Provide only the fields you want to update.
    """
    try:
        form_uuid = UUID(form_id)
        
        # Build update kwargs
        update_data = {}
        if request.title is not None:
            update_data["title"] = request.title
        if request.description is not None:
            update_data["description"] = request.description
        if request.category is not None:
            update_data["category"] = request.category
        if request.is_public is not None:
            update_data["is_public"] = request.is_public
        if request.keywords is not None:
            update_data["keywords"] = request.keywords
        if request.effective_date is not None:
            update_data["effective_date"] = request.effective_date
        if request.business_area_ids is not None:
            update_data["business_area_ids"] = [UUID(ba_id) for ba_id in request.business_area_ids]
        
        form = FormService.update_form(
            db=db,
            form_id=form_uuid,
            updated_by_id=UUID(current_user.sub),
            **update_data
        )
        
        if not form:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Form not found"
            )
        
        return FormResponse(**FormService.get_form_with_details(db, form.id))
    
    except ValueError as e:
        if "invalid literal" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid form ID or business area ID format"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Soft delete a form (sets deleted_at timestamp).
    
    The form will no longer appear in list operations but the data is preserved.
    """
    try:
        form_uuid = UUID(form_id)
        deleted = FormService.delete_form(
            db=db,
            form_id=form_uuid,
            deleted_by_id=UUID(current_user.sub)
        )
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Form not found"
            )
    
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid form ID format"
        )


@router.get("", response_model=FormListResponse)
async def list_forms(
    skip: int = Query(0, ge=0, description="Number of forms to skip"),
    limit: int = Query(20, ge=1, le=100, description="Number of forms to return (max 100)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status"),
    is_public: Optional[bool] = Query(None, description="Filter by public status"),
    sort_by: str = Query("created_at", regex="^(created_at|updated_at|title)$", description="Sort field"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    db: Session = Depends(get_db),
) -> FormListResponse:
    """
    List forms with filtering, pagination, and sorting.
    
    - **skip**: Number of forms to skip (for pagination)
    - **limit**: Max forms to return (1-100, default 20)
    - **category**: Filter by category
    - **status**: Filter by status (draft, pending_review, approved, published, archived)
    - **is_public**: Filter by public/private status
    - **sort_by**: Sort by created_at, updated_at, or title
    - **sort_order**: Sort ascending (asc) or descending (desc)
    """
    forms, total = FormService.list_forms(
        db=db,
        skip=skip,
        limit=limit,
        category=category,
        status=status,
        is_public=is_public,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    
    items = [
        FormResponse(**FormService.get_form_with_details(db, form.id))
        for form in forms
    ]
    
    return FormListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items,
    )


# ============================================================================
# ARCHIVE & UNARCHIVE ENDPOINTS
# ============================================================================

@router.post("/{form_id}/archive", response_model=FormResponse)
async def archive_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormResponse:
    """Archive a form (mark as archived)."""
    try:
        form_uuid = UUID(form_id)
        form = FormService.archive_form(
            db=db,
            form_id=form_uuid,
            archived_by_id=UUID(current_user.sub)
        )
        
        if not form:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Form not found"
            )
        
        return FormResponse(**FormService.get_form_with_details(db, form.id))
    
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid form ID format"
        )


@router.post("/{form_id}/unarchive", response_model=FormResponse)
async def unarchive_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormResponse:
    """Unarchive a form (restore from archived status)."""
    try:
        form_uuid = UUID(form_id)
        form = FormService.unarchive_form(
            db=db,
            form_id=form_uuid,
            unarchived_by_id=UUID(current_user.sub)
        )
        
        if not form:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Form not found or not in archived status"
            )
        
        return FormResponse(**FormService.get_form_with_details(db, form.id))
    
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid form ID format"
        )
