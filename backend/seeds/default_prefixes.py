"""Seed script to create default form number prefixes (TASK-401)."""

from uuid import UUID
from sqlalchemy.orm import Session
from backend.models import FormNumberPrefix


# Predefined prefix UUIDs (stable across runs)
FORM_NUMBER_PREFIXES = [
    {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "prefix": "H",
        "description": "Highway forms",
        "current_sequence": 0,
        "padding_length": 4,
        "max_number_length": 10,
    },
    {
        "id": "660e8400-e29b-41d4-a716-446655440002",
        "prefix": "CVSE",
        "description": "Commercial Vehicle Safety and Enforcement forms",
        "current_sequence": 0,
        "padding_length": 4,
        "max_number_length": 10,
    },
    {
        "id": "660e8400-e29b-41d4-a716-446655440003",
        "prefix": "INS",
        "description": "Insurance forms",
        "current_sequence": 0,
        "padding_length": 4,
        "max_number_length": 10,
    },
    {
        "id": "660e8400-e29b-41d4-a716-446655440004",
        "prefix": "T",
        "description": "Transportation general forms",
        "current_sequence": 0,
        "padding_length": 4,
        "max_number_length": 10,
    },
    {
        "id": "660e8400-e29b-41d4-a716-446655440005",
        "prefix": "MV",
        "description": "Motor vehicle forms",
        "current_sequence": 0,
        "padding_length": 4,
        "max_number_length": 10,
    },
]


def seed_default_prefixes(db: Session) -> None:
    """
    Seed database with default form number prefixes.

    Only creates prefixes that don't already exist (idempotent).
    Prefixes are stored uppercase by convention.
    """
    for pfx_data in FORM_NUMBER_PREFIXES:
        existing = db.query(FormNumberPrefix).filter_by(
            id=UUID(pfx_data["id"])
        ).first()

        if not existing:
            prefix = FormNumberPrefix(
                id=UUID(pfx_data["id"]),
                prefix=pfx_data["prefix"].upper(),
                description=pfx_data["description"],
                current_sequence=pfx_data["current_sequence"],
                padding_length=pfx_data["padding_length"],
                max_number_length=pfx_data["max_number_length"],
                is_case_sensitive=False,
                is_active=True,
            )
            db.add(prefix)

    db.commit()
    print("✓ Default form number prefixes seeded successfully")
