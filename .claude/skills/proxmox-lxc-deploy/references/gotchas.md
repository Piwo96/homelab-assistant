# Gotchas — Full Debug History

Every single problem hit during the rolly first-deploy session, with symptom, root cause, and fix. Skim by symptom column; the fixes are battle-tested.

## SSH / Authentication

### G-1. `Permission denied (publickey,password)` after a successful `ssh-copy-id`

**Symptom:** `ssh-copy-id` reported "Number of key(s) added: 1", but every subsequent SSH attempt fails with "Permission denied". `ssh -v` shows `Server accepts key: id_rsa` then immediately rejects auth.

**Root cause:** `~/.ssh/id_rsa` has a passphrase. `ssh-copy-id` works because it logs in with the user's password to write `authorized_keys`. Subsequent SSH (under BatchMode=yes from `deploy.sh`) tries to USE the key for signing, hits the passphrase prompt, can't prompt in batch mode → fails.

**Fix:** Use `id_ed25519` (no passphrase) instead. In `deploy.sh`, `SSH_BASE_OPTS` forces `-o IdentitiesOnly=yes -i $SSH_PRIV` so only the explicit key is offered. Override default with `SSH_KEY_PATH=~/.ssh/id_ed25519.pub` in env, derive `SSH_PRIV=${SSH_PUB%.pub}`.

### G-2. `ssh-copy-id` prompts for `id_rsa` passphrase repeatedly

**Symptom:** Running `ssh-copy-id -i ~/.ssh/id_ed25519.pub root@host` keeps asking for the id_rsa passphrase, not the host's root password.

**Root cause:** `ssh-copy-id` first tries to log in with ALL identities to filter out keys already installed. It offers id_rsa, which is the LOCKED key, and gets stuck on the passphrase.

**Fix:** Force password auth for the copy step:
```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub \
    -o PreferredAuthentications=password \
    -o PubkeyAuthentication=no \
    root@host
```

### G-3. LXC has SSH listening on port 22 but `Permission denied` for our key

**Symptom:** `nc -zv lxc-ip 22` succeeds, but `ssh root@lxc-ip` rejects auth. The LXC was just created with `--ssh-key "$(cat id_rsa.pub)"`.

**Root cause:** Proxmox's `ssh-public-keys` form parameter on the `POST /nodes/{node}/lxc` endpoint is unreliable on some versions — the request succeeds, the LXC's config doesn't show the key, and `/root/.ssh/authorized_keys` inside the LXC is empty.

**Fix:** Inject the key out-of-band via the Proxmox host using `pct push`. See `inject_ssh_key()` in `infra/rolly/deploy.sh`:
1. SCP the public key to the Proxmox host: `scp ~/.ssh/id_ed25519.pub root@proxmox:/tmp/key.pub`
2. SSH to Proxmox host and run:
   ```
   pct exec $VMID -- mkdir -p /root/.ssh
   pct push $VMID /tmp/key.pub /root/.ssh/authorized_keys
   pct exec $VMID -- chmod 700 /root/.ssh
   pct exec $VMID -- chmod 600 /root/.ssh/authorized_keys
   ```
3. Clean up the temp file on the host.

**Prerequisite:** the Mac's pubkey must already be on the Proxmox host (one-time `ssh-copy-id` to the host itself). See G-2 for the syntax.

### G-4. Re-running `deploy.sh` after a partial failure: `wait_for_ssh` times out

**Symptom:** First deploy crashed before SSH-key injection. Second deploy finds the existing LXC by hostname, skips create + skips key inject, then SSH polling times out.

**Root cause:** `inject_ssh_key()` was guarded by `[ -z "$EXISTING_VMID" ]` — skipped for reused LXCs.

**Fix:** Always run `inject_ssh_key()`. `pct push` overwrites `authorized_keys` idempotently, so re-injecting is safe.

## Environment Files

### G-5. `bash source` fails on `.env` with `command not found: <random-string>`

**Symptom:** `deploy.sh` aborts at "Loading config" with e.g. `line 46: a8E%ENbEUVW66P#Q5cS6r: command not found`.

**Root cause:** Some `.env` value contains a space, `$`, or `#` that bash interprets as command separator / variable / comment. `set -a; source .env; set +a` is broken for non-trivial values.

