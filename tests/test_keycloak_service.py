"""Unit tests for KeyCloak authentication service."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from keycloak import KeycloakAuthenticationError, KeycloakConnectionError
from keycloak.exceptions import KeycloakGetError

from backend.auth.keycloak_service import KeyCloakService, keycloak_service
from backend.config import settings


@pytest.fixture
def mock_keycloak_client():
    """Mock KeyCloak OpenID client."""
    with patch('backend.auth.keycloak_service.KeycloakOpenID') as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def keycloak_svc(mock_keycloak_client):
    """KeyCloak service instance with mocked client."""
    service = KeyCloakService()
    return service


class TestKeyCloakServiceInitialization:
    """Test KeyCloak service initialization."""
    
    def test_service_initialization(self, mock_keycloak_client):
        """Test that KeyCloak service initializes correctly."""
        service = KeyCloakService()
        assert service.keycloak_openid is not None


class TestGetAuthUrl:
    """Test authorization URL generation."""
    
    @patch('backend.auth.keycloak_service.requests.get')
    def test_get_auth_url_success(self, mock_requests_get, keycloak_svc, mock_keycloak_client):
        """Test successful auth URL generation."""
        # Mock the well-known config HTTP response
        mock_response = Mock()
        mock_response.json.return_value = {
            'authorization_endpoint': 'https://keycloak.example.com/auth/realms/test/protocol/openid-connect/auth'
        }
        mock_response.raise_for_status = Mock()
        mock_requests_get.return_value = mock_response
        
        auth_url = keycloak_svc.get_auth_url(state="test-state-123")
        
        assert "https://keycloak.example.com" in auth_url
        assert "state=test-state-123" in auth_url
    
    @patch('backend.auth.keycloak_service.requests.get')
    def test_get_auth_url_failure(self, mock_requests_get, keycloak_svc, mock_keycloak_client):
        """Test auth URL generation failure."""
        # Mock network error
        mock_requests_get.side_effect = Exception("Connection failed")
        
        with pytest.raises(ValueError, match="Failed to generate authorization URL"):
            keycloak_svc.get_auth_url(state="test-state")


class TestExchangeCodeForToken:
    """Test authorization code exchange."""
    
    def test_exchange_code_success(self, keycloak_svc, mock_keycloak_client):
        """Test successful code exchange."""
        mock_keycloak_client.token.return_value = {
            "access_token": "access-token-123",
            "refresh_token": "refresh-token-456",
            "expires_in": 300,
            "token_type": "Bearer"
        }
        
        result = keycloak_svc.exchange_code_for_token(code="auth-code-123")
        
        assert result["access_token"] == "access-token-123"
        assert result["refresh_token"] == "refresh-token-456"
        mock_keycloak_client.token.assert_called_once()
    
    def test_exchange_code_authentication_error(self, keycloak_svc, mock_keycloak_client):
        """Test code exchange with authentication error."""
        mock_keycloak_client.token.side_effect = KeycloakAuthenticationError("Invalid code")
        
        with pytest.raises(ValueError, match="Authentication failed"):
            keycloak_svc.exchange_code_for_token(code="invalid-code")
    
    def test_exchange_code_connection_error(self, keycloak_svc, mock_keycloak_client):
        """Test code exchange with connection error."""
        mock_keycloak_client.token.side_effect = KeycloakConnectionError("Service unavailable")
        
        with pytest.raises(ValueError, match="KeyCloak service unavailable"):
            keycloak_svc.exchange_code_for_token(code="auth-code")


class TestGetUserInfo:
    """Test user information retrieval."""
    
    def test_get_user_info_success(self, keycloak_svc, mock_keycloak_client):
        """Test successful user info retrieval."""
        mock_keycloak_client.userinfo.return_value = {
            "sub": "user-uuid-123",
            "email": "user@example.com",
            "name": "Test User",
            "given_name": "Test",
            "family_name": "User"
        }
        
        userinfo = keycloak_svc.get_user_info(access_token="access-token")
        
        assert userinfo["sub"] == "user-uuid-123"
        assert userinfo["email"] == "user@example.com"
        assert userinfo["name"] == "Test User"
    
    def test_get_user_info_failure(self, keycloak_svc, mock_keycloak_client):
        """Test user info retrieval failure."""
        mock_keycloak_client.userinfo.side_effect = KeycloakGetError("Unauthorized")
        
        with pytest.raises(ValueError, match="Failed to retrieve user information"):
            keycloak_svc.get_user_info(access_token="invalid-token")


class TestTokenIntrospection:
    """Test token introspection."""
    
    def test_introspect_token_active(self, keycloak_svc, mock_keycloak_client):
        """Test introspecting an active token."""
        mock_keycloak_client.introspect.return_value = {
            "active": True,
            "sub": "user-uuid",
            "exp": 1234567890,
            "iat": 1234567800
        }
        
        result = keycloak_svc.introspect_token(token="access-token")
        
        assert result["active"] is True
        assert result["sub"] == "user-uuid"
    
    def test_introspect_token_inactive(self, keycloak_svc, mock_keycloak_client):
        """Test introspecting an inactive token."""
        mock_keycloak_client.introspect.return_value = {"active": False}
        
        result = keycloak_svc.introspect_token(token="expired-token")
        
        assert result["active"] is False
    
    def test_introspect_token_failure(self, keycloak_svc, mock_keycloak_client):
        """Test token introspection failure."""
        mock_keycloak_client.introspect.side_effect = Exception("Introspection failed")
        
        with pytest.raises(ValueError, match="Token introspection failed"):
            keycloak_svc.introspect_token(token="token")


class TestRefreshToken:
    """Test token refresh."""
    
    def test_refresh_token_success(self, keycloak_svc, mock_keycloak_client):
        """Test successful token refresh."""
        mock_keycloak_client.refresh_token.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 300
        }
        
        result = keycloak_svc.refresh_token(refresh_token="refresh-token")
        
        assert result["access_token"] == "new-access-token"
        assert result["refresh_token"] == "new-refresh-token"
    
    def test_refresh_token_invalid(self, keycloak_svc, mock_keycloak_client):
        """Test refresh with invalid token."""
        mock_keycloak_client.refresh_token.side_effect = KeycloakAuthenticationError("Invalid token")
        
        with pytest.raises(ValueError, match="Invalid refresh token"):
            keycloak_svc.refresh_token(refresh_token="invalid-refresh")


class TestLogout:
    """Test logout functionality."""
    
    def test_logout_success(self, keycloak_svc, mock_keycloak_client):
        """Test successful logout."""
        mock_keycloak_client.logout.return_value = None
        
        result = keycloak_svc.logout(refresh_token="refresh-token")
        
        assert result is True
        mock_keycloak_client.logout.assert_called_once_with("refresh-token")
    
    def test_logout_already_invalid(self, keycloak_svc, mock_keycloak_client):
        """Test logout with already invalid token."""
        mock_keycloak_client.logout.side_effect = Exception("Token invalid")
        
        # Should still return True (goal is to clear session)
        result = keycloak_svc.logout(refresh_token="invalid-token")
        
        assert result is True


class TestDecodeToken:
    """Test token decoding."""
    
    def test_decode_token_success(self, keycloak_svc):
        """Test successful token decode."""
        # Create a sample JWT token (unverified decode)
        import jwt
        payload = {"sub": "user-123", "email": "test@example.com", "roles": ["admin"]}
        token = jwt.encode(payload, "secret", algorithm="HS256")
        
        decoded = keycloak_svc.decode_token(token)
        
        assert decoded["sub"] == "user-123"
        assert decoded["email"] == "test@example.com"
    
    def test_decode_token_invalid(self, keycloak_svc):
        """Test decoding invalid token."""
        with pytest.raises(ValueError, match="Invalid token format"):
            keycloak_svc.decode_token("not-a-valid-token")


class TestExtractRoles:
    """Test role extraction from token."""
    
    def test_extract_roles_from_payload(self, keycloak_svc):
        """Test extracting roles from KeyCloak token payload."""
        payload = {
            "sub": "user-123",
            "resource_access": {
                settings.KEYCLOAK_CLIENT_ID: {
                    "roles": ["admin", "staff_manager"]
                }
            }
        }
        
        roles = keycloak_svc.extract_roles(payload)
        
        assert "admin" in roles
        assert "staff_manager" in roles
        assert len(roles) == 2
    
    def test_extract_roles_no_resource_access(self, keycloak_svc):
        """Test extracting roles when resource_access is missing."""
        payload = {"sub": "user-123"}
        
        roles = keycloak_svc.extract_roles(payload)
        
        assert roles == []
    
    def test_extract_roles_no_client_roles(self, keycloak_svc):
        """Test extracting roles when client has no roles."""
        payload = {
            "sub": "user-123",
            "resource_access": {
                "other-client": {
                    "roles": ["some-role"]
                }
            }
        }
        
        roles = keycloak_svc.extract_roles(payload)
        
        assert roles == []


class TestGenerateAppTokens:
    """Test application token generation."""
    
    @patch('backend.auth.keycloak_service.jwt_handler')
    def test_generate_app_tokens(self, mock_jwt_handler, keycloak_svc):
        """Test generating application JWT tokens."""
        mock_jwt_handler.generate_access_token.return_value = "app-access-token"
        mock_jwt_handler.generate_refresh_token.return_value = "app-refresh-token"
        
        tokens = keycloak_svc.generate_app_tokens(
            user_id="user-uuid",
            email="user@example.com",
            name="Test User",
            roles=["admin"]
        )
        
        assert tokens["access_token"] == "app-access-token"
        assert tokens["refresh_token"] == "app-refresh-token"
        assert tokens["token_type"] == "Bearer"
        assert tokens["expires_in"] == 1800
        
        mock_jwt_handler.generate_access_token.assert_called_once_with(
            user_id="user-uuid",
            email="user@example.com",
            name="Test User",
            roles=["admin"]
        )
        mock_jwt_handler.generate_refresh_token.assert_called_once_with(
            user_id="user-uuid"
        )
