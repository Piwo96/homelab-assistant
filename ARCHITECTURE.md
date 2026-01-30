# Homelab Assistant - Architecture

> Telegram-basierter Agent zur Steuerung von Homelab-Infrastruktur mit lokalem LLM und Self-Annealing.

## Überblick

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Telegram User                                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI (main.py)                                                   │
│  ├─ Webhook Authentication                                           │
│  ├─ Request Deduplication                                            │
│  └─ Background Tasks (Git Pull, Metadata Generation)                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Semantic Router (semantic_router.py) - FAST PRE-FILTER             │
│  ├─ EmbeddingGemma-300M (LM Studio /v1/embeddings)                  │
│  ├─ Cosine Similarity Matching (~50ms)                              │
│  ├─ Cached Embeddings (data/embedding_cache.json)                   │
│  └─ Deterministic Arg Extraction (arg_extractor.py)                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
   HIGH (≥0.75)          MEDIUM (0.40-0.75)      LOW (<0.40)
   Skip LLM              Narrow to top 2         Smalltalk
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Intent Classification (intent_classifier.py) - LLM FALLBACK        │
│  ├─ LM Studio (lokales LLM)                                          │
│  ├─ Dynamic Tool Definitions (optional: filtered by semantic router)│
│  └─ Conversation History Context                                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  Skill Executor  │ │  Conversational  │ │  Skill Creator   │
│  (subprocess)    │ │  (follow-ups)    │ │  (Claude API)    │
└────────┬─────────┘ └──────────────────┘ └────────┬─────────┘
         │                                          │
         ▼                                          ▼
┌──────────────────┐                      ┌──────────────────┐
│  Skill Scripts   │                      │  Git Branch +    │
│  (*_api.py)      │                      │  Pull Request    │
└──────────────────┘                      └──────────────────┘
```

## 3-Layer Architektur

Das System folgt einer strikten Schichtentrennung:

| Layer | Beschreibung | Komponenten |
|-------|--------------|-------------|
| **Directives** | Was zu tun ist (Markdown SOPs) | `SKILL.md`, `keywords.json`, `examples.json` |
| **Orchestration** | Entscheidungsfindung (LLM) | `intent_classifier.py`, `skill_executor.py` |
| **Execution** | Deterministische Ausführung | `*_api.py` Scripts |

**Warum?** Fehler akkumulieren: 90% Genauigkeit pro Schritt = 59% über 5 Schritte. Durch Verlagerung der Komplexität in deterministische Skills bleibt die Fehlerquote niedrig.

## Projektstruktur

```
homelab-assistant/
├── agent/                              # Core Agent
│   ├── main.py                         # FastAPI + Webhook Handler
│   ├── semantic_router.py              # Embedding-based Intent Pre-Filter
│   ├── arg_extractor.py                # Deterministic Argument Extraction
│   ├── intent_classifier.py            # LM Studio Intent Classification
│   ├── skill_executor.py               # Skill Ausführung
│   ├── tool_registry.py                # Dynamic Skill Registry
│   ├── skill_loader.py                 # SKILL.md Parser
│   ├── edit_utils.py                   # Safe Edit System (Search-Replace)
│   ├── skill_creator.py                # Skill Creation Workflow
│   ├── fix_generator.py                # Error Fix Generation
│   ├── error_approval.py               # Admin Approval Workflow
│   ├── keyword_extractor.py            # LM Studio Keyword Generation
│   ├── example_generator.py            # LM Studio Example Generation
│   ├── chat_history.py                 # Conversation Memory
│   ├── database.py                     # SQLite Storage
│   ├── telegram_handler.py             # Telegram API
│   └── config.py                       # Settings (Pydantic)
│
├── .claude/skills/                     # Skill Definitions
│   ├── homeassistant/                  # Smart Home
│   ├── proxmox/                        # Virtualization
│   ├── pihole/                         # DNS/Ad-Blocking
│   ├── unifi-network/                  # Network Infrastructure
│   ├── unifi-protect/                  # Cameras/NVR
│   ├── git/                            # Git Operations
│   └── self-annealing/                 # Error Tracking
│
├── data/                               # Runtime Data
│   ├── conversations.db                # SQLite Database
│   └── embedding_cache.json            # Pre-computed Skill Embeddings
│
└── .env                                # Configuration
```

## Request Flow

### 1. Telegram Message empfangen

```python
# main.py
@app.post("/webhook")
async def webhook(request: Request):
    # 1. Verify webhook signature (X-Telegram-Bot-Api-Secret-Token)
    # 2. Deduplicate (processed_updates table)
    # 3. Route to handler
```

### 2. Intent Classification

Intent classification happens in two stages for optimal performance:

**2.1 Semantic Router (Fast Pre-Filter)**

```python
# semantic_router.py - ~50ms, embedding-based
match = await route(message, settings, skills)

if match.skill_similarity >= 0.75:
    # HIGH confidence → skip LLM entirely
    args = extract_args(message, match.skill)
    return IntentResult(match.skill, match.action, args, "high")
