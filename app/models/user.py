from pydantic import BaseModel, EmailStr
from enum import Enum
from typing import List, Optional

class UserRole(str, Enum):
    """The 5 Tiers of RBAC for the Lumina Platform."""
    SUPER_ADMIN = "super_admin"   # Can publish to live, manage all tenants
    ADMIN = "admin"               # Can approve Super User changes
    SUPER_USER = "super_user"     # Client-side: Can edit and submit for review
    USER = "user"                 # Client-side: View only, no edit access
    CONTRIBUTOR = "contributor"   # Internal: Can create drafts but not approve

class User(BaseModel):
    uid: str                      # From Firebase Auth
    email: EmailStr
    role: UserRole
    assigned_tenants: List[str] = []  # List of tenant_ids this user can access
    is_active: bool = True

class TokenData(BaseModel):
    """Used for parsing the decoded JWT token."""
    uid: Optional[str] = None
    role: Optional[str] = None