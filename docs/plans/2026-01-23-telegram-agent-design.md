# Telegram-gesteuerter Homelab-Agent

> Design-Dokument erstellt am 2026-01-23

## Ziel
Ein selbst-erweiternder KI-Agent, erreichbar über Telegram, der:
- Smart-Home und Homelab steuert (bestehende Skills)
- Natürliche Sprache versteht (LM Studio lokal)
- Neue Fähigkeiten automatisch erstellt (Claude API)
- Für die Familie nutzbar ist (Allowlist)

---

## Architektur

```
Telegram → DuckDNS:8443 → Fritz-Box → Proxmox LXC (Agent)
                                           │
                         ┌─────────────────┼─────────────────┐
                         ▼                 ▼                 ▼
                   Gaming-PC          Claude API        Bestehende
                   (LM Studio)        (Skill-Erstellung) Skills
```

**Zwei-Tier-LLM-System:**
- **Tier 1**: LM Studio (lokal, schnell) für bekannte Intents
- **Tier 2**: Claude API (cloud, mächtig) für Skill-Erstellung
  - ⚠️ **Mit Admin-Genehmigung**: Inline Keyboard Buttons, Timeout 5 Min

---

## Implementierungsschritte

### Phase 1: Infrastruktur vorbereiten

#### 1.1 Proxmox LXC erstellen
```bash
pct create 200 local:vztmpl/debian-12-standard_12.2-1_amd64.tar.zst \
  --hostname telegram-agent \
  --memory 1024 \
  --cores 2 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --storage local-lvm \
  --rootfs local-lvm:8
```

#### 1.2 Basis-Software installieren
```bash
apt update && apt install -y python3 python3-pip python3-venv git certbot curl
```

#### 1.3 Let's Encrypt Zertifikat
```bash
certbot certonly --standalone -d DEINE-DOMAIN.duckdns.org
```

#### 1.4 Fritz-Box konfigurieren
- Statische IP für LXC (z.B. 192.168.178.200)
- Port-Freigabe: 8443 extern → 8443 intern (TCP)

#### 1.5 DuckDNS Cronjob
```bash
echo "*/5 * * * * curl -s 'https://www.duckdns.org/update?domains=DOMAIN&token=TOKEN'" | crontab -
```

---

### Phase 2: Telegram Bot einrichten

#### 2.1 Bot erstellen
1. @BotFather in Telegram öffnen
2. `/newbot` → Name und Username wählen
3. Bot-Token speichern

#### 2.2 Webhook setzen (nach Agent-Deployment)
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://DOMAIN.duckdns.org:8443/webhook&secret_token=<SECRET>"
```

#### 2.3 User-IDs ermitteln
1. @userinfobot in Telegram → eigene ID
2. Frau dasselbe machen lassen
3. IDs in TELEGRAM_ALLOWED_USERS eintragen

---

### Phase 3: Gaming-PC vorbereiten (LM Studio)

#### 3.1 LM Studio installieren
- Download: https://lmstudio.ai
- Server-Modus aktivieren (Port 1234)
- Modell laden: Mistral 7B Instruct oder Llama 3 8B (GGUF Q4/Q5)

#### 3.2 Autostart einrichten
- Windows: LM Studio in Autostart-Ordner
- Oder: Task Scheduler → Bei Anmeldung starten

#### 3.3 Wake-on-LAN aktivieren
- BIOS: ErP Ready = Disabled, Wake on PCI-E = Enabled
- Windows: Fast Startup deaktivieren, "Wake on Magic Packet" aktivieren
- MAC-Adresse notieren

---

### Phase 4: Agent-Service entwickeln

#### 4.1 Projektstruktur erweitern

```
homelab-assistant/
├── agent/
│   ├── __init__.py
│   ├── main.py              # FastAPI App
│   ├── config.py            # Settings, Pydantic
│   ├── telegram_handler.py  # Webhook, Signaturprüfung, Inline Keyboards
│   ├── intent_classifier.py # LM Studio Client
│   ├── skill_executor.py    # Bestehende Skills aufrufen
│   ├── skill_creator.py     # Claude API + Admin-Approval
│   └── wol.py               # Wake-on-LAN
├── .env                      # Secrets erweitern
└── requirements.txt          # Dependencies erweitern
```

#### 4.2 Neue Dependencies
```
fastapi
uvicorn[standard]
python-telegram-bot
httpx
wakeonlan
anthropic
pydantic-settings
```

#### 4.3 Hauptkomponenten

**main.py** - FastAPI Webhook Handler
```python
from fastapi import FastAPI, Request, HTTPException
from .config import settings
from .telegram_handler import verify_signature, handle_update, handle_callback

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    if not verify_signature(request, settings.telegram_webhook_secret):
        raise HTTPException(403, "Invalid signature")

    data = await request.json()

    # Callback Query (Inline Keyboard Button gedrückt)
    if "callback_query" in data:
        await handle_callback(data["callback_query"])
    else:
        await handle_update(data)

    return {"ok": True}
