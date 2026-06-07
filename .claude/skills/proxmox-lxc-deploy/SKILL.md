---
name: proxmox-lxc-deploy
description: Deploying or RE-deploying self-hosted homelab apps (e.g. the Rolly Telegram bot) to the local Proxmox host as unprivileged LXCs with Caddy + Let's Encrypt (DuckDNS DNS-01) public HTTPS. Load this BEFORE running any infra/*/deploy.sh or reading deploy/setup scripts by hand. Triggers (DE+EN, non-exhaustive) - 'deployen', 'deploy', 'redeploy', 'neu deployen', 'ausrollen', 'auf die LXC bringen / spielen', 'Rolly deployen', 'Aenderung live bringen', 'roll out a service', 'push to the homelab', 'deploy to Proxmox'. Note - the LXC pulls origin/master via git, so commit+push first; deploy.sh does NOT rsync the local tree.
version: 1.1.0
author: Philipp Rollmann
tags:
  - homelab
  - deployment
  - lxc
  - proxmox
  - caddy
  - letsencrypt
  - duckdns
  - systemd
requires:
  - python3
  - openssl
  - ssh
  - scp
  - existing proxmox skill (for create-lxc/delete-lxc/wait-task/templates)
triggers:
  - /deploy-lxc
  - proxmox deploy
  - deploy to homelab
  - lxc deployment
intent_hints:
  - "Neuen Bot/Service auf Proxmox deployen wie rolly"
  - "Eigene App mit DuckDNS + Let's Encrypt veröffentlichen"
  - "LXC anlegen mit Caddy reverse proxy"
  - "Public HTTPS endpoint via FritzBox + UniFi für homelab"
---

# Proxmox LXC Deploy

End-to-end pattern for deploying a self-hosted app on the local Proxmox host with a public HTTPS endpoint. The canonical working example is `infra/rolly/` — this skill captures the patterns and gotchas so a future deploy doesn't repeat the same debugging.

## Architecture

```
Telegram / Internet
    │  HTTPS (configurable port, 8443 for rolly)
    ▼
sophia-und-philipp.duckdns.org  ← DuckDNS hostname
    │  resolves to FritzBox public IPv4 (DuckDNS auto-update from FB)
    ▼
FritzBox 192.168.178.1
    │  Exposed Host → 192.168.178.20 (UniFi gateway)
    ▼
UniFi Gateway 192.168.178.20  ← MUST have its own port-forward rule
    │  TCP <port> → 192.168.10.X:<port>
    ▼
LXC on Proxmox 192.168.10.140
    │  static IP, e.g. 192.168.10.200
    ├── Caddy (caddy add-package github.com/caddy-dns/duckdns)
    │     • listens :<public_port>
    │     • LE cert via DNS-01 (no port 80 needed)
    │     • reverse_proxy → 127.0.0.1:<internal_port>
    ├── systemd unit (your app, Type=simple)
    │     • EnvironmentFile=/opt/<app>/.env
    │     • Restart=on-failure
    └── /opt/<app> = git checkout of the public repo
```

**Why this stack:**

- **LXC, not VM** — single Bun/Python/Node process + venv. Boots in seconds, idle ~200 MB. No VM kernel overhead.
- **Caddy + DuckDNS DNS-01** — no inbound port 80 needed, auto-renew built-in, one `caddy add-package` step instead of `xcaddy build` (no Go toolchain).
- **systemd** — OS-native restart-on-failure, journalctl logs, no pm2/forever dep.

## Prerequisites (one-time, per Mac)

These MUST be done before `./deploy.sh` can succeed:

1. **Proxmox API token** in the project's `.env` (or `agent/.env`):
   ```
   PROXMOX_HOST=192.168.10.140
   PROXMOX_PORT=8006
   PROXMOX_TOKEN_ID=root@pam!homelab
   PROXMOX_TOKEN_SECRET=<uuid>
   PROXMOX_VERIFY_SSL=false
   ```
   Token created in Proxmox UI → Datacenter → Permissions → API Tokens (uncheck "Privilege Separation").

2. **SSH key without passphrase, copied to Proxmox host**. The `id_rsa` key likely has a passphrase, which BatchMode SSH refuses. Use ed25519 instead:
   ```bash
   # If you don't have one:
   ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
   # Copy to Proxmox host (use password auth — id_rsa might also be locked):
   ssh-copy-id -i ~/.ssh/id_ed25519.pub \
       -o PreferredAuthentications=password \
       -o PubkeyAuthentication=no \
       root@192.168.10.140
   ```

