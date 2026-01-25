#!/usr/bin/env python3
"""
Self-Annealing API Client

CLI tool for autonomous self-improvement: error tracking, skill updates,
and automatic GitHub sync.

Usage:
    python annealing_api.py log-error "ConnectionTimeout" "API failed"
    python annealing_api.py log-resolution err_001 "Added retry logic"
    python annealing_api.py update-skill homeassistant "Added edge case"
    python annealing_api.py anneal "fix(skill): add timeout handling"
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import git_api from same directory
sys.path.insert(0, str(Path(__file__).parent))
from git_api import GitAPI


def load_env():
    """Load environment variables from .env file if present."""
    env_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path(__file__).parent.parent.parent.parent.parent / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key.strip(), value.strip())
            break


class ErrorStore:
    """Persistent error tracking store."""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or Path(__file__).parent.parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_path = self.data_dir / "errors.json"
        self._load()

    def _load(self):
        """Load errors from disk."""
        if self.store_path.exists():
            with open(self.store_path) as f:
                self.data = json.load(f)
        else:
            self.data = {"errors": [], "patterns": []}

    def _save(self):
        """Save errors to disk."""
        with open(self.store_path, "w") as f:
            json.dump(self.data, f, indent=2, default=str)

    def _generate_id(self) -> str:
        """Generate a unique error ID."""
        date = datetime.now().strftime("%Y%m%d")
        count = len([e for e in self.data["errors"] if e["id"].startswith(f"err_{date}")]) + 1
        return f"err_{date}_{count:03d}"

    def log_error(self, error: str, context: str, metadata: Dict = None) -> Dict:
        """Log a new error."""
        error_entry = {
            "id": self._generate_id(),
            "timestamp": datetime.now().isoformat(),
            "error": error,
            "context": context,
            "metadata": metadata or {},
            "resolved": False,
            "resolution": None,
            "resolved_at": None,
        }
        self.data["errors"].append(error_entry)
        self._save()
        return error_entry

    def log_resolution(self, error_id: str, resolution: str) -> Optional[Dict]:
        """Mark an error as resolved."""
        for error in self.data["errors"]:
            if error["id"] == error_id:
                error["resolved"] = True
                error["resolution"] = resolution
                error["resolved_at"] = datetime.now().isoformat()
                self._save()
                return error
        return None

    def list_errors(self, unresolved_only: bool = False, limit: int = 20) -> List[Dict]:
        """List errors."""
        errors = self.data["errors"]
        if unresolved_only:
            errors = [e for e in errors if not e["resolved"]]
        return sorted(errors, key=lambda x: x["timestamp"], reverse=True)[:limit]

    def get_error(self, error_id: str) -> Optional[Dict]:
        """Get a specific error by ID."""
        for error in self.data["errors"]:
            if error["id"] == error_id:
                return error
        return None

    def add_pattern(self, pattern: str, solution: str, skill: str = None) -> Dict:
        """Add a learned pattern."""
        pattern_entry = {
            "id": f"pat_{len(self.data['patterns']) + 1:03d}",
            "timestamp": datetime.now().isoformat(),
            "pattern": pattern,
            "solution": solution,
            "skill": skill,
        }
        self.data["patterns"].append(pattern_entry)
        self._save()
        return pattern_entry

    def list_patterns(self) -> List[Dict]:
        """List learned patterns."""
        return self.data.get("patterns", [])


class SkillManager:
    """Manage skill files."""

    def __init__(self, skills_dir: Path = None):
        self.skills_dir = skills_dir or Path(__file__).parent.parent.parent
        if not self.skills_dir.exists():
            raise ValueError(f"Skills directory not found: {self.skills_dir}")

    def list_skills(self) -> List[str]:
        """List available skills."""
        skills = []
        for item in self.skills_dir.iterdir():
            if item.is_dir() and (item / "SKILL.md").exists():
                skills.append(item.name)
        return sorted(skills)

    def get_skill_path(self, skill_name: str) -> Optional[Path]:
        """Get path to a skill directory."""
        skill_path = self.skills_dir / skill_name
        if skill_path.exists() and (skill_path / "SKILL.md").exists():
            return skill_path
        return None

    def update_skill(self, skill_name: str, section: str, content: str) -> Dict:
        """Update a skill file with new content."""
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            return {"success": False, "error": f"Skill not found: {skill_name}"}

        skill_file = skill_path / "SKILL.md"

        try:
            with open(skill_file) as f:
                current_content = f.read()

            # Add to Edge Cases section if it exists
            if section.lower() == "edge_cases" or section.lower() == "edge cases":
                # Find the Edge Cases table
                edge_cases_pattern = r"(\| Scenario \| Behavior \| Mitigation \|.*?\n(?:\|.*?\n)*)"
                match = re.search(edge_cases_pattern, current_content, re.DOTALL)

                if match:
                    # Add new row to the table
                    table = match.group(1)
                    new_row = f"| {content} |\n"
                    new_table = table.rstrip() + "\n" + new_row
                    new_content = current_content.replace(table, new_table)
                else:
                    # Add Edge Cases section if it doesn't exist
                    new_content = current_content + f"\n\n## Edge Cases\n\n{content}\n"
            else:
                # Append to the end of the file
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                new_content = current_content + f"\n\n## Update ({timestamp})\n\n{content}\n"

            with open(skill_file, "w") as f:
                f.write(new_content)

            return {
                "success": True,
                "skill": skill_name,
                "file": str(skill_file),
                "section": section,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def add_to_troubleshooting(self, skill_name: str, problem: str, solution: str) -> Dict:
        """Add entry to TROUBLESHOOTING.md."""
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            return {"success": False, "error": f"Skill not found: {skill_name}"}

        troubleshooting_file = skill_path / "TROUBLESHOOTING.md"

        try:
            if troubleshooting_file.exists():
                with open(troubleshooting_file) as f:
                    content = f.read()
            else:
                content = f"# Troubleshooting - {skill_name}\n\n"

            # Add new entry
            entry = f"""
