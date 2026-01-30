import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Import Routers
from app.api.v1.endpoints import admin, demos, auth

app = FastAPI(
    title="Lumina Platform",
    description="Chatbot Orchestration Backend"
)

# Setup Directories
os.makedirs("app/static", exist_ok=True)
os.makedirs("app/templates", exist_ok=True)

# Mount Static & Templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- API ROUTES ---
# Consistent /api/v1 prefix for all data endpoints
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])

# --- FRONTEND ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serves the Login Page."""
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Serves the main Control Panel."""
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/health")
async def health():
    return {"status": "ok", "project": "tp-lumina-485907"}

# --- CATCH-ALL ROUTE (LAST) ---
# This matches /{slug} for the demo pages. Must be last.
app.include_router(demos.router, tags=["Demos"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)