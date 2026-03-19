"""Authentication API endpoints."""

import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, status, Depends, Request, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, Role, UserRole, AuditLog
from backend.auth.keycloak_service import keycloak_service
from backend.auth.jwt_handler import jwt_handler
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Request/Response Models
class LoginRequest(BaseModel):
    """Optional request body for login initiation."""
    frontend_redirect_uri: Optional[str] = None


class LoginResponse(BaseModel):
    """Response for successful login."""
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user: dict


class LoginInitResponse(BaseModel):
    """Response for login initiation."""
    authorization_url: str
    state: str


class CallbackRequest(BaseModel):
    """Request to exchange Keycloak code for app tokens."""
    code: str
    state: str


class RefreshTokenRequest(BaseModel):
    """Request to refresh access token."""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Request to logout."""
    refresh_token: Optional[str] = None


# In-memory state storage (in production, use Redis or similar)
# Maps state -> {created_at, purpose, redirect_uri}
_auth_states = {}


def generate_state(redirect_uri: Optional[str] = None) -> str:
    """Generate a secure random state for CSRF protection."""
    state = secrets.token_urlsafe(32)
    _auth_states[state] = {"purpose": "login", "redirect_uri": redirect_uri}
    return state


def validate_state(state: str) -> Optional[dict]:
    """Validate and consume a state token. Returns state data dict or None if invalid."""
    return _auth_states.pop(state, None)


def _get_request_metadata(request: Request) -> tuple[Optional[str], Optional[str]]:
    """Extract request metadata for audit logs."""
    return request.client.host if request.client else None, request.headers.get("user-agent")


def _is_allowed_redirect_uri(uri: str) -> bool:
    """Check whether the redirect URI's origin is in the configured CORS origins allowlist."""
    try:
        parsed = urlparse(uri)
        if not parsed.scheme or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        allowed_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
        return origin in allowed_origins
    except Exception:
        return False


def _resolve_redirect_uri(http_request: Request, body: Optional[LoginRequest]) -> str:
    """
    Determine the redirect URI to embed in the Keycloak authorization URL.

    Priority:
      1. Explicit ``frontend_redirect_uri`` from the request body (if present and allowed).
      2. Derived from the ``Origin`` request header + '/callback' (if origin is allowed).
      3. Configured ``KEYCLOAK_REDIRECT_URI`` as a final fallback.
    """
    # Priority 1: explicit URI supplied by the frontend
    if body and body.frontend_redirect_uri:
        if not _is_allowed_redirect_uri(body.frontend_redirect_uri):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Redirect URI origin is not in the allowed origins list",
            )
        return body.frontend_redirect_uri

    # Priority 2: derive from the browser's Origin header
    origin = http_request.headers.get("origin")
    if origin:
        derived = f"{origin}/callback"
        if _is_allowed_redirect_uri(derived):
            return derived

    # Priority 3: fall back to static env-var config
    return settings.KEYCLOAK_REDIRECT_URI or ""


def _create_auth_audit_log(
    db: Session,
    *,
    action: str,
    user: Optional[User],
    keycloak_id: Optional[str],
    ip_address: Optional[str],
    user_agent: Optional[str],
    extra_values: Optional[dict] = None,
) -> None:
    """Create and persist authentication audit record."""
    payload = {"keycloak_id": keycloak_id} if keycloak_id else {}
    if extra_values:
        payload.update(extra_values)

    db.add(
        AuditLog(
            entity_type="auth",
            entity_id=str(user.id) if user else "unknown",
            action=action,
            user_id=user.id if user else None,
            new_values=payload or None,
            ip_address=ip_address,
            user_agent=user_agent,
            description=f"{action} event",
        )
    )


@router.post("/login", response_model=LoginInitResponse)
async def login(
    http_request: Request,
    request: Optional[LoginRequest] = Body(default=None),
):
    """
    Initiate KeyCloak OIDC login flow.

    Accepts an optional JSON body with ``frontend_redirect_uri`` — the URL
    Keycloak should redirect the browser back to after authentication (must
    resolve to the frontend ``/callback`` page).  When omitted the redirect
    URI is derived from the request ``Origin`` header or the configured
    ``KEYCLOAK_REDIRECT_URI`` fallback.

    Returns Keycloak authorization URL for frontend redirect.
    """
    try:
        redirect_uri = _resolve_redirect_uri(http_request, request)
        state = generate_state(redirect_uri=redirect_uri)
        auth_url = keycloak_service.get_auth_url(state=state, redirect_uri=redirect_uri)

        logger.info("Generated Keycloak login URL")
        return LoginInitResponse(authorization_url=auth_url, state=state)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login initiation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to initiate login flow"
        )


