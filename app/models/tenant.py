from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ApprovalStatus:
    DRAFT = "draft"
    PENDING_ADMIN = "pending_admin_review"
    PENDING_SUPER_ADMIN = "pending_super_admin_review"
    PUBLISHED = "published"

class ChatbotConfig(BaseModel):
    bot_name: str
    primary_color: str = "#10B981"
    welcome_message: str = "Hello! How can I help you?"
    logo_url: Optional[str] = None
    
    # --- CHANGED: Raw JavaScript Storage ---
    # This stores the exact code snippet you paste in the dashboard
    custom_js: Optional[str] = "" 

class Tenant(BaseModel):
    tenant_id: str
    client_name: str
    slug: str
    live_config: Optional[ChatbotConfig] = None
    pending_config: Optional[ChatbotConfig] = None
    approval_status: str = ApprovalStatus.DRAFT
    last_modified_by: str
    last_modified_at: datetime = Field(default_factory=datetime.utcnow)