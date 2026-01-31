import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from firebase_admin import auth as firebase_auth
from datetime import datetime

# Models
from app.models.tenant import ChatbotConfig, Tenant, ApprovalStatus
from app.models.user import User

# Core Services
from app.api.v1.endpoints.auth import get_current_user
from app.db.firestore import db
from app.services.workflow import WorkflowService
from app.core.rbac import check_permission, Action
from app.storage import upload_file_to_gcs

# New Services
from app.services.audit import log_activity
from app.services.notifications import notify_admins, notify_user_by_email

# Setup Logging
logger = logging.getLogger("lumina.admin")
router = APIRouter()

# --- 1. AUDIT LOGS ---
@router.get("/audit-logs")
async def get_audit_logs(limit: int = 50, user: dict = Depends(get_current_user)):
    """Fetches system activity logs (Super Admin Only)."""
    if user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        docs = db.collection("audit_logs")\
                 .order_by("timestamp", direction="DESCENDING")\
                 .limit(limit)\
                 .stream()
        
        logs = []
        for doc in docs:
            d = doc.to_dict()
            # Serialize timestamp for JSON response
            if isinstance(d.get("timestamp"), datetime):
                d["timestamp"] = d["timestamp"].isoformat()
            logs.append(d)
        return logs
    except Exception as e:
        logger.error(f"Audit fetch failed: {e}")
        return []

# --- 2. STATS ---
@router.get("/stats")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    """Aggregates dashboard counts based on Role & Visibility."""
    if not check_permission(user["role"], Action.VIEW_DASHBOARD):
        raise HTTPException(status_code=403, detail="Access denied")

    stats = {"projects": 0, "approvals": 0, "users": 0}
    try:
        if user["role"] == "super_admin":
            # Count only active (non-archived) items
            all_tenants = list(db.collection("tenants").stream())
            stats["projects"] = len([t for t in all_tenants if not t.to_dict().get("is_archived", False)])
            
            all_users = list(db.collection("users").stream())
            stats["users"] = len([u for u in all_users if not u.to_dict().get("is_archived", False)])
        else:
            # For non-admins, count assigned projects
            user_doc = db.collection("users").document(user["uid"]).get()
            if user_doc.exists:
                assigned = user_doc.to_dict().get("assigned_tenants", [])
                stats["projects"] = len(assigned)

        # Count Pending Approvals
        if user["role"] in ["admin", "super_admin"]:
            target_status = "pending_admin_review" if user["role"] == "admin" else "pending_super_admin_review"
            query = db.collection("tenants").where("approval_status", "==", target_status).stream()
            stats["approvals"] = len(list(query))

        return stats
    except Exception as e:
        logger.error(f"Stats aggregation failed: {e}")
        return stats

# --- 3. ASSET UPLOAD ---
@router.post("/upload")
async def upload_asset(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Uploads image to GCS (Used for Banners/Avatars)."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")

    if file.content_type not in ["image/jpeg", "image/png", "image/webp", "image/gif"]:
        raise HTTPException(status_code=400, detail="Only images allowed")

    try:
        public_url = upload_file_to_gcs(file.file, file.filename, file.content_type)
        return {"url": public_url}
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Image upload failed")

# --- 4. TENANT READ OPERATIONS ---
@router.get("/my-tenants")
async def get_user_tenants(user: dict = Depends(get_current_user)):
    """Returns list of ACTIVE tenants visible to current user."""
    if not check_permission(user["role"], Action.VIEW_DASHBOARD):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        user_doc = db.collection("users").document(user["uid"]).get()
        assigned_ids = user_doc.to_dict().get("assigned_tenants", []) if user_doc.exists else []
        
        tenants_list = []

        if user["role"] == "super_admin":
            docs = db.collection("tenants").stream()
            for doc in docs:
                t = doc.to_dict()
                # Exclude archived from main workspace
                if not t.get("is_archived", False):
                    tenants_list.append(format_tenant_response(t))
        else:
            if not assigned_ids: return []
            for tid in assigned_ids:
                if not tid: continue
                doc = db.collection("tenants").document(tid.strip()).get()
                if doc.exists:
                    t = doc.to_dict()
                    if not t.get("is_archived", False):
                        tenants_list.append(format_tenant_response(t))

        return tenants_list
    except Exception:
        raise HTTPException(status_code=500, detail="Internal Server Error")

def format_tenant_response(t: dict):
    return {
        "name": t.get("client_name"),
        "slug": t.get("slug"),
        "status": t.get("approval_status", "draft"),
        "tenant_id": t.get("tenant_id"),
        "live_config": t.get("live_config"),
        "is_archived": t.get("is_archived", False)
    }

