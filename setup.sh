#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Homelab Assistant - Setup Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./setup.sh              # Full setup (dependencies + env check)
#   ./setup.sh --deps       # Install dependencies only
#   ./setup.sh --env        # Check/create .env only
#   ./setup.sh --test       # Test all skill connections
#
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_step() {
    echo -e "${YELLOW}▸${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# ─────────────────────────────────────────────────────────────────────────────
# Install Dependencies
# ─────────────────────────────────────────────────────────────────────────────

install_dependencies() {
    print_header "Installing Python Dependencies"

    # Check Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 not found. Please install Python 3.9+"
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    print_success "Python $PYTHON_VERSION found"

    # Check pip
    if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
        print_error "pip not found. Please install pip"
        exit 1
    fi

    # Install requirements
    print_step "Installing packages from requirements.txt..."
    if python3 -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet; then
        print_success "All dependencies installed"
    else
        print_error "Failed to install dependencies"
        exit 1
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Setup Environment
# ─────────────────────────────────────────────────────────────────────────────

setup_env() {
    print_header "Environment Configuration"

    # Create .env.example if not exists
    if [ ! -f "$ENV_EXAMPLE" ]; then
        print_step "Creating .env.example template..."
        cat > "$ENV_EXAMPLE" << 'EOF'
# ═══════════════════════════════════════════════════════════════════════════════
# Homelab Assistant - Environment Configuration
# ═══════════════════════════════════════════════════════════════════════════════
# Copy this file to .env and fill in your values:
#   cp .env.example .env
# ═══════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# Proxmox VE
# ─────────────────────────────────────────────────────────────────────────────
PROXMOX_HOST=192.168.10.140
PROXMOX_PORT=8006
PROXMOX_TOKEN_ID=root@pam!homelab
PROXMOX_TOKEN_SECRET=your-token-uuid-here
PROXMOX_VERIFY_SSL=false

# ─────────────────────────────────────────────────────────────────────────────
# Pi-hole
# ─────────────────────────────────────────────────────────────────────────────
PIHOLE_HOST=192.168.10.102
PIHOLE_PORT=80
PIHOLE_PASSWORD=your-pihole-password

# ─────────────────────────────────────────────────────────────────────────────
# UniFi Network (also used by UniFi Protect)
# ─────────────────────────────────────────────────────────────────────────────
UNIFI_HOST=192.168.1.1
UNIFI_PORT=443
UNIFI_USERNAME=admin
UNIFI_PASSWORD=your-unifi-password
UNIFI_SITE=default
UNIFI_VERIFY_SSL=false

# ─────────────────────────────────────────────────────────────────────────────
# Home Assistant
# ─────────────────────────────────────────────────────────────────────────────
HOMEASSISTANT_HOST=homeassistant.local
HOMEASSISTANT_PORT=8123
HOMEASSISTANT_TOKEN=your-long-lived-access-token
HOMEASSISTANT_SSL=false
HOMEASSISTANT_VERIFY_SSL=true
EOF
        print_success "Created .env.example"
    fi

    # Check if .env exists
    if [ ! -f "$ENV_FILE" ]; then
        print_info ".env file not found"
        echo ""
        read -p "Create .env from template? [Y/n] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            print_success "Created .env from template"
            print_info "Edit .env with your credentials: nano $ENV_FILE"
        fi
    else
        print_success ".env file exists"

        # Check for required variables
        missing=()

        # Check each service
        if ! grep -q "PROXMOX_TOKEN_SECRET=." "$ENV_FILE" 2>/dev/null || grep -q "PROXMOX_TOKEN_SECRET=your-" "$ENV_FILE" 2>/dev/null; then
            missing+=("PROXMOX_TOKEN_SECRET")
        fi
        if ! grep -q "PIHOLE_PASSWORD=." "$ENV_FILE" 2>/dev/null || grep -q "PIHOLE_PASSWORD=your-" "$ENV_FILE" 2>/dev/null; then
            missing+=("PIHOLE_PASSWORD")
        fi
        if ! grep -q "UNIFI_PASSWORD=." "$ENV_FILE" 2>/dev/null || grep -q "UNIFI_PASSWORD=your-" "$ENV_FILE" 2>/dev/null; then
            missing+=("UNIFI_PASSWORD")
        fi
        if ! grep -q "HOMEASSISTANT_TOKEN=." "$ENV_FILE" 2>/dev/null || grep -q "HOMEASSISTANT_TOKEN=your-" "$ENV_FILE" 2>/dev/null; then
            missing+=("HOMEASSISTANT_TOKEN")
        fi

        if [ ${#missing[@]} -gt 0 ]; then
            print_info "Some credentials may need to be configured:"
            for var in "${missing[@]}"; do
                echo "       - $var"
            done
        fi
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Test Connections
# ─────────────────────────────────────────────────────────────────────────────

test_connections() {
    print_header "Testing Skill Connections"

    SKILLS_DIR="$SCRIPT_DIR/.claude/skills"

    # Test Proxmox
    print_step "Testing Proxmox..."
    if python3 "$SKILLS_DIR/proxmox/scripts/proxmox_api.py" nodes > /dev/null 2>&1; then
        print_success "Proxmox: Connected"
    else
        print_error "Proxmox: Failed (check PROXMOX_* in .env)"
    fi

    # Test Pi-hole
    print_step "Testing Pi-hole..."
    if python3 "$SKILLS_DIR/pihole/scripts/pihole_api.py" status > /dev/null 2>&1; then
        print_success "Pi-hole: Connected"
    else
        print_error "Pi-hole: Failed (check PIHOLE_* in .env)"
    fi

    # Test UniFi Network
    print_step "Testing UniFi Network..."
    if python3 "$SKILLS_DIR/unifi-network/scripts/network_api.py" health > /dev/null 2>&1; then
        print_success "UniFi Network: Connected"
    else
        print_error "UniFi Network: Failed (check UNIFI_* in .env)"
    fi

    # Test UniFi Protect
    print_step "Testing UniFi Protect..."
    if python3 "$SKILLS_DIR/unifi-protect/scripts/protect_api.py" cameras > /dev/null 2>&1; then
        print_success "UniFi Protect: Connected"
    else
        print_error "UniFi Protect: Failed (uses UNIFI_* credentials)"
    fi

    # Test Home Assistant
    print_step "Testing Home Assistant..."
    if python3 "$SKILLS_DIR/homeassistant/scripts/homeassistant_api.py" status > /dev/null 2>&1; then
        print_success "Home Assistant: Connected"
    else
        print_error "Home Assistant: Failed (check HOMEASSISTANT_* in .env)"
    fi

    echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# Print Usage
# ─────────────────────────────────────────────────────────────────────────────

print_usage() {
    print_header "Homelab Assistant - Quick Reference"

    echo "Available Skills:"
    echo ""
    echo "  /proxmox        - Manage VMs, containers, storage"
    echo "  /pihole         - DNS & ad-blocking management"
    echo "  /unifi-network  - Network devices & clients"
    echo "  /unifi-protect  - Cameras & NVR"
    echo "  /homeassistant  - Smart home automation"
    echo ""
    echo "Direct CLI Usage:"
    echo ""
    echo "  # Proxmox"
    echo "  python .claude/skills/proxmox/scripts/proxmox_api.py nodes"
    echo "  python .claude/skills/proxmox/scripts/proxmox_api.py containers pve-rollmann"
    echo ""
    echo "  # Pi-hole"
    echo "  python .claude/skills/pihole/scripts/pihole_api.py summary"
    echo "  python .claude/skills/pihole/scripts/pihole_api.py block example.com"
    echo ""
    echo "  # UniFi Network"
    echo "  python .claude/skills/unifi-network/scripts/network_api.py health"
    echo "  python .claude/skills/unifi-network/scripts/network_api.py clients"
    echo ""
    echo "  # UniFi Protect"
    echo "  python .claude/skills/unifi-protect/scripts/protect_api.py cameras"
    echo "  python .claude/skills/unifi-protect/scripts/protect_api.py events --last 24h"
    echo ""
    echo "  # Home Assistant"
    echo "  python .claude/skills/homeassistant/scripts/homeassistant_api.py status"
    echo "  python .claude/skills/homeassistant/scripts/homeassistant_api.py entities"
    echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

main() {
    case "${1:-}" in
        --deps)
            install_dependencies
            ;;
        --env)
            setup_env
            ;;
        --test)
            test_connections
            ;;
        --help|-h)
            echo "Usage: ./setup.sh [--deps|--env|--test|--help]"
            echo ""
            echo "Options:"
            echo "  --deps    Install Python dependencies only"
            echo "  --env     Check/create .env configuration only"
            echo "  --test    Test all skill connections"
            echo "  --help    Show this help message"
            echo ""
            echo "Without arguments: Full setup (deps + env + usage info)"
            ;;
        *)
            print_header "Homelab Assistant Setup"
            install_dependencies
            setup_env
            test_connections
            print_usage
            ;;
    esac
}

main "$@"
