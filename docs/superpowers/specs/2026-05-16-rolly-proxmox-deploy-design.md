# Rolly Proxmox Deployment — Design Spec

**Date:** 2026-05-16
**Author:** Philipp Rollmann (with Claude)
**Status:** Draft, pending user review
**Predecessor:** [`2026-05-16-new-agent-design.md`](2026-05-16-new-agent-design.md) — Rolly itself (Plan 1, complete)

## 1. Context & Goals

Rolly (the new TypeScript/Bun Telegram-Agent under `agent/`) is built, tested locally via curl-driven webhooks, and ready to deploy. This spec covers the production deployment to the user's local Proxmox host at `192.168.10.140`, reachable from the internet via DuckDNS so that Telegram can deliver webhook updates.

The Proxmox host runs other workloads already; the user's FritzBox routes between subnets `192.168.10.x` (Proxmox) and `192.168.1.x` (LM Studio on Gaming PC). DuckDNS hostname `sophia-und-philipp.duckdns.org` already resolves to the FritzBox's public IPv4 (FritzBox-side auto-update). Port `443` is occupied by an existing VPN service.

### Goals

1. Run Rolly as a long-lived LXC on Proxmox, addressable from Telegram's webhook delivery service.
2. Terminate TLS locally via Let's Encrypt cert obtained through DNS-01 (DuckDNS API) — no inbound port 80 required.
3. Make redeploys idempotent: `./deploy.sh` re-run pulls latest code, rebuilds, restarts services, leaves a working bot.
4. Extend the existing `proxmox` skill with `create-lxc` / `delete-lxc` / `wait-task` / `templates` actions so future LXC provisioning is a one-liner — closing the capability gap discovered during this work.

### Non-Goals (v1)

- Auto-update on git push (user prefers manual `./deploy.sh`).
- Backups of `/opt/rolly/data/conversations.db` (separate concern; FritzBox + Proxmox snapshots cover disaster recovery).
- Generic reusable `proxmox-lxc-deploy` skill (premature abstraction; revisit once a second bot exists).
- HA / failover (single LXC is sufficient for personal use).
- Monitoring/alerting integration (Pi-hole + UniFi are present but out of scope here).
- Migrating the existing VPN endpoint or any other Proxmox workload.

## 2. High-Level Architecture

```
Telegram cloud
    │  HTTPS POST /webhook
    ▼
sophia-und-philipp.duckdns.org:8443
    │  (FritzBox public IPv4, DuckDNS auto-update)
    ▼
FritzBox  ── Port-Forward TCP 8443 → 192.168.10.200:8443
    │   ── Inter-VLAN route 192.168.10 ↔ 192.168.1 (existing)
    ▼
LXC "rolly" — vmid auto, IP 192.168.10.200/24, Debian 12 unprivileged
    ├── Caddy 2.x (custom build with caddy-dns/duckdns)
    │     • listens 0.0.0.0:8443
    │     • obtains cert for sophia-und-philipp.duckdns.org via Let's Encrypt DNS-01
    │     • reverse_proxy 127.0.0.1:8080
    ├── systemd unit "rolly.service"
    │     • runs Bun (agent/src/main.ts)
    │     • listens 127.0.0.1:8080
    │     • EnvironmentFile=/opt/rolly/.env
    │     • Restart=on-failure
    │   → outbound HTTPS to LM Studio @ 192.168.1.135:1234 (via FritzBox route)
    │   → outbound HTTPS to Home Assistant
    │   → spawns Python subprocesses for skill execution
    └── /opt/rolly = git clone of Piwo96/homelab-assistant (public GitHub)
```

**Why not a full VM:** Rolly is a single Bun process plus Python subprocesses — LXC is sufficient, boots in seconds, uses ~200MB idle. Full VM would need ~1GB just for the kernel.

### 2.1 Hardware Requirements

LXC resources (provisioned via `proxmox_api.py create-lxc`):

