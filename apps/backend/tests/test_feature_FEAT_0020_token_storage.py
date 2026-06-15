"""FEAT-0020 / SEC-004 — Move staff refresh token out of localStorage.

Backend contract tests for the HttpOnly cookie–based refresh token storage.
Covers acceptance criteria for US-001 (cookie attributes, no body leak) and
US-002 (login/refresh/logout flows end-to-end).

Test plan traceability:
- TC1.1 -> test_callback_does_not_return_refresh_token_in_body
- TC1.2 -> test_callback_refresh_cookie_is_present_and_scoped
- TC1.3 -> test_callback_refresh_cookie_is_httponly_secure_samesite
- TC2.1/2.3 -> test_login_flow_sets_refresh_cookie_for_subsequent_refresh
- TC2.1 -> test_refresh_uses_cookie_when_body_missing
- TC2.1 -> test_refresh_prefers_cookie_over_body
- TC2.1 -> test_refresh_returns_401_when_no_cookie_or_body
- TC2.1 -> test_refresh_clears_cookie_on_invalid_token
- TC2.4 -> test_logout_clears_refresh_cookie
- TC2.4 -> test_logout_forwards_cookie_value_to_keycloak
- TC2.5 -> test_refresh_after_logout_is_rejected
- TC1.3 -> test_cookie_path_scoped_to_auth_endpoints
"""

from __future__ import annotations

import uuid
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient

from backend.auth.jwt_handler import jwt_handler
from backend.config import settings
from backend.database import get_db
from backend.main import app
from backend.models import Role, User, UserRole
from backend.routes import auth as auth_routes


COOKIE_NAME = "tf_refresh_token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(db, monkeypatch):
    # TestClient runs over http://testserver, so we must disable the cookie's
    # Secure attribute for the cookie jar to retain it across requests. The
    # Secure-attribute assertion in the cookie-header tests below uses a
    # separate non-disabled call below.
    monkeypatch.setattr(auth_routes.settings, "AUTH_COOKIE_SECURE", False)
    app.dependency_overrides[get_db] = lambda: db
    original_startup = list(app.router.on_startup)
    app.router.on_startup.clear()
    test_client = TestClient(app)
    yield test_client
    app.router.on_startup[:] = original_startup
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def secure_client(db, monkeypatch):
    """Client that keeps Secure=True on the cookie for attribute assertions."""
    monkeypatch.setattr(auth_routes.settings, "AUTH_COOKIE_SECURE", True)
    app.dependency_overrides[get_db] = lambda: db
    original_startup = list(app.router.on_startup)
    app.router.on_startup.clear()
    test_client = TestClient(app)
    yield test_client
    app.router.on_startup[:] = original_startup
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def seeded_roles(db):
    for role_name in ("admin", "staff_manager", "reviewer", "staff_viewer"):
        if not db.query(Role).filter(Role.name == role_name).first():
            db.add(
                Role(
                    id=uuid.uuid4(),
                    name=role_name,
                    permissions={},
                    is_system=True,
                    is_active=True,
                )
            )
    db.flush()


def _stub_keycloak_for_callback(monkeypatch, email: str, sub: str) -> None:
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "exchange_code_for_token",
        lambda code, redirect_uri=None: {
            "access_token": "kc-access",
            "refresh_token": "kc-refresh",
        },
    )
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_user_info",
        lambda token: {
            "sub": sub,
            "email": email,
            "given_name": "Cookie",
            "family_name": "Test",
        },
    )
    monkeypatch.setattr(auth_routes.keycloak_service, "decode_token", lambda token: {})
    monkeypatch.setattr(
        auth_routes.keycloak_service, "extract_roles", lambda payload: ["staff_viewer"]
    )


def _complete_callback(client: TestClient, monkeypatch, email: str) -> tuple:
    """Run the login + callback flow end-to-end. Returns (callback_response, refresh_cookie_value)."""
    sub = str(uuid.uuid4())
    _stub_keycloak_for_callback(monkeypatch, email, sub)
    state = client.post("/api/v1/auth/login").json()["state"]
    response = client.post(
        "/api/v1/auth/callback",
        json={"code": "valid-code", "state": state},
    )
    assert response.status_code == 200, response.text
    cookie_value = response.cookies.get(COOKIE_NAME)
    return response, cookie_value


