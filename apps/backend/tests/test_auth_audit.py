"""Auth audit logging tests for TASK-421."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth.jwt_handler import jwt_handler
from backend.database import get_db
from backend.models import AuditLog, Role, User, UserRole
from backend.routes import auth as auth_routes


@pytest.fixture()
def audit_client(db):
    app.dependency_overrides[get_db] = lambda: db
    original_startup = list(app.router.on_startup)
    app.router.on_startup.clear()
    client = TestClient(app)
    yield client
    app.router.on_startup[:] = original_startup
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def auth_seed(db):
    if not db.query(Role).filter(Role.name == "staff_viewer").first():
        db.add(
            Role(
                id=uuid.uuid4(),
                name="staff_viewer",
                permissions={},
                is_system=True,
                is_active=True,
            )
        )
        db.flush()


def _access_token(user: User) -> str:
    return jwt_handler.generate_access_token(
        user_id=str(user.id),
        email=str(user.email),
        name=f"{str(user.first_name or '')} {str(user.last_name or '')}".strip() or str(user.email),
        roles=["staff_viewer"],
    )


@pytest.mark.integration
def test_login_and_logout_audits_include_keycloak_id(
    audit_client: TestClient,
    db,
    monkeypatch,
    auth_seed,
):
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )
    state = audit_client.post("/api/v1/auth/login").json()["state"]

    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "exchange_code_for_token",
        lambda code, redirect_uri=None: {"access_token": "kc-access", "refresh_token": "kc-refresh"},
    )
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_user_info",
        lambda token: {
            "sub": "22222222-3333-4444-5555-666666666666",
            "email": "audit@example.com",
            "given_name": "Audit",
            "family_name": "User",
            "name": "Audit User",
        },
    )
    monkeypatch.setattr(auth_routes.keycloak_service, "decode_token", lambda token: {})
    monkeypatch.setattr(auth_routes.keycloak_service, "extract_roles", lambda payload: ["staff_viewer"])

    callback = audit_client.post(
        "/api/v1/auth/callback",
        json={"code": "ok", "state": state},
    )
    assert callback.status_code == 200
    callback_payload = callback.json()

    user = db.query(User).filter(User.email == "audit@example.com").first()
    assert user is not None

    monkeypatch.setattr(auth_routes.keycloak_service, "logout", lambda refresh_token: True)

    logout = audit_client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"Authorization": f"Bearer {_access_token(user)}"},
        cookies={"tf_refresh_token": "kc-refresh"},
    )
    assert logout.status_code == 200
    # FEAT-0020: refresh_token is delivered via HttpOnly cookie, not in the response body.
    assert "refresh_token" not in callback_payload

    login_audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "LOGIN", AuditLog.entity_type == "auth", AuditLog.user_id == user.id)
        .first()
    )
    assert login_audit is not None
    assert login_audit.new_values["keycloak_id"] == "22222222-3333-4444-5555-666666666666"

    logout_audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "LOGOUT", AuditLog.entity_type == "auth", AuditLog.user_id == user.id)
        .first()
    )
    assert logout_audit is not None
    assert logout_audit.new_values["keycloak_id"] == "22222222-3333-4444-5555-666666666666"


@pytest.mark.integration
def test_refresh_does_not_create_login_or_logout_audit(
    audit_client: TestClient,
    db,
    user_factory,
    role_factory,
):
    user = user_factory(email="refresh-no-audit@example.com")
    role = role_factory(name="staff_viewer")
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()

    refresh_token = jwt_handler.generate_refresh_token(user_id=str(user.id))

    response = audit_client.post(
        "/api/v1/auth/refresh",
        json={},
        cookies={"tf_refresh_token": refresh_token},
    )
    assert response.status_code == 200

    auth_audits = db.query(AuditLog).filter(AuditLog.entity_type == "auth", AuditLog.user_id == user.id).all()
    assert auth_audits == []
