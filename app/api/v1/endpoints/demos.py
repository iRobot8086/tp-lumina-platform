from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.db.firestore import db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/{slug}", response_class=HTMLResponse)
async def render_demo_page(slug: str, request: Request, preview: bool = False):
    """
    Renders the public demo page.
    - Standard: Loads 'live_config'.
    - ?preview=true: Loads 'pending_config' (Draft) if it exists.
    """
    # 1. Fetch Tenant
    tenants_ref = db.collection("tenants")
    query = tenants_ref.where("slug", "==", slug).limit(1).stream()
    
    tenant_doc = next(query, None)
    if not tenant_doc:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    tenant_data = tenant_doc.to_dict()
    
    # 2. Determine Config Source
    config = tenant_data.get("live_config")
    is_preview_mode = False

    if preview:
        pending = tenant_data.get("pending_config")
        if pending:
            config = pending
            is_preview_mode = True
            # Optional: Overwrite bot name to indicate preview
            # config["bot_name"] += " (Preview)" 
    
    # Fallback if config is missing entirely
    if not config:
        config = {
            "bot_name": "Setup Required",
            "welcome_message": "This tenant has not been configured yet.",
            "primary_color": "#6B7280"
        }

    # 3. Render Template
    # We pass 'is_preview' to the template so we can show a warning banner
    return templates.TemplateResponse("demo_base.html", {
        "request": request,
        "client_name": tenant_data.get("client_name", "Lumina Demo"),
        "config": config,
        "is_preview": is_preview_mode 
    })