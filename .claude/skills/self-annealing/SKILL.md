---
name: self-annealing
description: Autonomous self-improvement - error tracking, skill updates, and automatic GitHub sync
version: 1.0.0
author: Philipp Rollmann
tags:
  - homelab
  - self-annealing
  - git
  - automation
  - meta
requires:
  - python3
  - git
triggers:
  - /self-annealing
  - /anneal
  - /git
---

# Self-Annealing System

Autonomous self-improvement: track errors, update skills, commit and push to GitHub automatically.

## Goal

Enable the agent to learn from errors and improve itself without manual intervention. When something breaks:
1. Log the error
2. Fix it
3. Update the relevant skill (or create a new one)
4. Commit and push to GitHub
5. System is now stronger

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `GITHUB_REPO_PATH` | `.env` | No | Path to git repo (defaults to project root) |
| `GIT_AUTHOR_NAME` | `.env` | No | Commit author name (default: "Claude Self-Annealing") |
| `GIT_AUTHOR_EMAIL` | `.env` | No | Commit author email (default: "claude@homelab-assistant") |
| `AUTO_PUSH_ENABLED` | `.env` | No | Enable auto-push (default: true) |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/git_api.py` | Git operations: status, commit, push |
| `scripts/annealing_api.py` | Error tracking, skill management, orchestration |

## Outputs

- Git commit hashes
- Push confirmation
- Error logs (JSON)
- Updated/created skill files
- Status messages to stdout
- Errors to stderr

## Quick Start

1. Ensure git is configured:
   ```bash
   git config user.name "Your Name"
   git config user.email "your@email.com"
   ```

2. Optional: Configure `.env`:
   ```bash
   GIT_AUTHOR_NAME=Claude Self-Annealing
   GIT_AUTHOR_EMAIL=claude@homelab-assistant
   AUTO_PUSH_ENABLED=true
   ```

3. Test connection:
   ```bash
   python .claude/skills/self-annealing/scripts/git_api.py status
   ```

## Resources

- **[OPERATIONS.md](OPERATIONS.md)** - Common workflows and use cases
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues and solutions

## Common Commands

### Git Operations

```bash
# Check repository status
git_api.py status

# Commit changes with Conventional Commits format
git_api.py commit "fix(skill): correct API endpoint"
git_api.py commit "feat(homeassistant): add climate control"
git_api.py commit "docs(readme): update installation guide"

# Push to remote
git_api.py push

# Commit and push in one command
git_api.py commit-and-push "fix(agent): handle timeout errors"

# View recent commits
git_api.py log
git_api.py log --count 10
```

### Self-Annealing Operations

```bash
# Log an error for tracking
annealing_api.py log-error "ConnectionTimeout" "API call to Home Assistant failed after 30s"

# Log how the error was resolved
annealing_api.py log-resolution <error_id> "Increased timeout to 60s and added retry logic"

# Update an existing skill with learnings
annealing_api.py update-skill homeassistant "Added timeout configuration to Edge Cases section"

# Create a new skill
annealing_api.py create-skill "new-skill-name" "Description of what it does"

# Full annealing cycle: commit all changes and push
annealing_api.py anneal "fix(homeassistant): add retry logic for timeouts"

# View error history
annealing_api.py list-errors
annealing_api.py list-errors --unresolved
```

## Workflows

### After Fixing a Bug

1. Fix the issue in code
2. Log the resolution:
   ```bash
   annealing_api.py log-error "BugDescription" "Context of what happened"
   annealing_api.py log-resolution <id> "How it was fixed"
   ```
3. Update skill if applicable:
   ```bash
   annealing_api.py update-skill <skill-name> "Added edge case for X"
   ```
4. Commit and push:
   ```bash
   annealing_api.py anneal "fix(component): description of fix"
   ```

### After Discovering a New Pattern

1. Document the pattern in the relevant skill
2. Run the annealing cycle:
   ```bash
   annealing_api.py anneal "docs(skill): document new pattern for X"
   ```

### After Creating a New Skill

1. Create the skill structure:
   ```bash
   annealing_api.py create-skill "skill-name" "What it does"
   ```
2. Implement the skill scripts
3. Commit and push:
   ```bash
   annealing_api.py anneal "feat(skill-name): add new skill for X"
   ```

## Conventional Commits Format

All commits follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

Types:
- feat:     New feature
- fix:      Bug fix
- docs:     Documentation only
- style:    Formatting, no code change
- refactor: Code restructuring
- test:     Adding tests
- chore:    Maintenance tasks

Scope: Component affected (e.g., agent, homeassistant, pihole)
```

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| No git credentials | Push fails | Configure SSH key or token |
| Merge conflict | Push rejected | Pull first, resolve conflicts |
| No changes to commit | Commit skipped | Check `git status` first |
| Remote ahead | Push rejected | Pull and rebase first |
| Invalid commit message | Warning shown | Follow Conventional Commits |
| Skill not found | Error returned | Check skill name with `list-skills` |

## Error Store

Errors are tracked in `.claude/skills/self-annealing/data/errors.json`:

```json
{
  "errors": [
    {
      "id": "err_20240115_001",
      "timestamp": "2024-01-15T10:30:00Z",
      "error": "ConnectionTimeout",
      "context": "API call failed",
      "resolved": true,
      "resolution": "Added retry logic",
      "resolved_at": "2024-01-15T11:00:00Z"
    }
  ]
}
```

## Related Skills

- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
- [/homeassistant](../homeassistant/SKILL.md) - Smart home automation
- [/proxmox](../proxmox/SKILL.md) - Virtualization management
