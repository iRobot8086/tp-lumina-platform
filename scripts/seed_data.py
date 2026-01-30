import sys
import os
from datetime import datetime

# Add the parent directory to the path so we can import our models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.firestore import db
from app.models.tenant import Tenant, ChatbotConfig
from app.models.user import User, UserRole

def seed_platform():
    print("🌱 Starting Lumina Platform Seeding...")

    # 1. Create your First Super Admin User
    # Note: The 'uid' should match the actual UID from Firebase Auth 
    # after you sign up with Google for the first time.
    admin_uid = "y1gDBIhN5SZcjPKJzCVsqu0wslx2" 
    admin_email = "tp.crm.ema@gmail.com"

    user_ref = db.collection("users").document(admin_uid)
    user_data = User(
        uid=admin_uid,
        email=admin_email,
        role=UserRole.SUPER_ADMIN,
        assigned_tenants=["acme-corp-001"]
    )
    user_ref.set(user_data.dict())
    print(f"✅ Super Admin created: {admin_email}")

    # 2. Create your First Tenant (Client)
    tenant_id = "acme-corp-001"
    tenant_ref = db.collection("tenants").document(tenant_id)
    
    # Create an initial live config
    initial_config = ChatbotConfig(
        bot_name="Acme Helper",
        primary_color="#10B981", # Emerald Green
        welcome_message="Welcome to Acme Corp! How can we assist you today?",
        bot_id="demo-bot-123",
        logo_url="https://via.placeholder.com/150"
    )

    tenant_data = Tenant(
        tenant_id=tenant_id,
        client_name="Acme Corporation",
        slug="acme-inc",
        live_config=initial_config,
        approval_status="published",
        last_modified_by=admin_email,
        last_modified_at=datetime.utcnow().isoformat()
    )
    
    tenant_ref.set(tenant_data.dict())
    print(f"✅ Initial Tenant created: {tenant_data.client_name} (URL: /acme-inc)")

if __name__ == "__main__":
    seed_platform()