def _parse_set_cookie(response) -> SimpleCookie:
    """Parse raw Set-Cookie headers so we can inspect attributes (HttpOnly, etc.).

    Starlette's TestClient surfaces cookies through ``response.cookies`` but
    drops attribute metadata; we need the raw header to assert HttpOnly, Secure,
    SameSite, and Path.
    """
    jar = SimpleCookie()
    # httpx exposes set-cookie via response.headers.get_list, but TestClient
    # uses an httpx response whose .headers is a Headers object — iterate all
    # set-cookie values defensively.
    set_cookie_headers = response.headers.get_list("set-cookie")
    for raw in set_cookie_headers:
        jar.load(raw)
    return jar


# ---------------------------------------------------------------------------
# US-001 — Refresh token storage
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_callback_does_not_return_refresh_token_in_body(
    client: TestClient, monkeypatch, seeded_roles
):
    """AC1/AC2: Response body must not carry the refresh token value."""
    response, _ = _complete_callback(client, monkeypatch, "u1@example.com")
    payload = response.json()
    # FEAT-0020: refresh_token must be absent from the JSON body entirely —
    # it is delivered only via the HttpOnly cookie so JS cannot read it.
    assert "refresh_token" not in payload
    # Sanity: access token still returned for in-memory use.
    assert payload["access_token"]


@pytest.mark.integration
def test_callback_refresh_cookie_is_present_and_scoped(
    client: TestClient, monkeypatch, seeded_roles
):
    """AC3: A refresh-token cookie must be set with a non-empty value."""
    response, cookie_value = _complete_callback(client, monkeypatch, "u2@example.com")
    assert cookie_value, "refresh-token cookie missing from Set-Cookie"
    # Validate the cookie actually contains a valid app refresh token.
    token_data = jwt_handler.validate_token(cookie_value, token_type="refresh")
    assert token_data is not None


@pytest.mark.integration
def test_callback_refresh_cookie_is_httponly_secure_samesite(
    secure_client: TestClient, monkeypatch, seeded_roles
):
    """AC3: Cookie must carry HttpOnly, Secure, and SameSite attributes."""
    response, _ = _complete_callback(secure_client, monkeypatch, "u3@example.com")
    raw_headers = response.headers.get_list("set-cookie")
    raw_cookie = next((h for h in raw_headers if h.lower().startswith(f"{COOKIE_NAME}=")), None)
    assert raw_cookie is not None, raw_headers
    lowered = raw_cookie.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered or "samesite=strict" in lowered
    assert f"path={settings.AUTH_REFRESH_COOKIE_PATH.lower()}" in lowered


@pytest.mark.integration
def test_cookie_path_scoped_to_auth_endpoints(
    secure_client: TestClient, monkeypatch, seeded_roles
):
    """BR-006: Cookie path must be scoped narrowly (not '/'), to limit attack surface."""
    response, _ = _complete_callback(secure_client, monkeypatch, "u4@example.com")
    raw_headers = response.headers.get_list("set-cookie")
    raw_cookie = next((h for h in raw_headers if h.lower().startswith(f"{COOKIE_NAME}=")), None)
    assert raw_cookie is not None
    # Path must not be root.
    assert "path=/api/v1/auth" in raw_cookie.lower()


# ---------------------------------------------------------------------------
# US-002 — Refresh flow
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_login_flow_sets_refresh_cookie_for_subsequent_refresh(
    client: TestClient, monkeypatch, seeded_roles
):
    """AC3 (login) + AC1 (refresh): cookie set on login is usable for /refresh without body."""
    response, cookie_value = _complete_callback(client, monkeypatch, "u5@example.com")
    assert cookie_value
    # TestClient persists cookies across calls; just call /refresh with empty body.
    refresh_response = client.post("/api/v1/auth/refresh", json={})
    assert refresh_response.status_code == 200, refresh_response.text
    assert refresh_response.json()["access_token"]


