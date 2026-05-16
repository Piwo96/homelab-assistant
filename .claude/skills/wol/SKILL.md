---
name: wol
description: Gaming-PC per Wake-on-LAN aufwecken und LM Studio Verfügbarkeit prüfen
version: 1.0.0
author: Philipp Rollmann
tags:
  - homelab
  - wol
  - wake-on-lan
  - gaming-pc
  - lm-studio
requires:
  - python3
triggers:
  - /wol
  - /wake
intent_hints:
  - "PC aufwecken, Gaming-PC starten"
  - "Wake-on-LAN senden, Magic Packet"
  - "Ist der PC an, läuft LM Studio"
  - "Gaming-PC wecken, Computer hochfahren"
  - "LM Studio Status, Modelle verfügbar"
---

# Wake-on-LAN (Gaming PC)

Wake the Gaming PC via Magic Packet and check LM Studio availability.

## Goal

Wake the Gaming PC remotely via Wake-on-LAN and monitor LM Studio readiness, so local AI models can be used on demand.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `GAMING_PC_MAC` | `.env` | Yes | MAC-Adresse des Gaming-PC (Format: `AA:BB:CC:DD:EE:FF`) |
| `GAMING_PC_IP` | `.env` | Yes | IP-Adresse des Gaming-PC |
| `LM_STUDIO_URL` | `.env` | No | LM Studio API URL (default: `http://<GAMING_PC_IP>:1234`) |
| `WOL_TIMEOUT` | `.env` | No | Timeout in Sekunden bis PC bereit (default: 120) |

## Tools

| Tool | Purpose | Usage |
|------|---------|-------|
| `scripts/wol_api.py` | CLI for Wake-on-LAN and LM Studio checks | Command-line interface |

### CLI Usage
```bash
python .claude/skills/wol/scripts/wol_api.py <command> [arguments]
```

## Outputs

- Status messages (Magic Packet gesendet, PC erreichbar, etc.)
- LM Studio model info (JSON)
- Error messages to stderr with exit code 1

## Quick Start

1. Configure `.env`:
   ```bash
   GAMING_PC_MAC=A8:5E:45:E4:CF:98
   GAMING_PC_IP=192.168.178.50
   ```

2. Wake the PC:
   ```bash
   python .claude/skills/wol/scripts/wol_api.py wake
   ```

3. Check LM Studio:
   ```bash
   python .claude/skills/wol/scripts/wol_api.py status
   ```

## Common Commands

```bash
# Wake-on-LAN
wol_api.py wake                  # Magic Packet senden
wol_api.py wake --wait           # Senden und warten bis LM Studio erreichbar

# Status
wol_api.py status                # Prüfen ob PC/LM Studio erreichbar
wol_api.py models                # Geladene LM Studio Modelle auflisten

# Ping
wol_api.py ping                  # Einfacher Ping zum Gaming-PC
```

## Workflows

### Gaming-PC aufwecken und auf LM Studio warten
1. Magic Packet senden: `wol_api.py wake`
2. Warten bis LM Studio bereit: `wol_api.py wake --wait`
3. Modelle prüfen: `wol_api.py models`

### LM Studio Verfügbarkeit prüfen
1. Status abfragen: `wol_api.py status`
2. Falls nicht erreichbar: `wol_api.py wake --wait`

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| MAC nicht konfiguriert | Script bricht mit Fehler ab | `GAMING_PC_MAC` in `.env` setzen |
| PC bereits an | Magic Packet wird ignoriert, kein Schaden | `status` vorher prüfen |
| PC im Tiefschlaf (S4/S5) | WoL funktioniert nur wenn im BIOS aktiviert | BIOS-Einstellung prüfen |
| LM Studio nicht gestartet | PC erreichbar aber API antwortet nicht | LM Studio manuell starten oder Autostart einrichten |
| Timeout beim Warten | PC braucht länger als `WOL_TIMEOUT` | Timeout erhöhen oder PC manuell prüfen |
| Netzwerk-Broadcast blockiert | Magic Packet erreicht PC nicht | Subnet-Broadcast statt 255.255.255.255 nutzen |
| `ping -W` ist plattformabhängig | macOS BSD `ping` interpretiert `-W` als **Millisekunden**, Linux als **Sekunden** — `-W 2` auf macOS = 2 ms → Timeout sofort | `scripts/wol_api.py` branched auf `sys.platform == "darwin"` → `"2000"` ms, sonst `"2"` s |

## Related Skills

- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
- [/proxmox](../proxmox/SKILL.md) - VM/Container Management (Gaming-PC könnte eine VM sein)
