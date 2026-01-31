from enum import Enum
from typing import List, Dict

# --- 1. Define the Roles ---
class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"   # Can publish to live, manage users
    ADMIN = "admin"               # Can approve drafts -> super_admin
    CONTRIBUTOR = "contributor"   # Can edit drafts -> admin
    USER = "user"             # Read-only access
    SUPER_USER = "super_user"

# --- 2. Define the Actions (Privileges) ---
class Action(str, Enum):
    VIEW_DASHBOARD = "view_dashboard"
    EDIT_DRAFT = "edit_draft"
    SUBMIT_REVIEW = "submit_review"
    APPROVE_TO_SUPER = "approve_to_super"
    PUBLISH_LIVE = "publish_live"
    REJECT_CHANGES = "reject_changes"
    MANAGE_USERS = "manage_users"

# --- 3. The "Constitution" (Role -> Allowed Actions) ---
RBAC_POLICY: Dict[UserRole, List[Action]] = {
    
    # Super Admin: Can do absolutely everything
    UserRole.SUPER_ADMIN: [
        Action.VIEW_DASHBOARD,
        Action.EDIT_DRAFT,
        Action.SUBMIT_REVIEW,
        Action.APPROVE_TO_SUPER,
        Action.PUBLISH_LIVE,
        Action.REJECT_CHANGES,
        Action.MANAGE_USERS
    ],

    # Admin: Can edit and approve for the Contributor, but cannot Publish
    UserRole.ADMIN: [
        Action.VIEW_DASHBOARD,
        Action.EDIT_DRAFT,
        Action.SUBMIT_REVIEW,
        Action.APPROVE_TO_SUPER,
        Action.REJECT_CHANGES
    ],

    # Contributor: Can only edit and submit for review
    UserRole.CONTRIBUTOR: [
        Action.VIEW_DASHBOARD,
        Action.EDIT_DRAFT,
        Action.SUBMIT_REVIEW
    ],

    # USER: Read-only
    UserRole.USER: [
        Action.VIEW_DASHBOARD
    ],
     # SUPER USER: Read, and Submit Requests
    UserRole.SUPER_USER: [
        Action.VIEW_DASHBOARD,
        Action.EDIT_DRAFT
    ]
}

def check_permission(role: str, action: Action) -> bool:
    """Helper function to check if a role is allowed to perform an action."""
    # Default to empty list if role is unknown/invalid
    allowed_actions = RBAC_POLICY.get(role, [])
    return action in allowed_actions