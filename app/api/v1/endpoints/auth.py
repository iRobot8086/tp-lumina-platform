import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header, UploadFile, File
from firebase_admin import auth
from pydantic import BaseModel
from typing import Optional
from app.db.firestore import db
from app.storage import upload_file_to_gcs

logger = logging.getLogger("lumina.auth")
router = APIRouter()

# --- MODELS ---
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
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token["uid"]
        email = decoded_token["email"]

        # Fetch Role from Firestore
        user_doc = db.collection("users").document(uid).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            role = user_data.get("role", "contributor")
        else:
            # Fallback/Auto-create logic if needed, or default to contributor
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

        auth.update_user(current_user["uid"], **update_args)
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
            
        auth.update_user(current_user["uid"], password=data.password)
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
        # Prefix with 'avatars/' to keep bucket organized
        filename = f"avatars/{current_user['uid']}-{file.filename}"
        public_url = upload_file_to_gcs(file.file, filename, file.content_type)
        
        # Auto-update profile with new URL
        auth.update_user(current_user["uid"], photo_url=public_url)
        
        return {"url": public_url}
    except Exception as e:
        logger.error(f"Avatar upload failed: {e}")
        raise HTTPException(status_code=500, detail="Upload failed")