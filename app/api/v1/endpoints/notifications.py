from fastapi import APIRouter, Depends, HTTPException
from app.api.v1.endpoints.auth import get_current_user
from app.db.firestore import db
from datetime import datetime

router = APIRouter()

@router.get("/")
async def get_my_notifications(user: dict = Depends(get_current_user)):
    """Fetches the current user's unread notifications."""
    try:
        # Fetch notifications (unread first, then by time)
        docs = db.collection("users").document(user["uid"])\
                 .collection("notifications")\
                 .order_by("timestamp", direction="DESCENDING")\
                 .limit(20)\
                 .stream()
        
        notifications = []
        for doc in docs:
            n = doc.to_dict()
            n["id"] = doc.id
            if isinstance(n.get("timestamp"), datetime):
                n["timestamp"] = n["timestamp"].isoformat()
            notifications.append(n)
        return notifications
    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return []

@router.post("/{notification_id}/read")
async def mark_notification_read(notification_id: str, user: dict = Depends(get_current_user)):
    """Marks a notification as read."""
    try:
        ref = db.collection("users").document(user["uid"])\
                .collection("notifications").document(notification_id)
        ref.update({"is_read": True})
        return {"status": "success"}
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to update")

@router.delete("/{notification_id}")
async def delete_notification(notification_id: str, user: dict = Depends(get_current_user)):
    """Deletes a notification."""
    try:
        db.collection("users").document(user["uid"])\
          .collection("notifications").document(notification_id).delete()
        return {"status": "deleted"}
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to delete")