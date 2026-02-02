import logging
from typing import Optional
from datetime import datetime
from firebase_admin import auth as firebase_auth
from app.db.firestore import db
from pydantic import BaseModel, EmailStr
from app.storage import upload_file_to_gcs
from fastapi import APIRouter, Depends, HTTPException, status, Header, UploadFile, File

# Import the notification service
from app.services.notifications import notify_admins

logger = logging.getLogger("lumina.auth")

router = APIRouter()

# --- MODELS ---

class AccessRequest(BaseModel):
    full_name: str
    email: EmailStr
    company: Optional[str] = None
    reason: str

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    photo_url: Optional[str] = None

class PasswordUpdate(BaseModel):
    password: str

# --- DEPENDENCY ---
async def get_current_user(authorization: str = Header(...)):
    """
    Verifies the Firebase Bearer Token and retrieves user role from Firestore.
    """
    try:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid header format")
        
        token = authorization.split("Bearer ")[1]
        decoded_token = firebase_auth.verify_id_token(token)
        uid = decoded_token["uid"]
        email = decoded_token["email"]

        # Fetch Role from Firestore
        user_doc = db.collection("users").document(uid).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            role = user_data.get("role", "contributor")
        else:
            role = "contributor"

        return {
            "uid": uid, 
            "email": email, 
            "role": role, 
            "name": decoded_token.get("name"),
            "picture": decoded_token.get("picture")
        }
    except Exception as e:
        logger.error(f"Auth failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

# --- ROUTES ---

@router.get("/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """Returns the current user's profile information."""
    return current_user

@router.put("/me")
async def update_profile(data: UserUpdate, current_user: dict = Depends(get_current_user)):
    """Updates the user's display name and photo URL in Firebase Auth."""
    try:
        update_args = {}
        if data.display_name: update_args["display_name"] = data.display_name
        if data.photo_url: update_args["photo_url"] = data.photo_url
        
        if not update_args:
            return {"message": "No changes requested"}

        firebase_auth.update_user(current_user["uid"], **update_args)
        return {"message": "Profile updated successfully"}
    except Exception as e:
        logger.error(f"Profile update failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/me/password")
async def change_password(data: PasswordUpdate, current_user: dict = Depends(get_current_user)):
    """Updates the user's password."""
    try:
        if len(data.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
            
        firebase_auth.update_user(current_user["uid"], password=data.password)
        return {"message": "Password changed successfully"}
    except Exception as e:
        logger.error(f"Password change failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/me/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Allows any logged-in user to upload an avatar."""
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(status_code=400, detail="Only images allowed")

    try:
        filename = f"avatars/{current_user['uid']}-{file.filename}"
        public_url = upload_file_to_gcs(file.file, filename, file.content_type)
        
        firebase_auth.update_user(current_user["uid"], photo_url=public_url)
        return {"url": public_url}
    except Exception as e:
        logger.error(f"Avatar upload failed: {e}")
        raise HTTPException(status_code=500, detail="Upload failed")

@router.post("/request-access")
async def request_access(request_data: AccessRequest):
    """
    Public endpoint for users to request access.
    """
    # 1. Check duplication in Auth
    try:
        firebase_auth.get_user_by_email(request_data.email)
        raise HTTPException(status_code=400, detail="User already registered. Please log in.")
    except firebase_auth.UserNotFoundError:
        pass 

    # 2. Check pending duplicates in DB
    existing_req = db.collection("access_requests").where("email", "==", request_data.email).where("status", "==", "pending").get()
    if existing_req:
        raise HTTPException(status_code=400, detail="A pending request for this email already exists.")

    try:
        # 3. Save Request
        doc_ref = db.collection("access_requests").document()
        data = request_data.dict()
        data.update({
            "status": "pending",
            "timestamp": datetime.utcnow().isoformat() # ISO format for robust sorting
        })
        doc_ref.set(data)

        # 4. Notify Admins (Triggers Bell Icon)
        await notify_admins(
            title="New Access Request", 
            message=f"{request_data.full_name} requests access.", 
            link="requests"
        )
        
        return {"message": "Request submitted successfully. Admins have been notified."}
    except Exception as e:
        logger.error(f"Access request error: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit request.")