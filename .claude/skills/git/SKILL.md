---
name: git
description: Git-Operationen - Status, Commit, Push, Pull, Branches und Pull Requests
version: 1.1.0
author: Philipp Rollmann
tags:
  - homelab
  - git
  - automation
requires:
  - python3
  - git
triggers:
  - /git
  - committe
  - pushe
  - commit
  - push
intent_hints:
  - "Code committen, pushen, pullen"
  - "Git-Status, Änderungen anzeigen"
  - "Branch erstellen, wechseln, mergen"
  - "Pull Request erstellen"
---

# Git Management

Führe Git-Operationen aus: Status prüfen, Änderungen committen und pushen.

## Goal

Ermöglicht das Verwalten von Git-Repositories direkt über Telegram-Befehle.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `GITHUB_REPO_PATH` | `.env` | No | Pfad zum Git-Repo (Standard: Projekt-Root) |
| `GIT_AUTHOR_NAME` | `.env` | No | Commit-Author (Standard: "Homelab Assistant") |
| `GIT_AUTHOR_EMAIL` | `.env` | No | Author-Email (Standard: "homelab@assistant") |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/git_api.py` | CLI für alle Git-Operationen |

## Outputs

- Git-Status (Branch, Änderungen)
- Commit-Bestätigungen mit Hash
- Push-Ergebnis
- Fehler zu stderr

## Resources

- **[OPERATIONS.md](OPERATIONS.md)** - Detailed workflows and use cases
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Common issues and solutions

## Common Commands

```bash
# Status prüfen
git_api.py status

# Änderungen committen (auto-generierte Message)
git_api.py commit

# Mit eigener Message
git_api.py commit --message "fix(agent): handle timeout"

# Pushen
git_api.py push

# Pullen
git_api.py pull

# Alles in einem Schritt
git_api.py commit-and-push
git_api.py commit-and-push --message "feat(skill): add new feature"

# Commit-Verlauf
git_api.py log
git_api.py log --count 10
```

## Branch Management

```bash
# Aktuellen Branch anzeigen
git_api.py branch

# Neuen Branch erstellen und wechseln
git_api.py create-branch feature/new-feature

# Zu Branch wechseln
git_api.py checkout main

# Branch mergen
git_api.py merge feature/new-feature

# Lokalen Branch löschen
git_api.py delete-branch feature/old-feature

# Remote Branch löschen
git_api.py delete-remote-branch feature/old-feature

# Änderungen verwerfen (cleanup)
git_api.py discard-changes

# Vergleichs-URL generieren
git_api.py compare-url main feature/new-feature
```

## GitHub Pull Request Operations

**Requirement**: GitHub CLI (`gh`) must be installed and authenticated.

```bash
# Install gh CLI (macOS)
brew install gh

# Authenticate
gh auth login

# Pull Request erstellen
git_api.py create-pr --title "Add new feature" --body "Description" --base main

# PR-Informationen abrufen
git_api.py pr-info 123

# PR mergen (und Branch löschen)
git_api.py merge-pr 123

# PR schließen (ohne merge)
git_api.py close-pr 123
```

> **Note**: PR operations will fail with "GitHub CLI (gh) nicht installiert" if `gh` is not available. See TROUBLESHOOTING.md for setup instructions.

## Conventional Commits Format

Alle Commits folgen dem [Conventional Commits](https://www.conventionalcommits.org/) Standard:

```
<type>(<scope>): <description>

Types:
- feat:     Neue Funktion
- fix:      Bugfix
- docs:     Nur Dokumentation
- style:    Formatierung, kein Code-Change
- refactor: Code-Umstrukturierung
- test:     Tests hinzufügen
- chore:    Wartungsaufgaben

Scope: Betroffene Komponente (z.B. agent, homeassistant, pihole)
```

## Commit Author

Commits werden unter dem Hauptaccount erstellt (konfiguriert via `GIT_AUTHOR_NAME` und `GIT_AUTHOR_EMAIL` in `.env`). Es wird **kein Co-Authored-By Header** verwendet - alle Commits erscheinen direkt unter dem konfigurierten Author.

## Auto-Message Generation

Wenn keine Message angegeben wird, analysiert der Skill die Änderungen und generiert automatisch eine passende Conventional Commit Message basierend auf:

- Geänderten Dateien und deren Pfade
- Art der Änderung (neue Dateien, Modifikationen, Löschungen)
- Erkennung von Skill-Verzeichnissen und Agent-Code

## Edge Cases

| Szenario | Verhalten | Mitigation |
|----------|-----------|------------|
| Keine Änderungen | Commit wird übersprungen | Check `git_api.py status` first |
| Kein Remote konfiguriert | Push schlägt fehl mit Hinweis | Configure remote: `git remote add origin <url>` |
| Merge-Konflikt | Warnung, manuelles Eingreifen nötig | Resolve conflicts manually, then commit |
| Lange Commit-Message | Automatisch gekürzt auf 72 Zeichen | Keep messages concise |
| Ungültiges Conventional Commit Format | Warning ausgegeben, Commit erfolgt trotzdem | Follow format: `type(scope): description` |
| `gh` CLI nicht installiert | PR operations fail | Install via `brew install gh` or apt |
| Branch nicht auf Remote | Push mit `--set-upstream` | Automatically handled by script |
| Uncommitted changes beim Branch-Wechsel | Änderungen bleiben erhalten | Use `discard-changes` to clean up |

## Beispiel-Anfragen

- "Zeig mir den Git-Status"
- "Committe die Änderungen"
- "Pushe den Code"
- "Committe und pushe alles"
- "Mach einen Commit mit Message fix(agent): timeout erhöht"