| Resource | Minimum | Recommended (default in `config.env.example`) | Rationale |
|----------|---------|----------------------------------------------|-----------|
| vCPU cores | 1 | **2** | Bun handles webhooks single-threaded, but Python skill subprocesses run in parallel. 1 core would block concurrent requests. |
| RAM | 512 MB | **1024 MB** | Bun idle ~120 MB, Caddy ~25 MB, one running skill ~80 MB, OS ~150 MB → ~400 MB steady-state. 1 GB leaves headroom for traffic spikes and DB cache. Caddy is installed prebuilt — no compile spike. |
| Disk | 5 GB | **10 GB** | OS ~1.5 GB, Bun + node_modules ~300 MB, Python venv ~200 MB, Caddy + cert + logs ~50 MB, repo ~50 MB → ~2 GB used. Rest is buffer for `conversations.db` growth, logs, kernel/package updates. |
| Network | bridge `vmbr0`, static IP | bridge `vmbr0`, static `192.168.10.200/24` | Outbound required to LM Studio (cross-subnet), Home Assistant, GitHub, Anthropic, DuckDNS, Let's Encrypt. |

Proxmox host must have free: ≥2 vCPU quota, ≥1 GB RAM, ≥10 GB on the chosen storage (`local-lvm` by default).

LM Studio host (separate hardware, not provisioned here): existing Gaming PC, RTX 2070 Super 8 GB VRAM — per `project_gaming_pc_hardware.md` memory.

**Why Caddy over nginx + certbot:** DNS-01 cert renewal is built-in via the `caddy-dns/duckdns` plugin. No cron, no separate certbot service, no hooks. Single config file. The plugin is pulled at install time via `caddy add-package github.com/caddy-dns/duckdns` (Caddy 2.7+) — downloads a prebuilt binary with the module from caddyserver.com, no Go toolchain or local build required.

**Why DNS-01 over HTTP-01:** HTTP-01 would require port 80 open and forwarded, conflicting with potential other services and adding attack surface. DNS-01 needs only the DuckDNS token, which the user already has.

## 3. Component Boundaries

### 3.1 `proxmox` skill (existing — extended)

| Concern | Owns |
|---------|------|
| Proxmox API communication | All HTTP calls to Proxmox |
| LXC lifecycle | create, start/stop (existing), delete, config, mounts (existing), snapshots (existing) |
| Task polling | `wait-task` polls UPID until terminal state |
| Template listing | `templates` lists `vztmpl` content for a storage |

New CLI actions added to `scripts/proxmox_api.py`:

```bash
proxmox_api.py create-lxc --vmid <auto|N> --hostname <h> --template <volid> \
                          --cores 2 --memory 1024 --disk 10 \
                          --bridge vmbr0 --ip 192.168.10.200/24 --gateway 192.168.10.1 \
                          --ssh-key "<pubkey-string>" [--unprivileged] [--start] \
                          [--nameserver 192.168.10.1] [--storage local-lvm]
# Returns JSON: { "vmid": 200, "node": "pve", "upid": "UPID:pve:..." }
# Waits for task completion before returning unless --no-wait.

proxmox_api.py delete-lxc --vmid 200 [--node pve] [--force]
# Stops then destroys. Returns JSON: { "vmid": 200, "deleted": true }

proxmox_api.py templates [--node pve] [--storage local]
# Returns array of { volid, format, size } for content=vztmpl

proxmox_api.py wait-task --upid <UPID> [--node pve] [--timeout 600]
# Polls until status=stopped, returns JSON: { "exitstatus": "OK", "duration_s": 12 }
```

Implementation details:

