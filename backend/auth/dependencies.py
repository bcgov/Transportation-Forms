"""FastAPI dependencies for JWT authentication and authorization."""

from typing import Optional
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials

from backend.auth.jwt_handler import jwt_handler, TokenData
from backend.auth.authorization import (
    require_permission,
    require_any_permission,
    require_all_permissions,
    has_permission,
    has_any_permission,
    has_all_permissions,
    is_admin,
)


security = HTTPBearer(
    description="JWT Bearer token",
    auto_error=True
)

# Development mode - bypass authentication
ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
IS_DEVELOPMENT = ENVIRONMENT == "development"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> TokenData:
    """
    Extract and validate JWT token from request headers.
    
    Args:
        credentials: HTTP Bearer credentials from request header
        
    Returns:
        TokenData object with user information
        
    Raises:
        HTTPException: 401 if token is invalid or missing
    """
    token = credentials.credentials
    
    # Development mode: allow demo token
    if IS_DEVELOPMENT and token == "demo-token":
        return TokenData(
            sub="550e8400-e29b-41d4-a716-446655440000",  # Demo UUID
            email="demo@example.com",
            name="Demo User",
            roles=["admin"],
            token_type="access"
        )
    
    try:
        token_data = jwt_handler.validate_token(token, token_type="access")
        if token_data is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return token_data
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))
) -> Optional[TokenData]:
    """
    Extract and validate JWT token if present (optional authentication).
    
    Args:
        credentials: HTTP Bearer credentials (optional)
        
    Returns:
        TokenData object if token is present and valid, None otherwise
    """
    if credentials is None:
        return None
    
    token = credentials.credentials
    
    try:
        token_data = jwt_handler.validate_token(token, token_type="access")
        return token_data
    except ValueError:
        return None


async def get_user_with_role(required_roles: list):
    """
    Factory function to create a dependency that checks for required roles.
    
    Args:
        required_roles: List of role names/IDs that are allowed
        
    Returns:
        Async function that validates user has required role
    """
    async def check_role(user: TokenData = Depends(get_current_user)) -> TokenData:
        if not any(role in user.roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {required_roles}"
            )
        return user
    
    return check_role


# Predefined role checkers
async def require_admin(user: TokenData = Depends(get_current_user)) -> TokenData:
    """Dependency to require admin role."""
    if "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required"
        )
    return user


async def require_staff_manager(user: TokenData = Depends(get_current_user)) -> TokenData:
    """Dependency to require staff manager role."""
    required_roles = ["admin", "staff_manager"]
    if not any(role in user.roles for role in required_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff manager or admin role required"
        )
    return user


async def require_reviewer(user: TokenData = Depends(get_current_user)) -> TokenData:
    """Dependency to require reviewer role."""
    required_roles = ["admin", "reviewer"]
    if not any(role in user.roles for role in required_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer or admin role required"
        )
    return user
