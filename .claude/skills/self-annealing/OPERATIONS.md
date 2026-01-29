# Self-Annealing Operations

> Part of the [Self-Annealing skill](SKILL.md) - Read SKILL.md first for overview and setup.

Common workflows for autonomous self-improvement.

## Quick Reference

| Operation | Command | When to Use |
|-----------|---------|-------------|
| Check status | `git_api.py status` | Before any changes |
| Commit + push | `annealing_api.py anneal "message"` | After any fix |
| Log error | `annealing_api.py log-error "type" "context"` | When error occurs |
| Full cycle | `annealing_api.py full-cycle "err" "ctx" "fix"` | Complete fix workflow |

## Workflow 1: Bug Fix Cycle

Use when you've fixed a bug and want to document + commit + push automatically.

```bash
# 1. Fix the bug in code (done manually or by agent)

# 2. Run full annealing cycle
annealing_api.py full-cycle \
  "ConnectionTimeout" \
  "Home Assistant API call failed after 30s" \
  "Increased timeout to 60s and added exponential backoff" \
  --skill homeassistant \
  --message "fix(homeassistant): add retry logic for API timeouts"

# This will:
# - Log the error
# - Log the resolution
# - Update homeassistant/TROUBLESHOOTING.md
# - Add pattern to learned patterns
# - Commit all changes
# - Push to GitHub
```

## Workflow 2: Quick Commit + Push

Use when you've made changes and just want to commit and push.

```bash
# Check what's changed
git_api.py status

# Commit and push
annealing_api.py anneal "fix(agent): handle edge case in intent classifier"

# Or if you only want to commit (no push)
annealing_api.py anneal "docs(readme): update installation" --no-push
```

## Workflow 3: Error Tracking Only

Use when you want to track an error for later analysis.

```bash
# 1. Log the error when it occurs
annealing_api.py log-error "RateLimitExceeded" "UniFi API returned 429"

# Output: Logged: err_20240115_001

# 2. Later, when fixed, log the resolution
annealing_api.py log-resolution err_20240115_001 "Added rate limiting with 1s delay between calls"

# 3. Extract pattern and update skill
annealing_api.py learn err_20240115_001 --skill unifi-network
```

## Workflow 4: New Skill Creation

Use when you need to add a completely new capability.

```bash
# 1. Create skill scaffold
annealing_api.py create-skill "mqtt" "Manage MQTT broker and message queues"

# Output:
# Created: mqtt
#   Path: .claude/skills/mqtt
#   Files: SKILL.md, scripts/mqtt_api.py

# 2. Implement the skill (edit files)

# 3. Commit and push
annealing_api.py anneal "feat(mqtt): add MQTT broker management skill"
```

## Workflow 5: Skill Update

Use when you discover a new edge case or pattern for an existing skill.

```bash
# Add to Edge Cases table
annealing_api.py update-skill homeassistant "HA restart | Commands fail | Wait 60s and retry"

# Or add to troubleshooting
annealing_api.py update-skill homeassistant "Token expires after 1 year, renew in HA UI" --section troubleshooting
```

## Workflow 6: View History

```bash
# Recent errors
annealing_api.py list-errors

# Only unresolved
annealing_api.py list-errors --unresolved

# Learned patterns
annealing_api.py list-patterns

# Git history
git_api.py log --count 10

# Available skills
annealing_api.py list-skills
```

## Workflow 7: Pre-Push Validation

Before pushing, verify everything is clean:

```bash
# 1. Check git status
git_api.py status

# 2. View diff
git_api.py diff

# 3. If clean, commit and push
annealing_api.py anneal "type(scope): description"
```

## Conventional Commits Cheat Sheet

| Type | When to Use | Example |
|------|-------------|---------|
| `feat` | New feature | `feat(pihole): add blocklist management` |
| `fix` | Bug fix | `fix(agent): handle timeout errors` |
| `docs` | Documentation | `docs(readme): update setup guide` |
| `refactor` | Code restructure | `refactor(skills): consolidate API clients` |
| `test` | Add tests | `test(homeassistant): add unit tests` |
| `chore` | Maintenance | `chore(deps): update requirements.txt` |

## Automation Tips

### Make scripts executable
```bash
chmod +x .claude/skills/self-annealing/scripts/*.py
```

### Add to PATH (optional)
```bash
export PATH="$PATH:$(pwd)/.claude/skills/self-annealing/scripts"

# Now you can run directly:
git_api.py status
annealing_api.py anneal "fix: something"
```

### Environment Variables

```bash
# .env
GIT_AUTHOR_NAME=Claude Self-Annealing
GIT_AUTHOR_EMAIL=claude@homelab-assistant
AUTO_PUSH_ENABLED=true
```

## Agent Integration

### Option 1: Direct Python Import (Recommended)

The agent can import and call functions directly:

```python
from .claude.skills.self_annealing.scripts.annealing_api import execute

# Log error
result = execute("log-error", {
    "error": "ConnectionTimeout",
    "context": "API call failed after 30s"
})

# Full annealing cycle
result = execute("full-cycle", {
    "error": "ConnectionTimeout",
    "context": "API call failed",
    "resolution": "Added retry logic",
    "skill": "homeassistant",
    "message": "fix(homeassistant): add retry for timeouts"
})

# Returns Python dicts, not CLI output strings
```

### Option 2: CLI via Subprocess

```python
import subprocess

def self_anneal(message: str):
    """Commit and push current changes."""
    result = subprocess.run(
        ["python", ".claude/skills/self-annealing/scripts/annealing_api.py",
         "anneal", message],
        capture_output=True,
        text=True,
    )
    return result.stdout
```

## Error Store Location

Errors are persisted in:
```
.claude/skills/self-annealing/data/errors.json
```

This file is git-tracked, so error history and patterns are versioned.
