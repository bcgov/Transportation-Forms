"""Privacy regressions for FEAT-0030 identity-provider service logging."""

import logging
from unittest.mock import MagicMock

import jwt
import pytest
import requests

from backend.auth import keycloak_service as keycloak_module
from backend.auth.keycloak_service import KeyCloakService

LOGGER_NAME = "backend.auth.keycloak_service"
SENTINEL = "sensitive-provider-detail-feat0030"


@pytest.fixture
def service() -> KeyCloakService:
    instance = object.__new__(KeyCloakService)
    instance.enabled = True
    instance.base_url = "https://identity.example/auth"
    instance.realm_url = "https://identity.example/auth/realms/test"
    instance._well_known_config = {
        "authorization_endpoint": "https://identity.example/authorize",
        "token_endpoint": "https://identity.example/token",
        "userinfo_endpoint": "https://identity.example/userinfo",
        "end_session_endpoint": "https://identity.example/logout",
    }
    instance.keycloak_openid = MagicMock()
    return instance


def _assert_private(
    caplog: pytest.LogCaptureFixture, error: Exception | None = None
) -> None:
    records = [record for record in caplog.records if record.name == LOGGER_NAME]
    assert SENTINEL not in caplog.text
    assert all(record.exc_info is None for record in records)
    if error is not None:
        assert SENTINEL not in str(error)


def test_success_logs_omit_state_url_email_and_roles(
    service: KeyCloakService,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = MagicMock()
    response.json.return_value = {"email": f"{SENTINEL}@example.com"}
    monkeypatch.setattr(
        keycloak_module.requests, "get", MagicMock(return_value=response)
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        service.get_auth_url(SENTINEL)
        service.get_user_info("opaque-access-token")
        service.extract_roles(
            {
                "resource_access": {
                    keycloak_module.settings.KEYCLOAK_CLIENT_ID: {"roles": [SENTINEL]}
                }
            }
        )

    _assert_private(caplog)


@pytest.mark.parametrize(
    "operation",
    (
        "authorization_url",
        "token_exchange",
        "user_info",
        "introspection",
        "refresh",
        "decode",
    ),
)
def test_failure_logs_and_errors_omit_provider_details(
    service: KeyCloakService,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    operation: str,
) -> None:
    if operation == "authorization_url":
        service._get_well_known_config = MagicMock(side_effect=RuntimeError(SENTINEL))
        call = lambda: service.get_auth_url("opaque-state")
    elif operation == "token_exchange":
        response = MagicMock()
        response.text = SENTINEL
        error = requests.exceptions.HTTPError(SENTINEL, response=response)
        monkeypatch.setattr(
            keycloak_module.requests, "post", MagicMock(side_effect=error)
        )
        call = lambda: service.exchange_code_for_token("opaque-code")
    elif operation == "user_info":
        monkeypatch.setattr(
            keycloak_module.requests,
            "get",
            MagicMock(side_effect=RuntimeError(SENTINEL)),
        )
        call = lambda: service.get_user_info("opaque-access-token")
    elif operation == "introspection":
        service.keycloak_openid.introspect.side_effect = RuntimeError(SENTINEL)
        call = lambda: service.introspect_token("opaque-token")
    elif operation == "refresh":
        service.keycloak_openid.refresh_token.side_effect = RuntimeError(SENTINEL)
        call = lambda: service.refresh_token("opaque-refresh-token")
    else:
        monkeypatch.setattr(
            jwt,
            "decode",
            MagicMock(side_effect=RuntimeError(SENTINEL)),
        )
        call = lambda: service.decode_token("opaque-token")

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            call()

    _assert_private(caplog, exc_info.value)


def test_best_effort_logout_and_role_fallback_omit_provider_details(
    service: KeyCloakService,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = MagicMock(status_code=204)
    monkeypatch.setattr(
        keycloak_module.requests, "post", MagicMock(return_value=response)
    )
    service.keycloak_openid.logout.side_effect = RuntimeError(SENTINEL)

    class MalformedPayload:
        def get(self, _key, _default):
            raise RuntimeError(SENTINEL)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        assert service.logout("opaque-refresh-token") is True
        assert service.extract_roles(MalformedPayload()) == []

    _assert_private(caplog)