```

**telegram_handler.py** - Inline Keyboard für Admin-Approval
```python
import httpx
from .config import settings

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

async def send_message(chat_id: int, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        })

async def send_approval_request(admin_id: int, text: str, request_id: str):
    """Sendet Nachricht mit Inline Keyboard Buttons"""
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": admin_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "✅ Ja, erstellen", "callback_data": f"approve:{request_id}"},
                    {"text": "❌ Nein", "callback_data": f"reject:{request_id}"}
                ]]
            }
        })

async def handle_callback(callback_query: dict):
    """Verarbeitet Button-Klicks"""
    from .skill_creator import handle_approval

    data = callback_query["data"]  # z.B. "approve:abc123"
    action, request_id = data.split(":")
    user_id = callback_query["from"]["id"]

    # Nur Admin darf genehmigen
    if user_id != settings.admin_telegram_id:
        return

    approved = (action == "approve")
    result = await handle_approval(request_id, approved)

    # Button-Nachricht aktualisieren
    await answer_callback(callback_query["id"], "✅ Erledigt" if approved else "❌ Abgelehnt")
```

**intent_classifier.py** - LM Studio Integration
```python
import httpx
from .wol import ensure_lm_studio_available
from .config import settings

INTENT_PROMPT = """Du bist ein Intent-Classifier für Smart Home.
Antworte NUR mit JSON.

Bekannte Skills:
- homeassistant: Lichter, Szenen, Klima, Automationen
- proxmox: VMs, Container starten/stoppen
- unifi-network: Netzwerk, Clients
- unifi-protect: Kameras, Aufnahmen

Beispiele:
"Mach das Licht im Wohnzimmer an" → {"skill": "homeassistant", "action": "turn_on", "entity": "light.wohnzimmer"}
"Starte den Plex-Container" → {"skill": "proxmox", "action": "start", "target": "plex"}
"UNBEKANNT" → {"skill": "unknown", "description": "..."}
"""

async def classify_intent(message: str) -> dict:
    await ensure_lm_studio_available()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.lm_studio_url}/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": INTENT_PROMPT},
                    {"role": "user", "content": message}
                ],
                "temperature": 0.1,
                "max_tokens": 200
            }
        )
    return parse_response(response.json())
```

**skill_executor.py** - Bestehende Skills aufrufen
```python
import subprocess
from pathlib import Path

SKILL_SCRIPTS = {
    "homeassistant": "homeassistant_api.py",
    "proxmox": "proxmox_api.py",
    "unifi-network": "network_api.py",
    "unifi-protect": "protect_api.py",
}

async def execute_skill(intent: dict) -> str:
    script = SKILL_SCRIPTS.get(intent["skill"])
    script_path = Path(f".claude/skills/{intent['skill']}/scripts/{script}")

    result = subprocess.run(
        ["python", str(script_path), intent["action"], *intent.get("args", [])],
        capture_output=True, text=True
    )
    return result.stdout or result.stderr
```

**skill_creator.py** - Claude API für neue Skills (mit Admin-Genehmigung)
```python
import anthropic
import asyncio
from .config import settings
from .telegram_handler import send_message, send_approval_request

# Pending approvals: {request_id: {user_request, requester_name, requester_id}}
pending_approvals = {}

