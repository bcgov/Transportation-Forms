"""
Tests for authorization and RBAC module.

Test coverage:
- Permission checking functions (has_permission, has_any_permission, has_all_permissions)
- Resource-action permission checking
- FastAPI dependencies (@require_permission, @require_any_permission, @require_all_permissions)
- Permission inheritance logic
- Audit logging for permission checks
- Default roles and seed functionality
"""

import pytest
import uuid
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from backend.database import Base, engine, SessionLocal
from backend.models import User, Role, UserRole, AuditLog
from backend.auth.jwt_handler import TokenData
from backend.auth.permissions import (
    Permission,
    DEFAULT_ROLES,
    get_inherited_permissions,
    get_permission_for_resource_action,
)
from backend.auth.authorization import (
    get_user_permissions,
    has_permission,
    has_any_permission,
    has_all_permissions,
    check_resource_permission,
    log_permission_check,
    require_permission,
    require_any_permission,
    require_all_permissions,
    is_admin,
)
from backend.seeds.default_roles import seed_default_roles, get_role_by_name, get_all_system_roles


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
def db():
    """Create a test database session."""
    Base.metadata.create_all(bind=engine)
    
    db_session = SessionLocal()
    yield db_session
    
    db_session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def admin_user(db: Session):
    """Create an admin user with admin role."""
    user = User(
        id=uuid.uuid4(),
        azure_id="admin-001",
        email="admin@test.com",
        first_name="Admin",
        last_name="User",
        is_active=True,
    )
    db.add(user)
    
    # Create and assign admin role
    admin_role = Role(
        id=uuid.uuid4(),
        name="admin",
        description="Admin role",
        permissions=[p.value if hasattr(p, 'value') else str(p) for p in DEFAULT_ROLES["admin"]["permissions"]],
        is_system=True,
        is_active=True,
    )
    db.add(admin_role)
    
    user_role = UserRole(
        id=uuid.uuid4(),
        user_id=user.id,
        role_id=admin_role.id,
    )
    db.add(user_role)
    db.commit()
    
    return user


@pytest.fixture
def reviewer_user(db: Session):
    """Create a reviewer user."""
    user = User(
        id=uuid.uuid4(),
        azure_id="reviewer-001",
        email="reviewer@test.com",
        first_name="Review",
        last_name="User",
        is_active=True,
    )
    db.add(user)
    
    # Create and assign reviewer role
    reviewer_role = Role(
        id=uuid.uuid4(),
        name="reviewer",
        description="Reviewer role",
        permissions=[p.value if hasattr(p, 'value') else str(p) for p in DEFAULT_ROLES["reviewer"]["permissions"]],
        is_system=True,
        is_active=True,
    )
    db.add(reviewer_role)
    
    user_role = UserRole(
        id=uuid.uuid4(),
        user_id=user.id,
        role_id=reviewer_role.id,
    )
    db.add(user_role)
    db.commit()
    
    return user


@pytest.fixture
def token_data_admin(admin_user):
    """Create TokenData for admin user."""
    return TokenData(
        sub=str(admin_user.id),
        email=admin_user.email,
        name="Admin User",
        roles=["admin"],
    )


@pytest.fixture
def token_data_reviewer(reviewer_user):
    """Create TokenData for reviewer user."""
    return TokenData(
        sub=str(reviewer_user.id),
        email=reviewer_user.email,
        name="Review User",
        roles=["reviewer"],
    )


# ============================================================================
# TESTS: Permission Definitions
# ============================================================================

