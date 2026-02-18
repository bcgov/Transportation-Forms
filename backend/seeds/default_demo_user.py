"""Seed demo user for development mode."""

from uuid import UUID
from sqlalchemy.orm import Session
from backend.models import User, UserRole, Role


DEMO_USER_ID = "550e8400-e29b-41d4-a716-446655440000"


def seed_demo_user(db: Session) -> None:
    """
    Seed a demo user for development/testing.
    
    This user is used when the application is in development mode
    and a "demo-token" is used for authentication.
    """
    # Check if demo user already exists
    existing = db.query(User).filter_by(id=UUID(DEMO_USER_ID)).first()
    
    if not existing:
        # Create demo user
        demo_user = User(
            id=UUID(DEMO_USER_ID),
            keycloak_id=DEMO_USER_ID,  # Use same UUID for Keycloak ID
            email="demo@example.com",
            first_name="Demo",
            last_name="User",
            is_active=True,
        )
        db.add(demo_user)
        db.flush()
        
        # Assign admin role
        admin_role = db.query(Role).filter_by(name="admin").first()
        if admin_role:
            user_role = UserRole(
                user_id=demo_user.id,
                role_id=admin_role.id
            )
            db.add(user_role)
        
        db.commit()
        print("✓ Demo user seeded successfully")
    else:
        print("ℹ Demo user already exists")
