"""
Seed default roles and permissions to the database.

This script creates the 4 system roles with their associated permissions:
- admin: Full system access
- staff_manager: Form workflow and staff management
- reviewer: Form review and approval
- staff_viewer: Read-only access to published forms
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.models import Role
from backend.auth.permissions import DEFAULT_ROLES, Permission


def seed_default_roles(db: Session) -> dict:
    """
    Create default roles with their permissions.
    
    Args:
        db: Database session
        
    Returns:
        Dictionary with counts of roles created/updated
        
    Example:
        from backend.database import SessionLocal
        from backend.seeds.default_roles import seed_default_roles
        
        db = SessionLocal()
        results = seed_default_roles(db)
        print(f"Created: {results['created']}, Updated: {results['updated']}")
    """
    
    results = {
        "created": 0,
        "updated": 0,
        "failed": 0,
        "roles": [],
    }
    
    for role_name, role_config in DEFAULT_ROLES.items():
        try:
            # Check if role already exists
            existing_role = db.query(Role).filter(
                Role.name == role_name,
                Role.deleted_at.is_(None)
            ).first()
            
            if existing_role:
                # Update existing role
                existing_role.description = role_config["description"]
                existing_role.permissions = [p.value if hasattr(p, 'value') else str(p) for p in role_config["permissions"]]
                existing_role.is_system = role_config["is_system"]
                existing_role.is_active = True
                db.commit()
                results["updated"] += 1
                results["roles"].append({
                    "name": role_name,
                    "status": "updated",
                    "id": str(existing_role.id),
                })
            else:
                # Create new role
                new_role = Role(
                    name=role_name,
                    description=role_config["description"],
                    permissions=[p.value if hasattr(p, 'value') else str(p) for p in role_config["permissions"]],
                    is_system=role_config["is_system"],
                    is_active=True,
                )
                db.add(new_role)
                db.commit()
                results["created"] += 1
                results["roles"].append({
                    "name": role_name,
                    "status": "created",
                    "id": str(new_role.id),
                    "permissions_count": len(role_config["permissions"]),
                })
                
        except IntegrityError:
            db.rollback()
            results["failed"] += 1
            results["roles"].append({
                "name": role_name,
                "status": "failed",
                "error": "Integrity constraint violation",
            })
        except Exception as e:
            db.rollback()
            results["failed"] += 1
            results["roles"].append({
                "name": role_name,
                "status": "failed",
                "error": str(e),
            })
    
    return results


def get_role_by_name(db: Session, role_name: str) -> Role:
    """
    Get a role by name.
    
    Args:
        db: Database session
        role_name: Name of the role
        
    Returns:
        Role object or None
    """
    return db.query(Role).filter(
        Role.name == role_name,
        Role.is_active == True,
        Role.deleted_at.is_(None)
    ).first()


def get_all_system_roles(db: Session) -> list[Role]:
    """
    Get all system-defined roles.
    
    Args:
        db: Database session
        
    Returns:
        List of system Role objects
    """
    return db.query(Role).filter(
        Role.is_system == True,
        Role.is_active == True,
        Role.deleted_at.is_(None)
    ).all()