class TestPermissionDefinitions:
    """Test permission enum and constants."""
    
    def test_permission_enum_has_all_permissions(self):
        """Test that Permission enum has all expected permissions."""
        expected_perms = [
            "FORM_CREATE", "FORM_READ", "FORM_EDIT", "FORM_DELETE",
            "FORM_ARCHIVE", "FORM_SUBMIT_FOR_REVIEW", "FORM_REVIEW",
            "FORM_APPROVE", "FORM_PUBLISH",
            "USER_CREATE", "USER_READ", "USER_EDIT", "USER_DELETE",
            "USER_MANAGE_ROLES", "USER_MANAGE_PERMISSIONS",
            "ROLE_CREATE", "ROLE_READ", "ROLE_EDIT", "ROLE_DELETE",
            "AUDIT_LOG_VIEW", "AUDIT_LOG_EXPORT", "REPORT_VIEW",
            "SYSTEM_CONFIG", "SYSTEM_HEALTH",
        ]
        for perm_name in expected_perms:
            assert hasattr(Permission, perm_name), f"Missing permission: {perm_name}"
    
    def test_default_roles_exist(self):
        """Test that all 4 default roles are defined."""
        expected_roles = ["admin", "staff_manager", "reviewer", "staff_viewer"]
        assert set(DEFAULT_ROLES.keys()) == set(expected_roles)
    
    def test_admin_role_has_all_permissions(self):
        """Test that admin role has comprehensive permissions."""
        admin_perms = DEFAULT_ROLES["admin"]["permissions"]
        assert len(admin_perms) > 20  # Should have many permissions
        assert Permission.FORM_CREATE in admin_perms
        assert Permission.USER_MANAGE_ROLES in admin_perms
        assert Permission.SYSTEM_CONFIG in admin_perms
    
    def test_reviewer_role_has_limited_permissions(self):
        """Test that reviewer role has only review-related permissions."""
        reviewer_perms = DEFAULT_ROLES["reviewer"]["permissions"]
        assert Permission.FORM_READ in reviewer_perms
        assert Permission.FORM_REVIEW in reviewer_perms
        assert Permission.FORM_CREATE not in reviewer_perms  # Should not have
        assert Permission.USER_MANAGE_ROLES not in reviewer_perms  # Should not have
    
    def test_staff_viewer_role_read_only(self):
        """Test that staff_viewer only has read permissions."""
        viewer_perms = DEFAULT_ROLES["staff_viewer"]["permissions"]
        for perm in viewer_perms:
            # All should be READ-like permissions
            assert "read" in perm or "view" in perm


# ============================================================================
# TESTS: Permission Inheritance
# ============================================================================

class TestPermissionInheritance:
    """Test permission inheritance logic."""
    
    def test_delete_implies_edit(self):
        """Test that delete permission implies edit permission."""
        perms = [Permission.FORM_DELETE]
        inherited = get_inherited_permissions(perms)
        assert Permission.FORM_EDIT in inherited
        assert Permission.FORM_DELETE in inherited
    
    def test_manage_roles_implies_read_users(self):
        """Test that manage_roles permission implies read_users."""
        perms = [Permission.USER_MANAGE_ROLES]
        inherited = get_inherited_permissions(perms)
        assert Permission.USER_READ in inherited
        assert Permission.USER_MANAGE_ROLES in inherited
    
    def test_manage_business_area_implies_read(self):
        """Test that manage business_area implies read."""
        perms = [Permission.BUSINESS_AREA_MANAGE]
        inherited = get_inherited_permissions(perms)
        assert Permission.BUSINESS_AREA_READ in inherited


# ============================================================================
# TESTS: Resource-Action Permission Mapping
# ============================================================================

class TestResourceActionPermissions:
    """Test resource-action to permission mapping."""
    
    def test_get_form_create_permission(self):
        """Test getting permission for form:create."""
        perm = get_permission_for_resource_action("forms", "create")
        assert perm == Permission.FORM_CREATE
    
    def test_get_user_manage_permission(self):
        """Test getting permission for user:manage_roles."""
        perm = get_permission_for_resource_action("users", "manage_roles")
        assert perm == Permission.USER_MANAGE_ROLES
    
    def test_unknown_resource_raises_error(self):
        """Test that unknown resource raises ValueError."""
        with pytest.raises(ValueError, match="Unknown resource"):
            get_permission_for_resource_action("unknown_resource", "read")
    
    def test_unknown_action_raises_error(self):
        """Test that unknown action raises ValueError."""
        with pytest.raises(ValueError, match="Unknown action"):
            get_permission_for_resource_action("forms", "unknown_action")


# ============================================================================
# TESTS: Permission Checking Functions
# ============================================================================

