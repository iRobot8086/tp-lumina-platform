from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import auth as firebase_auth
from datetime import datetime

from app.models.tenant import ChatbotConfig, Tenant, ApprovalStatus
from app.models.user import User
from app.api.v1.endpoints.auth import get_current_user
from app.db.firestore import db
from app.services.workflow import WorkflowService
from app.core.rbac import check_permission, Action
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/my-tenants")
async def get_user_tenants(user: dict = Depends(get_current_user)):
    if not check_permission(user["role"], Action.VIEW_DASHBOARD):
        raise HTTPException(status_code=403, detail="Access denied")

    user_doc = db.collection("users").document(user["uid"]).get()
    assigned_ids = user_doc.to_dict().get("assigned_tenants", []) if user_doc.exists else []
    
    tenants_list = []
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
            "tenant_id": t.get("tenant_id"),
            "live_config": t.get("live_config")
        })
    return tenants_list

@router.get("/approvals")
async def list_pending_approvals(user: dict = Depends(get_current_user)):
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

# --- WORKFLOW ROUTES ---

@router.post("/submit-draft/{tenant_id}")
async def submit_draft(tenant_id: str, config: ChatbotConfig, user: dict = Depends(get_current_user)):
    if not check_permission(user["role"], Action.EDIT_DRAFT):
        raise HTTPException(status_code=403, detail="Permission denied")
    return await WorkflowService.process_submission(tenant_id, config.dict(), user["role"], user["email"])

@router.post("/approve/{tenant_id}")
async def approve_config(tenant_id: str, user: dict = Depends(get_current_user)):
    if not check_permission(user["role"], Action.SUBMIT_REVIEW):
         raise HTTPException(status_code=403, detail="Permission denied")
    return await WorkflowService.process_approval(tenant_id, user["role"], user["email"])

# --- TENANT MANAGEMENT ---

@router.get("/tenants")
async def list_all_tenants(current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    return [doc.to_dict() for doc in db.collection("tenants").stream()]

@router.post("/tenants")
async def create_tenant(payload: dict, current_user: dict = Depends(get_current_user)):
    """Onboard Tenant with Raw Custom JS."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")

    tenant_id = payload.get("tenant_id")
    slug = payload.get("slug")
    
    if not tenant_id or not slug:
        raise HTTPException(status_code=400, detail="ID and Slug required")
    if db.collection("tenants").document(tenant_id).get().exists:
         raise HTTPException(status_code=400, detail="Tenant ID already exists")

    initial_config = ChatbotConfig(
        bot_name=payload.get("bot_name", "My Bot"),
        primary_color=payload.get("primary_color", "#10B981"),
        welcome_message=payload.get("welcome_message", "Hello!"),
        
        # --- NEW: Capture raw JS from payload ---
        custom_js=payload.get("custom_js", "") 
    )

    new_tenant = Tenant(
        tenant_id=tenant_id,
        client_name=payload.get("client_name"),
        slug=slug,
        live_config=initial_config,
        approval_status=ApprovalStatus.PUBLISHED,
        last_modified_by=current_user["email"],
        last_modified_at=datetime.utcnow()
    )

    db.collection("tenants").document(tenant_id).set(new_tenant.dict())
    return {"message": "Tenant onboarded", "url": f"/{slug}"}

@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    db.collection("tenants").document(tenant_id).delete()
    return {"message": "Tenant offboarded"}

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
        logger.error(f"Onboarding failed: {e}")
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
        logger.error(f"Deletion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))