@router.post("/callback", response_model=LoginResponse)
async def auth_callback(
    request: CallbackRequest,
    http_request: Request,
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
        if not request.code or not request.state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both code and state are required"
            )

        state_data = validate_state(request.state)
        if state_data is None:
            logger.warning(f"Invalid or expired state parameter: {request.state}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter. Please try logging in again."
            )

        # Use the redirect_uri that was stored when the state was generated so
        # that it exactly matches the value Keycloak received during the auth
        # request — required by the OIDC spec for the token exchange.
        stored_redirect_uri = state_data.get("redirect_uri") or settings.KEYCLOAK_REDIRECT_URI
        keycloak_tokens = keycloak_service.exchange_code_for_token(request.code, redirect_uri=stored_redirect_uri)
        keycloak_access_token = keycloak_tokens["access_token"]

        userinfo = keycloak_service.get_user_info(keycloak_access_token)

        keycloak_user_id = userinfo.get("sub")
        email = userinfo.get("email")
        first_name = userinfo.get("given_name", "")
        last_name = userinfo.get("family_name", "")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not provided by KeyCloak"
            )

        keycloak_payload = keycloak_service.decode_token(keycloak_access_token)
        keycloak_roles = keycloak_service.extract_roles(keycloak_payload)

        user = db.query(User).filter(User.email == email).first()

        if not user:
            user = User(
                keycloak_id=keycloak_user_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_active=True,
                last_login=datetime.now(timezone.utc),
            )
            db.add(user)
            db.flush()
            logger.info(f"Created new user: {email}")
        else:
            user.keycloak_id = keycloak_user_id
            user.first_name = first_name
            user.last_name = last_name
            user.last_login = datetime.now(timezone.utc)
            logger.info(f"Updated existing user: {email}")

        local_role_names = map_keycloak_roles_to_local(keycloak_roles)

        if not local_role_names:
            local_role_names = ["staff_viewer"]
            logger.warning(f"No roles found for user {email}, defaulting to staff_viewer")

        local_roles = db.query(Role).filter(Role.name.in_(local_role_names)).all()

        db.query(UserRole).filter(UserRole.user_id == user.id).delete()

        for role in local_roles:
            user_role = UserRole(user_id=user.id, role_id=role.id)
            db.add(user_role)

        ip_address, user_agent = _get_request_metadata(http_request)
        _create_auth_audit_log(
            db,
            action="LOGIN",
            user=user,
            keycloak_id=keycloak_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            extra_values={"last_login": user.last_login.isoformat()},
        )

        db.commit()
        db.refresh(user)

        user_full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
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
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keycloak authentication failed"
        )
    except Exception as e:
        logger.error(f"Callback processing failed: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication failed"
        )


@router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """
    Refresh access token using refresh token.
    
    This uses our application's refresh token (not KeyCloak's).
    """
    try:
        token_data = jwt_handler.validate_token(
            request.refresh_token,
            token_type="refresh"
        )

        user_id = UUID(token_data.sub) if isinstance(token_data.sub, str) else token_data.sub
        user = db.query(User).filter(User.id == user_id).first()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )

        user.last_login = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)

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

    except HTTPException:
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )


@router.post("/logout")
async def logout(
    request: LogoutRequest,
    http_request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Logout user by clearing tokens.
    
    In a production system with Redis, this would blacklist the tokens.
    For now, client should discard tokens.
    """
    try:
        user_id = UUID(current_user.sub) if isinstance(current_user.sub, str) else current_user.sub
        user = db.query(User).filter(User.id == user_id).first()

        if request.refresh_token:
            try:
                keycloak_service.logout(request.refresh_token)
            except Exception as e:
                logger.warning(f"KeyCloak logout failed: {str(e)}")

        ip_address, user_agent = _get_request_metadata(http_request)
        _create_auth_audit_log(
            db,
            action="LOGOUT",
            user=user,
            keycloak_id=user.keycloak_id if user else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.commit()

        return {
            "message": "Successfully logged out",
            "detail": "Please discard your tokens"
        }

    except Exception as e:
        logger.error(f"Logout failed: {str(e)}")
        db.rollback()
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
            "keycloak_id": user.keycloak_id,
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