class TestPermissionChecking:
    """Test permission checking functions."""
    
    @pytest.mark.asyncio
    async def test_get_user_permissions_admin(self, db: Session, admin_user):
        """Test getting permissions for admin user."""
        perms = await get_user_permissions(str(admin_user.id), db)
        assert len(perms) > 20
        assert Permission.FORM_CREATE.value in perms
        assert Permission.USER_MANAGE_ROLES.value in perms
    
    @pytest.mark.asyncio
    async def test_get_user_permissions_reviewer(self, db: Session, reviewer_user):
        """Test getting permissions for reviewer user."""
        perms = await get_user_permissions(str(reviewer_user.id), db)
        assert Permission.FORM_READ.value in perms
        assert Permission.FORM_REVIEW in perms
        assert Permission.FORM_CREATE.value not in perms
    
    @pytest.mark.asyncio
    async def test_get_user_permissions_nonexistent_user(self, db: Session):
        """Test getting permissions for nonexistent user returns empty set."""
        fake_id = str(uuid.uuid4())
        perms = await get_user_permissions(fake_id, db)
        assert perms == set()
    
    @pytest.mark.asyncio
    async def test_has_permission_true(self, db: Session, admin_user):
        """Test has_permission returns True when user has permission."""
        result = await has_permission(
            str(admin_user.id),
            Permission.FORM_CREATE.value,
            db
        )
        assert result is True
    
    @pytest.mark.asyncio
    async def test_has_permission_false(self, db: Session, reviewer_user):
        """Test has_permission returns False when user lacks permission."""
        result = await has_permission(
            str(reviewer_user.id),
            Permission.USER_MANAGE_ROLES.value,
            db
        )
        assert result is False
    
    @pytest.mark.asyncio
    async def test_has_any_permission_true(self, db: Session, admin_user):
        """Test has_any_permission returns True when user has at least one."""
        result = await has_any_permission(
            str(admin_user.id),
            [Permission.FORM_CREATE.value, Permission.USER_MANAGE_ROLES.value],
            db
        )
        assert result is True
    
    @pytest.mark.asyncio
    async def test_has_any_permission_false(self, db: Session, reviewer_user):
        """Test has_any_permission returns False when user has none."""
        result = await has_any_permission(
            str(reviewer_user.id),
            [Permission.SYSTEM_CONFIG.value, Permission.USER_MANAGE_ROLES.value],
            db
        )
        assert result is False
    
    @pytest.mark.asyncio
    async def test_has_all_permissions_true(self, db: Session, admin_user):
        """Test has_all_permissions returns True when user has all."""
        result = await has_all_permissions(
            str(admin_user.id),
            [Permission.FORM_CREATE.value, Permission.USER_MANAGE_ROLES.value],
            db
        )
        assert result is True
    
    @pytest.mark.asyncio
    async def test_has_all_permissions_false(self, db: Session, reviewer_user):
        """Test has_all_permissions returns False when missing one."""
        result = await has_all_permissions(
            str(reviewer_user.id),
            [Permission.FORM_READ.value, Permission.FORM_CREATE.value],
            db
        )
        assert result is False


# ============================================================================
# TESTS: Resource Permission Checking
# ============================================================================

class TestResourcePermissionChecking:
    """Test resource-based permission checking."""
    
    @pytest.mark.asyncio
    async def test_check_resource_permission_true(self, db: Session, admin_user):
        """Test check_resource_permission returns True for allowed action."""
        result = await check_resource_permission(
            str(admin_user.id),
            "forms",
            "create",
            db
        )
        assert result is True
    
    @pytest.mark.asyncio
    async def test_check_resource_permission_false(self, db: Session, reviewer_user):
        """Test check_resource_permission returns False for denied action."""
        result = await check_resource_permission(
            str(reviewer_user.id),
            "users",
            "manage_roles",
            db
        )
        assert result is False
    
    @pytest.mark.asyncio
    async def test_check_resource_permission_unknown_resource(self, db: Session, admin_user):
        """Test check_resource_permission handles unknown resource."""
        result = await check_resource_permission(
            str(admin_user.id),
            "unknown",
            "read",
            db
        )
        assert result is False


# ============================================================================
# TESTS: Audit Logging
# ============================================================================