- `create-lxc` calls `POST /nodes/{node}/lxc` with the form-encoded params per the Proxmox API. The body is built from CLI flags; `net0` is constructed as `name=eth0,bridge={bridge},ip={ip},gw={gateway}`. `rootfs` is `{storage}:{disk}` (GB). `ssh-public-keys` is URL-encoded. `start=1` and `unprivileged=1` set as flags. If `--vmid auto`, the script first calls `GET /cluster/nextid` and uses that value.
- The endpoint returns a UPID string. Unless `--no-wait` is passed, the action then loops `GET /nodes/{node}/tasks/{upid}/status` every 2s (max 10 min) until `status=stopped`, returning the `exitstatus`.
- `delete-lxc` shutdowns first (`POST /nodes/{node}/lxc/{vmid}/status/shutdown`), waits for it to be stopped (timeout 30s, then `--force` does hard stop), then `DELETE /nodes/{node}/lxc/{vmid}`.
- All actions exit non-zero on API or task failure, with stderr containing the Proxmox error message.

### 3.2 `infra/rolly/` (new — Rolly-specific deployment)

Not a generic skill — Rolly-specific operational glue. Lives in the repo so it's versioned with the code it deploys.

```
infra/rolly/
├── deploy.sh              # Mac-side orchestrator (~150 LOC bash)
├── config.env.example     # template for user secrets/config (gitignored real copy)
├── setup-lxc.sh           # in-LXC installer (~120 LOC bash, idempotent)
├── Caddyfile.tmpl         # envsubst template
├── rolly.service.tmpl     # systemd unit template
├── caddy.service          # static systemd unit
└── README.md              # manual one-time steps + troubleshooting
```

Repo additions outside `infra/rolly/`:
- `.gitignore` — append `infra/rolly/config.env` (the real, filled-in copy)

### 3.3 Boundary contract

`deploy.sh` only calls into the `proxmox` skill via its CLI. It does not import Python or talk to the Proxmox API directly. This keeps the skill the single source of truth for Proxmox semantics and lets the agent itself eventually orchestrate LXC creation if desired.

`setup-lxc.sh` only runs commands inside the LXC. It does not know about Proxmox. Decoupled lifecycle: provisioning (Mac → Proxmox API) and configuration (Mac → SSH → LXC) are independent and resumable.

## 4. Deploy Flow (detailed)

### 4.1 Manual one-time setup (documented in `infra/rolly/README.md`)

1. **Rotate the Telegram bot token** at @BotFather (`/revoke` for the existing bot, copy the new token).
2. **FritzBox port-forward:** TCP `8443` external → `192.168.10.200:8443` internal. Verify no conflict with the existing VPN forward.
3. **DuckDNS token:** copy from duckdns.org dashboard (top of page after login). Same token works for all subdomains under the account.
4. **Proxmox storage:** verify `local-lvm` has ≥10 GB free and `local` has the Debian 12 template (`pveam download local debian-12-standard` if missing — script will detect and tell the user).
5. **SSH key:** the Mac's `~/.ssh/id_rsa.pub` is used. If absent: `ssh-keygen` first.

### 4.2 Repeatable deploy

```bash
cd infra/rolly
cp config.env.example config.env    # first time only
# Edit config.env with real values
./deploy.sh
```

`./deploy.sh` steps:

1. **Validate `config.env`** — bash `set -u`; check that every required var is non-empty:
   `DUCKDNS_HOST`, `DUCKDNS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` (generated if missing), `TELEGRAM_ALLOWED_USERS`, `ADMIN_TELEGRAM_ID`, `HA_URL`, `HA_TOKEN`, `LM_STUDIO_URL`, `INTERNAL_NOTIFY_TOKEN` (generated if missing). Fail-fast with a clear error.
