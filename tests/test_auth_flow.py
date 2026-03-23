"""Auth flow tests for TASK-421."""

from datetime import datetime, timezone
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth.jwt_handler import jwt_handler
from backend.database import get_db
from backend.models import AuditLog, Role, User, UserRole
from backend.routes import auth as auth_routes


@pytest.fixture()
def auth_client(db):
    """Create a TestClient with DB dependency override."""
    app.dependency_overrides[get_db] = lambda: db
    original_startup = list(app.router.on_startup)
    app.router.on_startup.clear()
    client = TestClient(app)
    yield client
    app.router.on_startup[:] = original_startup
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def seeded_roles(db):
    """Seed default local roles used by role mapping."""
    role_names = ["admin", "staff_manager", "reviewer", "staff_viewer"]
    for role_name in role_names:
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


def _auth_headers_for_user(user: User, roles: list[str]) -> dict:
    token = jwt_handler.generate_access_token(
        user_id=str(user.id),
        email=str(user.email),
        name=f"{str(user.first_name or '')} {str(user.last_name or '')}".strip() or str(user.email),
        roles=roles,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
def test_login_returns_authorization_url(auth_client: TestClient, monkeypatch):
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )

    response = auth_client.post("/api/v1/auth/login")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authorization_url"].startswith("https://keycloak.example/auth")
    assert payload["state"]


@pytest.mark.integration
def test_callback_success_creates_user_updates_last_login_and_returns_tokens(
    auth_client: TestClient,
    db,
    monkeypatch,
    seeded_roles,
):
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )
    login_response = auth_client.post("/api/v1/auth/login")
    state = login_response.json()["state"]

    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "exchange_code_for_token",
        lambda code, redirect_uri=None: {"access_token": "kc-access", "refresh_token": "kc-refresh"},
    )
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_user_info",
        lambda token: {
            "sub": "11111111-2222-3333-4444-555555555555",
            "email": "task421@example.com",
            "given_name": "Task",
            "family_name": "User",
            "name": "Task User",
        },
    )
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "decode_token",
        lambda token: {"resource_access": {"test-client": {"roles": ["staff_viewer"]}}},
    )
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "extract_roles",
        lambda payload: ["staff_viewer"],
    )

    response = auth_client.post(
        "/api/v1/auth/callback",
        json={"code": "valid-code", "state": state},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["user"]["email"] == "task421@example.com"
    assert payload["user"]["roles"] == ["staff_viewer"]

    user = db.query(User).filter(User.email == "task421@example.com").first()
    assert user is not None
    assert user.keycloak_id == "11111111-2222-3333-4444-555555555555"
    assert user.last_login is not None

    login_audit = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "auth", AuditLog.action == "LOGIN", AuditLog.user_id == user.id)
        .first()
    )
    assert login_audit is not None
    assert login_audit.new_values["keycloak_id"] == "11111111-2222-3333-4444-555555555555"


@pytest.mark.integration
def test_callback_invalid_state_returns_400(auth_client: TestClient):
    response = auth_client.post(
        "/api/v1/auth/callback",
        json={"code": "valid-code", "state": "invalid-state"},
    )

    assert response.status_code == 400


@pytest.mark.integration
def test_refresh_success_returns_new_access_token_and_updates_last_login(
    auth_client: TestClient,
    db,
    user_factory,
    role_factory,
):
    user = user_factory(email="refresh@example.com")
    role = role_factory(name="staff_viewer")
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()

    refresh_token = jwt_handler.generate_refresh_token(user_id=str(user.id))

    before_refresh = user.last_login
    response = auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]

    # T1: Verify JWT role claims are embedded in the refreshed access token.
    refreshed_token_data = jwt_handler.validate_token(response.json()["access_token"])
    assert "staff_viewer" in (refreshed_token_data.roles or [])

    db.refresh(user)
    assert user.last_login is not None
    if before_refresh:
        assert user.last_login >= before_refresh


@pytest.mark.integration
def test_refresh_invalid_token_returns_401(auth_client: TestClient):
    response = auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not-a-token"},
    )

    assert response.status_code == 401


