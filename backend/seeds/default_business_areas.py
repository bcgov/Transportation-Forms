"""Seed script to create default business areas."""

from uuid import UUID
from sqlalchemy.orm import Session
from backend.models import BusinessArea


# Predefined business area UUIDs (stable across runs)
BUSINESS_AREAS = [
    {
        "id": "550e8400-e29b-41d4-a716-446655440001",
        "name": "Licensing",
        "description": "Business licensing and permits",
        "sort_order": 1,
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440002",
        "name": "Permits",
        "description": "Transportation permits and approvals",
        "sort_order": 2,
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440003",
        "name": "Applications",
        "description": "General applications and submissions",
        "sort_order": 3,
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440004",
        "name": "Compliance",
        "description": "Compliance and regulatory forms",
        "sort_order": 4,
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440005",
        "name": "Reporting",
        "description": "Reporting and documentation",
        "sort_order": 5,
    },
]


def seed_default_business_areas(db: Session) -> None:
    """
    Seed database with default business areas.
    
    Only creates business areas that don't already exist.
    """
    for ba_data in BUSINESS_AREAS:
        # Check if business area already exists
        existing = db.query(BusinessArea).filter_by(
            id=UUID(ba_data["id"])
        ).first()
        
        if not existing:
            business_area = BusinessArea(
                id=UUID(ba_data["id"]),
                name=ba_data["name"],
                description=ba_data["description"],
                sort_order=ba_data["sort_order"],
                is_active=True,
            )
            db.add(business_area)
    
    db.commit()
    print("✓ Default business areas seeded successfully")
