"""Seed the initial admin user for fresh deployments.

Reads INITIAL_ADMIN_EMAIL from the environment.  Idempotent — no-op if the
user already exists with the admin role already assigned.  Called from the
migrations init container entrypoint when INITIAL_ADMIN_EMAIL is set.
"""

import os

from sqlalchemy.orm import Session

from backend.models import User, UserRole, Role
from backend.database import SessionLocal


def seed_initial_admin(db: Session, email: str) -> None:
    """Create the initial admin user and assign the admin role.

    Safe to call on every deployment — checks for existing records before
    inserting and never overwrites data.
    """
    existing = (
        db.query(User).filter(User.email == email, User.deleted_at.is_(None)).first()
    )

    admin_role = (
        db.query(Role).filter(Role.name == "admin", Role.deleted_at.is_(None)).first()
    )

    if not admin_role:
        print("WARNING: admin role not found — run default role seeds first")
        return

    if existing:
        # User exists — ensure they have the admin role (idempotent)
        has_admin = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == existing.id,
                UserRole.role_id == admin_role.id,
                UserRole.deleted_at.is_(None),
            )
            .first()
        )
        if not has_admin:
            db.add(UserRole(user_id=existing.id, role_id=admin_role.id))
            db.commit()
            print(f"Admin role assigned to existing user {email!r}")
        else:
            print(
                f"Initial admin {email!r} already exists with admin role — no changes needed"
            )
        return

    user = User(
        email=email,
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=admin_role.id))
    db.commit()
    print(f"Initial admin {email!r} seeded successfully")


if __name__ == "__main__":
    email = os.environ.get("INITIAL_ADMIN_EMAIL", "").strip()
    if not email:
        raise SystemExit("INITIAL_ADMIN_EMAIL is not set — skipping admin seed")
    db = SessionLocal()
    try:
        seed_initial_admin(db, email)
    finally:
        db.close()