2. **Verify proxmox skill reachable** — `proxmox_api.py nodes` returns ≥1 node.
3. **Check existing LXC** — `proxmox_api.py containers` filtered by `hostname=rolly`. If found, skip create and reuse its vmid + IP. If not, proceed.
4. **Verify template available** — `proxmox_api.py templates` includes `debian-12-standard`. Abort with instructions if missing.
5. **Create LXC** (only if step 3 found nothing) — `proxmox_api.py create-lxc --vmid auto --hostname rolly --template "local:vztmpl/debian-12-standard_*_amd64.tar.zst" --cores 2 --memory 1024 --disk 10 --bridge vmbr0 --ip 192.168.10.200/24 --gateway 192.168.10.1 --ssh-key "$(cat ~/.ssh/id_rsa.pub)" --unprivileged --start`. Capture returned vmid.
6. **Wait for SSH** — loop `ssh -o ConnectTimeout=3 -o BatchMode=yes -o StrictHostKeyChecking=accept-new root@192.168.10.200 echo ok` every 3s, timeout 120s.
7. **Copy artifacts** — `scp` of `setup-lxc.sh`, `Caddyfile.tmpl`, `rolly.service.tmpl`, `caddy.service`, and the assembled `.env` (built from `config.env` plus generated secrets) to `/root/` in the LXC.
8. **Run setup** — `ssh root@192.168.10.200 'bash /root/setup-lxc.sh'`. Stream stdout.
9. **Health check** — `ssh root@192.168.10.200 'curl -fsS http://localhost:8080/health'`. Then `curl -fsS https://${DUCKDNS_HOST}:8443/health` from the Mac to confirm Caddy + DNS-01 cert + FritzBox forward all work end-to-end.
10. **Print setWebhook command** — exact ready-to-paste:
    ```
    curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
      -d "url=https://${DUCKDNS_HOST}:8443/webhook" \
      -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
      -d "drop_pending_updates=true"
    ```

**Idempotency:** every step above is safe to re-run. Existing LXC reused, `git pull` on /opt/rolly (no re-clone), `xcaddy build` skipped if `/usr/local/bin/caddy` exists and matches expected version, `systemctl restart` instead of `start`.

### 4.3 In-LXC setup (`setup-lxc.sh`)

Runs as root inside the LXC. Idempotent (script checks-then-acts on every step).

1. **APT install** (idempotent via apt) — base packages: `git curl ca-certificates python3 python3-pip python3-venv unzip gettext-base` (provides `envsubst`). Then add the official Caddy repo (Cloudsmith key + `deb.list`) and `apt install caddy` — provides `/usr/bin/caddy` as a stable, prebuilt binary.
2. **Bun** — if `/root/.bun/bin/bun` missing: `curl -fsSL https://bun.sh/install | bash`. Add to PATH for the script.
3. **Code** — if `/opt/rolly` missing: `git clone https://github.com/Piwo96/homelab-assistant.git /opt/rolly`. Else `git -C /opt/rolly pull --ff-only`.
4. **Agent deps** — `cd /opt/rolly/agent && bun install`.
5. **Skill deps** (Python) — if `/opt/rolly/.venv` missing: `python3 -m venv /opt/rolly/.venv`. Then `/opt/rolly/.venv/bin/pip install -r /opt/rolly/requirements.txt` (always run; pip is idempotent).
6. **DuckDNS plugin for Caddy** — if `caddy list-modules` doesn't include `dns.providers.duckdns`: `systemctl stop caddy && caddy add-package github.com/caddy-dns/duckdns && systemctl start caddy` (or restart). The command downloads a prebuilt Caddy binary with the requested module from caddyserver.com — no Go toolchain required, ~30s on first run, skipped on re-runs.
7. **.env placement** — `mv /root/.env /opt/rolly/.env && chmod 600 /opt/rolly/.env`.
8. **Caddyfile** — `envsubst < /root/Caddyfile.tmpl > /etc/caddy/Caddyfile` (substitutes `${DUCKDNS_HOST}` and `${DUCKDNS_TOKEN}`).
9. **systemd units** — `envsubst < /root/rolly.service.tmpl > /etc/systemd/system/rolly.service`; `cp /root/caddy.service /etc/systemd/system/`.
10. **Start** — `systemctl daemon-reload`; `systemctl enable --now rolly.service caddy.service`; or `systemctl restart` if already running.
11. **Wait + smoke test** — `sleep 3 && curl -fsS http://127.0.0.1:8080/health`. Non-zero exit on failure.

