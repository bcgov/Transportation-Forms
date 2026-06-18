"""Business Areas API endpoints.

Read-only endpoints for listing active business areas.
Business area CRUD management is handled in a future admin task
(SPECIFICATION.md FR-ADMIN-014 through FR-ADMIN-018).
"""

from typing import List
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import BusinessArea

# ============================================================================
# Pydantic Models
# ============================================================================


class BusinessAreaResponse(BaseModel):
    """Response model for a single business area."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str

# ============================================================================
# Router
# ============================================================================

router = APIRouter(
    prefix="/business-areas",
    tags=["Business Areas"],
)


@router.get("", response_model=List[BusinessAreaResponse])
async def list_business_areas(
    db: Session = Depends(get_db),
) -> List[BusinessAreaResponse]:
    """
    List all active business areas (sorted by display order, then name).

    Used by the form create/edit UI to populate the business area
    multi-select list.  The list is read-only; management of business areas
    is reserved for a future admin panel feature.
    """
    areas = (
        db.query(BusinessArea)
        .filter(
            BusinessArea.deleted_at.is_(None),
        )
        .order_by(BusinessArea.name)
        .all()
    )

    return [
        BusinessAreaResponse(
            id=str(area.id),
            name=area.name,
        )
        for area in areas
    ]
