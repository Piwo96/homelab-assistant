#!/usr/bin/env python3
"""
Git API Client for Homelab Assistant

CLI tool for git operations with auto-generated Conventional Commits messages.

Usage:
    python git_api.py status
    python git_api.py commit
    python git_api.py commit --message "fix(agent): handle timeout"
    python git_api.py push
    python git_api.py commit-and-push
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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
    """Git operations client with auto-commit message generation."""

    CONVENTIONAL_COMMIT_PATTERN = re.compile(
        r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)"
        r"(\([a-zA-Z0-9_-]+\))?"
        r"!?:\s.+"
    )

    # Mapping of path patterns to scopes
    SCOPE_PATTERNS = [
        (r"^agent/", "agent"),
        (r"^\.claude/skills/([^/]+)/", lambda m: m.group(1)),
        (r"^tests/", "test"),
        (r"^docs/", "docs"),
        (r"^requirements", "deps"),
        (r"^\.env", "config"),
        (r"^Dockerfile", "docker"),
        (r"^docker-compose", "docker"),
    ]

    def __init__(self, repo_path: str = None):
        load_env()

        self.repo_path = repo_path or os.environ.get(
            "GITHUB_REPO_PATH",
            str(Path(__file__).parent.parent.parent.parent.parent)
        )
        self.author_name = os.environ.get("GIT_AUTHOR_NAME", "Homelab Assistant")
        self.author_email = os.environ.get("GIT_AUTHOR_EMAIL", "homelab@assistant")

        # Verify it's a git repository
        if not Path(self.repo_path, ".git").exists():
            print(f"Error: {self.repo_path} is not a git repository", file=sys.stderr)
            sys.exit(1)

    def _run_git(self, *args, check: bool = True) -> Tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        cmd = ["git", "-C", self.repo_path] + list(args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except Exception as e:
            return 1, "", str(e)

    def status(self) -> Dict:
        """Get repository status."""
        # Get current branch
        _, branch, _ = self._run_git("rev-parse", "--abbrev-ref", "HEAD")

        # Get remote tracking status
        _, tracking, _ = self._run_git("rev-parse", "--abbrev-ref", "@{upstream}")

        # Check if ahead/behind
        behind, ahead = 0, 0
        if tracking:
            _, ahead_behind, _ = self._run_git(
                "rev-list", "--left-right", "--count", f"{tracking}...HEAD"
            )
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

        return {
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

    def _detect_scope(self, files: List[str]) -> Optional[str]:
        """Detect scope from changed files."""
        scopes = set()

        for file in files:
            for pattern, scope in self.SCOPE_PATTERNS:
                match = re.match(pattern, file)
                if match:
                    if callable(scope):
                        scopes.add(scope(match))
                    else:
                        scopes.add(scope)
                    break

        if len(scopes) == 1:
            return scopes.pop()
        elif len(scopes) > 1:
            # Multiple scopes - prioritize agent, then skills
            if "agent" in scopes:
                return "agent"
            # Return first skill if any
            skill_scopes = [s for s in scopes if s not in ("test", "docs", "deps", "config", "docker")]
            if skill_scopes:
                return skill_scopes[0]
        return None

    def _detect_type(self, files: List[str], staged: List[str], modified: List[str]) -> str:
        """Detect commit type from changes."""
        # Check for new files (likely feat)
        new_files = [f for f in staged if f not in modified]

        # Check file extensions and paths
        has_docs = any(f.endswith(".md") or f.startswith("docs/") for f in files)
        has_tests = any("test" in f.lower() for f in files)
        has_config = any(f in (".env", "requirements.txt", "pyproject.toml") or f.startswith(".") for f in files)

        # Determine type
        if has_docs and len([f for f in files if not f.endswith(".md")]) == 0:
            return "docs"
        if has_tests and len([f for f in files if "test" not in f.lower()]) == 0:
            return "test"
        if has_config and len(files) == 1:
            return "chore"
        if new_files and len(new_files) == len(staged):
            return "feat"

        # Default to fix for modifications
        return "fix"

    def _generate_description(self, files: List[str], commit_type: str) -> str:
        """Generate commit description from files."""
        if len(files) == 1:
            filename = Path(files[0]).name
            if commit_type == "feat":
                return f"add {filename}"
            elif commit_type == "docs":
                return f"update {filename}"
            else:
                return f"update {filename}"

        # Multiple files - describe by scope
        if all("skill" in f.lower() for f in files):
            return "update skill configuration"
        if all(f.startswith("agent/") for f in files):
            return "update agent logic"

        # Generic
        if commit_type == "feat":
            return "add new functionality"
        elif commit_type == "fix":
            return "fix issues"
        else:
            return "update code"

    def generate_commit_message(self) -> Optional[str]:
        """Auto-generate a Conventional Commits message based on changes."""
        status = self.status()

        all_files = status["staged"] + status["modified"] + status["untracked"]
        if not all_files:
            return None

        # Detect components
        commit_type = self._detect_type(all_files, status["staged"], status["modified"])
        scope = self._detect_scope(all_files)
        description = self._generate_description(all_files, commit_type)

        # Build message
        if scope:
            message = f"{commit_type}({scope}): {description}"
        else:
            message = f"{commit_type}: {description}"

        # Ensure max 72 chars
        if len(message) > 72:
            message = message[:69] + "..."

        return message

    def validate_commit_message(self, message: str) -> Tuple[bool, str]:
        """Validate commit message follows Conventional Commits."""
        if not message:
            return False, "Commit message cannot be empty"

        first_line = message.split("\n")[0]

        if not self.CONVENTIONAL_COMMIT_PATTERN.match(first_line):
            return False, (
                "Commit message muss Conventional Commits Format haben:\n"
                "  <type>(<scope>): <description>\n"
                "  Types: feat, fix, docs, style, refactor, test, chore"
            )

        if len(first_line) > 72:
            return False, f"Erste Zeile sollte <= 72 Zeichen sein (hat {len(first_line)})"

        return True, "Valid"

    def commit(self, message: str = None, add_all: bool = True) -> Dict:
        """Create a commit with the given or auto-generated message."""
        # Auto-generate message if not provided
        if not message:
            message = self.generate_commit_message()
            if not message:
                return {"success": False, "error": "Keine Änderungen zum Committen"}

        # Validate message
        valid, validation_msg = self.validate_commit_message(message)
        if not valid:
            print(f"Warning: {validation_msg}", file=sys.stderr)

        # Stage all changes
        if add_all:
            returncode, _, stderr = self._run_git("add", "-A")
            if returncode != 0:
                return {"success": False, "error": f"Staging fehlgeschlagen: {stderr}"}

        # Check if there are staged changes
        status = self.status()
        if not status.get("staged") and not add_all:
            return {"success": False, "error": "Keine Änderungen zum Committen"}

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
            _, commit_hash, _ = self._run_git("rev-parse", "--short", "HEAD")

            return {
                "success": True,
                "hash": commit_hash,
                "message": message,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def push(self, set_upstream: bool = False) -> Dict:
        """Push commits to remote."""
        args = ["push"]

        if set_upstream:
            _, branch, _ = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
            args.extend(["-u", "origin", branch])

        returncode, stdout, stderr = self._run_git(*args)

        if returncode != 0:
            # Check if we need to set upstream
            if "no upstream branch" in stderr.lower() or "set-upstream" in stderr.lower():
                return self.push(set_upstream=True)
            return {"success": False, "error": stderr}

        return {
            "success": True,
            "message": stdout or stderr or "Erfolgreich gepusht",
        }

    def commit_and_push(self, message: str = None) -> Dict:
        """Commit all changes and push to remote."""
        # First commit
        commit_result = self.commit(message, add_all=True)
        if not commit_result.get("success"):
            return commit_result

        # Then push
        push_result = self.push()
        if not push_result.get("success"):
            return {
                "success": False,
                "error": f"Commit OK, aber Push fehlgeschlagen: {push_result.get('error')}",
                "commit": commit_result,
            }

        return {
            "success": True,
            "commit": commit_result,
            "push": push_result,
        }

    def log(self, count: int = 5) -> Dict:
        """Get recent commit history."""
        returncode, stdout, stderr = self._run_git("log", f"-{count}", "--oneline")

        if returncode != 0:
            return {"success": False, "error": stderr}

        commits = []
        for line in stdout.split("\n"):
            if line:
                parts = line.split(" ", 1)
                commits.append({
                    "hash": parts[0],
                    "message": parts[1] if len(parts) > 1 else ""
                })

        return {"success": True, "commits": commits}

    # --- Branching Operations ---

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        _, branch, _ = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return branch

    def create_branch(self, branch_name: str, checkout: bool = True) -> Dict:
        """Create a new branch.

        Args:
            branch_name: Name for the new branch
            checkout: If True, switch to the new branch

        Returns:
            Dict with success status
        """
        # Create the branch
        returncode, _, stderr = self._run_git("branch", branch_name)
        if returncode != 0:
            if "already exists" in stderr:
                # Branch exists, just checkout if requested
                if checkout:
                    return self.checkout(branch_name)
                return {"success": True, "message": "Branch existiert bereits"}
            return {"success": False, "error": stderr}

        if checkout:
            return self.checkout(branch_name)

        return {"success": True, "branch": branch_name}

    def checkout(self, branch_name: str) -> Dict:
        """Switch to a branch.

        Args:
            branch_name: Branch to switch to

        Returns:
            Dict with success status
        """
        returncode, _, stderr = self._run_git("checkout", branch_name)
        if returncode != 0:
            return {"success": False, "error": stderr}

        return {"success": True, "branch": branch_name}

    def discard_changes(self, paths: list = None) -> Dict:
        """Discard all uncommitted changes in the working directory.

        This is essential for cleanup after failed operations, as uncommitted
        changes persist across branch switches when branches share the same base.

        Args:
            paths: Optional list of paths to discard. If None, discards all.

        Returns:
            Dict with success status
        """
        if paths:
            args = ["checkout", "--"] + paths
        else:
            args = ["checkout", "--", "."]

        returncode, _, stderr = self._run_git(*args)
        if returncode != 0:
            return {"success": False, "error": stderr}

        return {"success": True}

    def delete_branch(self, branch_name: str, force: bool = False) -> Dict:
        """Delete a branch.

        Args:
            branch_name: Branch to delete
            force: Force delete even if not merged

        Returns:
            Dict with success status
        """
        flag = "-D" if force else "-d"
        returncode, _, stderr = self._run_git("branch", flag, branch_name)
        if returncode != 0:
            return {"success": False, "error": stderr}

        return {"success": True, "deleted": branch_name}

    def merge_branch(self, branch_name: str, message: str = None) -> Dict:
        """Merge a branch into the current branch.

        Args:
            branch_name: Branch to merge
            message: Optional merge commit message

        Returns:
            Dict with success status
        """
        args = ["merge", branch_name]
        if message:
            args.extend(["-m", message])

        returncode, stdout, stderr = self._run_git(*args)
        if returncode != 0:
            return {"success": False, "error": stderr}

        return {"success": True, "message": stdout or "Branch gemerged"}

    def delete_remote_branch(self, branch_name: str) -> Dict:
        """Delete a branch on the remote.

        Args:
            branch_name: Branch to delete on remote

        Returns:
            Dict with success status
        """
        returncode, _, stderr = self._run_git("push", "origin", "--delete", branch_name)
        if returncode != 0:
            if "remote ref does not exist" in stderr:
                return {"success": True, "message": "Branch existiert nicht auf Remote"}
            return {"success": False, "error": stderr}

        return {"success": True, "deleted": branch_name}

    def get_remote_url(self) -> Optional[str]:
        """Get the remote URL for origin.

        Returns:
            Remote URL or None
        """
        _, url, _ = self._run_git("remote", "get-url", "origin")
        return url if url else None

    def get_github_compare_url(self, base_branch: str, compare_branch: str) -> Optional[str]:
        """Generate a GitHub compare URL for two branches.

        Args:
            base_branch: Base branch (e.g., 'master')
            compare_branch: Branch to compare (e.g., 'fix/err_123')

        Returns:
            GitHub compare URL or None
        """
        remote_url = self.get_remote_url()
        if not remote_url:
            return None

        # Convert git URL to HTTPS
        # git@github.com:user/repo.git -> https://github.com/user/repo
        # https://github.com/user/repo.git -> https://github.com/user/repo
        if remote_url.startswith("git@"):
            # git@github.com:user/repo.git
            remote_url = remote_url.replace("git@", "https://").replace(":", "/", 1)

        # Remove .git suffix
        if remote_url.endswith(".git"):
            remote_url = remote_url[:-4]

        return f"{remote_url}/compare/{base_branch}...{compare_branch}"

    def pull(self) -> Dict:
        """Pull changes from remote.

        Returns:
            Dict with success status and output
        """
        returncode, stdout, stderr = self._run_git("pull")
        if returncode != 0:
            return {"success": False, "error": stderr}

        return {"success": True, "output": stdout or stderr or "Erfolgreich gepullt"}

    # --- GitHub PR Operations (requires gh CLI) ---

    def _run_gh(self, *args) -> Tuple[int, str, str]:
        """Run a GitHub CLI command."""
        cmd = ["gh"] + list(args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=self.repo_path,
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError:
            return 1, "", "GitHub CLI (gh) nicht installiert"
        except Exception as e:
            return 1, "", str(e)

    def create_pr(self, title: str, body: str, base: str = "master") -> Dict:
        """Create a Pull Request.

        Args:
            title: PR title
            body: PR description
            base: Base branch to merge into

        Returns:
            Dict with PR URL and number if successful
        """
        returncode, stdout, stderr = self._run_gh(
            "pr", "create",
            "--title", title,
            "--body", body,
            "--base", base,
        )

        if returncode != 0:
            return {"success": False, "error": stderr}

        # Parse PR URL from output
        pr_url = stdout.strip()

        # Extract PR number from URL
        pr_number = None
        if "/pull/" in pr_url:
            pr_number = pr_url.split("/pull/")[-1].split("/")[0]

        return {
            "success": True,
            "url": pr_url,
            "number": pr_number,
        }

    def merge_pr(self, pr_number: str, delete_branch: bool = True) -> Dict:
        """Merge a Pull Request.

        Args:
            pr_number: PR number to merge
            delete_branch: Delete the branch after merge

        Returns:
            Dict with success status
        """
        args = ["pr", "merge", pr_number, "--merge"]
        if delete_branch:
            args.append("--delete-branch")

        returncode, stdout, stderr = self._run_gh(*args)

        if returncode != 0:
            return {"success": False, "error": stderr}

        return {"success": True, "message": stdout or "PR gemerged"}

    def close_pr(self, pr_number: str, delete_branch: bool = True) -> Dict:
        """Close a Pull Request without merging.

        Args:
            pr_number: PR number to close
            delete_branch: Delete the associated branch

        Returns:
            Dict with success status
        """
        # Close the PR
        returncode, _, stderr = self._run_gh("pr", "close", pr_number)
        if returncode != 0:
            return {"success": False, "error": stderr}

        result = {"success": True, "closed": pr_number}

        # Delete branch if requested
        if delete_branch:
            # Get branch name from PR
            rc, stdout, _ = self._run_gh("pr", "view", pr_number, "--json", "headRefName", "-q", ".headRefName")
            if rc == 0 and stdout:
                branch_name = stdout.strip()
                # Delete remote branch
                self._run_git("push", "origin", "--delete", branch_name)
                # Delete local branch
                self.delete_branch(branch_name, force=True)
                result["deleted_branch"] = branch_name

        return result

    def get_pr_info(self, pr_number: str) -> Dict:
        """Get information about a Pull Request.

        Args:
            pr_number: PR number

        Returns:
            Dict with PR info
        """
        returncode, stdout, stderr = self._run_gh(
            "pr", "view", pr_number,
            "--json", "number,title,state,url,headRefName,baseRefName"
        )

        if returncode != 0:
            return {"success": False, "error": stderr}

        import json as json_module
        try:
            data = json_module.loads(stdout)
            return {"success": True, **data}
        except json_module.JSONDecodeError:
            return {"success": False, "error": "Konnte PR-Info nicht parsen"}


def main():
    parser = argparse.ArgumentParser(
        description="Git operations for Homelab Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Status command
    subparsers.add_parser("status", help="Zeige Repository-Status")

    # Commit command
    commit_parser = subparsers.add_parser("commit", help="Änderungen committen")
    commit_parser.add_argument(
        "--message", "-m",
        help="Commit-Message (optional - wird sonst auto-generiert)"
    )

    # Push command
    subparsers.add_parser("push", help="Zum Remote pushen")

    # Commit-and-push command
    cap_parser = subparsers.add_parser("commit-and-push", help="Committen und pushen")
    cap_parser.add_argument(
        "--message", "-m",
        help="Commit-Message (optional - wird sonst auto-generiert)"
    )

    # Log command
    log_parser = subparsers.add_parser("log", help="Letzte Commits anzeigen")
    log_parser.add_argument("--count", "-n", type=int, default=5, help="Anzahl Commits")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    git = GitAPI()

    if args.command == "status":
        result = git.status()
        if result.get("success"):
            print(f"📍 Branch: {result['branch']}")
            if result.get("tracking"):
                status_parts = []
                if result.get("ahead"):
                    status_parts.append(f"↑{result['ahead']}")
                if result.get("behind"):
                    status_parts.append(f"↓{result['behind']}")
                if status_parts:
                    print(f"   Remote: {result['tracking']} ({', '.join(status_parts)})")
                else:
                    print(f"   Remote: {result['tracking']} (aktuell)")

            if result.get("clean"):
                print("✅ Keine Änderungen")
            else:
                if result.get("staged"):
                    print(f"📦 Staged: {len(result['staged'])} Dateien")
                    for f in result["staged"][:5]:
                        print(f"   • {f}")
                    if len(result["staged"]) > 5:
                        print(f"   ... und {len(result['staged']) - 5} weitere")
                if result.get("modified"):
                    print(f"✏️  Geändert: {len(result['modified'])} Dateien")
                    for f in result["modified"][:5]:
                        print(f"   • {f}")
                if result.get("untracked"):
                    print(f"❓ Neu: {len(result['untracked'])} Dateien")
        else:
            print(f"❌ Fehler: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "commit":
        result = git.commit(message=args.message)
        if result.get("success"):
            print(f"✅ Committed: {result['hash']}")
            print(f"   {result['message']}")
        else:
            print(f"❌ {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "push":
        result = git.push()
        if result.get("success"):
            print(f"✅ {result.get('message')}")
        else:
            print(f"❌ {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "commit-and-push":
        result = git.commit_and_push(message=args.message)
        if result.get("success"):
            commit = result["commit"]
            print(f"✅ Committed: {commit['hash']}")
            print(f"   {commit['message']}")
            print(f"✅ Gepusht!")
        else:
            print(f"❌ {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "log":
        result = git.log(count=args.count)
        if result.get("success"):
            print("📜 Letzte Commits:")
            for commit in result["commits"]:
                print(f"   {commit['hash']} {commit['message']}")
        else:
            print(f"❌ {result.get('error')}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