@pytest.mark.integration
def test_logout_forwards_refresh_token_and_writes_audit_log(
    auth_client: TestClient,
    db,
    user_factory,
    monkeypatch,
):
    user = user_factory(email="logout@example.com", first_name="Logout", last_name="User")
    user.keycloak_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    db.flush()

    captured: dict[str, str | None] = {"refresh_token": None}

    def _logout(refresh_token: str) -> bool:
        captured["refresh_token"] = refresh_token
        return True

    monkeypatch.setattr(auth_routes.keycloak_service, "logout", _logout)

    response = auth_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "kc-refresh-token"},
        headers=_auth_headers_for_user(user, ["staff_viewer"]),
    )

    assert response.status_code == 200
    assert captured["refresh_token"] == "kc-refresh-token"

    logout_audit = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "auth", AuditLog.action == "LOGOUT", AuditLog.user_id == user.id)
        .first()
    )
    assert logout_audit is not None
    assert logout_audit.new_values["keycloak_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.mark.integration
def test_me_returns_authenticated_user_with_keycloak_id(auth_client: TestClient, db, user_factory):
    user = user_factory(email="me@example.com", first_name="Me", last_name="User")
    user.keycloak_id = "99999999-8888-7777-6666-555555555555"
    db.flush()

    response = auth_client.get(
        "/api/v1/auth/me",
        headers=_auth_headers_for_user(user, ["staff_viewer"]),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "me@example.com"
    assert payload["keycloak_id"] == "99999999-8888-7777-6666-555555555555"


# ---------------------------------------------------------------------------
# Dynamic redirect URI tests (TASK-421 fix)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_login_uses_frontend_redirect_uri_from_body(auth_client: TestClient, monkeypatch):
    """Login endpoint must embed the caller-supplied frontend_redirect_uri in the auth URL."""
    monkeypatch.setattr(
        auth_routes.settings,
        "CORS_ORIGINS",
        "http://localhost:30300,http://localhost:8000",
    )
    captured: dict = {}

    def _get_auth_url(state: str, redirect_uri=None) -> str:
        captured["redirect_uri"] = redirect_uri
        return f"https://keycloak.example/auth?state={state}&redirect_uri={redirect_uri}"

    monkeypatch.setattr(auth_routes.keycloak_service, "get_auth_url", _get_auth_url)

    response = auth_client.post(
        "/api/v1/auth/login",
        json={"frontend_redirect_uri": "http://localhost:30300/callback"},
        headers={"Origin": "http://localhost:30300"},
    )

    assert response.status_code == 200
    assert captured["redirect_uri"] == "http://localhost:30300/callback"
    assert "http://localhost:30300/callback" in response.json()["authorization_url"]


@pytest.mark.integration
def test_login_derives_redirect_uri_from_origin_header(auth_client: TestClient, monkeypatch):
    """When no body is supplied, the backend must derive redirect URI from the Origin header."""
    monkeypatch.setattr(
        auth_routes.settings,
        "CORS_ORIGINS",
        "http://localhost:30300,http://localhost:8000",
    )
    captured: dict = {}

    def _get_auth_url(state: str, redirect_uri=None) -> str:
        captured["redirect_uri"] = redirect_uri
        return f"https://keycloak.example/auth?state={state}"

    monkeypatch.setattr(auth_routes.keycloak_service, "get_auth_url", _get_auth_url)

    response = auth_client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:30300"},
    )

    assert response.status_code == 200
    assert captured["redirect_uri"] == "http://localhost:30300/callback"


@pytest.mark.integration
def test_login_rejects_disallowed_redirect_uri(auth_client: TestClient, monkeypatch):
    """Login endpoint must return 400 when frontend_redirect_uri is not in the CORS allowlist."""
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )

    response = auth_client.post(
        "/api/v1/auth/login",
        json={"frontend_redirect_uri": "https://evil.example.com/callback"},
    )

    assert response.status_code == 400
    assert "allowed" in response.json()["detail"].lower()


@pytest.mark.integration
def test_callback_uses_redirect_uri_stored_in_state(
    auth_client: TestClient,
    db,
    monkeypatch,
    seeded_roles,
):
    """The code exchange must use the redirect_uri that was stored when the state was created."""
    monkeypatch.setattr(
        auth_routes.settings,
        "CORS_ORIGINS",
        "http://localhost:30300,http://localhost:8000",
    )
    captured: dict = {}

    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )

    login_response = auth_client.post(
        "/api/v1/auth/login",
        json={"frontend_redirect_uri": "http://localhost:30300/callback"},
        headers={"Origin": "http://localhost:30300"},
    )
    state = login_response.json()["state"]

    def _exchange(code: str, redirect_uri=None) -> dict:
        captured["redirect_uri"] = redirect_uri
        return {"access_token": "kc-access", "refresh_token": "kc-refresh"}

    monkeypatch.setattr(auth_routes.keycloak_service, "exchange_code_for_token", _exchange)
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_user_info",
        lambda token: {
            "sub": "aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb",
            "email": "redirecturi@example.com",
            "given_name": "Redirect",
            "family_name": "Test",
        },
    )
    monkeypatch.setattr(auth_routes.keycloak_service, "decode_token", lambda token: {})
    monkeypatch.setattr(auth_routes.keycloak_service, "extract_roles", lambda payload: ["staff_viewer"])

    callback_response = auth_client.post(
        "/api/v1/auth/callback",
        json={"code": "test-code", "state": state},
    )

    assert callback_response.status_code == 200
    assert captured["redirect_uri"] == "http://localhost:30300/callback"


@pytest.mark.integration
def test_callback_preserves_existing_portal_roles(
    auth_client: TestClient,
    db,
    monkeypatch,
    seeded_roles,
    user_factory,
):
    """A user whose portal role was upgraded to admin by an admin retains it on every subsequent login."""
    # Pre-create user with admin role assigned through the portal by an admin.
    user = user_factory(email="admin.existing@example.com")
    admin_role = db.query(Role).filter(Role.name == "admin").first()
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=admin_role.id))
    db.flush()

    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )
    login_response = auth_client.post("/api/v1/auth/login")
    state = login_response.json()["state"]

    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "exchange_code_for_token",
        lambda code, redirect_uri=None: {"access_token": "kc-access", "refresh_token": "kc-refresh"},
    )
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_user_info",
        lambda token: {
            "sub": "aaaabbbb-1111-2222-3333-ccccddddeeee",
            "email": "admin.existing@example.com",
            "given_name": "Admin",
            "family_name": "Existing",
        },
    )
    monkeypatch.setattr(auth_routes.keycloak_service, "decode_token", lambda token: {})
    monkeypatch.setattr(auth_routes.keycloak_service, "extract_roles", lambda payload: [])

    response = auth_client.post(
        "/api/v1/auth/callback",
        json={"code": "valid-code", "state": state},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "admin" in payload["user"]["roles"]
    assert "staff_viewer" not in payload["user"]["roles"]