3. **Debian 12 template available on Proxmox `local` storage**:
   ```bash
   # SSH to Proxmox host:
   pveam update && pveam download local debian-12-standard
   # Or via Proxmox UI → local → CT Templates.
   ```

4. **UniFi gateway credentials** in `.env` so we can manage the port-forward via API:
   ```
   UNIFI_HOST=...
   UNIFI_USERNAME=...
   UNIFI_PASSWORD=...
   UNIFI_API_KEY=...
   UNIFI_VERIFY_SSL=false
   ```
   The `unifi-network` skill is then used to create the forward (see deploy flow step 4).

5. **DuckDNS** subdomain exists and the FritzBox is configured to update it. Get the token from <https://www.duckdns.org/>.

6. **FritzBox Exposed Host** set to the UniFi gateway's WAN-side IP (e.g. 192.168.178.20). Verify in FB UI → Internet → Freigaben → Portfreigaben. **No per-port forwards needed on the FritzBox** — Exposed Host punts everything to UniFi.

## The Deploy Flow (rolly example)

The canonical example is `infra/rolly/`. The flow:

```
deploy.sh (Mac)
  1. Load env files (agent/.env via python parser — bash source breaks on passwords with spaces/#)
  2. Validate required vars
  3. proxmox_api.py nodes — verify API reachable
  4. proxmox_api.py containers — find existing LXC by hostname; if found, reuse
  5. proxmox_api.py templates — verify debian-12-standard available
  6. proxmox_api.py create-lxc (auto vmid via /cluster/nextid)
  7. SSH to Proxmox host → pct push the Mac's SSH pubkey into the LXC
     (Proxmox's API ssh-public-keys param is unreliable; pct push is)
  8. Poll for SSH on the LXC's static IP
  9. Assemble .env (project env + deploy-only adds: DUCKDNS_*, PORT, secrets)
 10. scp setup-lxc.sh + .env + Caddyfile.tmpl + service-templates → LXC:/root/
 11. ssh root@LXC 'bash /root/setup-lxc.sh' (the long step, ~2-3 min)
 12. Internal /health probe + public HTTPS /health probe (DNS-01 cert may take 30-90s)
 13. Print the setWebhook curl (or equivalent app activation step)
```

`setup-lxc.sh` (in-LXC, idempotent — every step check-then-act):
```
 1. apt-get install: base packages (no Go, no compiler) + official Caddy from Cloudsmith repo
 2. Install Bun via the upstream curl|bash (one-liner, lives in /root/.bun)
 3. git clone (or git pull) the public repo to /opt/<app>
 4. bun install in agent/
 5. python3 -m venv + pip install -r requirements.txt (for Python skills)
 6. caddy add-package github.com/caddy-dns/duckdns (no xcaddy, no Go)
 7. install -m 600 .env → /opt/<app>/.env
 8. python parses .env, exports vars, envsubst renders Caddyfile + systemd units
 9. systemctl daemon-reload + enable --now <app> caddy
10. Smoke test: curl localhost:<port>/health (5 retries × 2s)
```

## Adapting the rolly Template for a New App

1. **Pick an app name** (kebab-case, used as hostname + systemd unit + repo path): e.g. `myapp`.
2. **Pick a static IP** in the 192.168.10.0/24 range not yet used. Check via `proxmox_api.py containers`.
3. **Copy the template directory:**
   ```bash
   cp -r infra/rolly infra/myapp
   ```
4. **Edit `infra/myapp/config.env.example`:**
   - `LXC_HOSTNAME=myapp`
   - `LXC_IP_CIDR=192.168.10.X/24`
   - `DUCKDNS_HOST=myapp-pr.duckdns.org` (or reuse existing with different port)
   - `PUBLIC_PORT=<port>` (8443, 8444, etc.; must be Telegram-compatible if a bot)
   - `PORT=<internal_port>` Caddy reverse_proxy target
5. **Edit `infra/myapp/rolly.service.tmpl`:**
   - Rename file to `myapp.service.tmpl`
   - Update `Description=`
   - Update `WorkingDirectory=/opt/myapp/agent` (or wherever your entry point lives)
   - Update `ExecStart=` to your runtime + entry point
6. **Edit `infra/myapp/setup-lxc.sh`:**
   - Update `REPO_DIR="/opt/myapp"`
   - Update `REPO_URL=` if different
   - Update the rendered service name in steps 8-10
