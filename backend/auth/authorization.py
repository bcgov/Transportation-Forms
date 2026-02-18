"""
Authorization module for role-based access control (RBAC).

This module provides:
1. has_permission(user, resource, action) - Check if user has permission
2. @require_permission(resource, action) - FastAPI dependency decorator
3. Permission inheritance logic
4. Audit logging for permission checks
"""

from typing import Optional, List, Set, Callable, Any
from functools import wraps
from datetime import datetime

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import (
    Permission,
    DEFAULT_ROLES,
    get_inherited_permissions,
    get_permission_for_resource_action,
    RESOURCE_ACTION_PERMISSIONS,
)
from backend.models import User, Role, UserRole, AuditLog


# Lazy import to avoid circular dependency
def _get_current_user():
    """Lazy load get_current_user to avoid circular imports."""
    from backend.auth.dependencies import get_current_user
    return get_current_user# ============================================================================
# PERMISSION CHECKING FUNCTIONS
# ============================================================================

async def get_user_permissions(user_id: str, db: Session) -> Set[str]:
    """
    Get all permissions for a user including inherited permissions.
    
    Args:
        user_id: UUID of the user
        db: Database session
        
    Returns:
        Set of permission strings the user has
    """
    # Get user with roles
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return set()
    
    # Collect all permissions from all roles
    all_permissions = set()
    user_roles = db.query(UserRole).filter(
        UserRole.user_id == user_id,
        UserRole.deleted_at.is_(None)
    ).all()
    
    for user_role in user_roles:
        role = user_role.role
        if role and role.is_active and not role.deleted_at:
            if isinstance(role.permissions, list):
                all_permissions.update(role.permissions)
            elif isinstance(role.permissions, dict):
                all_permissions.update(role.permissions.keys())
    
    # Apply inheritance rules
    inherited = get_inherited_permissions(list(all_permissions))
    
    return inherited


async def has_permission(
    user_id: str,
    permission: str,
    db: Session
) -> bool:
    """
    Check if a user has a specific permission.
    
    Args:
        user_id: UUID of the user
        permission: Permission string to check
        db: Database session
        
    Returns:
        True if user has the permission, False otherwise
    """
    permissions = await get_user_permissions(user_id, db)
    return permission in permissions


async def has_any_permission(
    user_id: str,
    permissions: List[str],
    db: Session
) -> bool:
    """
    Check if user has any of the specified permissions.
    
    Args:
        user_id: UUID of the user
        permissions: List of permission strings
        db: Database session
        
    Returns:
        True if user has any of the permissions
    """
    user_permissions = await get_user_permissions(user_id, db)
    return any(perm in user_permissions for perm in permissions)


async def has_all_permissions(
    user_id: str,
    permissions: List[str],
    db: Session
) -> bool:
    """
    Check if user has all of the specified permissions.
    
    Args:
        user_id: UUID of the user
        permissions: List of permission strings
        db: Database session
        
    Returns:
        True if user has all of the permissions
    """
    user_permissions = await get_user_permissions(user_id, db)
    return all(perm in user_permissions for perm in permissions)


# ============================================================================
# RESOURCE-BASED PERMISSION CHECKING
# ============================================================================

async def check_resource_permission(
    user_id: str,
    resource: str,
    action: str,
    db: Session
) -> bool:
    """
    Check if user has permission for a resource-action pair.
    
    Args:
        user_id: UUID of the user
        resource: Resource type (e.g., 'forms', 'users')
        action: Action (e.g., 'create', 'read')
        db: Database session
        
    Returns:
        True if user has the permission
        
    Raises:
        ValueError: If resource-action is unknown
    """
    try:
        permission = get_permission_for_resource_action(resource, action)
        return await has_permission(user_id, permission, db)
    except ValueError:
        # Unknown resource-action combination
        return False


# ============================================================================
# AUDIT LOGGING FOR PERMISSION CHECKS
# ============================================================================

async def log_permission_check(
    user_id: str,
    permission: str,
    allowed: bool,
    resource: Optional[str] = None,
    action: Optional[str] = None,
    details: Optional[dict] = None,
    db: Optional[Session] = None
) -> None:
    """
    Log permission check for audit trail (especially failed attempts).
    
    Args:
        user_id: UUID of the user being checked
        permission: Permission being checked
        allowed: Whether the check passed
        resource: Resource name (optional)
        action: Action name (optional)
        details: Additional details dict (optional)
        db: Database session
    """
    if db is None:
        return
    
    # Only log failed attempts and sensitive operations
    if not allowed or permission in [
        Permission.USER_MANAGE_ROLES,
        Permission.USER_MANAGE_PERMISSIONS,
        Permission.ROLE_CREATE,
        Permission.ROLE_EDIT,
        Permission.ROLE_DELETE,
        Permission.SYSTEM_CONFIG,
        Permission.AUDIT_LOG_EXPORT,
    ]:
        try:
            # Verify user exists before creating audit log entry
            user_exists = db.query(User).filter(User.id == user_id).first()
            if not user_exists:
                return
            
            audit_entry = AuditLog(
                user_id=user_id,
                action="permission_check",
                entity_type="permission",
                entity_id=permission,
                old_values={},
                new_values={
                    "permission": permission,
                    "resource": resource,
                    "action": action,
                    "allowed": allowed,
                    **(details or {}),
                },
            )
            db.add(audit_entry)
            db.commit()
        except Exception:
            # Don't let audit logging failures break the app
            db.rollback()
            pass


