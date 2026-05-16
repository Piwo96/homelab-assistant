#!/usr/bin/env bash
# Rolly deployment orchestrator — runs on the Mac.
# Idempotent: re-runs reuse the existing LXC and just re-sync code + restart.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
PROXMOX_API="$REPO_ROOT/.claude/skills/proxmox/scripts/proxmox_api.py"

# SSH identity: defaults to id_ed25519 (passphraseless or agent-loaded).
# Override via SSH_KEY_PATH env var to point at a different public key
# (private key path is derived by stripping .pub).
SSH_PUB="${SSH_KEY_PATH:-$HOME/.ssh/id_ed25519.pub}"
SSH_PRIV="${SSH_PUB%.pub}"
SSH_BASE_OPTS=(-o StrictHostKeyChecking=accept-new
               -o UserKnownHostsFile=/dev/null
               -o BatchMode=yes -o ConnectTimeout=5
               -o IdentitiesOnly=yes -i "$SSH_PRIV")

log()  { printf "\n\033[1;34m▶ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
fail() { printf "  \033[1;31m✗\033[0m %s\n" "$1" >&2; exit 1; }

# Safely load a KEY=VALUE .env file into the current shell.
# Uses python to handle values with spaces, quotes, $, #, etc. that would
# break `source file` semantics.
load_env_file() {
    local path="$1"
    [ -f "$path" ] || return 1
    local tmp
    tmp=$(mktemp)
    python3 - "$path" > "$tmp" <<'PY'
import shlex, sys
with open(sys.argv[1]) as f:
    for raw in f:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if not k.replace("_", "").isalnum():
            continue
        v = v.strip()
        # Strip matching outer quotes if present
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        print(f"export {k}={shlex.quote(v)}")
PY
    # shellcheck disable=SC1090
    source "$tmp"
    rm -f "$tmp"
}

# --- 1. Load + validate config ---
load_config() {
    log "Loading config"
    # Step A: load the project's root .env (skill creds — HOMEASSISTANT_*,
    # PIHOLE_*, PROTECT_*, UNIFI_*, PROXMOX_*, TELEGRAM_*, LM_STUDIO_*, etc.)
    [ -f "$REPO_ROOT/.env" ] || fail "Missing $REPO_ROOT/.env (skill credentials)"
    load_env_file "$REPO_ROOT/.env"
    ok "Loaded $REPO_ROOT/.env"

    # Step B: load infra/rolly/config.env (deploy-specific settings)
    [ -f "$SCRIPT_DIR/config.env" ] || fail "Missing $SCRIPT_DIR/config.env (copy from config.env.example)"
    load_env_file "$SCRIPT_DIR/config.env"

    local required=(PROXMOX_HOST PROXMOX_TOKEN_ID PROXMOX_TOKEN_SECRET
                    LXC_HOSTNAME LXC_IP_CIDR LXC_GATEWAY LXC_BRIDGE
                    LXC_CORES LXC_MEMORY_MB LXC_DISK_GB LXC_STORAGE LXC_TEMPLATE_PREFIX
                    DUCKDNS_HOST DUCKDNS_TOKEN PUBLIC_PORT
                    TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS ADMIN_TELEGRAM_ID
                    LM_STUDIO_URL LM_STUDIO_MODEL)
    for v in "${required[@]}"; do
        [ -n "${!v:-}" ] || fail "Missing required variable: $v"
    done

    # Generate missing secrets if absent from either env file
    if [ -z "${TELEGRAM_WEBHOOK_SECRET:-}" ]; then
        TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 32)
        ok "Generated TELEGRAM_WEBHOOK_SECRET"
    fi
    if [ -z "${INTERNAL_NOTIFY_TOKEN:-}" ]; then
        INTERNAL_NOTIFY_TOKEN=$(openssl rand -hex 32)
        ok "Generated INTERNAL_NOTIFY_TOKEN"
    fi
    PORT="${PORT:-8080}"

    LXC_IP="${LXC_IP_CIDR%%/*}"  # strip CIDR for SSH target
    ok "Config validated. Target IP: $LXC_IP"
}

# --- 2. Verify proxmox skill reachable ---
verify_proxmox() {
    log "Verifying Proxmox API reachable"
    python3 "$PROXMOX_API" --json nodes >/dev/null || fail "proxmox_api.py nodes failed"
    ok "Proxmox API OK"
}

