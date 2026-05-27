"""Custom middleware for the public-backend service.

- RequestIDMiddleware: propagates or generates X-Request-ID.
- MethodRestrictionMiddleware: rejects non-GET/OPTIONS/HEAD with 405.
- StripSetCookieMiddleware: removes any Set-Cookie headers (defense-in-depth).
- XInternalAuthMiddleware: enforces the FEAT-0005 shared-secret header
  injected by the public-frontend NGINX edge (constant-time compare;
  ``/healthz`` and ``/readyz`` are exempt for kubelet probes).
"""

import hmac
import re
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_REQUEST_ID_MAX_LEN = 128
_REQUEST_ID_SAFE = re.compile(r"^[\w\-\.]+$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Propagate ``X-Request-ID`` from the incoming request or generate one."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        raw = request.headers.get("X-Request-ID", "")

        # Sanitise: allow only alphanumerics, hyphens, underscores, dots.
        if raw and _REQUEST_ID_SAFE.match(raw):
            request_id = raw[:_REQUEST_ID_MAX_LEN]
        else:
            request_id = uuid.uuid4().hex

        # Attach to request state for downstream use (logging, routes).
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class MethodRestrictionMiddleware(BaseHTTPMiddleware):
    """Return 405 for any HTTP method other than GET, HEAD, OPTIONS."""

    _ALLOWED = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method not in self._ALLOWED:
            return JSONResponse(
                status_code=405,
                content={"detail": "Method Not Allowed"},
                headers={"Allow": "GET, HEAD, OPTIONS"},
            )
        return await call_next(request)


class StripSetCookieMiddleware(BaseHTTPMiddleware):
    """Remove any ``Set-Cookie`` header from outgoing responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if "set-cookie" in response.headers:
            del response.headers["set-cookie"]
        return response


# Paths exempt from X-Internal-Auth.  Kubelet liveness/readiness probes
# call these without going through the public-frontend NGINX edge and
# therefore cannot supply the shared secret.
_AUTH_EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})


class XInternalAuthMiddleware(BaseHTTPMiddleware):
    """Enforce the ``X-Internal-Auth`` shared-secret header (FEAT-0005 / US-013).

    Defence-in-depth: the public-backend Service is ClusterIP-only and a
    NetworkPolicy limits ingress to ``app=public-frontend`` Pods, but this
    middleware adds an application-layer check so a misconfigured network
    policy does not silently expose the API.

    Security properties:

    * Constant-time comparison via :func:`hmac.compare_digest` — no timing
      oracle distinguishes ``correct``/``wrong``/``missing``.
    * Generic 403 body — never echoes the supplied or expected secret.
    * The expected secret is read from settings exactly once at construction
      time so log scrubbers cannot accidentally surface it via
      ``request.app.state``.
    * ``/healthz`` and ``/readyz`` are exempt for kubelet probes.

    If the configured secret is empty (test/local-dev convenience) the
    middleware degrades to a permissive no-op and emits a single warning so
    the misconfiguration is noisy in CI.  Production charts MUST inject a
    non-empty secret (see US-013 / charts/public-backend Secret).
    """

    def __init__(self, app, *, secret: str) -> None:
        super().__init__(app)
        # Encode once; compare_digest needs same-type bytes/str pair.
        self._expected: bytes = secret.encode("utf-8") if secret else b""
        self._enabled: bool = bool(self._expected)
        self._log = structlog.get_logger("public_backend.auth")
        if not self._enabled:
            self._log.warning(
                "internal_auth_disabled",
                reason="INTERNAL_AUTH_SECRET is empty; middleware is a no-op",
            )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in _AUTH_EXEMPT_PATHS:
            return await call_next(request)

        if not self._enabled:
            return await call_next(request)

        supplied = request.headers.get("X-Internal-Auth", "").encode("utf-8")
        if not hmac.compare_digest(supplied, self._expected):
            # Generic body — never disclose expected/supplied value, never
            # echo header in logs.  Real client IP is structurally safe to
            # log (no PII) and useful for ops.
            self._log.warning(
                "internal_auth_rejected",
                path=request.url.path,
                client_ip=request.headers.get("X-Real-IP")
                or (request.client.host if request.client else None),
            )
            return JSONResponse(
                status_code=403,
                content={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": "Forbidden",
                    "instance": request.url.path,
                },
                media_type="application/problem+json",
            )

        return await call_next(request)
