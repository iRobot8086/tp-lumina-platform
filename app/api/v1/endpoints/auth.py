from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth
from app.db.firestore import db

router = APIRouter()
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
        
        # Fetch Role from Firestore
        user_doc = db.collection("users").document(uid).get()
        role = "contributor"
        if user_doc.exists:
            role = user_doc.to_dict().get("role", "contributor")
        
        return {
            "uid": uid,
            "email": decoded_token.get('email'),
            "role": role
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.get("/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user