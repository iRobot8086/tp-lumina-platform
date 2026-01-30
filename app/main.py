import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()

# Import Routers
from app.api.v1.endpoints import admin, demos, auth

app = FastAPI(
    title="Lumina Platform",
    description="Chatbot Orchestration Backend"
)

# --- 1. SECURITY & MIDDLEWARE ---

# CORS: Allow frontend access (Adjust origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSP: Prevent XSS attacks by restricting script sources
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://www.gstatic.com https://chatbot.ema.co; "
            "connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com;"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# --- 2. SETUP ---
os.makedirs("app/static", exist_ok=True)
os.makedirs("app/templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- 3. API ROUTES ---
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])

# New Endpoint: Serve Frontend Config Dynamically
@app.get("/api/v1/config")
async def get_frontend_config():
    """Returns public Firebase config from environment variables."""
    return {
        "apiKey": os.getenv("FIREBASE_API_KEY"),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
        "projectId": os.getenv("GCP_PROJECT_ID"),
        "storageBucket": os.getenv("GCP_STORAGE_BUCKET"),
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
        "appId": os.getenv("FIREBASE_APP_ID")
    }

# --- 4. FRONTEND ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/health")
async def health():
    # Removed sensitive Project ID from response
    return {"status": "online"}

# --- 5. CATCH-ALL ROUTE (LAST) ---
app.include_router(demos.router, tags=["Demos"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)