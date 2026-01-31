from datetime import datetime
from app.db.firestore import db
import logging

logger = logging.getLogger("lumina.notifications")

async def send_in_app_notification(target_uid: str, title: str, message: str, link: str = "#", type: str = "info"):
    """
    Creates an in-app notification in Firestore for a specific user.
    """
    try:
        notification = {
            "title": title,
            "message": message,
            "link": link,
            "type": type, # info, success, warning, error
            "is_read": False,
            "timestamp": datetime.utcnow()
        }
        # Add to user's sub-collection
        db.collection("users").document(target_uid).collection("notifications").add(notification)
    except Exception as e:
        logger.error(f"Failed to send in-app notification to {target_uid}: {e}")

async def notify_admins(title: str, message: str, link: str):
    """
    Sends a notification to ALL Super Admins.
    """
    try:
        # Find all super admins
        admins = db.collection("users").where("role", "==", "super_admin").stream()
        for admin in admins:
            await send_in_app_notification(admin.id, title, message, link, "warning")
    except Exception as e:
        logger.error(f"Failed to notify admins: {e}")

async def notify_user_by_email(email: str, title: str, message: str, link: str):
    """
    Finds a user by email and sends them a notification.
    """
    try:
        users = db.collection("users").where("email", "==", email).limit(1).stream()
        for user in users:
            await send_in_app_notification(user.id, title, message, link, "success")
    except Exception as e:
        logger.error(f"Failed to notify user {email}: {e}")