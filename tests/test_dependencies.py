"""Unit tests for FastAPI authentication dependencies."""

import pytest
from fastapi import HTTPException, status
from fastapi.security.http import HTTPAuthorizationCredentials

from backend.auth.jwt_handler import jwt_handler, TokenData
from backend.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_admin,
    require_staff_manager,
    require_reviewer
)


class TestGetCurrentUser:
    """Test get_current_user dependency."""
    
    @pytest.mark.asyncio
    async def test_get_current_user_valid_token(self):
        """Test extracting user from valid token."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        token = jwt_handler.generate_access_token(user_id, email, name, roles)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        
        token_data = await get_current_user(credentials)
        
        assert token_data.sub == user_id
        assert token_data.email == email
        assert token_data.name == name
        assert token_data.roles == roles
    
    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self):
        """Test extracting user from invalid token raises 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token")
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    
    @pytest.mark.asyncio
    async def test_get_current_user_expired_token(self):
        """Test extracting user from expired token raises 401."""
        from datetime import timedelta
        
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        # Create expired token
        token = jwt_handler.generate_access_token(
            user_id, email, name, roles,
            expires_delta=timedelta(seconds=-1)
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetCurrentUserOptional:
    """Test get_current_user_optional dependency."""
    
    @pytest.mark.asyncio
    async def test_get_current_user_optional_no_credentials(self):
        """Test with no credentials returns None."""
        result = await get_current_user_optional(credentials=None)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_current_user_optional_valid_token(self):
        """Test with valid credentials returns TokenData."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        token = jwt_handler.generate_access_token(user_id, email, name, roles)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        
        result = await get_current_user_optional(credentials=credentials)
        
        assert result is not None
        assert result.sub == user_id
        assert result.email == email
    
    @pytest.mark.asyncio
    async def test_get_current_user_optional_invalid_token(self):
        """Test with invalid credential returns None."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token")
        
        result = await get_current_user_optional(credentials=credentials)
        
        assert result is None


class TestRequireAdmin:
    """Test require_admin role dependency."""
    
    @pytest.mark.asyncio
    async def test_require_admin_with_admin_role(self):
        """Test passing with admin role."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["admin"]
        )
        
        result = await require_admin(token_data)
        assert result == token_data
    
    @pytest.mark.asyncio
    async def test_require_admin_without_admin_role(self):
        """Test failing without admin role raises 403."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["staff_viewer"]
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(token_data)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


class TestRequireStaffManager:
    """Test require_staff_manager role dependency."""
    
    @pytest.mark.asyncio
    async def test_require_staff_manager_with_staff_manager_role(self):
        """Test passing with staff_manager role."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["staff_manager"]
        )
        
        result = await require_staff_manager(token_data)
        assert result == token_data
    
    @pytest.mark.asyncio
    async def test_require_staff_manager_with_admin_role(self):
        """Test passing with admin role (admin has all permissions)."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["admin"]
        )
        
        result = await require_staff_manager(token_data)
        assert result == token_data
    
    @pytest.mark.asyncio
    async def test_require_staff_manager_without_required_role(self):
        """Test failing without required role raises 403."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["staff_viewer"]
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await require_staff_manager(token_data)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


class TestRequireReviewer:
    """Test require_reviewer role dependency."""
    
    @pytest.mark.asyncio
    async def test_require_reviewer_with_reviewer_role(self):
        """Test passing with reviewer role."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["reviewer"]
        )
        
        result = await require_reviewer(token_data)
        assert result == token_data
    
    @pytest.mark.asyncio
    async def test_require_reviewer_with_admin_role(self):
        """Test passing with admin role."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["admin"]
        )
        
        result = await require_reviewer(token_data)
        assert result == token_data
    
    @pytest.mark.asyncio
    async def test_require_reviewer_without_required_role(self):
        """Test failing without required role raises 403."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["staff_viewer"]
        )
        
        with pytest.raises(HTTPException) as exc_info:
            await require_reviewer(token_data)
        
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
