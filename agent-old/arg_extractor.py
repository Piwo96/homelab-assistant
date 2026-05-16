"""Deterministic argument extraction from natural language messages.

Extracts common argument patterns (camera names, time ranges, IDs)
using regex so the LLM can be skipped for high-confidence semantic matches.
"""

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# === Camera / location names (Protect skill) ===
CAMERA_NAMES = {
    "einfahrt": "Einfahrt",
    "garten": "Garten",
    "grünstreifen": "Grünstreifen",
    "gruenstreifen": "Grünstreifen",
    "wohnzimmer": "Wohnzimmer",
    "küche": "Küche",
    "kueche": "Küche",
    "flur": "Flur",
    "haustür": "Haustür",
    "haustur": "Haustür",
    "tür": "Haustür",
    "tur": "Haustür",
    "garage": "Garage",
    "keller": "Keller",
    "terrasse": "Terrasse",
    "balkon": "Balkon",
}

# === Room names (Home Assistant) ===
ROOM_NAMES = {
    "wohnzimmer": "wohnzimmer",
    "schlafzimmer": "schlafzimmer",
    "küche": "kueche",
    "kueche": "kueche",
    "bad": "bad",
    "badezimmer": "bad",
    "flur": "flur",
    "kinderzimmer": "kinderzimmer",
    "arbeitszimmer": "arbeitszimmer",
    "büro": "buero",
    "buero": "buero",
    "keller": "keller",
    "garage": "garage",
    "terrasse": "terrasse",
    "balkon": "balkon",
    "garten": "garten",
}

# === Time range patterns ===
_TIME_PATTERNS = [
    # "letzte 24h", "letzten 2 Stunden", "letzte 30 Minuten"
    (re.compile(r"letzt(?:e|en|er)\s+(\d+)\s*(?:h|stunden?)", re.I), "hours"),
    (re.compile(r"letzt(?:e|en|er)\s+(\d+)\s*(?:min(?:uten)?)", re.I), "minutes"),
    (re.compile(r"letzt(?:e|en|er)\s+(\d+)\s*(?:tage?|d)", re.I), "days"),
    # "heute", "gestern"
    (re.compile(r"\bheute\b", re.I), "today"),
    (re.compile(r"\bgestern\b", re.I), "yesterday"),
    # "letzte Stunde"
    (re.compile(r"letzt(?:e|en|er)\s+Stunde", re.I), "1hour"),
]

# === VM/Container ID patterns ===
_VMID_PATTERN = re.compile(r"\b(?:vm|container|lxc|ct)\s*(\d{3,4})\b", re.I)
_BARE_ID_PATTERN = re.compile(r"\b(\d{3,4})\b")


def extract_args(
    message: str,
    skill: str,
    action: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract arguments deterministically from the user message.

    Called when the semantic router has high confidence, to avoid
    needing the LLM for argument parsing.

    Args:
        message: User's natural language message
        skill: The matched skill name
        action: The matched action name (if any)

    Returns:
        Dict of extracted arguments (may be empty)
    """
    args: Dict[str, Any] = {}
    msg_lower = message.lower()

    if skill == "unifi-protect":
        args.update(_extract_protect_args(msg_lower, action))
    elif skill == "homeassistant":
        args.update(_extract_ha_args(msg_lower, action))
    elif skill == "proxmox":
        args.update(_extract_proxmox_args(msg_lower, message, action))
    elif skill == "pihole":
        args.update(_extract_pihole_args(msg_lower, action))

    # Time range extraction (cross-skill)
    time_arg = _extract_time_range(msg_lower)
    if time_arg and "last" not in args:
        args["last"] = time_arg

    if args:
        logger.info(f"Extracted args for {skill}/{action}: {args}")

    return args


def _extract_protect_args(
    msg: str, action: Optional[str]
) -> Dict[str, Any]:
    """Extract UniFi Protect specific arguments."""
    args: Dict[str, Any] = {}

    # Camera name
    for key, canonical in CAMERA_NAMES.items():
        if key in msg:
            args["camera"] = canonical
            break

    # Detection type
    if action == "detections":
        if any(w in msg for w in ["kennzeichen", "nummernschild", "plate"]):
            args["type"] = "plate"
        elif any(w in msg for w in ["gesicht", "face"]):
            args["type"] = "face"
        elif any(w in msg for w in ["auto", "fahrzeug", "vehicle"]):
            args["type"] = "vehicle"
        elif any(w in msg for w in ["person", "mensch", "jemand"]):
            args["type"] = "person"

    return args


def _extract_ha_args(
    msg: str, action: Optional[str]
) -> Dict[str, Any]:
    """Extract Home Assistant specific arguments."""
    args: Dict[str, Any] = {}

    # Room/entity matching
    for key, room_id in ROOM_NAMES.items():
        if key in msg:
            if any(w in msg for w in ["licht", "lampe", "beleuchtung"]):
                args["entity_id"] = f"light.{room_id}"
            elif any(w in msg for w in ["temperatur", "temp"]):
                args["entity_id"] = f"sensor.{room_id}_temperature"
            elif any(w in msg for w in ["steckdose", "schalter"]):
                args["entity_id"] = f"switch.{room_id}"
            break

    return args


def _extract_proxmox_args(
    msg_lower: str, msg_original: str, action: Optional[str]
) -> Dict[str, Any]:
    """Extract Proxmox specific arguments."""
    args: Dict[str, Any] = {}

    # VM/Container ID
    m = _VMID_PATTERN.search(msg_original)
    if m:
        args["vmid"] = int(m.group(1))
    elif action in ("start", "stop", "shutdown", "reboot", "status"):
        # Try bare number for actions that need a VMID
        m = _BARE_ID_PATTERN.search(msg_original)
        if m:
            args["vmid"] = int(m.group(1))

    return args


def _extract_pihole_args(
    msg: str, action: Optional[str]
) -> Dict[str, Any]:
    """Extract Pi-hole specific arguments."""
    args: Dict[str, Any] = {}

    # Domain extraction for block/allow
    domain_match = re.search(
        r"(?:domain|seite|website)?\s*([\w.-]+\.(?:com|de|org|net|io|dev|co|me))",
        msg,
    )
    if domain_match:
        args["domain"] = domain_match.group(1)

    return args


def _extract_time_range(msg: str) -> Optional[str]:
    """Extract time range from message.

    Returns a string like "24h", "2d", "heute", "gestern".
    """
    for pattern, unit in _TIME_PATTERNS:
        m = pattern.search(msg)
        if m:
            if unit == "hours":
                return f"{m.group(1)}h"
            elif unit == "minutes":
                return f"{m.group(1)}m"
            elif unit == "days":
                return f"{m.group(1)}d"
            elif unit == "today":
                return "24h"
            elif unit == "yesterday":
                return "48h"
            elif unit == "1hour":
                return "1h"
    return None
