from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import auth as firebase_auth
from app.models.tenant import ChatbotConfig
from app.models.user import User
from app.api.v1.endpoints.auth import get_current_user
from app.db.firestore import db
from app.services.workflow import WorkflowService
from app.core.rbac import check_permission, Action

router = APIRouter()

# --- DASHBOARD DATA ---

@router.get("/my-tenants")
async def get_user_tenants(user: dict = Depends(get_current_user)):
    """Returns tenants assigned to the current user."""
    if not check_permission(user["role"], Action.VIEW_DASHBOARD):
        raise HTTPException(status_code=403, detail="Access denied")

    user_doc = db.collection("users").document(user["uid"]).get()
    if not user_doc.exists: return []
    
    assigned_ids = user_doc.to_dict().get("assigned_tenants", [])
    tenants_list = []
    
    # Super Admins see everything, others see assigned only
    if user["role"] == "super_admin":
        docs = db.collection("tenants").stream()
    else:
        if not assigned_ids: return []
        docs = db.collection("tenants").where("tenant_id", "in", assigned_ids).stream()

    for doc in docs:
        t = doc.to_dict()
        tenants_list.append({
            "name": t.get("client_name"),
            "slug": t.get("slug"),
            "status": t.get("approval_status", "draft"),
            "tenant_id": t.get("tenant_id")
        })
    return tenants_list

@router.get("/approvals")
async def list_pending_approvals(user: dict = Depends(get_current_user)):
    """Returns items waiting for this specific user's review."""
    role = user["role"]
    target_status = None
    
    if role == "admin": target_status = "pending_admin_review"
    elif role == "super_admin": target_status = "pending_super_admin_review"
    else: return []

    docs = db.collection("tenants").where("approval_status", "==", target_status).stream()
    pending = []
    for doc in docs:
        t = doc.to_dict()
        pending.append({
            "tenant_id": t.get("tenant_id"),
            "client_name": t.get("client_name"),
            "modified_by": t.get("last_modified_by"),
            "changes": t.get("pending_config")
        })
    return pending

# --- WORKFLOW ---

@router.post("/submit-draft/{tenant_id}")
async def submit_draft(tenant_id: str, config: ChatbotConfig, user: dict = Depends(get_current_user)):
    """Saves changes and moves to pending review."""
    if not check_permission(user["role"], Action.EDIT_DRAFT):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    return await WorkflowService.process_submission(
        tenant_id, config.dict(), user["role"], user["email"]
    )

@router.post("/approve/{tenant_id}")
async def approve_config(tenant_id: str, user: dict = Depends(get_current_user)):
    """Approves changes to the next stage."""
    if not check_permission(user["role"], Action.SUBMIT_REVIEW):
         raise HTTPException(status_code=403, detail="Permission denied")

    return await WorkflowService.process_approval(tenant_id, user["role"], user["email"])

# --- USER MANAGEMENT ---

@router.get("/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    return [doc.to_dict() for doc in db.collection("users").stream()]

@router.post("/users")
async def onboard_user(user_data: dict, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        user_record = firebase_auth.create_user(
            email=user_data.get("email"),
            password=user_data.get("password"),
            email_verified=False
        )
        new_user = User(
            uid=user_record.uid,
            email=user_data.get("email"),
            role=user_data.get("role", "contributor"),
            assigned_tenants=user_data.get("assigned_tenants", [])
        )
        db.collection("users").document(new_user.uid).set(new_user.dict())
        return {"message": "User created", "uid": new_user.uid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/users/{uid}")
async def offboard_user(uid: str, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        firebase_auth.delete_user(uid)
        db.collection("users").document(uid).delete()
        return {"message": "User deleted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ==========================================
# 4. TENANT MANAGEMENT (SUPER ADMIN)
# ==========================================

@router.get("/tenants")
async def list_all_tenants(current_user: dict = Depends(get_current_user)):
    """List all tenants for the management table."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS): # Reusing Super Admin Priv
        raise HTTPException(status_code=403, detail="Permission denied")
    
    tenants = []
    docs = db.collection("tenants").stream()
    for doc in docs:
        tenants.append(doc.to_dict())
    return tenants

@router.post("/tenants")
async def create_tenant(payload: dict, current_user: dict = Depends(get_current_user)):
    """
    Onboard a new Tenant with an initial Chatbot Config.
    Payload: { "client_name": "...", "slug": "...", "tenant_id": "...", "bot_name": "...", "primary_color": "..." }
    """
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")

    # 1. Validation
    tenant_id = payload.get("tenant_id")
    slug = payload.get("slug")
    if not tenant_id or not slug:
        raise HTTPException(status_code=400, detail="Tenant ID and Slug are required")

    # 2. Check for duplicates
    if db.collection("tenants").document(tenant_id).get().exists:
         raise HTTPException(status_code=400, detail="Tenant ID already exists")

    # 3. Create Initial Config
    initial_config = ChatbotConfig(
        bot_name=payload.get("bot_name", "My Bot"),
        primary_color=payload.get("primary_color", "#10B981"),
        welcome_message=payload.get("welcome_message", "Hello! How can we help?"),
        bot_id=f"bot-{tenant_id}",
        logo_url="https://via.placeholder.com/150"
    )

    # 4. Create Tenant Object
    from app.models.tenant import Tenant, ApprovalStatus # Ensure Import
    
    new_tenant = Tenant(
        tenant_id=tenant_id,
        client_name=payload.get("client_name"),
        slug=slug,
        live_config=initial_config, # Start live immediately? Or use pending_config if you prefer draft first.
        approval_status=ApprovalStatus.PUBLISHED, # Auto-publish for onboarding convenience
        last_modified_by=current_user["email"],
        last_modified_at=datetime.utcnow()
    )

    db.collection("tenants").document(tenant_id).set(new_tenant.dict())
    return {"message": "Tenant onboarded successfully", "url": f"/{slug}"}

@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, current_user: dict = Depends(get_current_user)):
    """Offboard a Tenant (Delete from DB)."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")

    db.collection("tenants").document(tenant_id).delete()
    return {"message": f"Tenant {tenant_id} offboarded."}