## {problem}

**Problem:** {problem}

**Solution:** {solution}

**Added:** {datetime.now().strftime("%Y-%m-%d")}

---
"""
            content += entry

            with open(troubleshooting_file, "w") as f:
                f.write(content)

            return {
                "success": True,
                "skill": skill_name,
                "file": str(troubleshooting_file),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_skill(self, name: str, description: str, author: str = "Claude Self-Annealing") -> Dict:
        """Create a new skill from template."""
        skill_path = self.skills_dir / name

        if skill_path.exists():
            return {"success": False, "error": f"Skill already exists: {name}"}

        try:
            # Create directory structure
            skill_path.mkdir(parents=True)
            (skill_path / "scripts").mkdir()

            # Create SKILL.md
            skill_md = f"""---
name: {name}
description: {description}
version: 1.0.0
author: {author}
tags:
  - homelab
  - {name}
requires:
  - python3
triggers:
  - /{name}
---

# {name.replace("-", " ").title()}

{description}

## Goal

[Define the primary goal of this skill]

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `EXAMPLE_VAR` | `.env` | No | Example variable |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/{name}_api.py` | CLI for {name} operations |

## Outputs

- Operation results
- Status messages to stdout
- Errors to stderr

## Quick Start

1. Configure `.env` if needed
2. Test: `python .claude/skills/{name}/scripts/{name}_api.py --help`

## Common Commands

```bash
# Example commands
{name}_api.py status
{name}_api.py list
```

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| [Scenario] | [What happens] | [How to handle] |

## Related Skills

- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
"""
            with open(skill_path / "SKILL.md", "w") as f:
                f.write(skill_md)

            # Create basic script template
            script_template = f'''#!/usr/bin/env python3
"""
{name.replace("-", " ").title()} API Client

Usage:
    python {name}_api.py status
    python {name}_api.py list
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="{description}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Status command
    subparsers.add_parser("status", help="Show status")

    # List command
    subparsers.add_parser("list", help="List items")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "status":
        print("Status: OK")

    elif args.command == "list":
        print("No items yet")


if __name__ == "__main__":
    main()
'''
            with open(skill_path / "scripts" / f"{name}_api.py", "w") as f:
                f.write(script_template)

            return {
                "success": True,
                "skill": name,
                "path": str(skill_path),
                "files": ["SKILL.md", f"scripts/{name}_api.py"],
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class SelfAnnealing:
    """Orchestrate the self-annealing process."""

    def __init__(self):
        load_env()
        self.error_store = ErrorStore()
        self.skill_manager = SkillManager()
        self.git = GitAPI()
        self.auto_push = os.environ.get("AUTO_PUSH_ENABLED", "true").lower() == "true"

    def anneal(self, commit_message: str, push: bool = None) -> Dict:
        """
        Full annealing cycle:
        1. Check for changes
        2. Commit all changes
        3. Push to remote (if enabled)
        """
        should_push = push if push is not None else self.auto_push

        # Check status first
        status = self.git.status()
        if status.get("clean"):
            return {"success": False, "error": "No changes to commit"}

        # Commit
        commit_result = self.git.commit(commit_message, add_all=True)
        if not commit_result.get("success"):
            return commit_result

        result = {
            "success": True,
            "commit": commit_result,
        }

        # Push if enabled
        if should_push:
            push_result = self.git.push()
            result["push"] = push_result
            if not push_result.get("success"):
                result["warning"] = f"Committed but push failed: {push_result.get('error')}"

        return result

    def learn_from_error(self, error_id: str, skill_name: str = None) -> Dict:
        """
        Extract pattern from resolved error and optionally update skill.
        """
        error = self.error_store.get_error(error_id)
        if not error:
            return {"success": False, "error": f"Error not found: {error_id}"}

        if not error.get("resolved"):
            return {"success": False, "error": "Error not yet resolved"}

        # Extract pattern
        pattern = self.error_store.add_pattern(
            pattern=error["error"],
            solution=error["resolution"],
            skill=skill_name,
        )

        result = {
            "success": True,
            "pattern": pattern,
        }

        # Update skill if specified
        if skill_name:
            skill_result = self.skill_manager.add_to_troubleshooting(
                skill_name,
                error["error"],
                error["resolution"],
            )
            result["skill_update"] = skill_result

        return result

    def full_cycle(
        self,
        error: str,
        context: str,
        resolution: str,
        skill_name: str = None,
        commit_message: str = None,
    ) -> Dict:
        """
        Complete self-annealing cycle:
        1. Log error
        2. Log resolution
        3. Update skill (if specified)
        4. Commit and push
        """
        results = {}

        # 1. Log error
        error_entry = self.error_store.log_error(error, context)
        results["error_logged"] = error_entry

        # 2. Log resolution
        resolved = self.error_store.log_resolution(error_entry["id"], resolution)
        results["resolution_logged"] = resolved

        # 3. Update skill if specified
        if skill_name:
            skill_result = self.skill_manager.add_to_troubleshooting(
                skill_name, error, resolution
            )
            results["skill_updated"] = skill_result

            # Also add pattern
            pattern = self.error_store.add_pattern(error, resolution, skill_name)
            results["pattern_added"] = pattern

        # 4. Generate commit message if not provided
        if not commit_message:
            if skill_name:
                commit_message = f"fix({skill_name}): {error.lower().replace(' ', '-')[:50]}"
            else:
                commit_message = f"fix(agent): {error.lower().replace(' ', '-')[:50]}"

        # 5. Commit and push
        anneal_result = self.anneal(commit_message)
        results["anneal"] = anneal_result

        results["success"] = anneal_result.get("success", False)
        return results


def main():
    parser = argparse.ArgumentParser(
        description="Self-Annealing: Error tracking, skill updates, and auto-commit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python annealing_api.py log-error "Timeout" "API call failed after 30s"
    python annealing_api.py log-resolution err_20240115_001 "Added retry"
    python annealing_api.py update-skill homeassistant "Added timeout handling"
    python annealing_api.py anneal "fix(agent): handle timeouts"
    python annealing_api.py full-cycle "Timeout" "API failed" "Added retry" --skill homeassistant
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Log error
    log_error_parser = subparsers.add_parser("log-error", help="Log a new error")
    log_error_parser.add_argument("error", help="Error type/name")
    log_error_parser.add_argument("context", help="Context/description")

    # Log resolution
    log_res_parser = subparsers.add_parser("log-resolution", help="Log error resolution")
    log_res_parser.add_argument("error_id", help="Error ID (e.g., err_20240115_001)")
    log_res_parser.add_argument("resolution", help="How it was resolved")

    # List errors
    list_errors_parser = subparsers.add_parser("list-errors", help="List tracked errors")
    list_errors_parser.add_argument("--unresolved", "-u", action="store_true", help="Only unresolved")
    list_errors_parser.add_argument("--limit", "-n", type=int, default=20, help="Max entries")

    # List patterns
    subparsers.add_parser("list-patterns", help="List learned patterns")

    # List skills
    subparsers.add_parser("list-skills", help="List available skills")

    # Update skill
    update_skill_parser = subparsers.add_parser("update-skill", help="Update a skill")
    update_skill_parser.add_argument("skill", help="Skill name")
    update_skill_parser.add_argument("content", help="Content to add")
    update_skill_parser.add_argument("--section", "-s", default="edge_cases", help="Section to update")

    # Create skill
    create_skill_parser = subparsers.add_parser("create-skill", help="Create a new skill")
    create_skill_parser.add_argument("name", help="Skill name")
    create_skill_parser.add_argument("description", help="Skill description")

    # Anneal (commit and push)
    anneal_parser = subparsers.add_parser("anneal", help="Commit and push changes")
    anneal_parser.add_argument("message", help="Commit message")
    anneal_parser.add_argument("--no-push", action="store_true", help="Don't push after commit")

    # Learn from error
    learn_parser = subparsers.add_parser("learn", help="Extract pattern from resolved error")
    learn_parser.add_argument("error_id", help="Error ID")
    learn_parser.add_argument("--skill", "-s", help="Skill to update")

    # Full cycle
    full_parser = subparsers.add_parser("full-cycle", help="Complete annealing cycle")
    full_parser.add_argument("error", help="Error type/name")
    full_parser.add_argument("context", help="Error context")
    full_parser.add_argument("resolution", help="How it was resolved")
    full_parser.add_argument("--skill", "-s", help="Skill to update")
    full_parser.add_argument("--message", "-m", help="Custom commit message")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    annealing = SelfAnnealing()

    if args.command == "log-error":
        result = annealing.error_store.log_error(args.error, args.context)
        print(f"Logged: {result['id']}")
        print(f"  Error: {result['error']}")
        print(f"  Context: {result['context']}")

    elif args.command == "log-resolution":
        result = annealing.error_store.log_resolution(args.error_id, args.resolution)
        if result:
            print(f"Resolved: {result['id']}")
            print(f"  Resolution: {result['resolution']}")
        else:
            print(f"Error not found: {args.error_id}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list-errors":
        errors = annealing.error_store.list_errors(
            unresolved_only=args.unresolved,
            limit=args.limit,
        )
        if not errors:
            print("No errors tracked")
        else:
            for e in errors:
                status = "Resolved" if e["resolved"] else "Open"
                print(f"[{status}] {e['id']}: {e['error']}")
                print(f"         Context: {e['context'][:50]}...")
                if e["resolved"]:
                    print(f"         Fix: {e['resolution'][:50]}...")

    elif args.command == "list-patterns":
        patterns = annealing.error_store.list_patterns()
        if not patterns:
            print("No patterns learned yet")
        else:
            for p in patterns:
                print(f"{p['id']}: {p['pattern']}")
                print(f"  Solution: {p['solution']}")
                if p.get("skill"):
                    print(f"  Skill: {p['skill']}")

    elif args.command == "list-skills":
        skills = annealing.skill_manager.list_skills()
        print("Available skills:")
        for skill in skills:
            print(f"  - {skill}")

    elif args.command == "update-skill":
        result = annealing.skill_manager.update_skill(
            args.skill, args.section, args.content
        )
        if result.get("success"):
            print(f"Updated: {result['skill']}")
            print(f"  File: {result['file']}")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "create-skill":
        result = annealing.skill_manager.create_skill(args.name, args.description)
        if result.get("success"):
            print(f"Created: {result['skill']}")
            print(f"  Path: {result['path']}")
            print(f"  Files: {', '.join(result['files'])}")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "anneal":
        result = annealing.anneal(args.message, push=not args.no_push)
        if result.get("success"):
            commit = result["commit"]
            print(f"Committed: {commit['short_hash']} {commit['message']}")
            if result.get("push", {}).get("success"):
                print("Pushed to remote")
            elif result.get("warning"):
                print(f"Warning: {result['warning']}")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "learn":
        result = annealing.learn_from_error(args.error_id, skill_name=args.skill)
        if result.get("success"):
            print(f"Pattern extracted: {result['pattern']['id']}")
            if result.get("skill_update", {}).get("success"):
                print(f"Updated skill: {args.skill}")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "full-cycle":
        result = annealing.full_cycle(
            error=args.error,
            context=args.context,
            resolution=args.resolution,
            skill_name=args.skill,
            commit_message=args.message,
        )
        if result.get("success"):
            print("Full annealing cycle completed:")
            print(f"  Error logged: {result['error_logged']['id']}")
            print(f"  Resolution logged: {result['resolution_logged']['id']}")
            if result.get("skill_updated", {}).get("success"):
                print(f"  Skill updated: {args.skill}")
            if result.get("pattern_added"):
                print(f"  Pattern added: {result['pattern_added']['id']}")
            commit = result["anneal"].get("commit", {})
            if commit:
                print(f"  Committed: {commit.get('short_hash')} {commit.get('message')}")
            if result["anneal"].get("push", {}).get("success"):
                print("  Pushed to remote")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
