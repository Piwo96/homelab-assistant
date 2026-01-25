"""Configuration management using Pydantic Settings."""

from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List, Union
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Telegram Bot
    telegram_bot_token: str
    telegram_webhook_secret: str
    # Use str type to prevent automatic JSON parsing, validator converts to list
    telegram_allowed_users: Union[str, List[int]] = []
    admin_telegram_id: int

    # LM Studio (local LLM) - must be set in .env
    lm_studio_url: str
    lm_studio_model: str = ""  # Model ID (optional - LM Studio uses loaded model if empty)
    lm_studio_timeout: int = 300  # 5 Min - großzügig für Thinking-Modelle

    # Gaming PC (for Wake-on-LAN) - must be set in .env
    gaming_pc_ip: str
    gaming_pc_mac: str

    # Claude API (for skill creation)
    anthropic_api_key: str = ""

    # Approval settings
    approval_timeout_minutes: int = 5

    # Wake-on-LAN timeout (seconds) - time to wait for PC to boot
    wol_timeout: int = 120  # 2 Min - covers cold boot, sleep, and hibernate

    @field_validator("wol_timeout")
    @classmethod
    def validate_wol_timeout(cls, v):
        """Validate Wake-on-LAN timeout is positive."""
        if v <= 0:
            raise ValueError("wol_timeout must be positive")
        return v

    # Chat history
    chat_history_limit: int = 50

    # Project paths
    project_root: Path = Path(__file__).parent.parent

    @field_validator("telegram_allowed_users", mode="before")
    @classmethod
    def parse_allowed_users(cls, v):
        """Parse comma-separated user IDs into a list of integers."""
        if isinstance(v, int):
            # Single user ID as integer
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            try:
                return [int(uid.strip()) for uid in v.split(",") if uid.strip()]
            except ValueError as e:
                raise ValueError(f"Invalid telegram_allowed_users format: {e}. Expected comma-separated integers.")
        if isinstance(v, list):
            return v
        return v

    @field_validator("gaming_pc_mac", mode="before")
    @classmethod
    def normalize_mac(cls, v):
        """Normalize MAC address format."""
        if isinstance(v, str) and v:
            # Remove common separators and convert to standard format
            clean = v.replace("-", "").replace(":", "").replace(".", "").upper()
            if len(clean) == 12:
                return ":".join(clean[i : i + 2] for i in range(0, 12, 2))
        return v

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Singleton instance
_settings = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