# --- 3. Check for existing LXC by hostname ---
find_existing_lxc() {
    log "Checking for existing LXC named '$LXC_HOSTNAME'"
    local found
    found=$(python3 "$PROXMOX_API" --json containers \
            | python3 -c "import sys,json; data=json.load(sys.stdin); \
                          m=[c for c in data if c.get('name')=='$LXC_HOSTNAME']; \
                          print(m[0]['vmid'] if m else '')")
    if [ -n "$found" ]; then
        EXISTING_VMID="$found"
        ok "Found existing LXC '$LXC_HOSTNAME' vmid=$found — will reuse"
    else
        EXISTING_VMID=""
        ok "No existing LXC found — will create"
    fi
}

# --- 4. Verify template available ---
verify_template() {
    log "Checking for template matching '$LXC_TEMPLATE_PREFIX'"
    LXC_TEMPLATE_VOLID=$(python3 "$PROXMOX_API" --json templates --storage local \
        | python3 -c "import sys,json; data=json.load(sys.stdin); \
            m=sorted([t['volid'] for t in data if '$LXC_TEMPLATE_PREFIX' in t['volid']]); \
            print(m[-1] if m else '')")
    if [ -z "$LXC_TEMPLATE_VOLID" ]; then
        fail "Template '$LXC_TEMPLATE_PREFIX' not found. SSH to Proxmox and run: pveam download local debian-12-standard"
    fi
    ok "Template: $LXC_TEMPLATE_VOLID"
}

# --- 5. Create LXC (if needed) ---
create_lxc_if_needed() {
    if [ -n "$EXISTING_VMID" ]; then
        VMID="$EXISTING_VMID"
        return
    fi
    log "Creating LXC '$LXC_HOSTNAME'"
    # Key injection happens out-of-band via inject_ssh_key (Proxmox API's
    # ssh-public-keys param is unreliable for some setups).
    local result
    result=$(python3 "$PROXMOX_API" --json create-lxc \
        --hostname "$LXC_HOSTNAME" \
        --template "$LXC_TEMPLATE_VOLID" \
        --cores "$LXC_CORES" --memory "$LXC_MEMORY_MB" --disk "$LXC_DISK_GB" \
        --storage "$LXC_STORAGE" --bridge "$LXC_BRIDGE" \
        --ip "$LXC_IP_CIDR" --gateway "$LXC_GATEWAY" \
        --nameserver "$LXC_GATEWAY")
    VMID=$(echo "$result" | python3 -c "import sys,json;print(json.load(sys.stdin)['vmid'])")
    ok "Created LXC vmid=$VMID"
}

# --- 5b. Inject Mac's SSH key into the LXC via Proxmox host ---
inject_ssh_key() {
    log "Installing SSH key in LXC via Proxmox host (pct push)"
    [ -f "$SSH_PUB" ] || fail "SSH key not found: $SSH_PUB"
    [ -f "$SSH_PRIV" ] || fail "SSH private key not found: $SSH_PRIV"

    # Verify Proxmox-host SSH works (prerequisite: ssh-copy-id root@$PROXMOX_HOST done once)
    ssh "${SSH_BASE_OPTS[@]}" "root@$PROXMOX_HOST" "echo ok" >/dev/null \
        || fail "Cannot SSH to Proxmox host root@$PROXMOX_HOST with key $SSH_PRIV. Run once: ssh-copy-id -i $SSH_PUB root@$PROXMOX_HOST"

    # Wait briefly for the LXC to finish booting before pct exec works
    sleep 5

    # SCP key to Proxmox host, then pct push into LXC
    scp "${SSH_BASE_OPTS[@]}" "$SSH_PUB" "root@$PROXMOX_HOST:/tmp/rolly_authkey.pub" >/dev/null \
        || fail "scp to Proxmox host failed"
    ssh "${SSH_BASE_OPTS[@]}" "root@$PROXMOX_HOST" "
        set -e
        pct exec $VMID -- mkdir -p /root/.ssh
        pct push $VMID /tmp/rolly_authkey.pub /root/.ssh/authorized_keys
        pct exec $VMID -- chmod 700 /root/.ssh
        pct exec $VMID -- chmod 600 /root/.ssh/authorized_keys
        rm -f /tmp/rolly_authkey.pub
    " >/dev/null || fail "pct push of SSH key failed"
    ok "SSH key installed in LXC $VMID"
}