class TestAuditLogging:
    """Test audit logging for permission checks."""
    
    @pytest.mark.asyncio
    async def test_log_permission_check_failed_attempt(self, db: Session):
        """Test that failed permission attempts are logged."""
        # Create a user first
        user = User(
            id=uuid.uuid4(),
            azure_id="test-audit-user-1",
            email="audit1@test.com",
            is_active=True,
        )
        db.add(user)
        db.commit()
        
        user_id = str(user.id)
        
        await log_permission_check(
            user_id=user_id,
            permission=Permission.USER_MANAGE_ROLES.value,
            allowed=False,
            resource="users",
            action="manage_roles",
            db=db,
        )
        
        # Check that audit log entry was created
        audit_entry = db.query(AuditLog).filter(
            AuditLog.user_id == user_id,
            AuditLog.action == "permission_check"
        ).first()
        assert audit_entry is not None
        assert audit_entry.entity_type == "permission"
    
    @pytest.mark.asyncio
    async def test_log_permission_check_sensitive_operation(self, db: Session):
        """Test that sensitive operations are logged."""
        # Create a user first
        user = User(
            id=uuid.uuid4(),
            azure_id="test-audit-user-2",
            email="audit2@test.com",
            is_active=True,
        )
        db.add(user)
        db.commit()
        
        user_id = str(user.id)
        
        await log_permission_check(
            user_id=user_id,
            permission=Permission.USER_MANAGE_PERMISSIONS.value,
            allowed=True,
            db=db,
        )
        
        # Check that audit log entry was created for sensitive operation
        audit_entry = db.query(AuditLog).filter(
            AuditLog.user_id == user_id,
        ).first()
        assert audit_entry is not None
    
    @pytest.mark.asyncio
    async def test_log_permission_check_no_db(self):
        """Test that audit logging handles missing database gracefully."""
        # Should not raise an exception
        await log_permission_check(
            user_id=str(uuid.uuid4()),
            permission=Permission.FORM_CREATE,
            allowed=True,
            db=None,
        )


# ============================================================================
# TESTS: FastAPI Dependencies
# ============================================================================

