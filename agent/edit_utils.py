"""Edit utilities for safe, targeted code modifications.

Instead of replacing entire files (which leads to lost code), this module
provides search-and-replace operations that only modify specific parts.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def apply_edit(
    file_path: Path,
    old_string: str,
    new_string: str,
) -> dict[str, Any]:
    """Apply a single search-and-replace edit to a file.

    Args:
        file_path: Path to the file to edit
        old_string: The exact string to find and replace
        new_string: The string to replace it with

    Returns:
        Dict with success status and details
    """
    if not file_path.exists():
        return {
            "success": False,
            "error": f"File not found: {file_path}",
        }

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read file: {e}",
        }

    # Check if old_string exists in file
    if old_string not in content:
        return {
            "success": False,
            "error": f"old_string not found in {file_path.name}. Cannot apply edit.",
            "hint": "The file may have changed or the old_string is incorrect.",
        }

    # Check for uniqueness - old_string should appear exactly once
    count = content.count(old_string)
    if count > 1:
        return {
            "success": False,
            "error": f"old_string found {count} times in {file_path.name}. Must be unique.",
            "hint": "Provide more context in old_string to make it unique.",
        }

    # Apply the replacement
    new_content = content.replace(old_string, new_string, 1)

    try:
        file_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write file: {e}",
        }

    logger.info(f"Applied edit to {file_path.name}")
    return {
        "success": True,
        "file": str(file_path),
        "chars_removed": len(old_string),
        "chars_added": len(new_string),
    }


def apply_edits(
    edits: list[dict[str, str]],
    base_path: Path,
) -> dict[str, Any]:
    """Apply multiple edits to files.

    Args:
        edits: List of edit operations, each with:
            - path: Relative path to file
            - old_string: String to find
            - new_string: String to replace with
        base_path: Base path to resolve relative paths against

    Returns:
        Dict with success status, applied edits, and any errors
    """
    if not edits:
        return {"success": False, "error": "No edits provided"}

    applied = []
    errors = []

    for edit in edits:
        rel_path = edit.get("path", "")
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")

        if not rel_path:
            errors.append({"error": "Missing path in edit"})
            continue

        if not old_string:
            errors.append({"path": rel_path, "error": "Missing old_string in edit"})
            continue

        # new_string can be empty (for deletions)
        if new_string is None:
            new_string = ""

        # Resolve and validate path
        full_path = (base_path / rel_path).resolve()

        # Security check: ensure path stays within base_path
        if not str(full_path).startswith(str(base_path.resolve())):
            errors.append({
                "path": rel_path,
                "error": "Path traversal attempt blocked",
            })
            continue

        result = apply_edit(full_path, old_string, new_string)

        if result["success"]:
            applied.append(rel_path)
        else:
            errors.append({
                "path": rel_path,
                "error": result.get("error"),
                "hint": result.get("hint"),
            })

    return {
        "success": len(errors) == 0,
        "applied": applied,
        "errors": errors if errors else None,
    }


def write_new_file(
    file_path: Path,
    content: str,
    base_path: Path,
) -> dict[str, Any]:
    """Write a completely new file (for 'create' operations only).

    Args:
        file_path: Relative path for the new file
        content: Full content of the new file
        base_path: Base path to resolve relative paths against

    Returns:
        Dict with success status
    """
    full_path = (base_path / file_path).resolve()

    # Security check
    if not str(full_path).startswith(str(base_path.resolve())):
        return {
            "success": False,
            "error": "Path traversal attempt blocked",
        }

    # Check if file already exists
    if full_path.exists():
        return {
            "success": False,
            "error": f"File already exists: {file_path}. Use edits to modify existing files.",
        }

    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        logger.info(f"Created new file: {full_path}")
        return {"success": True, "file": str(file_path)}
    except Exception as e:
        return {"success": False, "error": f"Failed to write file: {e}"}


def apply_changes(
    changes: dict[str, Any],
    base_path: Path,
) -> dict[str, Any]:
    """Apply a mix of new files and edits.

    This is the main entry point for applying Claude's suggested changes.

    Args:
        changes: Dict with optional keys:
            - new_files: List of {path, content} for new files
            - edits: List of {path, old_string, new_string} for modifications
        base_path: Base path to resolve relative paths against

    Returns:
        Dict with success status and details
    """
    new_files = changes.get("new_files", [])
    edits = changes.get("edits", [])

    results = {
        "success": True,
        "files_created": [],
        "files_edited": [],
        "errors": [],
    }

    # First, create any new files
    for file_info in new_files:
        rel_path = file_info.get("path", "")
        content = file_info.get("content", "")

        if not rel_path or not content:
            results["errors"].append({"error": "Missing path or content for new file"})
            continue

        result = write_new_file(Path(rel_path), content, base_path)

        if result["success"]:
            results["files_created"].append(rel_path)
        else:
            results["errors"].append({
                "path": rel_path,
                "error": result.get("error"),
            })

    # Then apply edits
    if edits:
        edit_result = apply_edits(edits, base_path)

        results["files_edited"] = edit_result.get("applied", [])

        if edit_result.get("errors"):
            results["errors"].extend(edit_result["errors"])

    # Overall success only if no errors
    results["success"] = len(results["errors"]) == 0

    return results
