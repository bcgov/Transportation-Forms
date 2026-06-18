"""Seed script to create default business areas."""

from uuid import UUID
from sqlalchemy.orm import Session
from backend.models import BusinessArea

# Predefined business area UUIDs (stable across runs)
BUSINESS_AREAS = [
    {
        "id": "550e8400-e29b-41d4-a716-446655440001",
        "name": "Licensing",
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440002",
        "name": "Permits",
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440003",
        "name": "Applications",
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440004",
        "name": "Compliance",
    },
    {
        "id": "550e8400-e29b-41d4-a716-446655440005",
        "name": "Reporting",
    },
]


def seed_default_business_areas(db: Session) -> None:
    """
    Seed database with default business areas.

    Idempotent: only inserts a row when neither the canonical ``id`` nor the
    ``name`` already exists. The ``business_areas.name`` column has a unique
    index, so we must check by name as well as by id — otherwise a second
    deploy that follows admin-driven CRUD (where an operator may have created
    the same name under a different ``id``) would crash with a
    ``UniqueViolation`` on insert.
    """
    for ba_data in BUSINESS_AREAS:
        target_id = UUID(ba_data["id"])
        target_name = ba_data["name"]

        # Skip if a row already exists with either the canonical id or the
        # canonical name (active or soft-deleted). We deliberately do NOT
        # mutate an existing row here — admin-managed Business Areas are the
        # source of truth once the system is live; the seed only fills gaps
        # on a fresh install.
        existing = (
            db.query(BusinessArea)
            .filter(
                (BusinessArea.id == target_id) | (BusinessArea.name == target_name)
            )
            .first()
        )

        if existing is None:
            db.add(
                BusinessArea(
                    id=target_id,
                    name=target_name,
                )
            )

    db.commit()
    print("✓ Default business areas seeded successfully")


# Alias for backward compatibility
seed_business_areas = seed_default_business_areas