class TestFastAPIDependencies:
    """Test FastAPI permission dependencies."""
    
    @pytest.mark.asyncio
    async def test_require_permission_allowed(self, db: Session, token_data_admin):
        """Test require_permission passes for allowed user."""
        dep = require_permission("forms", "create")
        
        # Should not raise
        result = await dep(token_data_admin, db)
        assert result == token_data_admin
    
    @pytest.mark.asyncio
    async def test_require_permission_denied(self, db: Session, token_data_reviewer):
        """Test require_permission raises for denied user."""
        dep = require_permission("users", "manage_roles")
        
        with pytest.raises(HTTPException) as exc_info:
            await dep(token_data_reviewer, db)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    
    @pytest.mark.asyncio
    async def test_require_permission_invalid_resource(self, db: Session, token_data_admin):
        """Test require_permission raises for invalid resource."""
        dep = require_permission("invalid_resource", "invalid_action")
        
        with pytest.raises(HTTPException) as exc_info:
            await dep(token_data_admin, db)
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    
    @pytest.mark.asyncio
    async def test_require_any_permission_allowed(self, db: Session, token_data_admin):
        """Test require_any_permission passes when user has one."""
        dep = require_any_permission(
            Permission.SYSTEM_CONFIG,
            Permission.SYSTEM_HEALTH,
        )
        
        result = await dep(token_data_admin, db)
        assert result == token_data_admin
    
    @pytest.mark.asyncio
    async def test_require_any_permission_denied(self, db: Session, token_data_reviewer):
        """Test require_any_permission raises when user has none."""
        dep = require_any_permission(
            Permission.SYSTEM_CONFIG,
            Permission.SYSTEM_HEALTH,
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await dep(token_data_reviewer, db)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    
    @pytest.mark.asyncio
    async def test_require_all_permissions_allowed(self, db: Session, token_data_admin):
        """Test require_all_permissions passes when user has all."""
        dep = require_all_permissions(
            Permission.FORM_CREATE,
            Permission.FORM_DELETE,
        )
        
        result = await dep(token_data_admin, db)
        assert result == token_data_admin
    
    @pytest.mark.asyncio
    async def test_require_all_permissions_denied(self, db: Session, token_data_reviewer):
        """Test require_all_permissions raises when missing one."""
        dep = require_all_permissions(
            Permission.FORM_READ,
            Permission.FORM_CREATE,
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await dep(token_data_reviewer, db)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ============================================================================
# TESTS: Default Roles Seeding
# ============================================================================

class TestDefaultRolesSeeding:
    """Test default roles seeding functionality."""
    
    def test_seed_default_roles_creates_roles(self, db: Session):
        """Test that seed_default_roles creates all 4 default roles."""
        results = seed_default_roles(db)
        
        assert results["created"] == 4
        assert results["updated"] == 0
        assert len(results["roles"]) == 4
    
    def test_seed_default_roles_idempotent(self, db: Session):
        """Test that seeding is idempotent."""
        # First seed
        results1 = seed_default_roles(db)
        assert results1["created"] == 4
        
        # Second seed
        results2 = seed_default_roles(db)
        assert results2["created"] == 0
        assert results2["updated"] == 4
    
    def test_get_role_by_name(self, db: Session):
        """Test getting role by name."""
        seed_default_roles(db)
        
        admin_role = get_role_by_name(db, "admin")
        assert admin_role is not None
        assert admin_role.name == "admin"
        assert admin_role.is_system is True
    
    def test_get_all_system_roles(self, db: Session):
        """Test getting all system roles."""
        seed_default_roles(db)
        
        roles = get_all_system_roles(db)
        assert len(roles) == 4
        role_names = {r.name for r in roles}
        assert role_names == {"admin", "staff_manager", "reviewer", "staff_viewer"}


# ============================================================================
# TESTS: Helper Functions
# ============================================================================

class TestHelperFunctions:
    """Test helper functions."""
    
    @pytest.mark.asyncio
    async def test_is_admin_true(self, db: Session, admin_user, token_data_admin):
        """Test is_admin returns True for admin user."""
        result = await is_admin(token_data_admin, db)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_is_admin_false(self, db: Session, token_data_reviewer):
        """Test is_admin returns False for non-admin user."""
        result = await is_admin(token_data_reviewer, db)
        assert result is False


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestAuthorizationIntegration:
    """Integration tests for authorization module."""
    
    @pytest.mark.asyncio
    async def test_admin_workflow(self, db: Session, admin_user):
        """Test typical admin workflow."""
        # Admin can create forms
        perms = await get_user_permissions(str(admin_user.id), db)
        assert Permission.FORM_CREATE in perms
        
        # Admin can manage users
        assert await has_permission(
            str(admin_user.id),
            Permission.USER_MANAGE_ROLES,
            db
        ) is True
        
        # Admin can manage system
        assert await has_permission(
            str(admin_user.id),
            Permission.SYSTEM_CONFIG,
            db
        ) is True
    
    @pytest.mark.asyncio
    async def test_reviewer_workflow(self, db: Session, reviewer_user):
        """Test typical reviewer workflow."""
        # Reviewer can read forms
        assert await has_permission(
            str(reviewer_user.id),
            Permission.FORM_READ.value,
            db
        ) is True
        
        # Reviewer can review forms
        assert await has_permission(
            str(reviewer_user.id),
            Permission.FORM_REVIEW.value,
            db
        ) is True
        
        # Reviewer cannot create users
        assert await has_permission(
            str(reviewer_user.id),
            Permission.USER_CREATE.value,
            db
        ) is False
    
    @pytest.mark.asyncio
    async def test_multiple_roles(self, db: Session):
        """Test user with multiple roles."""
        # Create user with two roles
        user = User(
            id=uuid.uuid4(),
            azure_id="multi-role-001",
            email="multi@test.com",
            is_active=True,
        )
        db.add(user)
        
        # Create two roles
        role1 = Role(
            id=uuid.uuid4(),
            name="reviewer",
            permissions=[p.value if hasattr(p, 'value') else str(p) for p in [Permission.FORM_REVIEW, Permission.FORM_READ]],
            is_system=True,
            is_active=True,
        )
        role2 = Role(
            id=uuid.uuid4(),
            name="staff_manager",
            permissions=[p.value if hasattr(p, 'value') else str(p) for p in [Permission.FORM_CREATE, Permission.FORM_EDIT]],
            is_system=True,
            is_active=True,
        )
        db.add(role1)
        db.add(role2)
        
        # Assign both roles
        ur1 = UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role1.id)
        ur2 = UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role2.id)
        db.add(ur1)
        db.add(ur2)
        db.commit()
        
        # Check that user has permissions from both roles
        perms = await get_user_permissions(str(user.id), db)
        assert Permission.FORM_REVIEW.value in perms
        assert Permission.FORM_CREATE.value in perms
