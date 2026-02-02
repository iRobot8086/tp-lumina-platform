import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from firebase_admin import auth as firebase_auth
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

# Models
from app.models.tenant import ChatbotConfig, Tenant, ApprovalStatus
from app.models.user import User

# Core Services
from app.api.v1.endpoints.auth import get_current_user
from app.db.firestore import db
from app.services.workflow import WorkflowService
from app.core.rbac import check_permission, Action, UserRole
from app.storage import upload_file_to_gcs

# New Services
from app.services.audit import log_activity
from app.services.notifications import notify_admins, notify_user_by_email

# Setup Logging
logger = logging.getLogger("lumina.admin")
router = APIRouter()

# --- INPUT MODELS ---
class RoleUpdate(BaseModel):
    role: str

class TenantAssignmentUpdate(BaseModel):
    assigned_tenants: List[str]

# --- HELPER: GET CLEAN ASSIGNED IDS ---
def get_clean_assigned_ids(user_doc_dict: dict) -> List[str]:
    """Helper to safely extract and clean assigned tenant IDs."""
    raw = user_doc_dict.get("assigned_tenants", [])
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(item).strip() for item in raw if item and str(item).strip()]

# --- 1. AUDIT LOGS ---
@router.get("/audit-logs")
async def get_audit_logs(limit: int = 50, user: dict = Depends(get_current_user)):
    if not check_permission(user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        docs = db.collection("audit_logs")\
                 .order_by("timestamp", direction="DESCENDING")\
                 .limit(limit)\
                 .stream()
        
        logs = []
        for doc in docs:
            d = doc.to_dict()
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
    if not check_permission(user["role"], Action.VIEW_DASHBOARD):
        raise HTTPException(status_code=403, detail="Access denied")

    stats = {"projects": 0, "approvals": 0, "users": 0}
    try:
        # SUPER ADMIN: See All Active
        if user["role"] == UserRole.SUPER_ADMIN.value:
            all_tenants = list(db.collection("tenants").stream())
            stats["projects"] = len([t for t in all_tenants if not t.to_dict().get("is_archived", False)])
            all_users = list(db.collection("users").stream())
            stats["users"] = len([u for u in all_users if not u.to_dict().get("is_archived", False)])
        
        # OTHERS: Check ACTUAL Validity of Assignments
        else:
            user_doc = db.collection("users").document(user["uid"]).get()
            if user_doc.exists:
                clean_ids = get_clean_assigned_ids(user_doc.to_dict())
                valid_count = 0
                for tid in clean_ids:
                    t_doc = db.collection("tenants").document(tid).get()
                    if t_doc.exists and not t_doc.to_dict().get("is_archived", False):
                        valid_count += 1
                stats["projects"] = valid_count

        # APPROVALS
        if check_permission(user["role"], Action.APPROVE_TO_SUPER) or check_permission(user["role"], Action.PUBLISH_LIVE):
            target_status = "pending_admin_review" if user["role"] == UserRole.ADMIN.value else "pending_super_admin_review"
            query = db.collection("tenants").where("approval_status", "==", target_status).stream()
            stats["approvals"] = len(list(query))

        return stats
    except Exception as e:
        logger.error(f"Stats aggregation failed: {e}")
        return stats

# --- 3. ASSET UPLOAD ---
@router.post("/upload")
async def upload_asset(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.EDIT_DRAFT):
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
    if not check_permission(user["role"], Action.VIEW_DASHBOARD):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        user_doc = db.collection("users").document(user["uid"]).get()
        tenants_list = []

        # SUPER ADMIN: Fetch All Active
        if user["role"] == UserRole.SUPER_ADMIN.value:
            docs = db.collection("tenants").stream()
            for doc in docs:
                t = doc.to_dict()
                if not t.get("is_archived", False):
                    tenants_list.append(format_tenant_response(t))
        
        # OTHERS: Fetch Assigned (Robustly)
        else:
            if not user_doc.exists: return []
            clean_ids = get_clean_assigned_ids(user_doc.to_dict())
            
            for tid in clean_ids:
                doc = db.collection("tenants").document(tid).get()
                if doc.exists:
                    t = doc.to_dict()
                    if not t.get("is_archived", False):
                        tenants_list.append(format_tenant_response(t))

        return tenants_list
    except Exception as e:
        logger.error(f"Error getting user tenants: {e}")
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
    if not check_permission(current_user["role"], Action.VIEW_DASHBOARD):
         raise HTTPException(status_code=403, detail="Access denied")

    if current_user["role"] != UserRole.SUPER_ADMIN.value:
        user_doc = db.collection("users").document(current_user["uid"]).get()
        clean_ids = get_clean_assigned_ids(user_doc.to_dict()) if user_doc.exists else []
        if tenant_id not in clean_ids:
            raise HTTPException(status_code=403, detail="Access denied to this tenant")

    doc = db.collection("tenants").document(tenant_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    data = doc.to_dict()
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
    can_approve = check_permission(user["role"], Action.APPROVE_TO_SUPER) or \
                  check_permission(user["role"], Action.PUBLISH_LIVE)
    
    if not can_approve: return []

    target_status = None
    if user["role"] == UserRole.ADMIN.value: target_status = "pending_admin_review"
    elif user["role"] == UserRole.SUPER_ADMIN.value: target_status = "pending_super_admin_review"
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

# --- 5. WORKFLOW ACTIONS ---
@router.post("/submit-draft/{tenant_id}")
async def submit_draft(tenant_id: str, config: ChatbotConfig, user: dict = Depends(get_current_user)):
    if not check_permission(user["role"], Action.EDIT_DRAFT):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    if user["role"] != UserRole.SUPER_ADMIN.value:
        user_doc = db.collection("users").document(user["uid"]).get()
        clean_ids = get_clean_assigned_ids(user_doc.to_dict()) if user_doc.exists else []
        if tenant_id not in clean_ids:
            raise HTTPException(status_code=403, detail="Not assigned to this tenant")

    result = await WorkflowService.process_submission(tenant_id, config.dict(), user["role"], user["email"])
    await log_activity(user["email"], user["role"], "SUBMIT_DRAFT", tenant_id, "Submitted new configuration draft")
    await notify_admins(title="New Draft Submitted", message=f"{user['email']} submitted a draft for {tenant_id}.", link="#")
    return result

@router.post("/approve/{tenant_id}")
async def approve_config(tenant_id: str, user: dict = Depends(get_current_user)):
    can_approve_to_super = check_permission(user["role"], Action.APPROVE_TO_SUPER)
    can_publish = check_permission(user["role"], Action.PUBLISH_LIVE)

    if not (can_approve_to_super or can_publish):
         raise HTTPException(status_code=403, detail="Permission denied")
    
    tenant_doc = db.collection("tenants").document(tenant_id).get()
    tenant_data = tenant_doc.to_dict()
    submitter_email = tenant_data.get("last_modified_by")

    result = await WorkflowService.process_approval(tenant_id, user["role"], user["email"])
    
    action_type = "PUBLISH_LIVE" if can_publish else "APPROVE_TO_SUPER"
    log_msg = "Published configuration" if can_publish else "Approved to Super Admin"

    await log_activity(user["email"], user["role"], action_type, tenant_id, log_msg)
    
    if submitter_email:
        msg = f"Your changes for {tenant_data.get('client_name')} have been approved."
        if can_publish: msg += " The site is now live."
        await notify_user_by_email(email=submitter_email, title="Draft Approved", message=msg, link=f"/{tenant_data.get('slug')}")

    return result

# --- 6. TENANT MANAGEMENT ---
@router.get("/tenants")
async def list_all_tenants(show_archived: bool = Query(False), current_user: dict = Depends(get_current_user)):
    """Used for Super Admin view AND populating the Multi-Select UI."""
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
        if not tenant_id or not slug: raise HTTPException(status_code=400, detail="ID/Slug required")
        if db.collection("tenants").document(tenant_id).get().exists: raise HTTPException(status_code=400, detail="Tenant ID already exists")

        raw_banners = payload.get("banner_urls", [])
        banner_list = [url.strip() for url in raw_banners.split('\n') if url.strip()] if isinstance(raw_banners, str) else raw_banners

        initial_config = ChatbotConfig(
            bot_name=payload.get("bot_name", "My Bot"),
            primary_color=payload.get("primary_color", "#10B981"),
            welcome_message=payload.get("welcome_message", "Hello!"),
            custom_js=payload.get("custom_js", ""),
            background_color=payload.get("background_color", "#F9FAFB"),
            banner_urls=banner_list
        )

        new_tenant = Tenant(
            tenant_id=tenant_id, client_name=payload.get("client_name"), slug=slug,
            live_config=initial_config, approval_status=ApprovalStatus.PUBLISHED,
            last_modified_by=current_user["email"], last_modified_at=datetime.utcnow()
        )
        data = new_tenant.dict()
        data["is_archived"] = False
        db.collection("tenants").document(tenant_id).set(data)
        
        await log_activity(current_user["email"], current_user["role"], "CREATE_TENANT", tenant_id, f"Created {slug}")
        return {"message": "Tenant onboarded", "url": f"/{slug}"}
    except Exception as e:
        logger.error(f"Tenant creation failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to onboard.")

@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    db.collection("tenants").document(tenant_id).update({"is_archived": True})
    await log_activity(current_user["email"], current_user["role"], "ARCHIVE_TENANT", tenant_id, "Archived tenant")
    return {"message": "Tenant archived"}

@router.post("/tenants/{tenant_id}/restore")
async def restore_tenant(tenant_id: str, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    db.collection("tenants").document(tenant_id).update({"is_archived": False})
    await log_activity(current_user["email"], current_user["role"], "RESTORE_TENANT", tenant_id, "Restored tenant")
    return {"message": "Tenant restored"}

# --- 7. USER MANAGEMENT ---
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
            uid=user_record.uid, email=user_data.get("email"), role=user_data.get("role", "contributor"),
            assigned_tenants=clean_tenants
        )
        data = new_user.dict()
        data["is_archived"] = False
        db.collection("users").document(new_user.uid).set(data)
        
        await log_activity(current_user["email"], current_user["role"], "CREATE_USER", user_data.get("email"), f"Role: {new_user.role}")
        return {"message": "User created", "uid": new_user.uid}
    except Exception as e:
        logger.error(f"User onboarding error: {e}")
        raise HTTPException(status_code=400, detail="Failed to create user.")

@router.put("/users/{uid}/role")
async def update_user_role(uid: str, payload: RoleUpdate, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    valid_roles = [r.value for r in UserRole]
    if payload.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {valid_roles}")

    db.collection("users").document(uid).update({"role": payload.role})
    await log_activity(current_user["email"], current_user["role"], "UPDATE_ROLE", uid, f"Changed role to {payload.role}")
    return {"message": "Role updated"}

@router.put("/users/{uid}/tenants")
async def update_user_tenants(uid: str, payload: TenantAssignmentUpdate, current_user: dict = Depends(get_current_user)):
    """Updates assigned tenants, strictly validating existence."""
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # 1. Clean incoming list
    clean_tenants = [t.strip() for t in payload.assigned_tenants if t.strip()]
    
    # 2. VALIDATION: Check which ones actually exist
    valid_tenants = []
    if clean_tenants:
        # Optimization: Fetch all active tenants once (better than loop for small/medium datasets)
        all_tenant_docs = db.collection("tenants").stream()
        active_tenant_ids = {doc.id for doc in all_tenant_docs if not doc.to_dict().get("is_archived", False)}
        
        for tid in clean_tenants:
            if tid in active_tenant_ids:
                valid_tenants.append(tid)
            else:
                logger.warning(f"Ignored invalid/archived tenant ID '{tid}' during assignment for user {uid}")

    # 3. Update Database with ONLY valid IDs
    db.collection("users").document(uid).update({"assigned_tenants": valid_tenants})
    
    await log_activity(current_user["email"], current_user["role"], "UPDATE_ACCESS", uid, f"Assigned: {valid_tenants}")
    return {"message": "Tenant assignments updated", "valid_count": len(valid_tenants)}

@router.delete("/users/{uid}")
async def offboard_user(uid: str, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        firebase_auth.update_user(uid, disabled=True)
        db.collection("users").document(uid).update({"is_archived": True})
        await log_activity(current_user["email"], current_user["role"], "ARCHIVE_USER", uid, "Disabled user access")
        return {"message": "User archived"}
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to archive user.")

@router.post("/users/{uid}/restore")
async def restore_user(uid: str, current_user: dict = Depends(get_current_user)):
    if not check_permission(current_user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        firebase_auth.update_user(uid, disabled=False)
        db.collection("users").document(uid).update({"is_archived": False})
        await log_activity(current_user["email"], current_user["role"], "RESTORE_USER", uid, "Restored user access")
        return {"message": "User restored"}
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to restore user.")

# --- ACCESS REQUESTS (Super Admin) ---
@router.get("/access-requests")
async def list_access_requests(user: dict = Depends(get_current_user)):
    """Fetches all pending access requests. (Super Admin Only)"""
    if not check_permission(user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    try:
        # FIX: Removed .order_by("timestamp") to prevent Missing Index Error
        docs = db.collection("access_requests").where("status", "==", "pending").stream()
        
        requests = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            requests.append(d)
        
        # Sort in Python instead (Robust)
        requests.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return requests
    except Exception as e:
        logger.error(f"Error fetching requests: {e}")
        return []

@router.post("/access-requests/{request_id}/approve")
async def approve_access_request(request_id: str, user: dict = Depends(get_current_user)):
    """Approves request: Creates Firebase User + Firestore Profile."""
    if not check_permission(user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        # 1. Fetch Request Data
        req_ref = db.collection("access_requests").document(request_id)
        req_doc = req_ref.get()
        if not req_doc.exists:
            raise HTTPException(status_code=404, detail="Request not found")
        data = req_doc.to_dict()

        # 2. Generate Temp Password
        temp_password = "Welcome123!" 

        # 3. Create Firebase User
        try:
            user_record = firebase_auth.create_user(
                email=data["email"],
                password=temp_password,
                display_name=data["full_name"],
                email_verified=True
            )
        except Exception as e:
            # Handle case where user might have signed up externally in the meantime
            raise HTTPException(status_code=400, detail=f"Could not create user: {str(e)}")

        # 4. Create Firestore User Profile
        new_user = User(
            uid=user_record.uid,
            email=data["email"],
            role="contributor", # Default role
            assigned_tenants=[]
        )
        # Assuming you have the User model logic to convert to dict
        user_dict = new_user.dict()
        user_dict["is_archived"] = False
        db.collection("users").document(new_user.uid).set(user_dict)

        # 5. Mark Request as Approved
        req_ref.update({
            "status": "approved",
            "processed_by": user["email"],
            "processed_at": datetime.utcnow()
        })

        # 6. Log & Notify
        await log_activity(user["email"], user["role"], "APPROVE_ACCESS", data["email"], "Created user from request")
        
        # In real world: Send email to data["email"] with temp_password
        
        return {"message": f"User created successfully. Temp password: {temp_password}"}

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Approval failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/access-requests/{request_id}/reject")
async def reject_access_request(request_id: str, user: dict = Depends(get_current_user)):
    """Rejects request."""
    if not check_permission(user["role"], Action.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    try:
        db.collection("access_requests").document(request_id).update({
            "status": "rejected",
            "processed_by": user["email"],
            "processed_at": datetime.utcnow()
        })
        return {"message": "Request rejected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to reject")