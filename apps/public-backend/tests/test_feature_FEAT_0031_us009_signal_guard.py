"""US-009: only the engagement path may use POST through the Public API."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware import MethodRestrictionMiddleware, RequestIDMiddleware


def test_post_is_allowed_only_for_exact_signal_path():
    app = FastAPI()
    app.add_middleware(MethodRestrictionMiddleware)

    @app.post("/api/public/v1/engagement/signal")
    def signal():
        return {"accepted": True}

    with TestClient(app) as client:
        assert client.post("/api/public/v1/engagement/signal").status_code == 200
        assert client.post("/api/public/v1/engagement/signal/").status_code == 405
        assert client.post("/api/public/v1/forms").status_code == 405


def test_signal_response_does_not_echo_caller_request_id():
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.post("/api/public/v1/engagement/signal")
    def signal():
        return {"accepted": False}

    with TestClient(app) as client:
        response = client.post(
            "/api/public/v1/engagement/signal",
            headers={"X-Request-ID": "caller-supplied-id"},
        )
        ordinary = client.get(
            "/ordinary", headers={"X-Request-ID": "caller-supplied-id"}
        )

    assert response.headers["x-request-id"] != "caller-supplied-id"
    assert ordinary.headers["x-request-id"] == "caller-supplied-id"