7. **Edit `infra/myapp/deploy.sh`:**
   - Update `AGENT_ENV` path if env lives elsewhere
   - Update the artifacts SCP list to match your service template filename
   - Update the print_webhook_command (or equivalent activation hint)
8. **Add UniFi port-forward via the unifi-network skill:**
   ```bash
   python3 .claude/skills/unifi-network/scripts/network_api.py \
     create-port-forward "MyApp" <port> 192.168.10.X <port> --proto tcp
   ```
9. **Run `./deploy.sh`** from the Mac.

## Common Gotchas

The skill's references file [references/gotchas.md](references/gotchas.md) has the full debug history. Quick TL;DR:

| Symptom | Root Cause | Fix |
|---|---|---|
| `ssh: Permission denied (publickey,password)` after ssh-copy-id | id_rsa has a passphrase; BatchMode SSH refuses to prompt | Use `id_ed25519`, force `-o IdentitiesOnly=yes -i id_ed25519` |
| `ssh-copy-id: Enter passphrase for id_rsa` | ssh-copy-id offers ALL keys to test, including the locked id_rsa | Force `-o PreferredAuthentications=password -o PubkeyAuthentication=no` |
| API call to `create-lxc` succeeds but `authorized_keys` is empty | Proxmox's `ssh-public-keys` form param is flaky on some versions | Use `pct push` via SSH to Proxmox host (deploy.sh `inject_ssh_key` step) |
| systemd `203/EXEC` for the bot | `ProtectHome=yes` blocks `/root/.bun/bin/bun` | Drop `ProtectHome=yes` from the unit (LXC already isolates) |
| `python: command not found` running a skill | Debian only has `python3`, no `python` | Set `PYTHON_BIN=/opt/<app>/.venv/bin/python` in `.env` |
| `Invalid environment: TELEGRAM_ALLOWED_USERS: expected comma-separated numbers` | Inline `#` comment in the `.env` value (`123 #456,789` parses as one string) | Move comments to their own line with `#` at column 0 |
| `.env: line N: <random-token>: command not found` | bash `source` breaks on values containing spaces, `#`, `$`, etc. | Use python parser (see `load_env_file` in deploy.sh and place_env_and_render in setup-lxc.sh) |
| Caddy: `i/o timeout` to auth nameserver during DNS-01 | FritzBox blocks outbound port 53 to arbitrary IPs | Set `propagation_timeout -1` in the tls block (the DuckDNS API already confirms the TXT record) |
| `Connection timed out` from Telegram to public IP | The UniFi port-forward is missing OR points at a stale internal IP | List with `network_api.py port-forwards`, delete+recreate via the unifi-network skill |
| Mac curl to public IP fails but Telegram reaches it | FritzBox hairpin NAT — public IP from inside the LAN doesn't loop back | Test from cellular instead; doesn't affect external-facing services |
| Bot loads but skills fail at `--help-json` | Python skill subprocess uses system python, not venv → packages missing | Same as `PYTHON_BIN=/opt/<app>/.venv/bin/python` fix |
| Embedding router picks "smalltalk" for skill-y queries | Embedding similarity too low for short German queries | `BYPASS_ROUTER=1` exposes the full skill catalogue to the LLM directly |
| LM Studio returns 400 to LLM call but `/v1/models` lists model | The `LM_STUDIO_MODEL` in `.env` doesn't match an actually-loaded model (e.g. stale `qwen` from earlier testing) | Verify the value matches one of `curl http://lm-studio:1234/v1/models` IDs |

## Files Pulled From This Skill

| File | Role |
|---|---|
| [SKILL.md](SKILL.md) | This document — entry point |
| [references/network-topology.md](references/network-topology.md) | The FritzBox 178.x ↔ UniFi VLAN 10.x story + why traffic flows through both |
| [references/gotchas.md](references/gotchas.md) | Full debug history with logs and exact fixes |

## Working Example

`infra/rolly/` in this repo is the live, working reference. Every file in this skill mirrors a real file there:

| Skill concept | rolly file |
|---|---|
| Mac orchestrator | `infra/rolly/deploy.sh` |
| In-LXC installer | `infra/rolly/setup-lxc.sh` |
| Caddy template | `infra/rolly/Caddyfile.tmpl` |
| systemd unit | `infra/rolly/rolly.service.tmpl` + `caddy.service` |
| User-facing config | `infra/rolly/config.env.example` |
| Manual prerequisites | `infra/rolly/README.md` |

Refer to those files for the canonical, syntax-verified versions of every artifact described above.