@router.get("/tenants/{tenant_id}")
async def get_tenant_details(tenant_id: str, current_user: dict = Depends(get_current_user)):
    """Fetches full details for Editing (prefers Draft config)."""
    if not check_permission(current_user["role"], Action.VIEW_DASHBOARD):
         raise HTTPException(status_code=403, detail="Access denied")

    # Assignment Check
    if current_user["role"] != "super_admin":
        user_doc = db.collection("users").document(current_user["uid"]).get()
        assigned_ids = user_doc.to_dict().get("assigned_tenants", []) if user_doc.exists else []
        if tenant_id not in assigned_ids:
            raise HTTPException(status_code=403, detail="Access denied to this tenant")

    doc = db.collection("tenants").document(tenant_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    data = doc.to_dict()
    # If a draft exists, return that for editing; otherwise live config
    display_config = data.get("pending_config") or data.get("live_config") or {}
    
    return {
        "tenant_id": data.get("tenant_id"),
        "client_name": data.get("client_name"),
        "slug": data.get("slug"),
        "config": display_config,
        "status": data.get("approval_status")
    }

@router.get("/approvals")
async def list_pending_approvals(user: dict = Depends(get_current_user)):
    """Lists tenants pending review."""
    role = user["role"]
    target_status = None
    if role == "admin": target_status = "pending_admin_review"
    elif role == "super_admin": target_status = "pending_super_admin_review"
    else: return []

    try:
        docs = db.collection("tenants").where("approval_status", "==", target_status).stream()
        return [{
            "tenant_id": t.to_dict().get("tenant_id"),
            "client_name": t.to_dict().get("client_name"),
            "slug": t.to_dict().get("slug"),
            "modified_by": t.to_dict().get("last_modified_by"),
            "changes": t.to_dict().get("pending_config")
        } for t in docs if not t.to_dict().get("is_archived", False)]
    except Exception as e:
        logger.error(f"Error fetching approvals: {e}")
        return []

# --- 5. WORKFLOW ACTIONS (Notifications & Logs) ---
@router.post("/submit-draft/{tenant_id}")
async def submit_draft(tenant_id: str, config: ChatbotConfig, user: dict = Depends(get_current_user)):
    """Submits changes for approval."""
    if not check_permission(user["role"], Action.EDIT_DRAFT):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    result = await WorkflowService.process_submission(tenant_id, config.dict(), user["role"], user["email"])
    
    # Log & Notify
    await log_activity(user["email"], user["role"], "SUBMIT_DRAFT", tenant_id, "Submitted new configuration draft")
    await notify_admins(
        title="New Draft Submitted",
        message=f"{user['email']} submitted a draft for {tenant_id}.",
        link="#"
    )
    
    return result

@router.post("/approve/{tenant_id}")
async def approve_config(tenant_id: str, user: dict = Depends(get_current_user)):
    """Approves and publishes a draft."""
    if not check_permission(user["role"], Action.SUBMIT_REVIEW):
         raise HTTPException(status_code=403, detail="Permission denied")
    
    # Retrieve submitter info before approving
    tenant_doc = db.collection("tenants").document(tenant_id).get()
    tenant_data = tenant_doc.to_dict()
    submitter_email = tenant_data.get("last_modified_by")

    # Execute Approval
    result = await WorkflowService.process_approval(tenant_id, user["role"], user["email"])
    
    # Log & Notify
    await log_activity(user["email"], user["role"], "APPROVE_TENANT", tenant_id, "Approved pending configuration")
    
    if submitter_email:
        await notify_user_by_email(
            email=submitter_email,
            title="Draft Approved",
            message=f"Your changes for {tenant_data.get('client_name')} have been published.",
            link=f"/{tenant_data.get('slug')}"
        )

    return result

# --- 6. TENANT MANAGEMENT (CRUD + Soft Delete) ---
@router.get("/tenants")
async def list_all_tenants(show_archived: bool = Query(False), current_user: dict = Depends(get_current_user)):
    """Lists all tenants (Super Admin view), filters archived by default."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    all_docs = [doc.to_dict() for doc in db.collection("tenants").stream()]
    filtered = [t for t in all_docs if t.get("is_archived", False) == show_archived]
    return filtered

@router.post("/tenants")
async def create_tenant(payload: dict, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        tenant_id = payload.get("tenant_id")
        slug = payload.get("slug")
        
        if not tenant_id or not slug:
            raise HTTPException(status_code=400, detail="ID and Slug required")
        if db.collection("tenants").document(tenant_id).get().exists:
             raise HTTPException(status_code=400, detail="Tenant ID already exists")

        # Process Banners
        raw_banners = payload.get("banner_urls", [])
        if isinstance(raw_banners, str):
            banner_list = [url.strip() for url in raw_banners.split('\n') if url.strip()]
        else:
            banner_list = raw_banners

        initial_config = ChatbotConfig(
            bot_name=payload.get("bot_name", "My Bot"),
            primary_color=payload.get("primary_color", "#10B981"),
            welcome_message=payload.get("welcome_message", "Hello!"),
            custom_js=payload.get("custom_js", ""),
            background_color=payload.get("background_color", "#F9FAFB"),
            banner_urls=banner_list
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
        
        tenant_data = new_tenant.dict()
        tenant_data["is_archived"] = False

        db.collection("tenants").document(tenant_id).set(tenant_data)
        
        await log_activity(current_user["email"], current_user["role"], "CREATE_TENANT", tenant_id, f"Created tenant {slug}")
        return {"message": "Tenant onboarded", "url": f"/{slug}"}
    except Exception as e:
        logger.error(f"Tenant creation failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to onboard tenant.")

@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, current_user: dict = Depends(get_current_user)):
    """Soft Delete: Archives the tenant."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    db.collection("tenants").document(tenant_id).update({"is_archived": True})
    await log_activity(current_user["email"], current_user["role"], "ARCHIVE_TENANT", tenant_id, "Archived tenant")
    return {"message": "Tenant archived"}

@router.post("/tenants/{tenant_id}/restore")
async def restore_tenant(tenant_id: str, current_user: dict = Depends(get_current_user)):
    """Restores archived tenant."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    db.collection("tenants").document(tenant_id).update({"is_archived": False})
    await log_activity(current_user["email"], current_user["role"], "RESTORE_TENANT", tenant_id, "Restored tenant")
    return {"message": "Tenant restored"}

# --- 7. USER MANAGEMENT (CRUD + Role + Archive) ---
@router.get("/users")
async def list_users(show_archived: bool = Query(False), current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    all_users = [doc.to_dict() for doc in db.collection("users").stream()]
    filtered = [u for u in all_users if u.get("is_archived", False) == show_archived]
    return filtered

@router.post("/users")
async def onboard_user(user_data: dict, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        raw_tenants = user_data.get("assigned_tenants", [])
        clean_tenants = [t.strip() for t in raw_tenants if t.strip()]

        user_record = firebase_auth.create_user(
            email=user_data.get("email"),
            password=user_data.get("password"),
            email_verified=False
        )
        new_user = User(
            uid=user_record.uid,
            email=user_data.get("email"),
            role=user_data.get("role", "contributor"),
            assigned_tenants=clean_tenants
        )
        
        user_dict = new_user.dict()
        user_dict["is_archived"] = False
        
        db.collection("users").document(new_user.uid).set(user_dict)
        await log_activity(current_user["email"], current_user["role"], "CREATE_USER", user_data.get("email"), f"Role: {new_user.role}")
        return {"message": "User created", "uid": new_user.uid}
    except Exception as e:
        logger.error(f"User onboarding error: {e}")
        raise HTTPException(status_code=400, detail="User creation failed. Email might exist.")

@router.put("/users/{uid}/role")
async def update_user_role(uid: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """Updates user role."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    new_role = payload.get("role")
    if new_role not in ["super_admin", "admin", "contributor"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    try:
        db.collection("users").document(uid).update({"role": new_role})
        await log_activity(current_user["email"], current_user["role"], "UPDATE_ROLE", uid, f"Changed role to {new_role}")
        return {"message": "Role updated"}
    except Exception as e:
        logger.error(f"Role update failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to update role")

@router.delete("/users/{uid}")
async def offboard_user(uid: str, current_user: dict = Depends(get_current_user)):
    """Soft Delete: Disables login & archives in DB."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        firebase_auth.update_user(uid, disabled=True)
        db.collection("users").document(uid).update({"is_archived": True})
        
        await log_activity(current_user["email"], current_user["role"], "ARCHIVE_USER", uid, "Disabled user access")
        return {"message": "User archived"}
    except Exception as e:
        logger.error(f"User deletion error: {e}")
        raise HTTPException(status_code=400, detail="Failed to archive user.")

@router.post("/users/{uid}/restore")
async def restore_user(uid: str, current_user: dict = Depends(get_current_user)):
    """Restores user access."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        firebase_auth.update_user(uid, disabled=False)
        db.collection("users").document(uid).update({"is_archived": False})
        
        await log_activity(current_user["email"], current_user["role"], "RESTORE_USER", uid, "Restored user access")
        return {"message": "User restored"}
    except Exception as e:
        logger.error(f"User restore error: {e}")
        raise HTTPException(status_code=400, detail="Failed to restore user.")