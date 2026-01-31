from datetime import datetime
from app.db.firestore import db
import logging

logger = logging.getLogger("lumina.audit")

async def log_activity(actor_email: str, actor_role: str, action: str, target_id: str, details: str = ""):
    """
    Logs an event to the 'audit_logs' collection in Firestore.
    """
    try:
        entry = {
            "timestamp": datetime.utcnow(),
            "actor_email": actor_email,
            "actor_role": actor_role,
            "action": action,
            "target_id": target_id,
            "details": details
        }
        db.collection("audit_logs").add(entry)
    except Exception as e:

        logger.error(f"Failed to write audit log: {e}")