"""
Permission definitions and role-permission mappings for RBAC.

This module defines:
1. All available permissions in the system (granular)
2. Default roles with their associated permissions
3. Permission inheritance rules
"""

from enum import Enum
from typing import List, Dict, Set


# ============================================================================
# PERMISSION DEFINITIONS
# ============================================================================

class Permission(str, Enum):
    """All available permissions in the system."""
    
    # Form Management Permissions
    FORM_CREATE = "form:create"
    FORM_READ = "form:read"
    FORM_EDIT = "form:edit"
    FORM_DELETE = "form:delete"
    FORM_ARCHIVE = "form:archive"
    
    # Form Workflow Permissions
    FORM_SUBMIT_FOR_REVIEW = "form:submit_for_review"
    FORM_REVIEW = "form:review"
    FORM_APPROVE = "form:approve"
    FORM_PUBLISH = "form:publish"
    
    # Business Area Permissions
    BUSINESS_AREA_CREATE = "business_area:create"
    BUSINESS_AREA_READ = "business_area:read"
    BUSINESS_AREA_EDIT = "business_area:edit"
    BUSINESS_AREA_DELETE = "business_area:delete"
    BUSINESS_AREA_MANAGE = "business_area:manage"
    
    # Category Management Permissions
    CATEGORY_CREATE = "category:create"
    CATEGORY_READ = "category:read"
    CATEGORY_EDIT = "category:edit"
    CATEGORY_DELETE = "category:delete"
    
    # User Management Permissions
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_EDIT = "user:edit"
    USER_DELETE = "user:delete"
    USER_MANAGE_ROLES = "user:manage_roles"
    USER_MANAGE_PERMISSIONS = "user:manage_permissions"
    
    # Role Management Permissions
    ROLE_CREATE = "role:create"
    ROLE_READ = "role:read"
    ROLE_EDIT = "role:edit"
    ROLE_DELETE = "role:delete"
    
    # Audit & Reporting Permissions
    AUDIT_LOG_VIEW = "audit_log:view"
    AUDIT_LOG_EXPORT = "audit_log:export"
    REPORT_VIEW = "report:view"
    
    # System Configuration Permissions
    SYSTEM_CONFIG = "system:config"
    SYSTEM_HEALTH = "system:health"


# ============================================================================
# DEFAULT ROLES & PERMISSION MAPPINGS
# ============================================================================

DEFAULT_ROLES: Dict[str, Dict[str, any]] = {
    "admin": {
        "description": "System administrator with full access",
        "is_system": True,
        "permissions": [
            # All form permissions
            Permission.FORM_CREATE,
            Permission.FORM_READ,
            Permission.FORM_EDIT,
            Permission.FORM_DELETE,
            Permission.FORM_ARCHIVE,
            Permission.FORM_SUBMIT_FOR_REVIEW,
            Permission.FORM_REVIEW,
            Permission.FORM_APPROVE,
            Permission.FORM_PUBLISH,
            
            # All business area permissions
            Permission.BUSINESS_AREA_CREATE,
            Permission.BUSINESS_AREA_READ,
            Permission.BUSINESS_AREA_EDIT,
            Permission.BUSINESS_AREA_DELETE,
            Permission.BUSINESS_AREA_MANAGE,
            
            # All category permissions
            Permission.CATEGORY_CREATE,
            Permission.CATEGORY_READ,
            Permission.CATEGORY_EDIT,
            Permission.CATEGORY_DELETE,
            
            # All user permissions
            Permission.USER_CREATE,
            Permission.USER_READ,
            Permission.USER_EDIT,
            Permission.USER_DELETE,
            Permission.USER_MANAGE_ROLES,
            Permission.USER_MANAGE_PERMISSIONS,
            
            # All role permissions
            Permission.ROLE_CREATE,
            Permission.ROLE_READ,
            Permission.ROLE_EDIT,
            Permission.ROLE_DELETE,
            
            # All audit permissions
            Permission.AUDIT_LOG_VIEW,
            Permission.AUDIT_LOG_EXPORT,
            Permission.REPORT_VIEW,
            
            # System configuration
            Permission.SYSTEM_CONFIG,
            Permission.SYSTEM_HEALTH,
        ],
    },
    
    "staff_manager": {
        "description": "Staff manager responsible for form workflow and staff coordination",
        "is_system": True,
        "permissions": [
            # Form CRUD
            Permission.FORM_CREATE,
            Permission.FORM_READ,
            Permission.FORM_EDIT,
            Permission.FORM_DELETE,
            Permission.FORM_ARCHIVE,
            
            # Form workflow
            Permission.FORM_SUBMIT_FOR_REVIEW,
            Permission.FORM_REVIEW,
            Permission.FORM_APPROVE,
            
            # Business areas (read + manage)
            Permission.BUSINESS_AREA_READ,
            Permission.BUSINESS_AREA_MANAGE,
            
            # Category read
            Permission.CATEGORY_READ,
            
            # User management (limited)
            Permission.USER_READ,
            
            # Audit log viewing
            Permission.AUDIT_LOG_VIEW,
            Permission.REPORT_VIEW,
        ],
    },
    
    "reviewer": {
        "description": "Form reviewer responsible for reviewing and approving forms",
        "is_system": True,
        "permissions": [
            # Form read and review
            Permission.FORM_READ,
            Permission.FORM_REVIEW,
            Permission.FORM_APPROVE,
            
            # Business areas (read only)
            Permission.BUSINESS_AREA_READ,
            
            # Categories (read only)
            Permission.CATEGORY_READ,
            
            # Audit log viewing
            Permission.AUDIT_LOG_VIEW,
        ],
    },
    
    "staff_viewer": {
        "description": "Staff member with read-only access to published forms",
        "is_system": True,
        "permissions": [
            # Form read only
            Permission.FORM_READ,
            
            # Business areas (read only)
            Permission.BUSINESS_AREA_READ,
            
            # Categories (read only)
            Permission.CATEGORY_READ,
        ],
    },
}