elif match.skill_similarity >= 0.40:
    # MEDIUM → narrow LLM to top 2 skills
    relevant_skills = [s for s, _ in match.top_skills[:2]]
    return await classify_with_llm(message, relevant_skills)
else:
    # LOW (<0.40) → treat as smalltalk
    return conversational_response()
```

**Why embedding-based routing?**
- Small local LLMs (7B-14B) struggle with complex tool-calling (5+ tools, 15-30 actions each)
- Embedding similarity with cosine distance is deterministic and fast (<1ms compute)
- EmbeddingGemma-300M runs alongside chat model in LM Studio
- Embeddings cached to disk, invalidated via SHA-256 hash of all skill metadata

**Cache Strategy:**
- Pre-computed embeddings for all skill intent_hints and command descriptions
- Stored in `data/embedding_cache.json`
- Cache key includes skill names, versions, hint texts, command descriptions
- Any SKILL.md change triggers re-embedding automatically
- Deferred initialization: computes on first LM Studio availability if not cached

**2.2 LLM Classification (Fallback)**

```python
# intent_classifier.py - ~2-5s, full LLM reasoning
async def classify_intent(message, history, registry):
    # 1. Build system prompt with skill examples
    # 2. Convert skills to OpenAI tool definitions
    # 3. Call LM Studio with tool-calling enabled
    # 4. Parse response → IntentResult(skill, action, args, confidence)
```

**LM Studio erhält:**
- System Prompt mit Skill-Beispielen
- Conversation History (für Kontext)
- Tool Definitions (dynamisch aus Registry, optional filtered by semantic router)
- User Message

**LM Studio antwortet mit:**
- Tool Call: `{"skill": "proxmox", "action": "start", "args": {"vmid": 100}}`
- Oder: Conversational Response (keine Tool-Nutzung)

**Deterministic Argument Extraction:**
- For HIGH confidence matches, regex patterns extract common args
- Camera names (Protect): "Einfahrt", "Garten", "Grünstreifen", etc.
- Room names (Home Assistant): "Wohnzimmer", "Küche", "Schlafzimmer", etc.
- Time ranges: "last 24h", "letzte 2 stunden", "seit gestern"
- VM/Container IDs: numeric patterns
- Avoids LLM entirely for argument parsing on clear matches

### 3. Skill Execution

```python
# skill_executor.py
async def execute_skill(skill_name, action, args, settings):
    # 1. Check admin permissions (write ops)
    # 2. Build command: python *_api.py {action} {args}
    # 3. Run in subprocess (30s timeout)
    # 4. Parse output (--json flag)
    # 5. On error → request_error_fix_approval()
```

## Skill System

### Skill Struktur

```
skill-name/
├── SKILL.md              # Definition + Dokumentation
├── scripts/
│   └── skill_name_api.py # Ausführbares Script
├── keywords.json         # [auto-generated] Homelab-Keywords
└── examples.json         # [auto-generated] Beispiel-Phrasen
```

### SKILL.md Format

```yaml
---
name: proxmox
description: Manage Proxmox VE virtualization
version: 1.0.0
tags: [infrastructure, virtualization]
triggers:
  - proxmox
  - vm
  - container
---

## Goal
Control Proxmox VE cluster...

## Commands
| Command | Description |
|---------|-------------|
| overview | Show cluster overview |
| start | Start VM/Container |
```

### Script Format (*_api.py)

```python
#!/usr/bin/env python3
"""Skill API with argparse CLI."""

import argparse
import json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    subparsers = parser.add_subparsers(dest='command')

    # Define commands
    start_parser = subparsers.add_parser('start', help='Start VM')
    start_parser.add_argument('vmid', type=int)

    args = parser.parse_args()

    if args.command == 'start':
        result = start_vm(args.vmid)
        if args.json:
            print(json.dumps(result))
        else:
            print(f"VM {args.vmid} started")

if __name__ == '__main__':
    main()
```

### Auto-Generated Metadata

**keywords.json** - für Homelab-Erkennung:
```json
["server", "vm", "container", "lxc", "qemu", "proxmox", "virtualisierung"]
```

**examples.json** - für Intent Classification:
```json
[
  {"phrase": "Starte VM 100", "action": "start", "args": {"vmid": 100}},
  {"phrase": "Zeig mir den Proxmox Status", "action": "overview"}
]
```

## Self-Annealing

### Error Fix Workflow

```
Skill Execution Failed
        │
        ▼
request_error_fix_approval()
        │
        ├─ Generate fix via Claude API (fix_generator.py)
        │   └─ Uses EDIT format (old_string → new_string)
        │
        ▼
Admin receives Telegram message
        │
        ├─ [Approve] → apply_fix() → Git commit → Feature branch
        │              └─ Search-and-replace (no full file rewrites!)
        │
        └─ [Reject] → Log and skip
```

### Safe Edit System

**Problem:** LLMs schreiben oft ganze Dateien neu → Code geht verloren

**Lösung:** Search-and-Replace statt Content-Replacement

```python
# edit_utils.py
def apply_edit(file_path, old_string, new_string):
    content = file_path.read_text()

    if old_string not in content:
        return {"success": False, "error": "old_string not found"}

    if content.count(old_string) > 1:
        return {"success": False, "error": "old_string not unique"}

    new_content = content.replace(old_string, new_string, 1)
    file_path.write_text(new_content)
    return {"success": True}