**Fix:** Parse `.env` via Python and emit shell-quoted exports. See `load_env_file()` in `infra/rolly/deploy.sh`:
```bash
python3 - "$path" > "$tmp" <<'PY'
import shlex, sys
with open(sys.argv[1]) as f:
    for raw in f:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        k = k.strip()
        if not k.replace("_", "").isalnum(): continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'): v = v[1:-1]
        print(f"export {k}={shlex.quote(v)}")
PY
source "$tmp"
```

The same pattern appears in `setup-lxc.sh` (`place_env_and_render` function).

### G-6. Bun's Zod parse fails: `TELEGRAM_ALLOWED_USERS: expected comma-separated numbers`

**Symptom:** systemd shows the service `activating (auto-restart)` in a loop; `journalctl -u <app>` shows `startup_failed err: Invalid environment: TELEGRAM_ALLOWED_USERS: expected comma-separated numbers` every 5s.

**Root cause:** The `.env` line was `TELEGRAM_ALLOWED_USERS=5024544400 #5024544400,5024544400`. The `#` mid-line is NOT a comment per standard .env convention — the entire string including `#` and trailing IDs is the value, and Bun's Zod regex for csv-numbers rejects the space.

**Fix:** Either:
- Move the comment to its own line with `#` at column 0: `# 5024544400,5024544400\nTELEGRAM_ALLOWED_USERS=5024544400`
- Or simply remove the alternates.

Don't try to strip `#` in the .env parser — `#` is legitimate in passwords. The convention is "comments must start at column 0".

### G-7. Sourcing project's root `.env` blew up; agent's `.env` works fine

**Symptom:** Same as G-5 plus the root `.env` had values from an old `agent-old` setup that no longer makes sense.

**Root cause:** Two `.env` files exist — `/<repo>/.env` (legacy) and `/<repo>/agent/.env` (current, canonical). User had been working in `agent/.env` for the new TS/Bun agent.

**Fix:** `deploy.sh` should source `$REPO_ROOT/agent/.env`, not `$REPO_ROOT/.env`. Single source of truth.

## Proxmox / LXC

### G-8. `proxmox_api.py status pve <vmid>` errors with `hostname lookup 'pve' failed`

**Symptom:** API returns 500: `hostname lookup 'pve' failed - failed to get address info`.

**Root cause:** The cluster node isn't named `pve` (Proxmox default) — on this setup it's `pve-rollmann`. Hardcoding "pve" doesn't work.

**Fix:** Use the auto-detect path. Most CLI commands accept node as optional and call `get_default_node()`. For commands that need it explicit, query first: `proxmox_api.py nodes` to learn the actual name.

### G-9. `proxmox_api.py status` for an LXC fails — endpoint mismatch

**Symptom:** `lxc-config` works on a vmid that exists, `status` returns empty / parse error.

**Root cause:** `status` calls `get_vm_status` (QEMU endpoint), which 404s for LXCs.

**Fix:** Out of scope for this skill — use `lxc-config` or `containers` (filtered) for LXC info. (Long-term: add `--lxc` to status, or auto-detect.)

### G-10. `debian-12-standard` template not auto-downloaded

**Symptom:** `create-lxc` aborts with "Template ... not found".

**Root cause:** Proxmox doesn't ship templates; user pre-downloads them.

**Fix:** Before first deploy:
```bash
# SSH to Proxmox host:
pveam update && pveam download local debian-12-standard
```

`deploy.sh` checks via `proxmox_api.py templates --storage local` and fails fast with this hint.

## systemd / Process Lifecycle

### G-11. Bot exits immediately with `203/EXEC` after systemd start

**Symptom:** `systemctl status <app>` shows `Process: PID ExecStart=/root/.bun/bin/bun run src/main.ts (code=exited, status=203/EXEC)`. The binary exists and runs fine when invoked directly.

**Root cause:** `ProtectHome=yes` in the systemd unit makes `/home/*` and `/root` inaccessible to the service. Bun lives in `/root/.bun/bin/bun` → unreadable → execve fails.

**Fix:** Drop `ProtectHome=yes` from the unit. The LXC already isolates the process; per-service home protection is overkill. Keep `ProtectSystem=full`, `PrivateTmp=yes`, `NoNewPrivileges=yes`.

### G-12. systemd `PrivateTmp=yes` hides diagnostic dumps

**Symptom:** Added `writeFileSync('/tmp/llm-request.json', body)` for debugging; `/tmp/llm-request.json` doesn't exist after the service writes it.

