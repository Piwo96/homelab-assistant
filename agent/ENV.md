# Telegram Agent - Umgebungsvariablen

Füge diese Variablen zu deiner `.env` Datei hinzu:

```bash
# === Telegram Agent ===

# Bot Token von @BotFather
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Erlaubte User-IDs (kommagetrennt)
# Finde deine ID mit @userinfobot in Telegram
TELEGRAM_ALLOWED_USERS=123456789,987654321

# Webhook Secret (beliebiger String für Signaturprüfung)
TELEGRAM_WEBHOOK_SECRET=mein-geheimer-string

# Admin User-ID (für Skill-Genehmigungen)
ADMIN_TELEGRAM_ID=123456789

# === Claude API (für Skill-Erstellung) ===
ANTHROPIC_API_KEY=sk-ant-api03-...

# === Gaming PC / LM Studio ===

# IP-Adresse des Gaming-PCs
GAMING_PC_IP=192.168.178.50

# MAC-Adresse für Wake-on-LAN (Format: AA:BB:CC:DD:EE:FF)
GAMING_PC_MAC=AA:BB:CC:DD:EE:FF

# LM Studio API URL
LM_STUDIO_URL=http://192.168.178.50:1234

# === Optional ===

# Timeout für LM Studio Anfragen (Sekunden)
LM_STUDIO_TIMEOUT=30

# Timeout für Skill-Genehmigungen (Minuten)
APPROVAL_TIMEOUT_MINUTES=5
```

## Webhook einrichten

Nach dem Deployment den Webhook setzen:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<DOMAIN>:8443/webhook&secret_token=<SECRET>"
```

## Agent starten

```bash
# Entwicklung
uvicorn agent.main:app --reload --port 8000

# Produktion (mit SSL)
uvicorn agent.main:app \
  --host 0.0.0.0 --port 8443 \
  --ssl-keyfile /path/to/privkey.pem \
  --ssl-certfile /path/to/fullchain.pem
```