# --- 6. Wait for SSH ---
wait_for_ssh() {
    log "Waiting for SSH on $LXC_IP"
    for i in $(seq 1 40); do  # 40 × 3s = 2 min
        if ssh "${SSH_BASE_OPTS[@]}" "root@$LXC_IP" "echo ok" >/dev/null 2>&1; then
            ok "SSH up after ${i} attempts"
            return
        fi
        sleep 3
    done
    fail "SSH did not come up within 2 min"
}

# --- 7. Assemble .env and SCP artifacts ---
upload_artifacts() {
    log "Uploading artifacts to LXC"
    local tmpdir
    tmpdir=$(mktemp -d)
    trap 'rm -rf "$tmpdir"' EXIT
    # The LXC's .env = the project's root .env (skill creds in their native names:
    # HOMEASSISTANT_*, PIHOLE_*, PROTECT_*, UNIFI_*, PROXMOX_*, LM_STUDIO_*,
    # TELEGRAM_*) plus the deploy-specific additions below.
    install -m 600 /dev/null "$tmpdir/.env"
    cp "$REPO_ROOT/.env" "$tmpdir/.env"
    chmod 600 "$tmpdir/.env"
    cat >> "$tmpdir/.env" <<EOF

# --- Added by infra/rolly/deploy.sh ---
TELEGRAM_WEBHOOK_SECRET=$TELEGRAM_WEBHOOK_SECRET
INTERNAL_NOTIFY_TOKEN=$INTERNAL_NOTIFY_TOKEN
PORT=$PORT
PUBLIC_PORT=$PUBLIC_PORT
DUCKDNS_HOST=$DUCKDNS_HOST
DUCKDNS_TOKEN=$DUCKDNS_TOKEN
PYTHON_BIN=/opt/rolly/.venv/bin/python
EOF

    scp "${SSH_BASE_OPTS[@]}" \
        "$tmpdir/.env" \
        "$SCRIPT_DIR/setup-lxc.sh" \
        "$SCRIPT_DIR/Caddyfile.tmpl" \
        "$SCRIPT_DIR/rolly.service.tmpl" \
        "$SCRIPT_DIR/caddy.service" \
        "root@$LXC_IP:/root/"
    rm -rf "$tmpdir"
    trap - EXIT
    ok "Artifacts uploaded"
}

# --- 8. Run setup in LXC ---
run_setup() {
    log "Running setup-lxc.sh inside LXC (this is the long step)"
    ssh "${SSH_BASE_OPTS[@]}" "root@$LXC_IP" "bash /root/setup-lxc.sh"
    ok "Setup completed inside LXC"
}

# --- 9. End-to-end health checks ---
health_checks() {
    log "End-to-end health checks"
    ssh "${SSH_BASE_OPTS[@]}" "root@$LXC_IP" "curl -fsS http://127.0.0.1:${PORT}/health" >/dev/null \
        || fail "Internal /health failed"
    ok "Internal /health OK"

    log "Waiting for Caddy to obtain the LE cert (DNS-01 can take ~30-90s on first run)..."
    for i in $(seq 1 30); do
        if curl -fsS --max-time 5 "https://${DUCKDNS_HOST}:${PUBLIC_PORT}/health" >/dev/null 2>&1; then
            ok "Public https://${DUCKDNS_HOST}:${PUBLIC_PORT}/health OK"
            return
        fi
        sleep 4
    done
    fail "Public endpoint never came up. SSH to LXC and check: journalctl -u caddy -n 50"
}

# --- 10. Print setWebhook command ---
print_webhook_command() {
    log "Set the Telegram webhook by running:"
    cat <<EOF

  curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \\
       -d "url=https://${DUCKDNS_HOST}:${PUBLIC_PORT}/webhook" \\
       -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \\
       -d "drop_pending_updates=true"

EOF
    ok "Done. Send /start to your bot to verify end-to-end."
}

main() {
    load_config
    verify_proxmox
    find_existing_lxc
    [ -z "$EXISTING_VMID" ] && verify_template
    create_lxc_if_needed
    # Always inject the key — idempotent and protects against re-deploys where
    # the LXC was created previously but the key isn't (yet) in authorized_keys.
    inject_ssh_key
    wait_for_ssh
    upload_artifacts
    run_setup
    health_checks
    print_webhook_command
}

main "$@"
