from datetime import datetime
from typing import Dict, Any
from fastapi import HTTPException, status
from app.db.firestore import db
from app.models.tenant import ApprovalStatus
from app.core.rbac import check_permission, Action  # <--- Import the new RBAC system

class WorkflowService:
    @staticmethod
    def get_tenant_doc(tenant_id: str):
        doc_ref = db.collection("tenants").document(tenant_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return doc_ref, doc.to_dict()

    @staticmethod
    async def process_submission(tenant_id: str, config_data: Dict[str, Any], user_role: str, user_email: str):
        """
        Logic for 'Submit for Review' or 'Save Draft'.
        """
        # 1. SECURITY CHECK
        if not check_permission(user_role, Action.EDIT_DRAFT):
             raise HTTPException(status_code=403, detail="You do not have permission to edit drafts.")

        doc_ref, _ = WorkflowService.get_tenant_doc(tenant_id)
        
        # 2. State Transition Logic
        # If a Super Admin edits, it can go straight to pending_super_admin if they want, 
        # but usually, we keep it simple: any edit resets to a Draft or Pending state.
        
        if check_permission(user_role, Action.PUBLISH_LIVE):
             # Super admins submitting changes essentially "Self-Approve" to the final stage
             new_status = ApprovalStatus.PENDING_SUPER_ADMIN
        else:
             new_status = ApprovalStatus.PENDING_ADMIN

        update_data = {
            "pending_config": config_data,
            "approval_status": new_status,
            "last_modified_by": user_email,
            "updated_at": datetime.utcnow()
        }
        
        doc_ref.update(update_data)
        return {"status": "success", "current_state": new_status}

    @staticmethod
    async def process_approval(tenant_id: str, user_role: str, user_email: str):
        """
        Logic for moving the state forward (Approve).
        """
        doc_ref, tenant = WorkflowService.get_tenant_doc(tenant_id)
        current_status = tenant.get("approval_status")
        pending_config = tenant.get("pending_config")

        if not pending_config:
            raise HTTPException(status_code=400, detail="No pending changes to approve")

        # --- SCENARIO 1: PUBLISHING TO LIVE (Super Admin) ---
        if check_permission(user_role, Action.PUBLISH_LIVE):
            # Super Admin can force publish from ANY state
            doc_ref.update({
                "live_config": pending_config,
                "pending_config": None, 
                "approval_status": ApprovalStatus.PUBLISHED,
                "last_modified_by": user_email,
                "updated_at": datetime.utcnow()
            })
            return {"message": "Changes published LIVE."}

        # --- SCENARIO 2: APPROVING TO NEXT STAGE (Admin) ---
        elif check_permission(user_role, Action.APPROVE_TO_SUPER):
            if current_status != ApprovalStatus.PENDING_ADMIN:
                 raise HTTPException(status_code=400, detail="Item is not waiting for Admin review.")
            
            doc_ref.update({
                "approval_status": ApprovalStatus.PENDING_SUPER_ADMIN,
                "last_modified_by": user_email
            })
            return {"message": "Approved. Sent to Super Admin."}
        else:
            raise HTTPException(status_code=403, detail="You do not have approval privileges.")