"""
BC Transportation Forms - FastAPI Backend
Main application entry point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import structlog
import os

# Configure logging
logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(
    title="BC Transportation Forms API",
    description="RESTful API for managing transportation forms",
    version="1.0.0",
)

# CORS Configuration (from environment variables)
origins = [
    "http://localhost:8000",
    "http://localhost:8080",
    "http://localhost:3000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Mount static files for frontend
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration"""
    return JSONResponse(
        status_code=200,
        content={"status": "healthy", "service": "BC Transportation Forms API"}
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
        status_code=404,
        content={"message": "Frontend index.html not found"}
    )


# Include API routes
from backend.routes import auth, forms

app.include_router(auth.router, prefix="/api/v1")
app.include_router(forms.router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
