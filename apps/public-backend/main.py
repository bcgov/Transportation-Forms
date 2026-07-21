"""Public Read-Only Forms API — FastAPI application entry point.

An independent, anonymous, read-only service that exposes publicly
visible transportation forms.

FEAT-0005 hardening (vs FEAT-0004):
  * **CORS removed** — same-origin via NGINX edge only.
  * ``X-Internal-Auth`` middleware enforces the shared secret injected
    by the public-frontend NGINX reverse proxy.
  * RFC 7807 problem JSON for every error class.
  * Stack traces are never exposed to clients.
"""

import structlog
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from logging_config import configure_logging
from middleware import (
    MethodRestrictionMiddleware,
    RequestIDMiddleware,
    StripSetCookieMiddleware,
    XInternalAuthMiddleware,
)
from problem import problem_response
from routes.forms import router as forms_router
from routes.business_areas import router as business_areas_router
from routes.sitemap import router as sitemap_router
from routes.cms import router as cms_router

# ---------- Logging ----------
configure_logging()
logger = structlog.get_logger()

# ---------- Startup / shutdown ----------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "public_backend_started",
        environment=settings.ENVIRONMENT,
        # Never log the secret value — only whether it's configured.
        internal_auth_configured=bool(settings.INTERNAL_AUTH_SECRET),
    )
    yield
    logger.info("public_backend_stopped")


# ---------- App ----------
app = FastAPI(
    title="BC Transportation Forms — Public API",
    description="Anonymous, read-only API for publicly visible transportation forms.",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# ---------- Middleware stack ----------
# Starlette executes the *last* added middleware first (outermost).
# Order (outer→inner): RequestID → XInternalAuth → MethodRestriction → StripSetCookie
# Rationale: every request must be tagged with an X-Request-ID *before*
# the auth check so rejected requests are still traceable in logs;
# auth runs before method restriction so spammy POSTs without the
# secret get a single 403 (not 405) — denying attackers a method-probe
# oracle.
app.add_middleware(StripSetCookieMiddleware)  # innermost
app.add_middleware(MethodRestrictionMiddleware)
app.add_middleware(XInternalAuthMiddleware, secret=settings.INTERNAL_AUTH_SECRET)
app.add_middleware(RequestIDMiddleware)  # outermost


# ---------- RFC 7807 problem-JSON exception handlers ----------
# These deliberately do **not** include stack traces, library versions,
# or file paths in the response body (US-014 AC14).


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Error"
    title_map = {
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        429: "Too Many Requests",
    }
    return problem_response(
        status=exc.status_code,
        title=title_map.get(exc.status_code, "Error"),
        detail=detail,
        instance=request.url.path,
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    # Surface the field-level errors in the ``errors`` extension member,
    # but strip any value that could echo PII / payload bytes.
    errors = []
    for err in exc.errors():
        errors.append(
            {
                "loc": list(err.get("loc", [])),
                "msg": err.get("msg", "invalid"),
                "type": err.get("type", "invalid"),
            }
        )
    return problem_response(
        status=400,
        title="Bad Request",
        detail="Request validation failed.",
        instance=request.url.path,
        extra={"errors": errors},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    # Log the real exception server-side; return a sanitised body.
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        exc_type=type(exc).__name__,
        # No traceback / message in the response, but it goes to the log.
        exc_message=str(exc),
    )
    return problem_response(
        status=500,
        title="Internal Server Error",
        detail="An internal error occurred.",
        instance=request.url.path,
    )


# ---------- Health probes (kubelet — exempt from X-Internal-Auth) ----------


@app.get("/healthz")
async def liveness():
    return {"status": "healthy"}


@app.get("/readyz")
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return problem_response(
            status=503,
            title="Service Unavailable",
            detail="database unavailable",
        )
    return {"status": "ready"}


# ---------- Routes ----------
app.include_router(forms_router)
app.include_router(business_areas_router)
app.include_router(sitemap_router)
app.include_router(cms_router)
