---
name: git
description: Git-Operationen - Status, Commit, Push mit Conventional Commits
version: 1.0.0
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

# Alles in einem Schritt
git_api.py commit-and-push
git_api.py commit-and-push --message "feat(skill): add new feature"
```

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

## Auto-Message Generation

Wenn keine Message angegeben wird, analysiert der Skill die Änderungen und generiert automatisch eine passende Conventional Commit Message basierend auf:

- Geänderten Dateien und deren Pfade
- Art der Änderung (neue Dateien, Modifikationen, Löschungen)
- Erkennung von Skill-Verzeichnissen und Agent-Code

## Edge Cases

| Szenario | Verhalten |
|----------|-----------|
| Keine Änderungen | Commit wird übersprungen |
| Kein Remote konfiguriert | Push schlägt fehl mit Hinweis |
| Merge-Konflikt | Warnung, manuelles Eingreifen nötig |
| Lange Commit-Message | Automatisch gekürzt auf 72 Zeichen |

## Beispiel-Anfragen

- "Zeig mir den Git-Status"
- "Committe die Änderungen"
- "Pushe den Code"
- "Committe und pushe alles"
- "Mach einen Commit mit Message fix(agent): timeout erhöht"
