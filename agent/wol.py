"""Wake-on-LAN functionality for Gaming PC with LM Studio."""

import asyncio
import httpx
from wakeonlan import send_magic_packet

from .config import Settings


async def wake_gaming_pc(settings: Settings) -> bool:
    """Send Wake-on-LAN magic packet to Gaming PC.

    Args:
        settings: Application settings containing MAC address

    Returns:
        True if packet was sent (doesn't guarantee PC woke up)
    """
    if not settings.gaming_pc_mac:
        return False

    # wakeonlan expects MAC without colons or with colons
    mac = settings.gaming_pc_mac.replace(":", "")
    send_magic_packet(mac)
    return True


async def is_lm_studio_available(settings: Settings, timeout: float = 5.0) -> bool:
    """Check if LM Studio API is responding.

    Args:
        settings: Application settings containing LM Studio URL
        timeout: Request timeout in seconds

    Returns:
        True if LM Studio is available and responding
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{settings.lm_studio_url}/v1/models")
            return response.status_code == 200
    except (httpx.RequestError, httpx.TimeoutException):
        return False


async def get_loaded_model(settings: Settings, timeout: float = 5.0) -> str | None:
    """Get the first loaded chat model from LM Studio.

    Args:
        settings: Application settings containing LM Studio URL
        timeout: Request timeout in seconds

    Returns:
        Model ID string or None if no models loaded
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{settings.lm_studio_url}/v1/models")
            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                # Filter out embedding models (they contain "embed" in name)
                chat_models = [m["id"] for m in models if "embed" not in m["id"].lower()]
                return chat_models[0] if chat_models else None
    except (httpx.RequestError, httpx.TimeoutException):
        return None
    return None


async def ensure_lm_studio_available(
    settings: Settings, max_wait: int | None = None, poll_interval: int = 5
) -> bool:
    """Ensure LM Studio is available, waking Gaming PC if needed.

    This function:
    1. Checks if LM Studio is already available
    2. If not, sends a WoL packet to wake the Gaming PC
    3. Polls until LM Studio becomes available or timeout

    Args:
        settings: Application settings
        max_wait: Maximum seconds to wait. If None, uses settings.wol_timeout (default: 120s)
        poll_interval: Seconds between availability checks

    Returns:
        True if LM Studio is available, False if timeout reached
    """
    # Check if already available
    if await is_lm_studio_available(settings):
        return True

    # Use configured timeout if not specified
    timeout: int = max_wait if max_wait is not None else settings.wol_timeout

    # Send Wake-on-LAN packet
    if not await wake_gaming_pc(settings):
        # No MAC configured, can't wake PC
        return False

    # Poll for availability - check immediately, then sleep between checks
    elapsed = 0
    while elapsed < timeout:
        if await is_lm_studio_available(settings):
            return True

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    return False
