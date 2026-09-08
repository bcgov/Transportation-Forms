"""Authentication API endpoints."""

import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID
from typing import Literal, Optional, cast
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, status, Depends, Request, Response, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.jwt_handler import REFRESH_TOKEN_EXPIRY

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
    """Response for successful login.

    FEAT-0020 / SEC-004: The refresh token is NOT returned in the response body.
    It is delivered as an HttpOnly Secure SameSite cookie so that JavaScript
    cannot read it from localStorage or sessionStorage.
    """

    access_token: str
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
    """Request to refresh access token.

    FEAT-0020: The canonical source for the refresh token is the HttpOnly
    cookie. No body fields are accepted for security.
    """
    pass


class LogoutRequest(BaseModel):
    """Request to logout.

    FEAT-0020: The canonical source for the refresh token is the HttpOnly
    cookie. No body fields are accepted for security.
    """
    pass


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
    return request.client.host if request.client else None, request.headers.get(
        "user-agent"
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Attach the refresh token to ``response`` as an HttpOnly Secure cookie.

    FEAT-0020 / SEC-004: The refresh token must not be readable by JavaScript;
    delivering it through an HttpOnly cookie removes the localStorage theft
    vector exploitable by XSS or compromised third-party scripts.
    """
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRY,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=cast("Literal['lax', 'strict', 'none']", (str(settings.AUTH_REFRESH_COOKIE_SAMESITE).lower() if str(settings.AUTH_REFRESH_COOKIE_SAMESITE).lower() in ("lax", "strict", "none") else "lax")),
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Remove the refresh-token cookie by setting Max-Age=0 (FEAT-0020)."""
    response.delete_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=cast("Literal['lax', 'strict', 'none']", (str(settings.AUTH_REFRESH_COOKIE_SAMESITE).lower() if str(settings.AUTH_REFRESH_COOKIE_SAMESITE).lower() in ("lax", "strict", "none") else "lax")),
    )


def _is_allowed_redirect_uri(uri: str) -> bool:
    """Check whether the redirect URI's origin is in the configured CORS origins allowlist."""
    try:
        parsed = urlparse(uri)
        if not parsed.scheme or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        allowed_origins = [
            o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()
        ]
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
    except Exception:
        logger.error("Login initiation failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to initiate login flow",
        )


@router.post("/callback", response_model=LoginResponse)
async def auth_callback(
    request: CallbackRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db),
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
                detail="Both code and state are required",
            )

        state_data = validate_state(request.state)
        if state_data is None:
            logger.warning("Invalid or expired OIDC state parameter")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter. Please try logging in again.",
            )

        # Use the redirect_uri that was stored when the state was generated so
        # that it exactly matches the value Keycloak received during the auth
        # request — required by the OIDC spec for the token exchange.
        stored_redirect_uri = (
            state_data.get("redirect_uri") or settings.KEYCLOAK_REDIRECT_URI
        )
        keycloak_tokens = keycloak_service.exchange_code_for_token(
            request.code, redirect_uri=stored_redirect_uri
        )
        keycloak_access_token = keycloak_tokens["access_token"]

        userinfo = keycloak_service.get_user_info(keycloak_access_token)

        keycloak_user_id = userinfo.get("sub")
        email = userinfo.get("email")
        first_name = userinfo.get("given_name", "")
        last_name = userinfo.get("family_name", "")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not provided by KeyCloak",
            )

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
            logger.info("Created new authenticated user")
        else:
            user.keycloak_id = keycloak_user_id  # type: ignore[assignment]
            user.first_name = first_name  # type: ignore[assignment]
            user.last_name = last_name  # type: ignore[assignment]
            user.last_login = datetime.now(timezone.utc)  # type: ignore[assignment]
            logger.info("Updated existing authenticated user")

        # New-user bootstrap only — never overwrite DB-assigned portal roles.
        existing_role_count = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user.id,
                UserRole.deleted_at.is_(None),
            )
            .count()
        )

        if existing_role_count == 0:
            default_role = (
                db.query(Role)
                .filter(
                    Role.name == "staff_viewer",
                    Role.deleted_at.is_(None),
                    Role.is_active.is_(True),
                )
                .first()
            )
            if default_role:
                db.add(UserRole(user_id=user.id, role_id=default_role.id))
                logger.info("Assigned default staff_viewer role to authenticated user")

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
        user = db.query(User).filter(User.id == user.id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication failed",
            )

        user_full_name = (
            f"{user.first_name or ''} {user.last_name or ''}".strip() or str(user.email)
        )
        from backend.routes.admin_users import _active_user_roles

        active_roles = _active_user_roles(user)
        role_names = [ur.role.name for ur in active_roles]
        all_permissions = list({
            p for ur in active_roles
            for p in (ur.role.permissions or [])
        })
        app_tokens = keycloak_service.generate_app_tokens(
            user_id=str(user.id),
            email=str(user.email),
            name=user_full_name,
            roles=role_names,
            permissions=all_permissions,
        )
        logger.info("Successfully authenticated user")

        # FEAT-0020: Set the refresh token as an HttpOnly Secure SameSite
        # cookie and omit it from the JSON response body so the staff portal
        # cannot store it in localStorage / sessionStorage where JavaScript
        # could read it.
        _set_refresh_cookie(response, app_tokens["refresh_token"])

        return LoginResponse(
            access_token=app_tokens["access_token"],
            token_type=app_tokens["token_type"],
            expires_in=int(app_tokens["expires_in"]),
            user={
                "id": str(user.id),
                "email": str(user.email),
                "name": user_full_name,
                "roles": role_names,
                "permissions": all_permissions,
            },
        )

    except HTTPException:
        raise
    except ValueError:
        logger.error("KeyCloak error during callback")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keycloak authentication failed",
        )
    except Exception:
        logger.error("Callback processing failed")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Authentication failed"
        )