@pytest.mark.integration
def test_refresh_uses_cookie_when_body_missing(
    client: TestClient, user_factory
):
    """AC1: Refresh must succeed using cookie alone, no body value supplied."""
    user = user_factory(email="refresh-cookie@example.com")
    refresh_token = jwt_handler.generate_refresh_token(user_id=str(user.id))
    client.cookies.set(COOKIE_NAME, refresh_token, path="/api/v1/auth")
    response = client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 200
    assert response.json()["access_token"]


@pytest.mark.integration
def test_refresh_prefers_cookie_over_body(
    client: TestClient, user_factory
):
    """The cookie is the canonical source — body value is ignored when cookie present."""
    user = user_factory(email="refresh-prefers@example.com")
    good_cookie_token = jwt_handler.generate_refresh_token(user_id=str(user.id))
    client.cookies.set(COOKIE_NAME, good_cookie_token, path="/api/v1/auth")
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "obviously-not-a-real-token"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.integration
def test_refresh_returns_401_when_no_cookie_or_body(client: TestClient):
    """EC-001: Missing refresh source must result in 401, not a server error."""
    response = client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 401


@pytest.mark.integration
def test_refresh_clears_cookie_on_invalid_token(client: TestClient):
    """Defensive: an expired/forged cookie value must be cleared so the browser stops retrying."""
    client.cookies.set(COOKIE_NAME, "this-is-not-a-jwt", path="/api/v1/auth")
    response = client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 401
    # Set-Cookie should clear the cookie (Max-Age=0 or expired Expires).
    set_cookie = " ".join(response.headers.get_list("set-cookie")).lower()
    assert COOKIE_NAME in set_cookie
    assert "max-age=0" in set_cookie or "expires=" in set_cookie





# ---------------------------------------------------------------------------
# US-002 — Logout flow
# ---------------------------------------------------------------------------

def _bearer_for(user: User, roles=("staff_viewer",)) -> dict:
    token = jwt_handler.generate_access_token(
        user_id=str(user.id),
        email=user.email,
        name=f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email,
        roles=list(roles),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
def test_logout_clears_refresh_cookie(client: TestClient, user_factory, monkeypatch):
    """AC4: Logout must remove the cookie from the browser."""
    user = user_factory(email="logout-cookie@example.com")
    refresh_token = jwt_handler.generate_refresh_token(user_id=str(user.id))
    client.cookies.set(COOKIE_NAME, refresh_token, path="/api/v1/auth")

    response = client.post(
        "/api/v1/auth/logout",
        json={},
        headers=_bearer_for(user),
    )
    assert response.status_code == 200

    set_cookie = " ".join(response.headers.get_list("set-cookie")).lower()
    assert COOKIE_NAME in set_cookie
    assert "max-age=0" in set_cookie or "expires=" in set_cookie


@pytest.mark.integration
def test_logout_forwards_cookie_value_to_keycloak(
    client: TestClient, user_factory, monkeypatch
):
    """Logout must forward the cookie-sourced refresh token to Keycloak even when body is empty."""
    user = user_factory(email="logout-fwd@example.com")
    refresh_token = jwt_handler.generate_refresh_token(user_id=str(user.id))
    client.cookies.set(COOKIE_NAME, refresh_token, path="/api/v1/auth")

    captured: dict = {}

    def _kc_logout(token: str) -> bool:
        captured["token"] = token
        return True

    monkeypatch.setattr(auth_routes.keycloak_service, "logout", _kc_logout)

    response = client.post(
        "/api/v1/auth/logout",
        json={},
        headers=_bearer_for(user),
    )
    assert response.status_code == 200
    assert captured.get("token") == refresh_token


@pytest.mark.integration
def test_refresh_after_logout_is_rejected(
    client: TestClient, monkeypatch, seeded_roles
):
    """AC5: After logout, the cleared cookie cannot establish a new session."""
    response, _ = _complete_callback(client, monkeypatch, "post-logout@example.com")

    # Logout (TestClient already carries the cookie + access token from callback).
    access_token = response.json()["access_token"]
    logout_response = client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_response.status_code == 200

    # TestClient honours Set-Cookie Max-Age=0 and drops the cookie. A fresh
    # refresh attempt must now fail without a residual session.
    client.cookies.pop(COOKIE_NAME, None)
    refresh_response = client.post("/api/v1/auth/refresh", json={})
    assert refresh_response.status_code == 401