async def request_skill_creation(user_request: str, requester_name: str, requester_id: int) -> str:
    """Schritt 1: Admin um Genehmigung bitten"""
    import uuid
    request_id = str(uuid.uuid4())[:8]

    # Speichere Anfrage
    pending_approvals[request_id] = {
        "user_request": user_request,
        "requester_name": requester_name,
        "requester_id": requester_id
    }

    # Sende Genehmigungsanfrage an Admin mit Inline Keyboard
    await send_approval_request(
        admin_id=settings.admin_telegram_id,
        text=f"🔔 **Neue Skill-Anfrage**\n\n"
             f"Von: {requester_name}\n"
             f"Anfrage: \"{user_request}\"\n\n"
             f"Soll ich einen Skill erstellen/erweitern?",
        request_id=request_id
    )

    # User informieren
    return "⏳ Deine Anfrage wurde an den Admin gesendet. Du bekommst Bescheid!"

async def handle_approval(request_id: str, approved: bool) -> str:
    """Schritt 2: Admin hat entschieden"""
    if request_id not in pending_approvals:
        return "❌ Anfrage nicht gefunden oder abgelaufen."

    request = pending_approvals.pop(request_id)

    if not approved:
        # User informieren
        await send_message(
            request["requester_id"],
            f"❌ Deine Anfrage wurde abgelehnt:\n\"{request['user_request']}\""
        )
        return "Anfrage abgelehnt."

    # Skill erstellen via Claude API
    result = await create_skill(request["user_request"])

    # User informieren
    await send_message(
        request["requester_id"],
        f"✅ Skill erstellt! Du kannst es jetzt nochmal versuchen:\n\"{request['user_request']}\""
    )

    return f"Skill erstellt: {result}"