```

**Claude API Format:**
```json
{
  "edits": [{
    "path": ".claude/skills/proxmox/scripts/proxmox_api.py",
    "old_string": "def broken():\n    return None",
    "new_string": "def broken():\n    return result or {}"
  }]
}
```

### Skill Creation Workflow

```
User: "Kannst du meine Waschmaschine steuern?"
        │
        ▼
is_homelab_related() → True (keyword match)
        │
        ▼
Admin Approval Request
        │
        ├─ [Approve] → create_skill() via Claude API
        │              │
        │              ▼
        │         Feature Branch + PR
        │              │
        │              ▼
        │         Admin Review (GitHub)
        │              │
        │              ├─ [Merge] → Skills reloaded
        │              └─ [Close] → Branch deleted
        │
        └─ [Reject] → Inform user
```

## External Integrations

| Service | Zweck | Config |
|---------|-------|--------|
| **Telegram Bot API** | Webhook + Messaging | `TELEGRAM_BOT_TOKEN` |
| **LM Studio** | Lokales LLM (Intent Classification) | `LM_STUDIO_URL` |
| **Claude API** | Skill Creation + Error Fixes | `ANTHROPIC_API_KEY` |
| **Gaming PC** | Host für LM Studio | `GAMING_PC_IP`, `GAMING_PC_MAC` (WoL) |
| **GitHub** | Code Storage + PRs | Via git_api.py |

## Permission Model

### Admin-Required Operations

| Skill | Write Operations |
|-------|-----------------|
| Proxmox | start, stop, shutdown, reboot, snapshot |
| Pi-hole | blocklist management |
| UniFi Network | firewall rules, port forwards |
| UniFi Protect | lighting control |

### Read-Only (Alle User)

- Status-Abfragen
- Übersichten
- Device-Listen

## Configuration

### Environment Variables (.env)

```bash
# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
TELEGRAM_ALLOWED_USERS=123,456,789
ADMIN_TELEGRAM_ID=123

# LM Studio (lokal)
LM_STUDIO_URL=http://192.168.178.50:1234
LM_STUDIO_MODEL=  # optional, auto-detect
EMBEDDING_MODEL=nomic-embed-text-v1.5  # or embeddinggemma-300m, auto-detect if not set

# Wake-on-LAN
GAMING_PC_IP=192.168.178.50
GAMING_PC_MAC=AA:BB:CC:DD:EE:FF

# Claude API (optional)
ANTHROPIC_API_KEY=...

# Git Sync
GIT_PULL_INTERVAL_MINUTES=5
```

## Data Storage

### SQLite (data/conversations.db)

**conversations Table:**
- Full conversation data
- Intent classification results
- Success/Error tracking
- Used for nightly analysis

**processed_updates Table:**
- Webhook deduplication
- 7-day retention

### In-Memory (chat_history.py)

- Per-chat deque (maxlen=50)
- Für LLM Context
- Gefiltert (keine internen Konzepte)

## Background Tasks

| Task | Interval | Zweck |
|------|----------|-------|
| Git Pull | 5 min | Code-Sync + Hot-Reload |
| Metadata Generation | Startup | Keywords/Examples generieren |
| Nightly Review | 24h | Conversation Analysis |

## API Endpoints

| Endpoint | Method | Beschreibung |
|----------|--------|--------------|
| `/webhook` | POST | Telegram Webhook |
| `/health` | GET | Health Check |
| `/reload-skills` | POST | Skills neu laden |
| `/generate-metadata` | POST | Keywords/Examples generieren |

## Key Design Decisions

1. **Semantic Router (Embedding-based Pre-Filter):**
   - Small LLMs (7B-14B) struggle with complex tool-calling (5+ tools × 15-30 actions)
   - Embedding similarity with EmbeddingGemma-300M provides fast (~50ms), deterministic routing
   - Three confidence zones: HIGH (≥0.75) skips LLM, MEDIUM (0.40-0.75) narrows to top 2 skills, LOW (<0.40) treats as smalltalk
   - Pure Python cosine similarity (<1ms for 256-768 dim vectors) - no numpy needed
   - Cache invalidation via SHA-256 hash of skill metadata - any SKILL.md change triggers re-embedding
   - Deterministic arg extraction via regex for camera names, time ranges, VM IDs on high-confidence matches

2. **Lokales LLM (LM Studio):** Keine Cloud-Abhängigkeit für Intent Classification

3. **Dynamic Registry:** Neue Skills funktionieren sofort nach SKILL.md hinzufügen

4. **Tool-Calling:** Strukturierte Outputs statt freiem Text

5. **Search-Replace Edits:** Verhindert versehentlichen Code-Verlust

6. **Approval Workflows:** Admin muss kritische Änderungen genehmigen

7. **Conversation History:** Kontext für Follow-up Fragen

8. **Auto-Generated Metadata:** Reduziert manuelle Arbeit bei neuen Skills