@router.post("/refresh")
async def refresh_token(
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Refresh access token using refresh token.

    This uses our application's refresh token (not KeyCloak's).

    FEAT-0020: The refresh token is exclusively sourced from the HttpOnly cookie
    set at login time to prevent XSS exfiltration.
    """
    try:
        token_value = http_request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not token_value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token missing",
            )

        token_data = jwt_handler.validate_token(token_value, token_type="refresh")
        if token_data is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        user_id = (
            UUID(token_data.sub) if isinstance(token_data.sub, str) else token_data.sub
        )
        user = (
            db.query(User)
            .filter(
                User.id == user_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .first()
        )

        if user is None or not bool(user.is_active):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )

        user.last_login = datetime.now(timezone.utc)  # type: ignore[assignment]
        db.commit()
        user = db.query(User).filter(User.id == user.id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Token refresh failed",
            )

        user_full_name = (
            f"{user.first_name or ''} {user.last_name or ''}".strip() or str(user.email)
        )
        from backend.routes.admin_users import _active_user_roles

        active_roles = _active_user_roles(user)
        role_names = [ur.role.name for ur in active_roles]
        all_permissions = list({p for ur in active_roles for p in (ur.role.permissions or [])})
        new_access_token = jwt_handler.generate_access_token(
            user_id=str(user.id),
            email=str(user.email),
            name=user_full_name,
            roles=role_names,
            permissions=all_permissions,
        )

        logger.info("Refreshed access token for authenticated user")

        return {
            "access_token": new_access_token,
            "token_type": "Bearer",
            "expires_in": 1800,
        }

    except HTTPException:
        raise
    except ValueError:
        db.rollback()
        # FEAT-0020: invalidate the bad cookie so subsequent requests don't
        # keep retrying with the same expired/forged value. Use a direct
        # JSONResponse here because HTTPException unwinds the request before
        # the cookie set on the injected ``response`` object can take effect.
        unauthorized = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired refresh token"},
        )
        _clear_refresh_cookie(unauthorized)
        return unauthorized
    except Exception:
        logger.error("Token refresh failed")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed",
        )


@router.post("/logout")
async def logout(
    http_request: Request,
    response: Response,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Logout user by clearing tokens.

    FEAT-0020: Clears the HttpOnly refresh-token cookie on the response so the
    browser cannot continue to silently refresh sessions after logout.
    Subsequent authenticated requests will return HTTP 401.
    """
    try:
        user_id = (
            UUID(current_user.sub)
            if isinstance(current_user.sub, str)
            else current_user.sub
        )
        user = db.query(User).filter(User.id == user_id).first()

        # Best-effort: forward the cookie value to Keycloak's end-session
        # endpoint. The cookie holds the application JWT refresh token, not a
        # Keycloak refresh token, so this call may be a no-op — but we still
        # attempt it so that any valid Keycloak session bound to the same token
        # subject is invalidated where possible.
        token_value = http_request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if token_value:
            try:
                keycloak_service.logout(token_value)
            except Exception:
                logger.warning("KeyCloak logout failed (best-effort)")

        ip_address, user_agent = _get_request_metadata(http_request)
        _create_auth_audit_log(
            db,
            action="LOGOUT",
            user=user,
            keycloak_id=str(user.keycloak_id) if user and user.keycloak_id is not None else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.commit()

        # FEAT-0020: Remove the HttpOnly refresh-token cookie from the browser.
        _clear_refresh_cookie(response)

        return {
            "message": "Successfully logged out",
            "detail": "Please discard your tokens",
        }

    except Exception:
        logger.error("Logout failed")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logout failed"
        )


@router.get("/me")
async def get_current_user_info(
    current_user: TokenData = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get current authenticated user information.
    """
    try:
        # Convert string UUID to UUID object
        user_id = (
            UUID(current_user.sub)
            if isinstance(current_user.sub, str)
            else current_user.sub
        )
        user = (
            db.query(User)
            .filter(
                User.id == user_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .first()
        )

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        user_full_name = (
            f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
        )
        from backend.routes.admin_users import _active_user_roles

        active_roles = _active_user_roles(user)
        all_permissions = list({
            p for ur in active_roles
            for p in (ur.role.permissions or [])
        })
        return {
            "id": str(user.id),
            "email": user.email,
            "name": user_full_name,
            "roles": [ur.role.name for ur in active_roles],
            "permissions": all_permissions,
            "keycloak_id": user.keycloak_id,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }

    except HTTPException:
        raise
    except Exception:
        logger.error("Failed to get user info")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user information",
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
        "viewer": "staff_viewer",
    }

    local_roles = []
    for keycloak_role in keycloak_roles:
        local_role = role_mapping.get(keycloak_role.lower())
        if local_role and local_role not in local_roles:
            local_roles.append(local_role)

    return local_roles
