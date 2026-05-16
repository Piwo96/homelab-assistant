#!/usr/bin/env bash
# Runs inside the LXC. Idempotent: every step is check-then-act.
# Expected files in /root before invocation:
#   .env, Caddyfile.tmpl, rolly.service.tmpl, caddy.service

set -euo pipefail

log() { printf "\n\033[1;34m▶ %s\033[0m\n" "$1"; }
ok()  { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }

REPO_URL="https://github.com/Piwo96/homelab-assistant.git"
REPO_DIR="/opt/rolly"

require_files() {
    for f in /root/.env /root/Caddyfile.tmpl /root/rolly.service.tmpl /root/caddy.service; do
        [ -f "$f" ] || { echo "Missing required file: $f" >&2; exit 1; }
    done
}

apt_install() {
    log "Installing base packages"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -yqq git curl ca-certificates python3 python3-pip \
                         python3-venv unzip gettext-base debian-keyring \
                         debian-archive-keyring apt-transport-https
    ok "base packages installed"
}

install_caddy_repo() {
    log "Configuring Caddy APT repo"
    if [ ! -f /etc/apt/sources.list.d/caddy-stable.list ]; then
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
            > /etc/apt/sources.list.d/caddy-stable.list
        apt-get update -qq
    fi
    apt-get install -yqq caddy
    ok "caddy installed: $(caddy version | head -1)"
}

install_bun() {
    log "Installing Bun"
    if [ ! -x /root/.bun/bin/bun ]; then
        curl -fsSL https://bun.sh/install | bash
    fi
    export PATH="/root/.bun/bin:$PATH"
    ok "bun: $(bun --version)"
}

clone_or_pull() {
    log "Syncing code at $REPO_DIR"
    if [ ! -d "$REPO_DIR/.git" ]; then
        git clone "$REPO_URL" "$REPO_DIR"
    else
        git -C "$REPO_DIR" pull --ff-only
    fi
    ok "repo at: $(git -C $REPO_DIR rev-parse --short HEAD)"
}

install_agent_deps() {
    log "Installing agent (Bun) deps"
    cd "$REPO_DIR/agent"
    /root/.bun/bin/bun install
    ok "agent deps installed"
}

install_skill_deps() {
    log "Installing Python skill deps"
    if [ ! -d "$REPO_DIR/.venv" ]; then
        python3 -m venv "$REPO_DIR/.venv"
    fi
    "$REPO_DIR/.venv/bin/pip" install -q --upgrade pip
    "$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"
    ok "python deps installed"
}

add_duckdns_plugin() {
    log "Ensuring caddy has caddy-dns/duckdns module"
    if ! caddy list-modules 2>/dev/null | grep -q "dns.providers.duckdns"; then
        systemctl stop caddy 2>/dev/null || true
        caddy add-package github.com/caddy-dns/duckdns
    fi
    ok "duckdns module present"
}

place_env_and_render() {
    log "Placing .env and rendering templates"
    install -m 600 /root/.env "$REPO_DIR/.env"
    chown root:root "$REPO_DIR/.env"
    # Render Caddyfile + rolly.service via envsubst (read vars from .env)
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
    mkdir -p /etc/caddy /var/log/caddy
    envsubst < /root/Caddyfile.tmpl > /etc/caddy/Caddyfile
    envsubst < /root/rolly.service.tmpl > /etc/systemd/system/rolly.service
    cp /root/caddy.service /etc/systemd/system/caddy.service
    ok "rendered /etc/caddy/Caddyfile + systemd units"
}

start_services() {
    log "Starting/restarting services"
    systemctl daemon-reload
    systemctl enable rolly.service caddy.service >/dev/null
    systemctl restart caddy.service
    systemctl restart rolly.service
    ok "services started"
}

smoke_test() {
    log "Smoke test: GET http://localhost:8080/health"
    for i in 1 2 3 4 5; do
        if curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null; then
            ok "rolly /health OK"
            return 0
        fi
        sleep 2
    done
    echo "Rolly /health did not respond. Check: journalctl -u rolly --no-pager -n 50" >&2
    exit 1
}

main() {
    require_files
    apt_install
    install_caddy_repo
    install_bun
    clone_or_pull
    install_agent_deps
    install_skill_deps
    add_duckdns_plugin
    place_env_and_render
    start_services
    smoke_test
    log "Setup complete"
}

main "$@"
