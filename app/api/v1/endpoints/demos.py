from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.db.firestore import db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/{slug}", response_class=HTMLResponse)
async def render_demo_page(request: Request, slug: str):
    
    # --- SAFEGUARD START ---
    # If the ordering in main.py fails, this prevents the error.
    reserved_routes = ["dashboard", "login", "auth", "static", "favicon.ico"]
    if slug in reserved_routes:
        # We raise 404 so FastAPI knows this isn't a tenant, 
        # but really this shouldn't be hit if main.py is correct.
        raise HTTPException(status_code=404, detail="Reserved route")
    # --- SAFEGUARD END ---

    query = db.collection("tenants").where("slug", "==", slug).limit(1).stream()
    tenant = None
    for doc in query:
        tenant = doc.to_dict()
    
    if not tenant or not tenant.get("live_config"):
        raise HTTPException(status_code=404, detail="Demo page not found or not published")

    return templates.TemplateResponse("demo_base.html", {
        "request": request,
        "config": tenant["live_config"],
        "client_name": tenant["client_name"]
    })