# ============================================================================
# PERMISSION GROUPS (for easier permission management)
# ============================================================================

PERMISSION_GROUPS: Dict[str, List[Permission]] = {
    "form_create": [Permission.FORM_CREATE],
    "form_read": [Permission.FORM_READ],
    "form_write": [
        Permission.FORM_CREATE,
        Permission.FORM_EDIT,
        Permission.FORM_DELETE,
        Permission.FORM_ARCHIVE,
    ],
    "form_workflow": [
        Permission.FORM_SUBMIT_FOR_REVIEW,
        Permission.FORM_REVIEW,
        Permission.FORM_APPROVE,
        Permission.FORM_PUBLISH,
    ],
    "business_area_manage": [
        Permission.BUSINESS_AREA_CREATE,
        Permission.BUSINESS_AREA_EDIT,
        Permission.BUSINESS_AREA_DELETE,
        Permission.BUSINESS_AREA_MANAGE,
    ],
    "user_manage": [
        Permission.USER_CREATE,
        Permission.USER_EDIT,
        Permission.USER_DELETE,
        Permission.USER_MANAGE_ROLES,
        Permission.USER_MANAGE_PERMISSIONS,
    ],
    "audit": [
        Permission.AUDIT_LOG_VIEW,
        Permission.AUDIT_LOG_EXPORT,
        Permission.REPORT_VIEW,
    ],
}


# ============================================================================
# PERMISSION INHERITANCE RULES
# ============================================================================

def get_inherited_permissions(permissions: List[str]) -> Set[str]:
    """
    Apply permission inheritance rules.
    
    Inheritance hierarchy:
    - No inheritance by default
    - This function can be extended to add inheritance logic
    
    Args:
        permissions: List of permission strings
        
    Returns:
        Set of permissions including inherited ones
    """
    result = set(permissions)
    
    # Example inheritance rules (can be extended):
    # If user has form delete, they implicitly have form edit
    if Permission.FORM_DELETE in result or "form:delete" in permissions:
        result.add(Permission.FORM_EDIT)
    
    # If user has user management role, they can read users
    if Permission.USER_MANAGE_ROLES in result or "user:manage_roles" in permissions:
        result.add(Permission.USER_READ)
    
    # If user can manage business areas, they can read them
    if Permission.BUSINESS_AREA_MANAGE in result or "business_area:manage" in permissions:
        result.add(Permission.BUSINESS_AREA_READ)
    
    return result


# ============================================================================
# RESOURCE-ACTION MAPPING (for @require_permission decorator)
# ============================================================================

RESOURCE_ACTION_PERMISSIONS: Dict[str, Dict[str, str]] = {
    "forms": {
        "create": Permission.FORM_CREATE,
        "read": Permission.FORM_READ,
        "update": Permission.FORM_EDIT,
        "delete": Permission.FORM_DELETE,
        "archive": Permission.FORM_ARCHIVE,
        "submit": Permission.FORM_SUBMIT_FOR_REVIEW,
        "review": Permission.FORM_REVIEW,
        "approve": Permission.FORM_APPROVE,
        "publish": Permission.FORM_PUBLISH,
    },
    "business_areas": {
        "create": Permission.BUSINESS_AREA_CREATE,
        "read": Permission.BUSINESS_AREA_READ,
        "update": Permission.BUSINESS_AREA_EDIT,
        "delete": Permission.BUSINESS_AREA_DELETE,
        "manage": Permission.BUSINESS_AREA_MANAGE,
    },
    "categories": {
        "create": Permission.CATEGORY_CREATE,
        "read": Permission.CATEGORY_READ,
        "update": Permission.CATEGORY_EDIT,
        "delete": Permission.CATEGORY_DELETE,
    },
    "users": {
        "create": Permission.USER_CREATE,
        "read": Permission.USER_READ,
        "update": Permission.USER_EDIT,
        "delete": Permission.USER_DELETE,
        "manage_roles": Permission.USER_MANAGE_ROLES,
        "manage_permissions": Permission.USER_MANAGE_PERMISSIONS,
    },
    "roles": {
        "create": Permission.ROLE_CREATE,
        "read": Permission.ROLE_READ,
        "update": Permission.ROLE_EDIT,
        "delete": Permission.ROLE_DELETE,
    },
    "audit": {
        "view": Permission.AUDIT_LOG_VIEW,
        "export": Permission.AUDIT_LOG_EXPORT,
    },
    "reports": {
        "view": Permission.REPORT_VIEW,
    },
    "system": {
        "config": Permission.SYSTEM_CONFIG,
        "health": Permission.SYSTEM_HEALTH,
    },
}


def get_permission_for_resource_action(resource: str, action: str) -> str:
    """
    Get the required permission for a resource-action pair.
    
    Args:
        resource: Resource name (e.g., 'forms', 'users')
        action: Action name (e.g., 'create', 'read')
        
    Returns:
        Permission string
        
    Raises:
        ValueError: If resource-action combination is not found
    """
    if resource not in RESOURCE_ACTION_PERMISSIONS:
        raise ValueError(f"Unknown resource: {resource}")
    
    if action not in RESOURCE_ACTION_PERMISSIONS[resource]:
        raise ValueError(f"Unknown action '{action}' for resource '{resource}'")
    
    return RESOURCE_ACTION_PERMISSIONS[resource][action]