async def create_skill(user_request: str) -> str:
    """Eigentliche Skill-Erstellung via Claude API"""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""
            Erstelle oder erweitere einen Skill für:
            "{user_request}"

            Skill-Struktur beachten:
            .claude/skills/<name>/
            ├── SKILL.md
            ├── API.md
            └── scripts/<name>_api.py
            """
        }]
    )
    return message.content[0].text
```

---

### Phase 5: Deployment

#### 5.1 Projekt auf LXC klonen
```bash
git clone https://github.com/USER/homelab-assistant.git /opt/homelab-assistant
cd /opt/homelab-assistant
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 5.2 .env konfigurieren
```bash
# Bestehende Einträge +
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_USERS=123456789,987654321
TELEGRAM_WEBHOOK_SECRET=random-string
ADMIN_TELEGRAM_ID=123456789          # DEINE Telegram User-ID (für Genehmigungen)

ANTHROPIC_API_KEY=sk-ant-...

GAMING_PC_IP=192.168.178.50
GAMING_PC_MAC=AA:BB:CC:DD:EE:FF
LM_STUDIO_URL=http://192.168.178.50:1234

# Approval Timeout (optional)
APPROVAL_TIMEOUT_MINUTES=5           # Nach 5 Min ohne Antwort → automatisch abgelehnt
```

#### 5.3 Systemd Service einrichten
```ini
# /etc/systemd/system/telegram-agent.service
[Unit]
Description=Telegram Homelab Agent
After=network.target

[Service]
Type=exec
WorkingDirectory=/opt/homelab-assistant
Environment=PATH=/opt/homelab-assistant/venv/bin
ExecStart=/opt/homelab-assistant/venv/bin/uvicorn agent.main:app \
    --host 0.0.0.0 --port 8443 \
    --ssl-keyfile /etc/letsencrypt/live/DOMAIN/privkey.pem \
    --ssl-certfile /etc/letsencrypt/live/DOMAIN/fullchain.pem
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now telegram-agent
```

#### 5.4 Webhook aktivieren
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://DOMAIN.duckdns.org:8443/webhook&secret_token=<SECRET>"
```

---

### Phase 6: Testen

#### 6.1 Basis-Tests
- [ ] LXC erreichbar aus dem Internet (curl https://DOMAIN:8443)
- [ ] Telegram Webhook antwortet
- [ ] User-Allowlist funktioniert (unbekannte User werden abgelehnt)

#### 6.2 Skill-Tests
- [ ] "Licht im Wohnzimmer an" → Home Assistant Aktion
- [ ] "Status vom Proxmox" → Proxmox API Antwort
- [ ] "Wecke den Gaming-PC" → WoL funktioniert

#### 6.3 Skill-Erstellung Test (mit Admin-Approval)
- [ ] Unbekannte Anfrage → Admin bekommt Genehmigungsanfrage
- [ ] Inline Keyboard Buttons funktionieren (✅/❌)
- [ ] Bei "Ja" → Claude erstellt Skill → User wird informiert
- [ ] Bei "Nein" → User bekommt Absage
- [ ] Timeout nach 5 Min → automatische Ablehnung
- [ ] Neuer Skill funktioniert bei erneutem Versuch

---

## Kritische Dateien

| Datei | Zweck |
|-------|-------|
| `agent/main.py` | FastAPI Webhook Handler (inkl. Callback Queries) |
| `agent/config.py` | Pydantic Settings |
| `agent/telegram_handler.py` | Signaturprüfung, Inline Keyboards, Callbacks |
| `agent/intent_classifier.py` | LM Studio Integration |
| `agent/skill_executor.py` | Bestehende Skills aufrufen |
| `agent/skill_creator.py` | Claude API + Admin-Approval-Flow |
| `.env` | Alle Secrets (inkl. ADMIN_TELEGRAM_ID) |
| `systemd/telegram-agent.service` | Systemd Unit |

---

## Sicherheit

- [x] Telegram-Signaturprüfung
- [x] User-Allowlist (nur genehmigte IDs)
- [x] HTTPS mit Let's Encrypt
- [x] Secrets in .env (nicht im Repo)
- [x] **Admin-Genehmigung für Skill-Erstellung** (Human-in-the-Loop)
  - Alle Tier-2-Anfragen (neue/erweiterte Skills) brauchen Admin-Approval
  - Inline Keyboard Buttons für schnelle Entscheidung
  - Timeout nach 5 Minuten → automatisch abgelehnt
  - Gilt für ALLE User inkl. Admin selbst
- [ ] Optional: Rate-Limiting pro User

---

## Kosten

| Posten | Kosten |
|--------|--------|
| Telegram Bot | Kostenlos |
| DuckDNS | Kostenlos |
| Let's Encrypt | Kostenlos |
| LM Studio | Kostenlos |
| Claude API | ~0.01-0.10€ pro Skill-Erstellung |
| **Gesamt** | **< 1€/Monat** (nur Claude API bei Bedarf) |

---

## Phase 7: Dynamic Tool-Calling (Upgrade)

> Entscheidung vom 2026-01-23: Wechsel von statischem Intent-Prompt zu dynamischem Tool-Calling

### Problem mit statischem Ansatz

Der ursprüngliche `intent_classifier.py` hatte einen hardcodierten `INTENT_PROMPT` mit allen Skills. Bei neuen Skills mussten zwei Dateien manuell aktualisiert werden:
- `intent_classifier.py` - INTENT_PROMPT
- `skill_executor.py` - SKILL_REGISTRY

### Neuer Ansatz: Dynamic Tool-Calling

```
.claude/skills/ → Tool Registry → LM Studio (Function Calling) → Skill Executor
```

**Neue Dateien:**
```
agent/
├── skill_loader.py        # SKILL.md YAML-Frontmatter Parser
├── tool_registry.py       # Zentrale Registry, lädt Skills beim Start
└── tool_caller.py         # LM Studio mit tools Parameter
```

**Vorteile:**
- Neue Skills werden automatisch erkannt
- Kein manuelles Update von Code nötig
- Skill-Erstellung via Claude API funktioniert sofort

### LLM-Modell

- **Qwen 2.5 7B Instruct** (nativer Function Calling Support)
- Format: GGUF Q4 (~4-5GB VRAM)
- Response Time: ~2-3s auf Gaming-PC GPU

### Tool-Schema (OpenAI-Format)

```json
{
  "type": "function",
  "function": {
    "name": "homeassistant",
    "description": "Manage Home Assistant smart home automation",
    "parameters": {
      "type": "object",
      "properties": {
        "action": {"type": "string", "enum": ["turn-on", "turn-off", ...]},
        "target": {"type": "string"},
        "args": {"type": "object"}
      },
      "required": ["action"]
    }
  }
}
```

---

## Erweiterungsmöglichkeiten (Zukunft)

- Sprachnachrichten via Whisper transkribieren
- Inline Keyboards für Bestätigungen
- Gruppen-Support (Familie-Chat mit Bot)
- Scheduled Messages ("Erinnere mich um 18 Uhr")
- Status-Dashboard via Telegram