## 5. Configuration Files

### 5.1 `config.env.example`

```bash
# --- Proxmox connection (also used by the skill itself, normally already in repo .env)
PROXMOX_HOST=192.168.10.140
PROXMOX_PORT=8006
PROXMOX_TOKEN_ID=root@pam!homelab
PROXMOX_TOKEN_SECRET=          # fill from your Proxmox token

# --- LXC placement
LXC_HOSTNAME=rolly
LXC_IP_CIDR=192.168.10.200/24
LXC_GATEWAY=192.168.10.1
LXC_BRIDGE=vmbr0
LXC_CORES=2
LXC_MEMORY_MB=1024
LXC_DISK_GB=10
LXC_STORAGE=local-lvm

# --- Public endpoint
DUCKDNS_HOST=sophia-und-philipp.duckdns.org
DUCKDNS_TOKEN=                  # from duckdns.org dashboard
PUBLIC_PORT=8443

# --- Telegram (rotate the token first!)
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=        # leave empty → deploy.sh generates
TELEGRAM_ALLOWED_USERS=         # comma-separated Telegram user IDs
ADMIN_TELEGRAM_ID=

# --- LM Studio (cross-subnet)
LM_STUDIO_URL=http://192.168.1.135:1234
LM_STUDIO_MODEL=gemma-4-e4b
EMBEDDING_MODEL=nomic-embed-text-v2-moe

# --- Home Assistant
HA_URL=http://homeassistant.local:8123
HA_TOKEN=

# --- Internal
INTERNAL_NOTIFY_TOKEN=          # leave empty → deploy.sh generates
PORT=8080
```

### 5.2 `Caddyfile.tmpl`

```caddy
{
    email letsencrypt@${DUCKDNS_HOST}
    # DNS-01 via DuckDNS — no port 80 required
    acme_dns duckdns ${DUCKDNS_TOKEN}
}

${DUCKDNS_HOST}:${PUBLIC_PORT} {
    reverse_proxy 127.0.0.1:${PORT}
    encode gzip
    log {
        output file /var/log/caddy/rolly.access.log
        format console
    }
}
```

### 5.3 `rolly.service.tmpl`

```ini
[Unit]
Description=Rolly Telegram Bot (Bun)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/rolly/agent
EnvironmentFile=/opt/rolly/.env
ExecStart=/root/.bun/bin/bun run src/main.ts
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

# Light hardening — LXC already isolates
NoNewPrivileges=yes
ProtectSystem=full
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

### 5.4 `caddy.service`

```ini
[Unit]
Description=Caddy reverse proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=root
ExecStart=/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/bin/caddy reload --config /etc/caddy/Caddyfile --force
Restart=on-abnormal
RestartSec=5s
LimitNOFILE=1048576
TimeoutStopSec=5s

[Install]
WantedBy=multi-user.target
```

## 6. Failure Modes & Recovery

| Scenario | Detection | Recovery |
|----------|-----------|----------|
| Proxmox API token expired | `proxmox_api.py nodes` returns 401 | User re-creates token in Proxmox UI, updates `.env` |
| LXC creation task fails (no IP, template missing) | `wait-task` returns non-OK exitstatus | `deploy.sh` aborts with the Proxmox error; no half-state because LXC is either created or not |
| SSH not coming up | 120s timeout in step 6 | Check Proxmox console, common cause: no SSH server in template; doc fixes in README |
| DNS-01 cert fails | Caddy logs `failed to obtain certificate` | Verify DUCKDNS_TOKEN with `curl https://www.duckdns.org/update?domains=${HOST}&token=${TOKEN}&txt=test` — should return `OK` |
| FritzBox forward wrong | `curl https://${DUCKDNS_HOST}:8443/health` from Mac times out | README has FritzBox screenshot section |
| Bot doesn't reply | `journalctl -u rolly -f` in LXC, check LM Studio reachable from LXC (`curl http://192.168.1.135:1234/v1/models`) | Likely subnet routing, or LM Studio not running on Gaming PC (auto-WoL is in Plan 1 code) |
| `git pull` fails (local changes in /opt/rolly) | setup-lxc.sh non-zero | Either don't edit /opt/rolly directly, or `git reset --hard` documented in README |
| Re-deploy after token rotation | new token in `config.env` → `.env` re-copied → systemctl restart picks it up automatically | None — by design |

