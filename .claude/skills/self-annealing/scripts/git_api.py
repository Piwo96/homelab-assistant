#!/usr/bin/env python3
"""
Git API Client for Self-Annealing

CLI tool for git operations: status, commit, push, log.
Follows Conventional Commits specification.

Usage:
    python git_api.py status
    python git_api.py commit "fix(agent): handle timeout"
    python git_api.py push
    python git_api.py commit-and-push "feat(skill): add new feature"
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


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


class GitAPI:
    """Git operations client."""

    CONVENTIONAL_COMMIT_PATTERN = re.compile(
        r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)"
        r"(\([a-zA-Z0-9_-]+\))?"
        r"!?:\s.+"
    )

    def __init__(self, repo_path: str = None):
        load_env()

        self.repo_path = repo_path or os.environ.get(
            "GITHUB_REPO_PATH",
            str(Path(__file__).parent.parent.parent.parent.parent)
        )
        self.author_name = os.environ.get("GIT_AUTHOR_NAME", "Claude Self-Annealing")
        self.author_email = os.environ.get("GIT_AUTHOR_EMAIL", "claude@homelab-assistant")
        self.auto_push = os.environ.get("AUTO_PUSH_ENABLED", "true").lower() == "true"

        # Verify it's a git repository
        if not Path(self.repo_path, ".git").exists():
            print(f"Error: {self.repo_path} is not a git repository", file=sys.stderr)
            sys.exit(1)

    def _run_git(self, *args, check: bool = True, capture: bool = True) -> Tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        cmd = ["git", "-C", self.repo_path] + list(args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                check=False,
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except Exception as e:
            return 1, "", str(e)

    def status(self, short: bool = False) -> dict:
        """Get repository status."""
        args = ["status", "--porcelain"] if short else ["status"]
        returncode, stdout, stderr = self._run_git(*args)

        if returncode != 0:
            print(f"Error: {stderr}", file=sys.stderr)
            return {"success": False, "error": stderr}

        # Get current branch
        _, branch, _ = self._run_git("rev-parse", "--abbrev-ref", "HEAD")

        # Get remote tracking status
        _, tracking, _ = self._run_git("rev-parse", "--abbrev-ref", "@{upstream}")

        # Check if ahead/behind
        _, ahead_behind, _ = self._run_git("rev-list", "--left-right", "--count", f"{tracking}...HEAD")

        behind, ahead = 0, 0
        if ahead_behind:
            parts = ahead_behind.split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

        # Parse porcelain output for file status
        _, porcelain, _ = self._run_git("status", "--porcelain")

        staged = []
        modified = []
        untracked = []

        for line in porcelain.split("\n"):
            if not line:
                continue
            status = line[:2]
            filename = line[3:]

            if status[0] in "MADRCT":
                staged.append(filename)
            if status[1] in "MADRCT":
                modified.append(filename)
            if status == "??":
                untracked.append(filename)

        result = {
            "success": True,
            "branch": branch,
            "tracking": tracking if tracking else None,
            "ahead": ahead,
            "behind": behind,
            "staged": staged,
            "modified": modified,
            "untracked": untracked,
            "clean": not (staged or modified or untracked),
        }

        return result

    def validate_commit_message(self, message: str) -> Tuple[bool, str]:
        """Validate commit message follows Conventional Commits."""
        if not message:
            return False, "Commit message cannot be empty"

        # Check first line
        first_line = message.split("\n")[0]

        if not self.CONVENTIONAL_COMMIT_PATTERN.match(first_line):
            return False, (
                "Commit message must follow Conventional Commits format:\n"
                "  <type>(<scope>): <description>\n"
                "  Types: feat, fix, docs, style, refactor, test, chore, perf, ci, build, revert\n"
                f"  Got: {first_line}"
            )

        if len(first_line) > 72:
            return False, f"First line should be <= 72 chars (got {len(first_line)})"

        return True, "Valid"

    def commit(self, message: str, add_all: bool = False, files: List[str] = None) -> dict:
        """Create a commit with the given message."""
        # Validate message
        valid, validation_msg = self.validate_commit_message(message)
        if not valid:
            print(f"Warning: {validation_msg}", file=sys.stderr)
            # Continue anyway but warn

        # Stage files if requested
        if add_all:
            returncode, _, stderr = self._run_git("add", "-A")
            if returncode != 0:
                return {"success": False, "error": f"Failed to stage files: {stderr}"}
        elif files:
            for f in files:
                returncode, _, stderr = self._run_git("add", f)
                if returncode != 0:
                    return {"success": False, "error": f"Failed to stage {f}: {stderr}"}

        # Check if there are staged changes
        status = self.status()
        if not status.get("staged") and not add_all:
            return {"success": False, "error": "No staged changes to commit"}

        # Create commit with author info
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = self.author_name
        env["GIT_AUTHOR_EMAIL"] = self.author_email
        env["GIT_COMMITTER_NAME"] = self.author_name
        env["GIT_COMMITTER_EMAIL"] = self.author_email

        cmd = ["git", "-C", self.repo_path, "commit", "-m", message]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            # Get commit hash
            _, commit_hash, _ = self._run_git("rev-parse", "HEAD")
            _, short_hash, _ = self._run_git("rev-parse", "--short", "HEAD")

            return {
                "success": True,
                "hash": commit_hash,
                "short_hash": short_hash,
                "message": message,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def push(self, force: bool = False, set_upstream: bool = False) -> dict:
        """Push commits to remote."""
        args = ["push"]

        if force:
            args.append("--force-with-lease")

        if set_upstream:
            _, branch, _ = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
            args.extend(["-u", "origin", branch])

        returncode, stdout, stderr = self._run_git(*args)

        if returncode != 0:
            # Check if we need to set upstream
            if "no upstream branch" in stderr.lower() or "set-upstream" in stderr.lower():
                return self.push(force=force, set_upstream=True)
            return {"success": False, "error": stderr}

        return {
            "success": True,
            "message": stdout or stderr or "Pushed successfully",
        }

    def pull(self, rebase: bool = True) -> dict:
        """Pull changes from remote."""
        args = ["pull"]
        if rebase:
            args.append("--rebase")

        returncode, stdout, stderr = self._run_git(*args)

        if returncode != 0:
            return {"success": False, "error": stderr}

        return {
            "success": True,
            "message": stdout or "Already up to date",
        }

    def log(self, count: int = 5, oneline: bool = True) -> dict:
        """Get recent commit history."""
        args = ["log", f"-{count}"]
        if oneline:
            args.append("--oneline")

        returncode, stdout, stderr = self._run_git(*args)

        if returncode != 0:
            return {"success": False, "error": stderr}

        commits = []
        for line in stdout.split("\n"):
            if line:
                if oneline:
                    parts = line.split(" ", 1)
                    commits.append({"hash": parts[0], "message": parts[1] if len(parts) > 1 else ""})
                else:
                    commits.append(line)

        return {
            "success": True,
            "commits": commits,
        }

    def commit_and_push(self, message: str, add_all: bool = True) -> dict:
        """Commit all changes and push to remote."""
        # First commit
        commit_result = self.commit(message, add_all=add_all)
        if not commit_result.get("success"):
            return commit_result

        # Then push
        push_result = self.push()
        if not push_result.get("success"):
            return {
                "success": False,
                "error": f"Committed but push failed: {push_result.get('error')}",
                "commit": commit_result,
            }

        return {
            "success": True,
            "commit": commit_result,
            "push": push_result,
        }

    def diff(self, staged: bool = False, file: str = None) -> dict:
        """Show diff of changes."""
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file:
            args.append(file)

        returncode, stdout, stderr = self._run_git(*args)

        if returncode != 0:
            return {"success": False, "error": stderr}

        return {
            "success": True,
            "diff": stdout,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Git operations for Self-Annealing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python git_api.py status
    python git_api.py commit "fix(agent): handle timeout errors"
    python git_api.py push
    python git_api.py commit-and-push "feat(skill): add self-annealing"
    python git_api.py log --count 10
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Status command
    status_parser = subparsers.add_parser("status", help="Show repository status")
    status_parser.add_argument("--short", "-s", action="store_true", help="Short format")

    # Commit command
    commit_parser = subparsers.add_parser("commit", help="Create a commit")
    commit_parser.add_argument("message", help="Commit message (Conventional Commits format)")
    commit_parser.add_argument("--all", "-a", action="store_true", help="Stage all changes")
    commit_parser.add_argument("--files", "-f", nargs="+", help="Specific files to stage")

    # Push command
    push_parser = subparsers.add_parser("push", help="Push to remote")
    push_parser.add_argument("--force", "-f", action="store_true", help="Force push (with lease)")

    # Pull command
    pull_parser = subparsers.add_parser("pull", help="Pull from remote")
    pull_parser.add_argument("--no-rebase", action="store_true", help="Merge instead of rebase")

    # Log command
    log_parser = subparsers.add_parser("log", help="Show commit history")
    log_parser.add_argument("--count", "-n", type=int, default=5, help="Number of commits")
    log_parser.add_argument("--full", action="store_true", help="Full format (not oneline)")

    # Commit-and-push command
    cap_parser = subparsers.add_parser("commit-and-push", help="Commit and push in one step")
    cap_parser.add_argument("message", help="Commit message (Conventional Commits format)")

    # Diff command
    diff_parser = subparsers.add_parser("diff", help="Show changes")
    diff_parser.add_argument("--staged", "-s", action="store_true", help="Show staged changes")
    diff_parser.add_argument("--file", "-f", help="Specific file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    git = GitAPI()

    if args.command == "status":
        result = git.status(short=args.short)
        if result.get("success"):
            print(f"Branch: {result['branch']}")
            if result.get("tracking"):
                print(f"Tracking: {result['tracking']}")
                if result.get("ahead"):
                    print(f"  Ahead by {result['ahead']} commit(s)")
                if result.get("behind"):
                    print(f"  Behind by {result['behind']} commit(s)")
            if result.get("clean"):
                print("Working tree clean")
            else:
                if result.get("staged"):
                    print(f"Staged: {', '.join(result['staged'])}")
                if result.get("modified"):
                    print(f"Modified: {', '.join(result['modified'])}")
                if result.get("untracked"):
                    print(f"Untracked: {', '.join(result['untracked'])}")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "commit":
        result = git.commit(args.message, add_all=args.all, files=args.files)
        if result.get("success"):
            print(f"Committed: {result['short_hash']} {result['message']}")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "push":
        result = git.push(force=args.force)
        if result.get("success"):
            print(result.get("message"))
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "pull":
        result = git.pull(rebase=not args.no_rebase)
        if result.get("success"):
            print(result.get("message"))
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "log":
        result = git.log(count=args.count, oneline=not args.full)
        if result.get("success"):
            for commit in result["commits"]:
                if isinstance(commit, dict):
                    print(f"{commit['hash']} {commit['message']}")
                else:
                    print(commit)
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "commit-and-push":
        result = git.commit_and_push(args.message)
        if result.get("success"):
            commit = result["commit"]
            print(f"Committed: {commit['short_hash']} {commit['message']}")
            print(f"Pushed: {result['push'].get('message')}")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "diff":
        result = git.diff(staged=args.staged, file=args.file)
        if result.get("success"):
            print(result.get("diff") or "No changes")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
