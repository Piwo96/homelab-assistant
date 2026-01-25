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
