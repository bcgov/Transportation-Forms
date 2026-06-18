"""Business Areas Admin API endpoints.

Admin endpoints for managing business areas and their contacts.
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import BusinessArea, BusinessAreaContact, Form
from backend.auth.authorization import require_permission
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData

router = APIRouter(
    prefix="/admin/business-areas",
    tags=["Admin Business Areas"],
)

# ============================================================================
# Pydantic Models
# ============================================================================

class BusinessAreaContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    contact_user_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None

class BusinessAreaAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    mailbox: Optional[str] = None
    contact_count: int
    linked_forms_count: int

class BusinessAreaCreateRequest(BaseModel):
    name: str = Field(..., max_length=75, pattern=r"^[A-Za-z0-9 \-&\(\).\/\']+$")
    mailbox: Optional[str] = Field(None, max_length=75, pattern=r"^[^@]+@[^@]+\.[^@]+$")

class BusinessAreaUpdateRequest(BaseModel):
    name: str = Field(..., max_length=75, pattern=r"^[A-Za-z0-9 \-&\(\).\/\']+$")
    mailbox: Optional[str] = Field(None, max_length=75, pattern=r"^[^@]+@[^@]+\.[^@]+$")

class BusinessAreaContactAddRequest(BaseModel):
    contact_user_id: Optional[UUID] = None
    name: Optional[str] = Field(None, max_length=150)
    email: Optional[str] = Field(None, max_length=75, pattern=r"^[^@]+@[^@]+\.[^@]+$")

class LinkedFormResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    form_number: str
    title: str
    status: str

# ============================================================================
# Routes
# ============================================================================

@router.get("", response_model=List[BusinessAreaAdminResponse])
async def list_admin_business_areas(
    db: Session = Depends(get_db),
    _=Depends(require_permission("business_areas", "manage")),
):
    """List business areas for admin view."""
    areas = db.query(BusinessArea).filter(BusinessArea.deleted_at.is_(None)).order_by(BusinessArea.name).all()
    results = []
    for area in areas:
        results.append(
            BusinessAreaAdminResponse(
                id=str(area.id),
                name=area.name,
                mailbox=area.mailbox,
                contact_count=len(area.contacts),
                linked_forms_count=len(area.forms),
            )
        )
    return results

@router.post("", response_model=BusinessAreaAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_business_area(
    req: BusinessAreaCreateRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    _=Depends(require_permission("business_areas", "create")),
):
    """Create a new business area."""
    # Check if exists active
    existing = db.query(BusinessArea).filter(BusinessArea.name == req.name).first()
    if existing:
        if existing.deleted_at:
            # AC3: Surface a structured payload so the client can offer to
            # restore the soft-deleted record. ``existing_id`` is the only
            # identifier the client needs to call the restore endpoint; we
            # deliberately do not echo any other attributes of the deleted
            # record back to an unauthenticated/unauthorised caller (the
            # ``business_areas:create`` permission is already enforced above).
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "soft_deleted_collision",
                    "message": (
                        "A deleted Business Area with this name already "
                        "exists. Would you like to restore it instead?"
                    ),
                    "existing_id": str(existing.id),
                },
            )
        raise HTTPException(status_code=400, detail="Name already exists")
    
    new_area = BusinessArea(name=req.name, mailbox=req.mailbox)
    db.add(new_area)
    db.commit()
    db.refresh(new_area)
    return BusinessAreaAdminResponse(
        id=str(new_area.id),
        name=new_area.name,
        mailbox=new_area.mailbox,
        contact_count=0,
        linked_forms_count=0
    )

@router.post(
    "/{area_id}/restore",
    response_model=BusinessAreaAdminResponse,
    status_code=status.HTTP_200_OK,
)
async def restore_business_area(
    area_id: UUID,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    _=Depends(require_permission("business_areas", "create")),
):
    """Restore a previously soft-deleted business area (FEAT-0025 AC3).

    Returns the restored business area in the same shape as the list/create
    endpoints so the client can navigate straight to the detail view.
    """
    from backend.services.business_areas_admin_service import BusinessAreaAdminService
    try:
        area = BusinessAreaAdminService.restore_business_area(
            db, str(area_id), current_user
        )
    except ValueError as exc:
        message = str(exc)
        if message == "Business Area not found":
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)

    return BusinessAreaAdminResponse(
        id=str(area.id),
        name=area.name,
        mailbox=area.mailbox,
        contact_count=len(area.contacts),
        linked_forms_count=len(area.forms),
    )

@router.put("/{area_id}", response_model=BusinessAreaAdminResponse)
async def update_business_area(
    area_id: UUID,
    req: BusinessAreaUpdateRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    _=Depends(require_permission("business_areas", "update")),
):
    area = db.query(BusinessArea).filter(BusinessArea.id == area_id).first()
    if not area or area.deleted_at:
        raise HTTPException(status_code=404, detail="Business Area not found")
    
    if area.name != req.name:
        existing = db.query(BusinessArea).filter(BusinessArea.name == req.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Name already exists")
    
    area.name = req.name
    area.mailbox = req.mailbox
    db.commit()
    db.refresh(area)
    
    return BusinessAreaAdminResponse(
        id=str(area.id),
        name=area.name,
        mailbox=area.mailbox,
        contact_count=len(area.contacts),
        linked_forms_count=len(area.forms),
    )

@router.delete("/{area_id}")
async def delete_business_area(
    area_id: UUID,
    replacement_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    _=Depends(require_permission("business_areas", "delete")),
):
    from backend.services.business_areas_admin_service import BusinessAreaAdminService
    try:
        result = BusinessAreaAdminService.delete_business_area(db, str(area_id), current_user, str(replacement_id) if replacement_id else None)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{area_id}/forms", response_model=List[LinkedFormResponse])
async def list_linked_forms(
    area_id: UUID,
    db: Session = Depends(get_db),
    _=Depends(require_permission("business_areas", "manage")),
):
    forms = db.query(Form).filter(Form.business_area_id == area_id).all()
    return [
        LinkedFormResponse(
            id=str(f.id),
            form_number=f.form_number_reservation.full_form_number if f.form_number_reservation else str(f.id),
            title=f.title,
            status=f.status
        ) for f in forms
    ]

@router.get("/{area_id}/contacts", response_model=List[BusinessAreaContactResponse])
async def list_contacts(
    area_id: UUID,
    db: Session = Depends(get_db),
    _=Depends(require_permission("business_areas", "manage")),
):
    contacts = db.query(BusinessAreaContact).filter(BusinessAreaContact.business_area_id == area_id).all()
    return [
        BusinessAreaContactResponse(
            id=str(c.id),
            contact_user_id=str(c.contact_user_id) if c.contact_user_id else None,
            name=c.name,
            email=c.email
        ) for c in contacts
    ]

@router.post("/{area_id}/contacts", response_model=BusinessAreaContactResponse, status_code=status.HTTP_201_CREATED)
async def add_contact(
    area_id: UUID,
    req: BusinessAreaContactAddRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    _=Depends(require_permission("business_areas", "update")),
):
    if req.contact_user_id:
        existing = db.query(BusinessAreaContact).filter(
            BusinessAreaContact.business_area_id == area_id,
            BusinessAreaContact.contact_user_id == req.contact_user_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Contact already exists")
    else:
        if not req.name or not req.email:
            raise HTTPException(status_code=400, detail="Name and email are required for free-form contact")
        existing = db.query(BusinessAreaContact).filter(
            BusinessAreaContact.business_area_id == area_id,
            BusinessAreaContact.email == req.email
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Contact already exists")

    new_contact = BusinessAreaContact(
        business_area_id=area_id,
        contact_user_id=req.contact_user_id,
        name=req.name if not req.contact_user_id else None,
        email=req.email if not req.contact_user_id else None
    )
    db.add(new_contact)
    db.commit()
    db.refresh(new_contact)
    return BusinessAreaContactResponse(
        id=str(new_contact.id),
        contact_user_id=str(new_contact.contact_user_id) if new_contact.contact_user_id else None,
        name=new_contact.name,
        email=new_contact.email
    )

@router.delete("/{area_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_contact(
    area_id: UUID,
    contact_id: UUID,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    _=Depends(require_permission("business_areas", "update")),
):
    contact = db.query(BusinessAreaContact).filter(
        BusinessAreaContact.id == contact_id,
        BusinessAreaContact.business_area_id == area_id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    db.delete(contact)
    db.commit()
    return None