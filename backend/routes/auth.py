"""Authentication API endpoints."""

import logging
import secrets
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, Role, UserRole
from backend.auth.keycloak_service import keycloak_service
from backend.auth.jwt_handler import jwt_handler
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Request/Response Models
class LoginResponse(BaseModel):
    """Response for successful login."""
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user: dict


class RefreshTokenRequest(BaseModel):
    """Request to refresh access token."""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Request to logout."""
    refresh_token: Optional[str] = None


# In-memory state storage (in production, use Redis or similar)
# Maps state -> {created_at, purpose}
_auth_states = {}


def generate_state() -> str:
    """Generate a secure random state for CSRF protection."""
    state = secrets.token_urlsafe(32)
    _auth_states[state] = {"purpose": "login"}
    return state


def validate_state(state: str) -> bool:
    """Validate and consume a state token."""
    if state in _auth_states:
        _auth_states.pop(state)
        return True
    return False


@router.get("/login")
async def login():
    """
    Initiate KeyCloak OIDC login flow.
    
    Returns redirect to KeyCloak login page.
    """
    try:
        # Generate CSRF state token
        state = generate_state()
        
        # Get KeyCloak authorization URL
        auth_url = keycloak_service.get_auth_url(state=state)
        
        logger.info("Redirecting to KeyCloak login")
        return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
        
    except Exception as e:
        logger.error(f"Login initiation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate login: {str(e)}"
        )


@router.get("/callback")
async def auth_callback(
    code: str = Query(..., description="Authorization code from KeyCloak"),
    state: str = Query(..., description="CSRF protection state"),
    db: Session = Depends(get_db)
):
    """
    Handle KeyCloak OIDC callback after user authentication.
    
    This endpoint:
    1. Validates the state parameter (CSRF protection)
    2. Exchanges authorization code for KeyCloak tokens
    3. Retrieves user information from KeyCloak
    4. Creates or updates user in local database
    5. Generates our application JWT tokens
    6. Returns tokens to client
    """
    try:
        # Validate state to prevent CSRF attacks
        if not validate_state(state):
            logger.warning(f"Invalid or expired state parameter: {state}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter. Please try logging in again."
            )
        
        # Exchange authorization code for tokens
        keycloak_tokens = keycloak_service.exchange_code_for_token(code)
        keycloak_access_token = keycloak_tokens["access_token"]
        
        # Get user information from KeyCloak
        userinfo = keycloak_service.get_user_info(keycloak_access_token)
        
        # Extract user details
        keycloak_user_id = userinfo.get("sub")  # KeyCloak user ID
        email = userinfo.get("email")
        first_name = userinfo.get("given_name", "")
        last_name = userinfo.get("family_name", "")
        full_name = userinfo.get("name", f"{first_name} {last_name}".strip())
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not provided by KeyCloak"
            )
        
        # Decode KeyCloak token to extract roles
        keycloak_payload = keycloak_service.decode_token(keycloak_access_token)
        keycloak_roles = keycloak_service.extract_roles(keycloak_payload)
        
        # Find or create user in local database
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            # Create new user
            user = User(
                keycloak_id=keycloak_user_id,  # Store Keycloak user UUID
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_active=True
            )
            db.add(user)
            db.flush()
            logger.info(f"Created new user: {email}")
        else:
            # Update existing user
            user.keycloak_id = keycloak_user_id  # Update Keycloak ID
            user.first_name = first_name
            user.last_name = last_name
            logger.info(f"Updated existing user: {email}")
        
        # Map KeyCloak roles to local roles
        local_role_names = map_keycloak_roles_to_local(keycloak_roles)
        
        # Ensure user has at least a default role if no roles found
        if not local_role_names:
            local_role_names = ["staff_viewer"]  # Default minimum role
            logger.warning(f"No roles found for user {email}, defaulting to staff_viewer")
        
        # Get local role objects
        local_roles = db.query(Role).filter(Role.name.in_(local_role_names)).all()
        
        # Assign roles to user (clear existing UserRoles and create new ones)
        # Clear existing user role associations
        db.query(UserRole).filter(UserRole.user_id == user.id).delete()
        
        # Create new user role associations
        for role in local_roles:
            user_role = UserRole(
                user_id=user.id,
                role_id=role.id
            )
            db.add(user_role)
        
        db.commit()
        db.refresh(user)
        
        # Generate our application JWT tokens
        user_full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
        # Extract role names from user.roles (UserRole objects)
        role_names = [user_role.role.name for user_role in user.roles]
        app_tokens = keycloak_service.generate_app_tokens(
            user_id=str(user.id),
            email=user.email,
            name=user_full_name,
            roles=role_names
        )
        
        logger.info(f"Successfully authenticated user: {email}")
        
        return LoginResponse(
            access_token=app_tokens["access_token"],
            refresh_token=app_tokens["refresh_token"],
            token_type=app_tokens["token_type"],
            expires_in=app_tokens["expires_in"],
            user={
                "id": str(user.id),
                "email": user.email,
                "name": user_full_name,
                "roles": role_names
            }
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"KeyCloak error during callback: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Callback processing failed: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}"
        )


@router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """
    Refresh access token using refresh token.
    
    This uses our application's refresh token (not KeyCloak's).
    """
    try:
        # Validate our refresh token
        token_data = jwt_handler.validate_token(
            request.refresh_token,
            token_type="refresh"
        )
        
        # Get user from database (convert string UUID to UUID object)
        user_id = UUID(token_data.sub) if isinstance(token_data.sub, str) else token_data.sub
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )
        
        # Generate new access token
        user_full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
        role_names = [user_role.role.name for user_role in user.roles]
        new_access_token = jwt_handler.generate_access_token(
            user_id=str(user.id),
            email=user.email,
            name=user_full_name,
            roles=role_names
        )
        
        logger.info(f"Refreshed access token for user: {user.email}")
        
        return {
            "access_token": new_access_token,
            "token_type": "Bearer",
            "expires_in": 1800
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )


@router.post("/logout")
async def logout(
    request: LogoutRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Logout user by clearing tokens.
    
    In a production system with Redis, this would blacklist the tokens.
    For now, client should discard tokens.
    """
    try:
        # If KeyCloak refresh token provided, invalidate it
        if request.refresh_token:
            try:
                # This would be the KeyCloak refresh token, not ours
                # For now, we just log it - client discards tokens
                logger.info(f"Logout requested for user: {current_user.email}")
            except Exception as e:
                logger.warning(f"KeyCloak logout failed: {str(e)}")
        
        return {
            "message": "Successfully logged out",
            "detail": "Please discard your tokens"
        }
        
    except Exception as e:
        logger.error(f"Logout failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed"
        )