**LXC destroy (full reset):**
```bash
proxmox_api.py delete-lxc --vmid <N> --force
./deploy.sh    # creates fresh
```

## 7. Security Notes

- **Telegram bot token rotation is a hard prerequisite** — the previous token was leaked in chat context. Without rotation, anyone holding the old token can send updates to the same bot.
- The `.env` file lives at `/opt/rolly/.env` with mode 600 (root-only). It contains: bot token, HA token, Proxmox token (also there because skills run inside this LXC), Anthropic API key (for self-annealing later), DuckDNS token.
- The LXC is **unprivileged** — kernel-level container isolation, root inside ≠ root on host.
- `TELEGRAM_WEBHOOK_SECRET` is sent as `X-Telegram-Bot-Api-Secret-Token` header by Telegram; Rolly verifies on every request. Without it, anyone who guesses the URL can forge updates.
- Caddy listens on `0.0.0.0:8443` (LXC-internal interface), so the only public attack surface is what FritzBox forwards. Telegram's IP range is well-known; if abuse appears, an `@allow` block by source IP can be added later.
- The Mac's SSH key is copied as authorized to the LXC. To rotate: edit `/root/.ssh/authorized_keys` in the LXC (via Proxmox console if SSH itself is broken).

## 8. Spec Open Questions / Follow-Ups

1. **Proxmox storage name for rootfs:** assumed `local-lvm`. If user's Proxmox uses different storage (e.g. ZFS), they override via `LXC_STORAGE` in `config.env`. The script does not auto-discover this — it'd add complexity for a one-time decision.
2. **Debian template version:** the script greps for `debian-12-standard_*_amd64.tar.zst`. If multiple match, it picks the lexicographically latest. If the user is on a newer Debian later, the script will keep working as long as the template prefix matches.
3. **Backup of `data/conversations.db`:** out of scope for this spec, but the systemd unit's `WorkingDirectory=/opt/rolly/agent` means the DB ends up in `/opt/rolly/data/` — easy target for `pct snapshot` or a future cron.
4. **Future generic skill:** if a second bot is deployed the same way, extract `infra/rolly/` patterns into a `proxmox-lxc-deploy` skill at that point — not before (YAGNI).
5. **Telegram-callable LXC creation:** because the proxmox-skill extension is real `--help-json` actions, the agent can theoretically call `proxmox.create-lxc` via Telegram once it has admin auth. We deliberately do not enable that in Plan 1's allow-list, but it becomes a no-cost capability for the future.

## 9. Rollout

1. Extend `proxmox_api.py` with `templates`, `wait-task`, `create-lxc`, `delete-lxc` and write tests for the new actions (mocked Proxmox HTTP responses).
2. Write `infra/rolly/` scaffolding (`deploy.sh`, `setup-lxc.sh`, templates, README).
3. User rotates the Telegram bot token at @BotFather.
4. User adds FritzBox port-forward and verifies DuckDNS token.
5. User fills `infra/rolly/config.env` from `.example`.
6. First deploy: `./deploy.sh`. Expected duration ~2–3 minutes (LXC create ~30s, apt+bun+venv ~90s, `caddy add-package` ~30s, rest negligible). Subsequent re-runs ~30s.
7. User runs the printed `setWebhook` curl, then `/start` in Telegram to verify end-to-end.
8. Archive any old (Polling-mode) deployment notes; this is the production entry-point.

A task-level implementation plan with checkpoints follows via the writing-plans skill after this spec is approved.
