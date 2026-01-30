from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ApprovalStatus:
    """Helper class to keep status strings consistent."""
    DRAFT = "draft"
    PENDING_ADMIN = "pending_admin_review"
    PENDING_SUPER_ADMIN = "pending_super_admin_review"
    PUBLISHED = "published"

class ChatbotConfig(BaseModel):
    bot_name: str
    primary_color: str = "#10B981"
    welcome_message: str = "Hello! How can I help you?"
    logo_url: Optional[str] = None
    ema_tenant_id: Optional[str] = ""    
    ema_project_id: Optional[str] = ""   
    ema_persona_id: Optional[str] = ""   

class Tenant(BaseModel):
    tenant_id: str
    client_name: str
    slug: str
    live_config: Optional[ChatbotConfig] = None
    pending_config: Optional[ChatbotConfig] = None
    approval_status: str = ApprovalStatus.DRAFT
    last_modified_by: str
    last_modified_at: datetime = Field(default_factory=datetime.utcnow)