@router.get("/me")
async def get_current_user_info(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current authenticated user information.
    """
    try:
        # Convert string UUID to UUID object
        user_id = UUID(current_user.sub) if isinstance(current_user.sub, str) else current_user.sub
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user_full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
        return {
            "id": str(user.id),
            "email": user.email,
            "name": user_full_name,
            "roles": [user_role.role.name for user_role in user.roles],
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user information"
        )


def map_keycloak_roles_to_local(keycloak_roles: list) -> list:
    """
    Map KeyCloak roles to local application roles.
    
    Args:
        keycloak_roles: List of role names from KeyCloak
        
    Returns:
        List of local role names
    """
    # Direct 1:1 mapping for now
    # In production, this could be more sophisticated
    role_mapping = {
        "admin": "admin",
        "staff_manager": "staff_manager",
        "reviewer": "reviewer",
        "staff_viewer": "staff_viewer",
        # Add aliases if needed
        "administrator": "admin",
        "manager": "staff_manager",
        "approver": "reviewer",
        "viewer": "staff_viewer"
    }
    
    local_roles = []
    for keycloak_role in keycloak_roles:
        local_role = role_mapping.get(keycloak_role.lower())
        if local_role and local_role not in local_roles:
            local_roles.append(local_role)
    
    return local_roles
