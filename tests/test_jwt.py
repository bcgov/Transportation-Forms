"""Unit tests for JWT token generation, validation, and refresh logic."""

import pytest
from datetime import datetime, timedelta, timezone
from freezegun import freeze_time

from backend.auth.jwt_handler import (
    JWTHandler,
    TokenData,
    ACCESS_TOKEN_EXPIRY,
    REFRESH_TOKEN_EXPIRY,
    jwt_handler
)


class TestJWTTokenGeneration:
    """Test JWT token generation."""
    
    def test_generate_access_token(self):
        """Test generating an access token with all claims."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin", "staff_manager"]
        
        token = jwt_handler.generate_access_token(user_id, email, name, roles)
        
        assert isinstance(token, str)
        assert len(token) > 0
        assert "." in token  # JWT format: header.payload.signature
    
    def test_generate_refresh_token(self):
        """Test generating a refresh token."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        
        token = jwt_handler.generate_refresh_token(user_id)
        
        assert isinstance(token, str)
        assert len(token) > 0
        assert "." in token
    
    def test_generate_access_token_with_custom_expiry(self):
        """Test generating access token with custom expiry time."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        custom_expiry = timedelta(hours=1)
        token = jwt_handler.generate_access_token(
            user_id, email, name, roles,
            expires_delta=custom_expiry
        )
        
        assert isinstance(token, str)


class TestJWTTokenValidation:
    """Test JWT token validation."""
    
    def test_validate_valid_access_token(self):
        """Test validating a valid access token."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin", "staff_manager"]
        
        token = jwt_handler.generate_access_token(user_id, email, name, roles)
        token_data = jwt_handler.validate_token(token, token_type="access")
        
        assert token_data is not None
        assert token_data.sub == user_id
        assert token_data.email == email
        assert token_data.name == name
        assert token_data.roles == roles
        assert token_data.token_type == "access"
    
    def test_validate_valid_refresh_token(self):
        """Test validating a valid refresh token."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        
        token = jwt_handler.generate_refresh_token(user_id)
        token_data = jwt_handler.validate_token(token, token_type="refresh")
        
        assert token_data is not None
        assert token_data.sub == user_id
        assert token_data.token_type == "refresh"
    
    def test_validate_empty_token(self):
        """Test validating an empty token raises error."""
        with pytest.raises(ValueError):
            jwt_handler.validate_token("", token_type="access")
    
    def test_validate_malformed_token(self):
        """Test validating a malformed token raises error."""
        with pytest.raises(ValueError):
            jwt_handler.validate_token("not.a.token", token_type="access")
    
    def test_validate_wrong_token_type(self):
        """Test validating token with wrong type raises error."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # Generate refresh token but validate as access token
        token = jwt_handler.generate_refresh_token(user_id)
        
        with pytest.raises(ValueError, match="Invalid token type"):
            jwt_handler.validate_token(token, token_type="access")
    
    @freeze_time("2026-02-17 12:00:00")
    def test_validate_expired_token(self):
        """Test validating an expired token raises error."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        # Create token that expires immediately
        token = jwt_handler.generate_access_token(
            user_id, email, name, roles,
            expires_delta=timedelta(seconds=0)
        )
        
        # Move time forward to after expiry
        with freeze_time("2026-02-17 12:00:01"):
            with pytest.raises(ValueError, match="expired"):
                jwt_handler.validate_token(token, token_type="access")


class TestJWTTokenRefresh:
    """Test JWT token refresh logic."""
    
    def test_refresh_access_token(self):
        """Test refreshing an access token using a refresh token."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin", "reviewer"]
        
        refresh_token = jwt_handler.generate_refresh_token(user_id)
        new_access_token = jwt_handler.refresh_access_token(
            refresh_token, user_id, email, name, roles
        )
        
        # Validate the new access token
        token_data = jwt_handler.validate_token(new_access_token, token_type="access")
        
        assert token_data.sub == user_id
        assert token_data.email == email
        assert token_data.name == name
        assert token_data.roles == roles
    
    def test_refresh_with_invalid_refresh_token(self):
        """Test refreshing with invalid refresh token raises error."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        with pytest.raises(ValueError):
            jwt_handler.refresh_access_token(
                "invalid.token.here", user_id, email, name, roles
            )
    
    def test_refresh_with_mismatched_user_id(self):
        """Test refreshing with mismatched user ID raises error."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        different_user_id = "550e8400-e29b-41d4-a716-446655440001"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        refresh_token = jwt_handler.generate_refresh_token(user_id)
        
        with pytest.raises(ValueError, match="mismatch"):
            jwt_handler.refresh_access_token(
                refresh_token, different_user_id, email, name, roles
            )


class TestJWTTokenExpiry:
    """Test JWT token expiry information."""
    
    @freeze_time("2026-02-17 12:00:00")
    def test_get_token_expiry_seconds(self):
        """Test getting remaining seconds until token expiry."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        # Create token with 1-hour expiry
        token = jwt_handler.generate_access_token(
            user_id, email, name, roles,
            expires_delta=timedelta(hours=1)
        )
        
        remaining = jwt_handler.get_token_expiry_seconds(token, token_type="access")
        
        # Should be approximately 3600 seconds (1 hour)
        assert remaining is not None
        assert 3590 <= remaining <= 3600
    
    def test_get_expiry_for_invalid_token(self):
        """Test getting expiry for invalid token returns None."""
        remaining = jwt_handler.get_token_expiry_seconds("invalid.token", token_type="access")
        assert remaining is None
    
    @freeze_time("2026-02-17 12:00:00")
    def test_get_expiry_for_expired_token(self):
        """Test getting expiry for expired token returns 0."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        email = "user@example.com"
        name = "Test User"
        roles = ["admin"]
        
        # Create token that expired 1 hour ago
        token = jwt_handler.generate_access_token(
            user_id, email, name, roles,
            expires_delta=timedelta(hours=-1)
        )
        
        remaining = jwt_handler.get_token_expiry_seconds(token, token_type="access")
        
        # Should be 0 or negative, but function returns max(0, remaining)
        assert remaining == 0


class TestTokenDataClass:
    """Test TokenData class."""
    
    def test_token_data_creation(self):
        """Test creating TokenData object."""
        token_data = TokenData(
            sub="550e8400-e29b-41d4-a716-446655440000",
            email="user@example.com",
            name="Test User",
            roles=["admin"],
            token_type="access"
        )
        
        assert token_data.sub == "550e8400-e29b-41d4-a716-446655440000"
        assert token_data.email == "user@example.com"
        assert token_data.name == "Test User"
        assert token_data.roles == ["admin"]
        assert token_data.token_type == "access"
    
    def test_token_data_default_type(self):
        """Test TokenData defaults token_type to access."""
        token_data = TokenData(
            sub="user123",
            email="user@example.com",
            name="Test User",
            roles=["admin"]
        )
        
        assert token_data.token_type == "access"


class TestJWTConstants:
    """Test JWT configuration constants."""
    
    def test_access_token_expiry_is_30_minutes(self):
        """Test access token expiry is set to 30 minutes."""
        assert ACCESS_TOKEN_EXPIRY == 30 * 60
    
    def test_refresh_token_expiry_is_7_days(self):
        """Test refresh token expiry is set to 7 days."""
        assert REFRESH_TOKEN_EXPIRY == 7 * 24 * 60 * 60
