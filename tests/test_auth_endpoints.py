"""Unit tests for authentication API endpoints."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.database import get_db, Base
from backend.models import User, Role
from backend.routes.auth import generate_state, validate_state, map_keycloak_roles_to_local

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture
def db_session():
    """Create a fresh database session for each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    # Create test roles
    roles_data = [
        {"name": "admin", "permissions": {"all": True}, "is_system": True},
        {"name": "staff_manager", "permissions": {"forms": "manage"}, "is_system": True},
        {"name": "reviewer", "permissions": {"forms": "review"}, "is_system": True},
        {"name": "staff_viewer", "permissions": {"forms": "view"}, "is_system": True}
    ]
    
    for role_data in roles_data:
        role = Role(**role_data)
        session.add(role)
    
    session.commit()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


class TestStateManagement:
    """Test CSRF state token management."""
    
    def test_generate_state(self):
        """Test state token generation."""
        state = generate_state()
        
        assert state is not None
        assert len(state) > 20  # Should be a long random string
    
    def test_validate_state_valid(self):
        """Test validating a valid state token."""
        state = generate_state()
        
        is_valid = validate_state(state)
        
        assert is_valid is True
    
    def test_validate_state_invalid(self):
        """Test validating an invalid state token."""
        is_valid = validate_state("invalid-state-token")
        
        assert is_valid is False
    
    def test_validate_state_consumed(self):
        """Test that state token can only be used once."""
        state = generate_state()
        
        # First use should succeed
        assert validate_state(state) is True
        
        # Second use should fail (token consumed)
        assert validate_state(state) is False


class TestLoginEndpoint:
    """Test /api/v1/auth/login endpoint."""
    
    @patch('backend.routes.auth.keycloak_service.get_auth_url')
    def test_login_success(self, mock_get_auth_url):
        """Test successful login initiation."""
        mock_get_auth_url.return_value = "https://keycloak.example.com/auth?state=xyz"
        
        response = client.get("/api/v1/auth/login", follow_redirects=False)
        
        assert response.status_code == 302
        assert "keycloak.example.com" in response.headers["location"]
    
    @patch('backend.routes.auth.keycloak_service.get_auth_url')
    def test_login_keycloak_error(self, mock_get_auth_url):
        """Test login when KeyCloak is unavailable."""
        mock_get_auth_url.side_effect = Exception("KeyCloak unavailable")
        
        response = client.get("/api/v1/auth/login")
        
        assert response.status_code == 500
        assert "Failed to initiate login" in response.json()["detail"]


class TestCallbackEndpoint:
    """Test /api/v1/auth/callback endpoint."""
    
    @patch('backend.routes.auth.keycloak_service.exchange_code_for_token')
    @patch('backend.routes.auth.keycloak_service.get_user_info')
    @patch('backend.routes.auth.keycloak_service.decode_token')
    @patch('backend.routes.auth.keycloak_service.extract_roles')
    @patch('backend.routes.auth.keycloak_service.generate_app_tokens')
    def test_callback_new_user(
        self,
        mock_gen_tokens,
        mock_extract_roles,
        mock_decode,
        mock_get_userinfo,
        mock_exchange,
        db_session
    ):
        """Test callback with new user creation."""
        # Generate valid state
        state = generate_state()
        
        # Mock KeyCloak responses
        mock_exchange.return_value = {"access_token": "kc-access-token"}
        mock_get_userinfo.return_value = {
            "sub": "kc-user-123",
            "email": "newuser@example.com",
            "given_name": "New",
            "family_name": "User",
            "name": "New User"
        }
        mock_decode.return_value = {"sub": "kc-user-123"}
        mock_extract_roles.return_value = ["admin"]
        mock_gen_tokens.return_value = {
            "access_token": "app-access-token",
            "refresh_token": "app-refresh-token",
            "token_type": "Bearer",
            "expires_in": 1800
        }
        
        response = client.get(
            f"/api/v1/auth/callback?code=auth-code-123&state={state}"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "app-access-token"
        assert data["user"]["email"] == "newuser@example.com"
        assert "admin" in data["user"]["roles"]
    
    def test_callback_invalid_state(self):
        """Test callback with invalid state parameter."""
        response = client.get(
            "/api/v1/auth/callback?code=auth-code&state=invalid-state"
        )
        
        assert response.status_code == 400
        assert "Invalid state parameter" in response.json()["detail"]
    
    @patch('backend.routes.auth.keycloak_service.exchange_code_for_token')
    def test_callback_invalid_code(self, mock_exchange, db_session):
        """Test callback with invalid authorization code."""
        state = generate_state()
        mock_exchange.side_effect = ValueError("Invalid authorization code")
        
        response = client.get(
            f"/api/v1/auth/callback?code=invalid-code&state={state}"
        )
        
        assert response.status_code == 401


class TestRefreshTokenEndpoint:
    """Test /api/v1/auth/refresh endpoint."""
    
    @patch('backend.routes.auth.jwt_handler.validate_token')
    def test_refresh_token_success(self, mock_validate, db_session):
        """Test successful token refresh."""
        # Create test user
        user = User(
            azure_id="test-kc-id",
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            is_active=True
        )
        db_session.add(user)
        db_session.commit()
        
        # Mock token validation
        from backend.auth.jwt_handler import TokenData
        user_full_name = f"{user.first_name} {user.last_name}"
        mock_validate.return_value = TokenData(
            sub=str(user.id),
            email=user.email,
            name=user_full_name,
            roles=[],
            token_type="refresh"
        )
        
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "valid-refresh-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"
    
    def test_refresh_token_invalid(self):
        """Test refresh with invalid token."""
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid-token"}
        )
        
        assert response.status_code == 401


