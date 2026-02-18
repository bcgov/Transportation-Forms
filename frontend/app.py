"""Simple web server for serving frontend pages with API integration."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Create FastAPI app for serving static files
app = FastAPI(title="Transportation Forms Frontend")

# Get the directory where this script is located
frontend_dir = os.path.dirname(os.path.abspath(__file__))

# Mount static files
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def root():
    """Serve the main index page."""
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend index.html not found"}

@app.get("/form-demo")
async def form_demo():
    """Serve the form demo page."""
    demo_path = os.path.join(frontend_dir, "form_demo.html")
    if os.path.exists(demo_path):
        return FileResponse(demo_path)
    return {"message": "Form demo page not found"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
