# Rolly — Proxmox Deployment

Deploy Rolly (the Telegram-Agent under `agent/`) as an LXC on the local Proxmox host, reachable from Telegram's cloud via DuckDNS + Caddy + Let's Encrypt.

See [the design spec](../../docs/superpowers/specs/2026-05-16-rolly-proxmox-deploy-design.md) for the full architecture and decisions.

## One-time manual setup

Do these once before the first `./deploy.sh`.

### 1. Rotate the Telegram bot token

Open Telegram → @BotFather → `/revoke` for the existing bot → copy the new token. Paste it into `config.env` as `TELEGRAM_BOT_TOKEN`.

### 2. DuckDNS token

Go to <https://www.duckdns.org/> → log in → copy the token from the top of the page (one token covers all your subdomains). Paste into `config.env` as `DUCKDNS_TOKEN`.

Verify the token works:
```
curl "https://www.duckdns.org/update?domains=${DUCKDNS_HOST%.duckdns.org}&token=${DUCKDNS_TOKEN}&txt=test"
# Expected output: OK
```

### 3. FritzBox port-forward

FritzBox UI → Internet → Permit Access → Port Sharing → Add:
- Protocol: TCP
- External port: 8443
- Internal device: the LXC at the IP from `LXC_IP_CIDR` (default `192.168.10.200`)
- Internal port: 8443

Save. The forward is persistent across reboots.

### 4. Proxmox API token

If you don't already have one: Proxmox UI → Datacenter → Permissions → API Tokens → Add. Uncheck "Privilege Separation" so the token inherits the user's permissions. Copy the token ID and secret into `config.env`.

### 5. Debian 12 template

The deploy script checks for the template and aborts with instructions if missing. To pre-download via the Proxmox UI:
- Node → local → CT Templates → Templates → search "debian-12-standard" → Download.

Or via SSH on the Proxmox host:
```
pveam update && pveam download local debian-12-standard
```

### 6. SSH key

The Mac's `~/.ssh/id_rsa.pub` is injected into the LXC for passwordless SSH. If absent: `ssh-keygen -t ed25519` first.

## Deploy

`deploy.sh` sources two files in order:
1. The project's root `.env` (your existing skill credentials — `TELEGRAM_BOT_TOKEN`, `HOMEASSISTANT_*`, `PIHOLE_*`, `PROTECT_*`, `UNIFI_*`, `PROXMOX_*`, `LM_STUDIO_*`, `ADMIN_TELEGRAM_ID`, etc.)
2. `infra/rolly/config.env` (deploy-specific: LXC sizing, DuckDNS token, public port)

You only need to fill `config.env` — your existing skill credentials in the root `.env` are reused automatically.

```bash
cd infra/rolly
cp config.env.example config.env
# Edit config.env — only DUCKDNS_TOKEN is missing on a fresh checkout
./deploy.sh
```

The first run takes ~2-3 minutes. Subsequent runs (after `git push`) are ~30 seconds and only refresh code + restart services.

At the end, `deploy.sh` prints the exact `setWebhook` command. Run it once. Then `/start` your bot in Telegram.

## Updating

```bash
# Just re-run deploy.sh — it git-pulls the LXC's checkout and restarts the service
./deploy.sh
```

## Troubleshooting

### Bot doesn't reply / nothing in journal

```bash
ssh root@192.168.10.200
journalctl -u rolly -f
# Check that LM Studio is reachable from the LXC:
curl http://192.168.1.135:1234/v1/models
```

If LM Studio isn't reachable: verify FritzBox routes between 192.168.10 and 192.168.1.

### Caddy can't get a cert

```bash
ssh root@192.168.10.200
journalctl -u caddy -n 100
```

Common causes:
- `DUCKDNS_TOKEN` wrong (verify with the curl test in step 2)
- Port 8443 not forwarded in FritzBox (although DNS-01 doesn't need it for the cert itself — only for traffic)

### Webhook not delivering

```
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Look at `last_error_date`, `last_error_message`, and `pending_update_count`. If `last_error_message` mentions cert: the LE cert isn't issued yet (wait a minute, re-run setWebhook).

### Reset the LXC

```bash
# From the Mac
python3 .claude/skills/proxmox/scripts/proxmox_api.py delete-lxc <vmid> --force
./deploy.sh   # creates a fresh LXC
```

## Files in this directory

| File | Role |
|---|---|
| `deploy.sh` | Mac-side orchestrator: validates config, calls `proxmox_api.py create-lxc`, SCPs setup artifacts, runs setup-lxc.sh |
| `setup-lxc.sh` | Runs inside the LXC: installs deps, clones repo, builds/configures Caddy, writes systemd units, starts services |
| `config.env.example` | Template for `config.env` (gitignored) — fill once per machine |
| `Caddyfile.tmpl` | Caddy config template (rendered with `envsubst` during setup) |
| `rolly.service.tmpl` | systemd unit for the Bun bot |
| `caddy.service` | systemd unit for Caddy |
