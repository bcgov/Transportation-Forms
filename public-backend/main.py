"""Public Read-Only Forms API — FastAPI application entry point.

An independent, anonymous, read-only service that exposes publicly
visible transportation forms.  No authentication.  No write operations.
"""

import os
import sys

# Ensure the public-backend directory is importable regardless of CWD.
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal, get_db
from logging_config import configure_logging
from middleware import (
    MethodRestrictionMiddleware,
    RequestIDMiddleware,
    StripSetCookieMiddleware,
)
from routes.forms import router as forms_router

# ---------- Logging ----------
configure_logging()
logger = structlog.get_logger()

# ---------- App ----------
app = FastAPI(
    title="BC Transportation Forms — Public API",
    description="Anonymous, read-only API for publicly visible transportation forms.",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ---------- CORS (US-002) ----------
_origins = [
    o.strip().rstrip("/")
    for o in settings.PUBLIC_CORS_ORIGINS.split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "If-None-Match", "X-Request-ID"],
)

# Middleware stack — added in innermost-first order.
# Starlette executes the *last* added middleware first (outermost).
app.add_middleware(StripSetCookieMiddleware)      # innermost
app.add_middleware(MethodRestrictionMiddleware)    # middle
app.add_middleware(RequestIDMiddleware)            # outermost


# ---------- Health probes (US-004 AC1 / AC2 / AC3) ----------

@app.get("/healthz")
async def liveness():
    return JSONResponse(content={"status": "healthy"})


@app.get("/readyz")
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "database unavailable"},
        )
    return JSONResponse(content={"status": "ready"})


# ---------- Routes ----------
app.include_router(forms_router)


# ---------- Startup / shutdown ----------

@app.on_event("startup")
async def startup_event():
    logger.info("public_backend_started", environment=settings.ENVIRONMENT)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("public_backend_stopped")
