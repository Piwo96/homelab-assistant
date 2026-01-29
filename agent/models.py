"""Data models for the Telegram agent."""

from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class IntentResult(BaseModel):
    """Result of intent classification from LM Studio."""

    skill: str  # homeassistant, proxmox, unifi-network, etc. or "unknown"/"error"
    action: str = ""  # turn_on, start, status, etc.
    target: Optional[str] = None  # entity_id, vmid, camera name, etc.
    args: Dict[str, Any] = {}  # Additional arguments
    confidence: float = 0.0  # 0.0 to 1.0
    description: Optional[str] = None  # For unknown intents
    raw_response: Optional[str] = None  # Raw LLM response for debugging


class ApprovalStatus(str, Enum):
    """Status of a skill creation approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    """A pending skill creation approval request."""

    request_id: str
    user_request: str  # Original user message
    requester_name: str
    requester_id: int
    chat_id: int  # Chat to respond to
    created_at: datetime
    message_id: Optional[int] = None  # Telegram message ID for updating
    status: ApprovalStatus = ApprovalStatus.PENDING
    skill_to_extend: Optional[str] = None  # Name of skill to extend (None for new)


class TelegramUser(BaseModel):
    """Telegram user information."""

    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Get display name for the user."""
        if self.username:
            return f"@{self.username}"
        full_name = self.first_name
        if self.last_name:
            full_name += f" {self.last_name}"
        return full_name


class SkillExecutionResult(BaseModel):
    """Result of executing a skill."""

    success: bool
    output: str
    error: Optional[str] = None
    skill: str
    action: str


class ErrorFixRequest(BaseModel):
    """A pending error fix approval request."""

    request_id: str
    error_type: str  # e.g., "ScriptError", "TimeoutExpired"
    error_message: str  # The actual error message
    skill: str  # Which skill failed
    action: str  # Which action failed
    context: str  # Additional context (command, etc.)
    created_at: datetime
    message_id: Optional[int] = None  # Telegram message ID for updating
    status: ApprovalStatus = ApprovalStatus.PENDING


# Infrastructure skills that require admin for write operations
# Key: skill name, Value: set of read-only actions (everything else requires admin)
INFRASTRUCTURE_SKILLS: Dict[str, set] = {
    "proxmox": {
        "nodes", "node-status", "overview", "vms", "containers",
        "status", "storage", "snapshots", "lxc-config",
    },
    "pihole": {
        "summary", "status", "top-domains", "top-ads", "top-clients",
        "query-types", "recent-queries", "recent-blocked", "query",
    },
    "unifi-network": {
        "health", "devices", "device-status", "clients", "client-info",
        "networks", "port-forwards", "firewall-rules",
        # Integration API v1 (read-only)
        "info", "sites", "device-detail", "device-stats",
        "pending-devices", "client-detail", "wifis",
        "network-detail", "network-references", "wifi-detail",
    },
    "unifi-protect": {
        "cameras", "camera", "snapshot", "events", "detections",
        "lights", "light-on", "light-off", "nvr", "sensors",
        # Integration API v1
        "detect", "meta", "chimes", "chime",
        "ptz-goto", "ptz-patrol-start", "ptz-patrol-stop",
        "rtsps-stream", "rtsps-streams", "rtsps-stream-delete",
        "viewers", "liveviews", "alarm",
    },
}


def is_admin_required(skill: str, action: str) -> bool:
    """Check if an action requires admin privileges.

    Args:
        skill: The skill name (e.g., "proxmox", "pihole")
        action: The action to perform (e.g., "start", "status")

    Returns:
        True if admin is required, False if action is allowed for all users
    """
    if skill not in INFRASTRUCTURE_SKILLS:
        # Non-infrastructure skills don't require admin
        return False

    # Normalize action name (underscores to dashes)
    action_normalized = action.replace("_", "-")

    # If action is in the read-only set, no admin required
    read_only_actions = INFRASTRUCTURE_SKILLS[skill]
    return action_normalized not in read_only_actions
