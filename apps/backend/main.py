"""
BC Transportation Forms - FastAPI Backend
Main application entry point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from botocore.exceptions import BotoCoreError, ClientError
from contextlib import asynccontextmanager
import structlog
import os

from backend.config import settings
from backend.routes import (
    auth,
    forms,
    business_areas,
    workflow,
    roles,
    access_requests,
    admin_users,
)
from backend.routes.business_areas_admin import router as business_areas_admin_router
from backend.routes.prefixes import public_router as prefixes_public_router
from backend.routes.prefixes import admin_router as prefixes_admin_router
from backend.routes.reservations import router as reservations_router
from backend.routes.stats import router as stats_router

# Configure logging
logger = structlog.get_logger()


# Initialise S3 object storage bucket on startup (idempotent — safe to run every boot).
#
# Note: default role/permission seeding is intentionally NOT performed here.
# Seeding writes are owned by the migrations job (see
# ``apps/backend/migrations/entrypoint.sh``) so that:
#   * failures fail the deployment fast instead of being silently logged
#   * request-serving pods don't compete for write access on boot
#   * startup latency is bounded and unrelated to schema/role drift
@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        import anyio

        from backend.services.s3_service import ensure_bucket_exists

        await anyio.to_thread.run_sync(ensure_bucket_exists)
        logger.info("s3_bucket_initialised")
    except (BotoCoreError, ClientError) as exc:
        logger.warning(
            "s3_bucket_initialisation_skipped",
            error_type=type(exc).__name__,
        )
    yield


# Create FastAPI app
app = FastAPI(
    title="BC Transportation Forms API",
    description="RESTful API for managing transportation forms",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Configuration (driven by CORS_ORIGINS environment variable)
origins = [
    origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Mount static files for frontend
frontend_dir = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
)
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration"""
    return JSONResponse(
        status_code=200,
        content={"status": "healthy", "service": "BC Transportation Forms API"},
    )


@app.get("/api/v1/")
async def root():
    """Root API endpoint"""
    return {
        "message": "BC Transportation Forms API v1.0.0",
        "docs": "/api/v1/docs",
        "redoc": "/api/v1/redoc",
    }


@app.get("/")
async def serve_frontend():
    """Serve the frontend index page"""
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(
        status_code=404, content={"message": "Frontend index.html not found"}
    )


# Include API routes

app.include_router(auth.router, prefix="/api/v1")
app.include_router(forms.router, prefix="/api/v1")
app.include_router(workflow.router, prefix="/api/v1")
app.include_router(business_areas.router, prefix="/api/v1")
app.include_router(business_areas_admin_router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")
app.include_router(access_requests.router, prefix="/api/v1")
app.include_router(admin_users.router, prefix="/api/v1")
app.include_router(prefixes_public_router, prefix="/api/v1")
app.include_router(prefixes_admin_router, prefix="/api/v1")
app.include_router(reservations_router, prefix="/api/v1")
app.include_router(stats_router, prefix="/api/v1")


@app.get("/{path:path}")
async def serve_frontend_paths(path: str):
    """Catch-all route to serve frontend for SPA routing"""
    # Check if this is an API route
    if path.startswith("api/"):
        return JSONResponse(
            status_code=404, content={"message": "API endpoint not found"}
        )

    # Check if this is a static file request
    if "." in path and path.split(".")[-1] in [
        "js",
        "css",
        "png",
        "jpg",
        "gif",
        "svg",
        "font",
        "woff",
        "woff2",
        "ttf",
        "eot",
    ]:
        # Resolve against the known frontend directory and normalize the path
        static_path = os.path.realpath(os.path.join(frontend_dir, path))
        # Ensure the resolved path is within the frontend directory to prevent directory traversal
        if os.path.commonpath([frontend_dir, static_path]) != frontend_dir:
            return JSONResponse(
                status_code=404, content={"message": "Static file not found"}
            )
        if os.path.exists(static_path):
            return FileResponse(static_path)
        return JSONResponse(
            status_code=404, content={"message": "Static file not found"}
        )

    # Serve frontend index.html for all other routes (SPA routing)
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(status_code=404, content={"message": "Frontend not found"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
