"""JWT token generation, validation, and refresh logic."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import jwt
from jwt import PyJWTError

from backend.auth.keys import PRIVATE_KEY, PUBLIC_KEY


# Token configuration (in seconds)
ACCESS_TOKEN_EXPIRY = 30 * 60  # 30 minutes
REFRESH_TOKEN_EXPIRY = 7 * 24 * 60 * 60  # 7 days
ALGORITHM = "RS256"
TOKEN_ISSUER = "transportation-forms-api"
TOKEN_AUDIENCE = "transportation-forms-web"


class TokenData:
    """Represents decoded JWT token data."""
    
    def __init__(
        self,
        sub: str,
        email: str,
        name: str,
        roles: list,
        token_type: str = "access"
    ):
        self.sub = sub  # Subject (user ID)
        self.email = email
        self.name = name
        self.roles = roles
        self.token_type = token_type


class JWTHandler:
    """JWT token handler for generating, validating, and refreshing tokens."""
    
    @staticmethod
    def generate_access_token(
        user_id: str,
        email: str,
        name: str,
        roles: list,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Generate an access token.
        
        Args:
            user_id: User UUID
            email: User email address
            name: User display name
            roles: List of role IDs/names
            expires_delta: Custom expiry time (defaults to 30 minutes)
            
        Returns:
            Encoded JWT token string
        """
        if expires_delta is None:
            expires_delta = timedelta(seconds=ACCESS_TOKEN_EXPIRY)
        
        now = datetime.now(timezone.utc)
        expire = now + expires_delta
        
        payload = {
            "sub": user_id,
            "email": email,
            "name": name,
            "roles": roles,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "exp": expire.timestamp(),
            "iat": now.timestamp(),
            "type": "access"
        }
        
        token = jwt.encode(payload, PRIVATE_KEY, algorithm=ALGORITHM)
        return token
    
    @staticmethod
    def generate_refresh_token(
        user_id: str,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Generate a refresh token.
        
        Args:
            user_id: User UUID
            expires_delta: Custom expiry time (defaults to 7 days)
            
        Returns:
            Encoded JWT refresh token string
        """
        if expires_delta is None:
            expires_delta = timedelta(seconds=REFRESH_TOKEN_EXPIRY)
        
        now = datetime.now(timezone.utc)
        expire = now + expires_delta
        
        payload = {
            "sub": user_id,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "exp": expire.timestamp(),
            "iat": now.timestamp(),
            "type": "refresh"
        }
        
        token = jwt.encode(payload, PRIVATE_KEY, algorithm=ALGORITHM)
        return token
    
    @staticmethod
    def validate_token(token: str, token_type: str = "access") -> Optional[TokenData]:
        """
        Validate and decode a JWT token.
        
        Args:
            token: JWT token string
            token_type: Expected token type ('access' or 'refresh')
            
        Returns:
            TokenData object if valid, None if invalid
            
        Raises:
            ValueError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                PUBLIC_KEY,
                algorithms=[ALGORITHM],
                audience=TOKEN_AUDIENCE,
                issuer=TOKEN_ISSUER
            )
            
            # Verify token type
            if payload.get("type") != token_type:
                raise ValueError(f"Invalid token type. Expected {token_type}, got {payload.get('type')}")
            
            # For refresh tokens, only sub is required
            if token_type == "refresh":
                return TokenData(
                    sub=payload.get("sub"),
                    email="",
                    name="",
                    roles=[],
                    token_type=token_type
                )
            
            # For access tokens, decode all claims
            return TokenData(
                sub=payload.get("sub"),
                email=payload.get("email"),
                name=payload.get("name"),
                roles=payload.get("roles", []),
                token_type=token_type
            )
            
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidAudienceError:
            raise ValueError("Invalid token audience")
        except jwt.InvalidIssuerError:
            raise ValueError("Invalid token issuer")
        except PyJWTError as e:
            raise ValueError(f"Token validation failed: {str(e)}")
    
    @staticmethod
    def refresh_access_token(refresh_token: str, user_id: str, email: str, name: str, roles: list) -> str:
        """
        Generate a new access token from a refresh token.
        
        Args:
            refresh_token: Valid refresh token string
            user_id: User UUID
            email: User email
            name: User name
            roles: User roles
            
        Returns:
            New access token string
            
        Raises:
            ValueError: If refresh token is invalid
        """
        token_data = JWTHandler.validate_token(refresh_token, token_type="refresh")
        
        if token_data is None:
            raise ValueError("Invalid refresh token")
        
        if token_data.sub != user_id:
            raise ValueError("Refresh token user ID mismatch")
        
        return JWTHandler.generate_access_token(user_id, email, name, roles)
    
    @staticmethod
    def get_token_expiry_seconds(token: str, token_type: str = "access") -> Optional[int]:
        """
        Get remaining time until token expiry.
        
        Args:
            token: JWT token string
            token_type: Expected token type
            
        Returns:
            Seconds until expiry, or None if token is invalid
        """
        try:
            # Decode without verifying expiration to get expiry timestamp
            payload = jwt.decode(
                token,
                PUBLIC_KEY,
                algorithms=[ALGORITHM],
                audience=TOKEN_AUDIENCE,
                issuer=TOKEN_ISSUER,
                options={"verify_exp": False}  # Don't reject expired tokens here
            )
            
            exp_timestamp = payload.get("exp")
            if exp_timestamp is None:
                return None
            
            now = datetime.now(timezone.utc).timestamp()
            seconds_remaining = int(exp_timestamp - now)
            
            return max(0, seconds_remaining)
            
        except PyJWTError:
            return None


# Export main handler
jwt_handler = JWTHandler()