**Root cause:** `PrivateTmp=yes` namespaces `/tmp` per-service (mounted at `/tmp/systemd-private-{random}/tmp/`).

**Fix:** Either configure the dump path explicitly to a non-tmp location (`LLM_DUMP_PATH=/var/log/llm-request.json`), or remove `PrivateTmp=yes` temporarily.

## Python / Venv

### G-13. Skill subprocess: `Executable not found in $PATH: "python"`

**Symptom:** Bot logs `skill_load_help_json_failed err: Executable not found in $PATH: "python"` for every Python skill at startup.

**Root cause:** Debian 12 only provides `python3` by default — no `python` alias. The agent's `cmd: ['python', ...]` doesn't resolve.

**Fix:** Make the binary configurable. In agent code, use `[process.env.PYTHON_BIN || 'python3', scriptPath, ...]`. In the LXC's `.env`, set `PYTHON_BIN=/opt/<app>/.venv/bin/python` so the venv's interpreter is used and venv-installed packages (`websockets`, `requests`, etc.) are available.

Alternative: `apt install python-is-python3` creates the symlink, but this still doesn't give you the venv's packages — `PYTHON_BIN` pointing into the venv is the proper fix.

### G-14. `websockets library required` even though it's in requirements.txt

**Symptom:** Skill subprocess errors with `Error: 'websockets' library required. Install with: pip install websockets`.

**Root cause:** Same as G-13. System `python3` doesn't have the venv's packages. The venv at `/opt/<app>/.venv` has `websockets` but isn't auto-activated.

**Fix:** Same as G-13: `PYTHON_BIN=/opt/<app>/.venv/bin/python`.

## Caddy / Let's Encrypt

### G-15. Caddy DNS-01: `dial tcp <auth-server-ip>:53: i/o timeout`

**Symptom:** Caddy gets stuck retrying ACME challenges. journalctl shows `checking DNS propagation of "_acme-challenge..." (resolvers=[192.168.10.1:53]): querying authoritative nameservers: dial tcp 15.223.106.16:53: i/o timeout`.

**Root cause:** Caddy's DNS-01 plugin tries to verify the TXT record by dialing the authoritative DuckDNS nameservers (AWS IPs) directly on UDP/TCP 53. FritzBox blocks outbound port 53 to arbitrary IPs (only the FB itself is allowed to do DNS).

**Fix:** Skip the self-check. The DuckDNS API already confirms the TXT record was set. In the Caddyfile:
```caddy
example.duckdns.org:8443 {
    tls {
        dns duckdns {env.DUCKDNS_TOKEN}
        propagation_timeout -1   # ← this disables the check
    }
    reverse_proxy 127.0.0.1:8080
}
```

`propagation_timeout -1` = don't self-verify; trust the provider.

### G-16. Caddy `caddy add-package` vs `xcaddy build`

**Symptom:** Initial spec called for `xcaddy build --with github.com/caddy-dns/duckdns`, which needs the Go toolchain (~400 MB disk, ~1 GB RAM spike during build).

**Fix:** Caddy 2.7+ ships `caddy add-package` which downloads a prebuilt binary with the requested module from caddyserver.com — no Go needed, ~30s, ~50 MB. Install via official APT repo:
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg.tmp
mv /usr/share/keyrings/caddy-stable-archive-keyring.gpg.tmp \
   /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -qq && apt-get install -yqq caddy
