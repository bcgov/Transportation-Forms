"""Authentication logging privacy tests for FEAT-0030 US-007."""

import logging

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.routes import auth as auth_routes


LOGGER_NAME = auth_routes.__name__
REFRESH_COOKIE_NAME = auth_routes.settings.AUTH_REFRESH_COOKIE_NAME


@pytest.fixture()
def auth_client(db):
    app.dependency_overrides[get_db] = lambda: db
    original_startup = list(app.router.on_startup)
    original_auth_states = dict(auth_routes._auth_states)
    app.router.on_startup.clear()
    client = TestClient(app)
    yield client
    client.close()
    app.router.on_startup[:] = original_startup
    auth_routes._auth_states.clear()
    auth_routes._auth_states.update(original_auth_states)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def _raise_sensitive_error(secret: str):
    def _raise(*args, **kwargs):
        raise RuntimeError(secret)

    return _raise


def _assert_secret_not_logged(caplog, secret: str) -> None:
    auth_records = [record for record in caplog.records if record.name == LOGGER_NAME]
    assert auth_records
    assert secret not in caplog.text
    assert all(record.exc_info is None for record in auth_records)


def _override_current_user(user) -> None:
    app.dependency_overrides[get_current_user] = lambda: TokenData(
        sub=str(user.id),
        email=str(user.email),
        name="FEAT-0030 Privacy Test",
        roles=[],
        token_type="access",
        permissions=[],
    )


@pytest.mark.integration
def test_login_exception_details_are_not_logged(auth_client, monkeypatch, caplog):
    secret = "SECRET-login-provider-detail"
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        _raise_sensitive_error(secret),
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        response = auth_client.post("/api/v1/auth/login")

    assert response.status_code == 400
    assert response.json() == {"detail": "Failed to initiate login flow"}
    _assert_secret_not_logged(caplog, secret)


@pytest.mark.integration
def test_callback_exception_details_are_not_logged(auth_client, monkeypatch, caplog):
    secret = "SECRET-callback-provider-detail"
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "get_auth_url",
        lambda state, redirect_uri=None: f"https://keycloak.example/auth?state={state}",
    )
    state = auth_client.post("/api/v1/auth/login").json()["state"]
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "exchange_code_for_token",
        _raise_sensitive_error(secret),
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        response = auth_client.post(
            "/api/v1/auth/callback",
            json={"code": "test-code", "state": state},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Authentication failed"}
    _assert_secret_not_logged(caplog, secret)


@pytest.mark.integration
def test_refresh_exception_details_are_not_logged(auth_client, monkeypatch, caplog):
    secret = "SECRET-refresh-token-detail"
    auth_client.cookies.set(REFRESH_COOKIE_NAME, "opaque-refresh-token")
    monkeypatch.setattr(
        auth_routes.jwt_handler,
        "validate_token",
        _raise_sensitive_error(secret),
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        response = auth_client.post("/api/v1/auth/refresh")

    assert response.status_code == 500
    assert response.json() == {"detail": "Token refresh failed"}
    _assert_secret_not_logged(caplog, secret)


@pytest.mark.integration
def test_keycloak_logout_exception_details_are_not_logged(
    auth_client,
    user_factory,
    monkeypatch,
    caplog,
):
    secret = "SECRET-keycloak-logout-detail"
    user = user_factory(email="keycloak-logout-privacy@example.com")
    _override_current_user(user)
    auth_client.cookies.set(REFRESH_COOKIE_NAME, "opaque-refresh-token")
    monkeypatch.setattr(
        auth_routes.keycloak_service,
        "logout",
        _raise_sensitive_error(secret),
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        response = auth_client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    _assert_secret_not_logged(caplog, secret)


@pytest.mark.integration
def test_logout_exception_details_are_not_logged(
    auth_client,
    db,
    user_factory,
    monkeypatch,
    caplog,
):
    secret = "SECRET-logout-database-detail"
    user = user_factory(email="logout-privacy@example.com")
    _override_current_user(user)
    monkeypatch.setattr(
        auth_routes,
        "_create_auth_audit_log",
        _raise_sensitive_error(secret),
    )
    monkeypatch.setattr(db, "rollback", lambda: None)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        response = auth_client.post("/api/v1/auth/logout")

    assert response.status_code == 500
    assert response.json() == {"detail": "Logout failed"}
    _assert_secret_not_logged(caplog, secret)


@pytest.mark.integration
def test_me_exception_details_are_not_logged(
    auth_client,
    user_factory,
    monkeypatch,
    caplog,
):
    from backend.routes import admin_users

    secret = "SECRET-user-role-database-detail"
    user = user_factory(email="me-privacy@example.com")
    _override_current_user(user)
    monkeypatch.setattr(
        admin_users,
        "_active_user_roles",
        _raise_sensitive_error(secret),
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        response = auth_client.get("/api/v1/auth/me")

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to retrieve user information"}
    _assert_secret_not_logged(caplog, secret)