"""
Seed default roles and permissions to the database.

This script creates the two system roles with their associated permissions:
- admin: Full system access
- staff_viewer: Read-only access to published forms
"""

from backend.auth.permissions import DEFAULT_ROLES
from backend.models import Role
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class _InvalidDefaultRoleState(Exception):
    pass


def _is_valid_default_role(role: Role) -> bool:
    return bool(role.is_system) and bool(role.is_active)


def _rollback(db: Session) -> bool:
    try:
        db.rollback()
    except Exception:
        return False
    return True


def seed_default_roles(db: Session) -> dict:
    """
    Create missing default roles without changing existing role configuration.

    Args:
        db: Database session

    Returns:
        Dictionary with counts of roles created, found, or failed

    Example:
        from backend.database import SessionLocal
        from backend.seeds.default_roles import seed_default_roles

        db = SessionLocal()
        results = seed_default_roles(db)
        print(
            f"Created: {results['created']}, "
            f"Existing: {results['existing']}"
        )
    """

    for attempt in range(2):
        try:
            existing_roles = {}
            missing_roles = []

            for role_name, role_config in DEFAULT_ROLES.items():
                existing_role = (
                    db.query(Role)
                    .filter(
                        Role.name == role_name,
                        Role.deleted_at.is_(None),
                    )
                    .first()
                )

                if existing_role:
                    if not _is_valid_default_role(existing_role):
                        raise _InvalidDefaultRoleState
                    existing_roles[role_name] = existing_role
                else:
                    missing_roles.append((role_name, role_config))

            created_roles = []
            for role_name, role_config in missing_roles:
                new_role = Role(
                    name=role_name,
                    description=role_config["description"],
                    permissions=[
                        p.value if hasattr(p, "value") else str(p)
                        for p in role_config["permissions"]
                    ],
                    is_system=role_config["is_system"],
                    is_active=True,
                )
                db.add(new_role)

                created_roles.append((role_name, role_config, new_role))

            if created_roles:
                db.commit()

            results = {
                "created": len(created_roles),
                "updated": 0,
                "existing": len(existing_roles),
                "failed": 0,
                "roles": [
                    {
                        "name": role_name,
                        "status": "existing",
                        "id": str(role.id),
                    }
                    for role_name, role in existing_roles.items()
                ]
                + [
                    {
                        "name": role_name,
                        "status": "created",
                        "id": str(new_role.id),
                        "permissions_count": len(role_config["permissions"]),
                    }
                    for role_name, role_config, new_role in created_roles
                ],
            }
            return results

        except IntegrityError:
            rollback_succeeded = _rollback(db)
            if rollback_succeeded and attempt == 0:
                continue
            raise RuntimeError("Default role seeding failed") from None
        except _InvalidDefaultRoleState:
            raise RuntimeError("Default role seeding failed") from None
        except Exception:
            _rollback(db)
            raise RuntimeError("Default role seeding failed") from None

    raise RuntimeError("Default role seeding failed")


# Alias for backward compatibility
seed_roles = seed_default_roles


def get_role_by_name(db: Session, role_name: str) -> Role:
    """
    Get a role by name.

    Args:
        db: Database session
        role_name: Name of the role

    Returns:
        Role object or None
    """
    return (
        db.query(Role)
        .filter(
            Role.name == role_name,
            Role.is_active.is_(True),
            Role.deleted_at.is_(None),
        )
        .first()
    )


def get_all_system_roles(db: Session) -> list[Role]:
    """
    Get all system-defined roles.

    Args:
        db: Database session

    Returns:
        List of system Role objects
    """
    return (
        db.query(Role)
        .filter(
            Role.is_system.is_(True),
            Role.is_active.is_(True),
            Role.deleted_at.is_(None),
        )
        .all()
    )