# ============================================================================
# FASTAPI DEPENDENCIES FOR PERMISSION CHECKING
# ============================================================================

def require_permission(resource: str, action: str):
    """
    FastAPI dependency to require a specific resource-action permission.
    
    Usage:
        @app.get("/forms/", dependencies=[Depends(require_permission("forms", "read"))])
        async def get_forms(...):
            ...
    
    Args:
        resource: Resource type (e.g., 'forms')
        action: Action (e.g., 'read')
        
    Returns:
        Dependency function that checks permission
    """
    
    async def check_permission(
        user: TokenData = Depends(_get_current_user()),
        db: Session = Depends(get_db),
    ) -> TokenData:
        """Check that user has the required permission."""
        
        # Convert resource and action to permission string
        try:
            permission = get_permission_for_resource_action(resource, action)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Configuration error: {str(e)}",
            )
        
        # Check permission
        has_perm = await has_permission(user.sub, permission, db)
        
        # Log permission check
        await log_permission_check(
            user_id=user.sub,
            permission=permission,
            allowed=has_perm,
            resource=resource,
            action=action,
            db=db,
        )
        
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {resource}:{action}",
            )
        
        return user
    
    return check_permission


def require_any_permission(*permissions: str):
    """
    FastAPI dependency to require any one of the specified permissions.
    
    Usage:
        @app.delete("/forms/{id}", dependencies=[
            Depends(require_any_permission("form:delete", "form:admin"))
        ])
        async def delete_form(...):
            ...
    
    Args:
        permissions: Variable number of permission strings
        
    Returns:
        Dependency function that checks if user has any permission
    """
    
    async def check_permissions(
        user: TokenData = Depends(_get_current_user()),
        db: Session = Depends(get_db),
    ) -> TokenData:
        """Check that user has at least one of the required permissions."""
        
        has_perm = await has_any_permission(user.sub, list(permissions), db)
        
        if not has_perm:
            await log_permission_check(
                user_id=user.sub,
                permission="|".join(permissions),
                allowed=False,
                db=db,
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required one of: {', '.join(permissions)}",
            )
        
        await log_permission_check(
            user_id=user.sub,
            permission="|".join(permissions),
            allowed=True,
            db=db,
        )
        
        return user
    
    return check_permissions


def require_all_permissions(*permissions: str):
    """
    FastAPI dependency to require all of the specified permissions.
    
    Usage:
        @app.patch("/forms/{id}/publish", dependencies=[
            Depends(require_all_permissions("form:edit", "form:approve"))
        ])
        async def publish_form(...):
            ...
    
    Args:
        permissions: Variable number of permission strings
        
    Returns:
        Dependency function that checks if user has all permissions
    """
    
    async def check_permissions(
        user: TokenData = Depends(_get_current_user()),
        db: Session = Depends(get_db),
    ) -> TokenData:
        """Check that user has all required permissions."""
        
        has_perm = await has_all_permissions(user.sub, list(permissions), db)
        
        if not has_perm:
            await log_permission_check(
                user_id=user.sub,
                permission="&".join(permissions),
                allowed=False,
                db=db,
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required all of: {', '.join(permissions)}",
            )
        
        await log_permission_check(
            user_id=user.sub,
            permission="&".join(permissions),
            allowed=True,
            db=db,
        )
        
        return user
    
    return check_permissions


# ============================================================================
# HELPER FUNCTION: Check if user has admin role
# ============================================================================

async def is_admin(user: TokenData, db: Session) -> bool:
    """
    Check if user has admin role.
    
    Args:
        user: TokenData object
        db: Database session
        
    Returns:
        True if user is admin
    """
    # Check if user has admin role in roles list
    if "admin" in (user.roles or []):
        return True
    
    # Fallback: check in database
    user_roles = db.query(UserRole).filter(
        UserRole.user_id == user.sub,
        UserRole.deleted_at.is_(None)
    ).all()
    
    return any(ur.role.name == "admin" for ur in user_roles if ur.role and ur.role.is_active)
