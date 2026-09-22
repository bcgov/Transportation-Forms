"""Database seeding utilities."""

from backend.seeds.default_roles import seed_default_roles
from backend.seeds.default_demo_user import seed_demo_user


def seed_all_defaults(db) -> None:
    """
    Run all default seeding functions.

    This should be called after database migrations.
    """
    role_seed_result = seed_default_roles(db)
    if role_seed_result["failed"]:
        raise RuntimeError("Default role seeding failed")
    seed_demo_user(db)
