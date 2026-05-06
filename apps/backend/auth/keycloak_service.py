"""KeyCloak OIDC authentication service."""

import logging
import requests
from typing import Optional, Dict, Any
from urllib.parse import urlencode
from keycloak import (
    KeycloakOpenID,
    KeycloakAuthenticationError,
)

from backend.config import settings
from backend.auth.jwt_handler import jwt_handler

logger = logging.getLogger(__name__)


class KeyCloakService:
    """Service for KeyCloak OIDC authentication.

    Note: BC Gov Keycloak uses a non-standard base path (/auth) which python-keycloak
    v7.x doesn't handle properly. We work around this by using direct HTTP requests
    for URL construction while still using the library for token operations.
    """

    def __init__(self):
        """Initialize KeyCloak OIDC client."""
        self.enabled = True
        self.keycloak_openid = None
        self.base_url = ""
        self.realm_url = ""
        self._well_known_config = None

        required_values = [
            settings.KEYCLOAK_SERVER_URL,
            settings.KEYCLOAK_REALM,
            settings.KEYCLOAK_CLIENT_ID,
            settings.KEYCLOAK_CLIENT_SECRET,
            settings.KEYCLOAK_REDIRECT_URI,
        ]

        if not all(required_values):
            self.enabled = False
            logger.warning("KeyCloak disabled: missing configuration values.")
            return

        try:
            self.keycloak_openid = KeycloakOpenID(
                server_url=settings.KEYCLOAK_SERVER_URL,
                client_id=settings.KEYCLOAK_CLIENT_ID,
                realm_name=settings.KEYCLOAK_REALM,
                client_secret_key=settings.KEYCLOAK_CLIENT_SECRET,
                verify=settings.KEYCLOAK_VERIFY_TLS,
            )

            # For BC Gov: Construct correct base URLs manually
            self.base_url = settings.KEYCLOAK_SERVER_URL.rstrip("/")
            if not self.base_url.endswith("/auth"):
                self.base_url = f"{self.base_url}/auth"
            self.realm_url = f"{self.base_url}/realms/{settings.KEYCLOAK_REALM}"

            logger.info(
                f"KeyCloak client initialized for realm: {settings.KEYCLOAK_REALM}"
            )
            logger.info(f"Realm URL: {self.realm_url}")
        except Exception as e:
            logger.error(f"Failed to initialize KeyCloak client: {str(e)}")
            raise

    def _ensure_enabled(self) -> None:
        """Ensure Keycloak is configured before use."""
        if not self.enabled:
            raise ValueError(
                "Keycloak is not configured. Set KEYCLOAK_* environment variables."
            )

    def _get_well_known_config(self) -> Dict[str, Any]:
        """Get OpenID well-known configuration (cached)."""
        self._ensure_enabled()
        if self._well_known_config is None:
            url = f"{self.realm_url}/.well-known/openid-configuration"
            response = requests.get(
                url, timeout=10, verify=settings.KEYCLOAK_VERIFY_TLS
            )
            response.raise_for_status()
            self._well_known_config = response.json()
        return self._well_known_config

    def get_auth_url(self, state: str, redirect_uri: Optional[str] = None) -> str:
        """
        Get the authorization URL for OIDC login.

        Args:
            state: CSRF protection state parameter
            redirect_uri: Frontend callback URL to embed in the auth URL.
                          Falls back to KEYCLOAK_REDIRECT_URI when not supplied.

        Returns:
            Authorization URL for redirect
        """
        try:
            # Use well-known config to get correct authorization endpoint
            config = self._get_well_known_config()
            auth_endpoint = config["authorization_endpoint"]

            params = {
                "client_id": settings.KEYCLOAK_CLIENT_ID,
                "redirect_uri": redirect_uri or settings.KEYCLOAK_REDIRECT_URI,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
            }

            auth_url = f"{auth_endpoint}?{urlencode(params)}"
            logger.debug(f"Generated auth URL: {auth_url[:100]}...")
            return auth_url
        except Exception as e:
            logger.error(f"Failed to generate auth URL: {str(e)}")
            raise ValueError(f"Failed to generate authorization URL: {str(e)}")

    def exchange_code_for_token(
        self, code: str, redirect_uri: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens.

        Args:
            code: Authorization code from KeyCloak callback
            redirect_uri: Must match the redirect_uri used in the original auth URL.
                          Falls back to KEYCLOAK_REDIRECT_URI when not supplied.

        Returns:
            Token response with access_token, refresh_token, etc.

        Raises:
            ValueError: If token exchange fails
        """
        try:
            # Use well-known config to get correct token endpoint
            config = self._get_well_known_config()
            token_endpoint = config["token_endpoint"]

            # Prepare token request
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri or settings.KEYCLOAK_REDIRECT_URI,
                "client_id": settings.KEYCLOAK_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
            }

            response = requests.post(
                token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
                verify=settings.KEYCLOAK_VERIFY_TLS,
            )
            response.raise_for_status()
            token_response = response.json()

            logger.info("Successfully exchanged authorization code for tokens")
            return token_response
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error during token exchange: {str(e)}")
            if e.response is not None:
                logger.error(f"Response: {e.response.text[:200]}")
            raise ValueError(f"Authentication failed: {str(e)}")
        except Exception as e:
            logger.error(f"Token exchange failed: {str(e)}")
            raise ValueError(f"Token exchange failed: {str(e)}")

    def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get user information from KeyCloak using access token.

        Args:
            access_token: KeyCloak access token

        Returns:
            User information dict with sub, email, name, etc.

        Raises:
            ValueError: If user info retrieval fails
        """
        try:
            # Use well-known config to get correct userinfo endpoint
            config = self._get_well_known_config()
            userinfo_endpoint = config["userinfo_endpoint"]

            response = requests.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
                verify=settings.KEYCLOAK_VERIFY_TLS,
            )
            response.raise_for_status()
            userinfo = response.json()

            logger.info(f"Retrieved user info for: {userinfo.get('email', 'unknown')}")
            return userinfo
        except requests.exceptions.HTTPError as e:
            logger.error(f"Failed to get user info: {str(e)}")
            raise ValueError(f"Failed to retrieve user information: {str(e)}")
        except Exception as e:
            logger.error(f"User info retrieval error: {str(e)}")
            raise ValueError(f"User info retrieval failed: {str(e)}")

    def introspect_token(self, token: str) -> Dict[str, Any]:
        """
        Introspect a token to validate and get token details.

        Args:
            token: Token to introspect (access or refresh token)

        Returns:
            Introspection response with active status and claims

        Raises:
            ValueError: If introspection fails
        """
        self._ensure_enabled()
        try:
            introspection = self.keycloak_openid.introspect(token)
            return introspection
        except Exception as e:
            logger.error(f"Token introspection failed: {str(e)}")
            raise ValueError(f"Token introspection failed: {str(e)}")

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: KeyCloak refresh token

        Returns:
            New token response with access_token, refresh_token, etc.

        Raises:
            ValueError: If token refresh fails
        """
        self._ensure_enabled()
        try:
            token_response = self.keycloak_openid.refresh_token(refresh_token)
            logger.info("Successfully refreshed access token")
            return token_response
        except KeycloakAuthenticationError as e:
            logger.error(f"Token refresh authentication error: {str(e)}")
            raise ValueError(f"Invalid refresh token: {str(e)}")
        except Exception as e:
            logger.error(f"Token refresh failed: {str(e)}")
            raise ValueError(f"Token refresh failed: {str(e)}")

    def logout(self, refresh_token: str) -> bool:
        """
        Logout user by invalidating refresh token.

        Args:
            refresh_token: KeyCloak refresh token to invalidate

        Returns:
            True if logout successful
        """
        self._ensure_enabled()
        try:
            config = self._get_well_known_config()
            logout_endpoint = config.get("end_session_endpoint")

            if logout_endpoint:
                response = requests.post(
                    logout_endpoint,
                    data={
                        "client_id": settings.KEYCLOAK_CLIENT_ID,
                        "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
                        "refresh_token": refresh_token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10,
                    verify=settings.KEYCLOAK_VERIFY_TLS,
                )
                # Some Keycloak installations return 204 No Content, some return 200.
                if response.status_code not in (200, 204):
                    logger.warning(
                        "Keycloak end-session endpoint returned non-success status: %s",
                        response.status_code,
                    )

            # Keep library call as fallback/compatibility.
            try:
                self.keycloak_openid.logout(refresh_token)
            except Exception as fallback_error:
                logger.debug(f"Library logout fallback warning: {str(fallback_error)}")

            logger.info("Successfully logged out user")
            return True
        except Exception as e:
            logger.warning(f"Logout failed (token may already be invalid): {str(e)}")
            # Return True anyway since the goal is to clear the session
            return True

    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decode a KeyCloak token without verification (for claims extraction).

        Args:
            token: JWT token from KeyCloak

        Returns:
            Decoded token payload
        """
        try:
            # KeyCloak tokens are standard JWTs, decode without verification for claims
            import jwt

            decoded = jwt.decode(token, options={"verify_signature": False})
            return decoded
        except Exception as e:
            logger.error(f"Token decode failed: {str(e)}")
            raise ValueError(f"Invalid token format: {str(e)}")

    def extract_roles(self, keycloak_token_payload: Dict[str, Any]) -> list:
        """
        Extract roles from KeyCloak token payload.

        Args:
            keycloak_token_payload: Decoded KeyCloak token

        Returns:
            List of role names from client roles
        """
        try:
            # KeyCloak client roles are in resource_access.[client_id].roles
            resource_access = keycloak_token_payload.get("resource_access", {})
            client_roles = resource_access.get(settings.KEYCLOAK_CLIENT_ID, {})
            roles = client_roles.get("roles", [])

            logger.info(f"Extracted roles: {roles}")
            return roles
        except Exception as e:
            logger.warning(
                f"Failed to extract roles, defaulting to empty list: {str(e)}"
            )
            return []

    def generate_app_tokens(
        self, user_id: str, email: str, name: str, roles: list, permissions: list = None
    ) -> Dict[str, str]:
        """
        Generate our application JWT tokens after KeyCloak authentication.

        Args:
            user_id: User UUID from our database
            email: User email
            name: User display name
            roles: List of role names
            permissions: Flat list of granular permission strings

        Returns:
            Dict with access_token and refresh_token
        """
        access_token = jwt_handler.generate_access_token(
            user_id=user_id,
            email=email,
            name=name,
            roles=roles,
            permissions=permissions if permissions is not None else [],
        )

        refresh_token = jwt_handler.generate_refresh_token(user_id=user_id)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": 1800,  # 30 minutes in seconds
        }


# Global KeyCloak service instance
keycloak_service = KeyCloakService()