systemctl stop caddy
caddy add-package github.com/caddy-dns/duckdns
```

LXC memory budget stays at 1 GB. See `setup-lxc.sh` `install_caddy_repo` + `add_duckdns_plugin`.

### G-17. Caddy keyring write breaks idempotency

**Symptom:** `apt-get update` fails with "BADSIG" or empty keyring file after an interrupted setup-lxc.sh run.

**Root cause:** The original code only guarded the `.list` file presence. If the script aborted between writing the keyring and the `.list`, the next run skipped re-writing the (corrupted) keyring.

**Fix:** Guard on both files AND write the keyring atomically (`.tmp` + `mv`):
```bash
if [ ! -f /etc/apt/sources.list.d/caddy-stable.list ] ||
   [ ! -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor \
        > /usr/share/keyrings/caddy-stable-archive-keyring.gpg.tmp
    mv /usr/share/keyrings/caddy-stable-archive-keyring.gpg.tmp \
       /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
fi
```

## Networking / Routing

### G-18. Telegram: `Connection timed out` despite "Webhook was set" success

**Symptom:** `setWebhook` returns `{"ok":true}` (Telegram only validates URL format), but `getWebhookInfo` shows `last_error_message: Connection timed out` and `pending_update_count > 0`.

**Root cause:** A port-forward is missing or points at the wrong internal IP. The classic cases:
- Stale UniFi forward pointing at a previous-deployment's IP (e.g. 192.168.10.187 from the old agent, while new LXC is at .200)
- FritzBox Exposed Host pointing at the wrong gateway IP

**Fix sequence:**
```bash
# 1. List UniFi forwards:
python3 .claude/skills/unifi-network/scripts/network_api.py port-forwards
# 2. If the forward points at a stale IP, delete it:
python3 ... delete-port-forward <rule_id>
# 3. Create the right forward:
python3 ... create-port-forward "AppName" <port> 192.168.10.<lxc> <port> --proto tcp
# 4. Re-check Telegram:
curl "https://api.telegram.org/bot${TOKEN}/getWebhookInfo"
```

### G-19. Hairpin NAT — Mac can't curl the public hostname

**Symptom:** From the Mac inside the LAN: `curl https://example.duckdns.org:8443/health` times out. From cellular data: works. Telegram (external) also works.

**Root cause:** FritzBox doesn't reflect a connection from the inside LAN back to itself via the public IP. This is "hairpin NAT" and is off by default on FritzBox.

**Fix:** Don't waste time on this. For testing from the Mac, use `--resolve` to bypass DNS:
```bash
curl --resolve example.duckdns.org:8443:192.168.10.200 \
     https://example.duckdns.org:8443/health
```
External clients (Telegram, browsers on cellular) are unaffected.

## LLM / Routing

### G-20. `AI_APICallError: Bad Request` to LM Studio

**Symptom:** Bot logs `handle_failed err: AI_APICallError: Bad Request` immediately after `lm_studio_health: up`. Direct curl to `/v1/chat/completions` with the same model works.

**Root cause:** `LM_STUDIO_MODEL` in `.env` is a stale model name (e.g. `qwen/qwen3-4b-2507` from earlier testing). LM Studio has the model loaded but the agent's configured ID doesn't match an actual served model in the way the AI SDK constructs the request.

**Fix:** Verify the model:
```bash
curl http://lm-studio-host:1234/v1/models | python3 -m json.tool
```
Pick the right `id` from the response and set `LM_STUDIO_MODEL=<that id>` in `.env`.

### G-21. Smart-Home queries route to "smalltalk" (no tools exposed)

**Symptom:** User asks "Schalte das Licht an", bot replies "Ich kann das leider nicht direkt anmachen, da ich nur ein Chatbot bin". Router log: `routed band: low, topScore: 0.287`.

**Root cause:** Embedding similarity between short German tool-y queries and the skill's description is too low for the HIGH (≥0.75) and even MED (≥0.40) bands. Smalltalk path runs without tools.

**Fix:** Set `BYPASS_ROUTER=1` in the LXC's `.env`. This skips the embedding router and exposes the full skill catalogue directly to the LLM, which picks the tool via function-calling. Slower per turn (more tool definitions in the prompt) but substantially better recall on short queries.

## Misc

### G-22. Empty `data/conversations.db` after deploy

**Symptom:** Bot starts fine but every interaction starts with empty history.

**Root cause:** Not a bug — the DB is per-deploy. If you wiped/recreated the LXC, history is gone.

**Fix:** If you want to preserve history across redeploys, add a Proxmox snapshot or bind-mount the `data/` dir from a shared storage. Out of scope for v1 of the skill.

### G-23. Inline UniFi port-forward update isn't supported by the skill

**Symptom:** Want to change a port-forward's target IP without deleting and recreating.

**Root cause:** `unifi-network` skill exposes `create-port-forward` and `delete-port-forward` but no in-place update. The UniFi controller API does support update but the skill doesn't.

**Fix:** Delete + recreate is fine for one-off operations:
```bash
python3 ... port-forwards   # find rule_id
python3 ... delete-port-forward <rule_id>
python3 ... create-port-forward "Name" <port> <ip> <port> --proto tcp
```

(If this becomes painful, extend the unifi-network skill with `update-port-forward`.)
