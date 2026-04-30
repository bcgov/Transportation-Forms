"""Custom middleware for the public-backend service.

- RequestIDMiddleware: propagates or generates X-Request-ID.
- MethodRestrictionMiddleware: rejects non-GET/OPTIONS/HEAD with 405.
- StripSetCookieMiddleware: removes any Set-Cookie headers (defense-in-depth).
"""

import re
import uuid

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
