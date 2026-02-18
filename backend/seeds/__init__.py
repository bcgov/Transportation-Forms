"""Database seeding utilities."""
from backend.seeds.default_roles import seed_default_roles
from backend.seeds.default_business_areas import seed_default_business_areas
from backend.seeds.default_demo_user import seed_demo_user


def seed_all_defaults(db) -> None:
    """
    Run all default seeding functions.
    
    This should be called after database migrations.
    """
    seed_default_roles(db)
    seed_default_business_areas(db)
    seed_demo_user(db)