class TestLogoutEndpoint:
    """Test /api/v1/auth/logout endpoint."""
    
    @patch('backend.routes.auth.get_current_user')
    def test_logout_success(self, mock_get_user):
        """Test successful logout."""
        from backend.auth.jwt_handler import TokenData
        mock_get_user.return_value = TokenData(
            sub="user-id",
            email="user@example.com",
            name="User",
            roles=["admin"]
        )
        
        response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "refresh-token"},
            headers={"Authorization": "Bearer access-token"}
        )
        
        assert response.status_code == 200
        assert "Successfully logged out" in response.json()["message"]


class TestGetCurrentUserEndpoint:
    """Test /api/v1/auth/me endpoint."""
    
    @patch('backend.routes.auth.get_current_user')
    def test_get_current_user_success(self, mock_get_user, db_session):
        """Test getting current user information."""
        from uuid import UUID
        # Create test user with role
        admin_role = db_session.query(Role).filter(Role.name == "admin").first()
        user = User(
            azure_id="test-kc-id",
            email="admin@example.com",
            first_name="Admin",
            last_name="User",
            is_active=True
        )
        db_session.add(user)
        db_session.flush()
        
        # Create user-role association
        from backend.models import UserRole
        user_role = UserRole(
            user_id=user.id,
            role_id=admin_role.id
        )
        db_session.add(user_role)
        db_session.commit()
        
        # Mock authentication
        from backend.auth.jwt_handler import TokenData
        user_full_name = f"{user.first_name} {user.last_name}"
        mock_get_user.return_value = TokenData(
            sub=str(user.id),
            email=user.email,
            name=user_full_name,
            roles=["admin"]
        )
        
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer access-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "admin@example.com"
        assert "admin" in data["roles"]


class TestRoleMapping:
    """Test KeyCloak role to local role mapping."""
    
    def test_map_direct_roles(self):
        """Test direct role mapping."""
        keycloak_roles = ["admin", "staff_manager"]
        
        local_roles = map_keycloak_roles_to_local(keycloak_roles)
        
        assert "admin" in local_roles
        assert "staff_manager" in local_roles
    
    def test_map_alias_roles(self):
        """Test alias role mapping."""
        keycloak_roles = ["administrator", "manager", "approver", "viewer"]
        
        local_roles = map_keycloak_roles_to_local(keycloak_roles)
        
        assert "admin" in local_roles
        assert "staff_manager" in local_roles
        assert "reviewer" in local_roles
        assert "staff_viewer" in local_roles
    
    def test_map_unknown_roles(self):
        """Test mapping unknown roles."""
        keycloak_roles = ["unknown_role", "invalid_role"]
        
        local_roles = map_keycloak_roles_to_local(keycloak_roles)
        
        assert local_roles == []
    
    def test_map_mixed_roles(self):
        """Test mapping mix of known and unknown roles."""
        keycloak_roles = ["admin", "unknown_role", "reviewer"]
        
        local_roles = map_keycloak_roles_to_local(keycloak_roles)
        
        assert "admin" in local_roles
        assert "reviewer" in local_roles
        assert len(local_roles) == 2
