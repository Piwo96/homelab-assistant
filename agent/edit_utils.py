"""Edit utilities for safe, targeted code modifications.

Instead of replacing entire files (which leads to lost code), this module
provides search-and-replace operations that only modify specific parts.

Supports three edit modes:
1. Exact match: old_string must match exactly
2. Fuzzy match: normalizes whitespace before matching
3. Insert after: finds a marker line and inserts code after it
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace for fuzzy matching.

    - Converts all line endings to \n
    - Removes trailing whitespace from lines
    - Preserves leading indentation
    - Collapses multiple blank lines to one
    """
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    # Remove trailing whitespace from each line
    lines = [line.rstrip() for line in lines]
    # Collapse multiple blank lines
    result = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank
    return '\n'.join(result)


def find_fuzzy_match(content: str, search: str) -> tuple[int, int] | None:
    """Find a fuzzy match in content, tolerating whitespace differences.

    Returns (start, end) indices of the match, or None if not found.
    """
    # First try exact match
    idx = content.find(search)
    if idx != -1:
        return (idx, idx + len(search))

    # Normalize both and try again
    norm_content = normalize_whitespace(content)
    norm_search = normalize_whitespace(search)

    idx = norm_content.find(norm_search)
    if idx == -1:
        return None

    # Map back to original content position
    # This is tricky - we need to find corresponding position in original
    # Strategy: find unique lines from the search that exist in content
    search_lines = [l.rstrip() for l in search.split('\n') if l.strip()]
    if not search_lines:
        return None

    # Find first non-empty line
    first_line = search_lines[0]
    last_line = search_lines[-1]

    # Find in original content
    start_idx = content.find(first_line)
    if start_idx == -1:
        # Try without leading whitespace
        first_line_stripped = first_line.strip()
        for i, line in enumerate(content.split('\n')):
            if line.strip() == first_line_stripped:
                start_idx = content.find(line)
                break

    if start_idx == -1:
        return None

    # Find last line
    end_search_start = start_idx
    end_idx = content.find(last_line, end_search_start)
    if end_idx == -1:
        last_line_stripped = last_line.strip()
        lines = content.split('\n')
        cumulative = 0  # Track position incrementally for O(n) complexity
        for i, line in enumerate(lines):
            if cumulative >= start_idx and line.strip() == last_line_stripped:
                end_idx = cumulative
                break
            cumulative += len(line) + 1  # +1 for newline

    if end_idx == -1:
        return None

    # Validate that end comes after start
    if end_idx < start_idx:
        logger.warning(f"Fuzzy match found last_line before first_line")
        return None

    # End position is after the last line
    end_idx = end_idx + len(last_line)
    # Include trailing newline if present
    if end_idx < len(content) and content[end_idx] == '\n':
        end_idx += 1

    return (start_idx, end_idx)


def apply_edit(
    file_path: Path,
    old_string: str,
    new_string: str,
    fuzzy: bool = True,
) -> dict[str, Any]:
    """Apply a single search-and-replace edit to a file.

    Args:
        file_path: Path to the file to edit
        old_string: The string to find and replace
        new_string: The string to replace it with
        fuzzy: If True, use fuzzy matching when exact match fails

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

    # Try exact match first
    match_pos = None
    match_method = "exact"

    if old_string in content:
        # Check for uniqueness
        count = content.count(old_string)
        if count > 1:
            return {
                "success": False,
                "error": f"old_string found {count} times in {file_path.name}. Must be unique.",
                "hint": "Provide more context in old_string to make it unique.",
            }
        match_pos = (content.find(old_string), content.find(old_string) + len(old_string))

    # Try fuzzy match if exact failed
    elif fuzzy:
        match_pos = find_fuzzy_match(content, old_string)
        if match_pos:
            match_method = "fuzzy"
            logger.info(f"Using fuzzy match for {file_path.name}")

    if not match_pos:
        return {
            "success": False,
            "error": f"old_string not found in {file_path.name}. Cannot apply edit.",
            "hint": "The file may have changed or the old_string is incorrect.",
        }

    # Apply the replacement
    start, end = match_pos
    new_content = content[:start] + new_string + content[end:]

    try:
        file_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write file: {e}",
        }

    logger.info(f"Applied edit ({match_method}) to {file_path.name}")
    return {
        "success": True,
        "file": str(file_path),
        "chars_removed": end - start,
        "chars_added": len(new_string),
        "match_method": match_method,
    }


def apply_insert_after(
    file_path: Path,
    marker: str,
    content_to_insert: str,
) -> dict[str, Any]:
    """Insert content after a marker line.

    This is more robust than old_string/new_string for appending code,
    as it only needs to find a unique marker line.

    Args:
        file_path: Path to the file to edit
        marker: A unique line/string to find (e.g., "class MyClass:" or "def main():")
        content_to_insert: The content to insert after the marker line

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

    # Find the marker
    marker_stripped = marker.strip()

    # Try exact match first
    if marker in content:
        # Check uniqueness
        count = content.count(marker)
        if count > 1:
            return {
                "success": False,
                "error": f"Marker found {count} times in {file_path.name}. Must be unique.",
                "hint": "Provide more context in marker to make it unique.",
            }
        idx = content.find(marker)
        # Find end of line
        end_of_line = content.find('\n', idx)
        if end_of_line == -1:
            end_of_line = len(content)
        insert_pos = end_of_line + 1
    else:
        # Try line-by-line fuzzy match
        lines = content.split('\n')
        insert_pos = None
        cumulative = 0
        match_count = 0

        for i, line in enumerate(lines):
            # Exact stripped match OR marker is substring of line
            if line.strip() == marker_stripped or marker_stripped in line:
                if insert_pos is None:
                    insert_pos = cumulative + len(line) + 1  # +1 for newline
                match_count += 1
            cumulative += len(line) + 1

        # Check uniqueness
        if match_count > 1:
            return {
                "success": False,
                "error": f"Marker found {match_count} times in {file_path.name}. Must be unique.",
                "hint": "Provide more context in marker to make it unique.",
            }

        if insert_pos is None:
            return {
                "success": False,
                "error": f"Marker '{marker[:50]}...' not found in {file_path.name}",
            }

    # Insert the content
    new_content = content[:insert_pos] + content_to_insert + content[insert_pos:]

    try:
        file_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write file: {e}",
        }

    logger.info(f"Inserted content after marker in {file_path.name}")
    return {
        "success": True,
        "file": str(file_path),
        "chars_added": len(content_to_insert),
    }


def apply_insert_before(
    file_path: Path,
    marker: str,
    content_to_insert: str,
) -> dict[str, Any]:
    """Insert content before a marker line.

    Useful for adding methods to a class before a specific function like main().

    Args:
        file_path: Path to the file to edit
        marker: A unique line/string to find (e.g., "def main():" or "if __name__")
        content_to_insert: The content to insert before the marker line

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

    # Find the marker
    marker_stripped = marker.strip()
    insert_pos = None

    # Try exact match first
    if marker in content:
        # Check uniqueness
        count = content.count(marker)
        if count > 1:
            return {
                "success": False,
                "error": f"Marker found {count} times in {file_path.name}. Must be unique.",
                "hint": "Provide more context in marker to make it unique.",
            }
        insert_pos = content.find(marker)
    else:
        # Try line-by-line fuzzy match
        lines = content.split('\n')
        cumulative = 0
        match_count = 0

        for i, line in enumerate(lines):
            if line.strip() == marker_stripped or marker_stripped in line:
                if insert_pos is None:
                    insert_pos = cumulative
                match_count += 1
            cumulative += len(line) + 1

        # Check uniqueness
        if match_count > 1:
            return {
                "success": False,
                "error": f"Marker found {match_count} times in {file_path.name}. Must be unique.",
                "hint": "Provide more context in marker to make it unique.",
            }

    if insert_pos is None:
        return {
            "success": False,
            "error": f"Marker '{marker[:50]}...' not found in {file_path.name}",
        }

    # Insert the content
    new_content = content[:insert_pos] + content_to_insert + content[insert_pos:]

    try:
        file_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write file: {e}",
        }

    logger.info(f"Inserted content before marker in {file_path.name}")
    return {
        "success": True,
        "file": str(file_path),
        "chars_added": len(content_to_insert),
    }


def apply_edits(
    edits: list[dict[str, str]],
    base_path: Path,
) -> dict[str, Any]:
    """Apply multiple edits to files.

    Supports two edit types:
    1. Replace: old_string + new_string (with fuzzy matching)
    2. Insert after: marker + insert (finds marker line and inserts after)

    Args:
        edits: List of edit operations, each with:
            - path: Relative path to file
            For replace: old_string, new_string
            For insert: marker, insert
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

        if not rel_path:
            errors.append({"error": "Missing path in edit"})
            continue

        # Resolve and validate path
        full_path = (base_path / rel_path).resolve()

        # Security check: ensure path stays within base_path
        if not str(full_path).startswith(str(base_path.resolve())):
            errors.append({
                "path": rel_path,
                "error": "Path traversal attempt blocked",
            })
            continue

        # Determine edit type
        if "marker" in edit and "insert" in edit:
            # Insert after marker mode
            result = apply_insert_after(
                full_path,
                edit["marker"],
                edit["insert"],
            )
        elif "marker" in edit and "insert_before" in edit:
            # Insert before marker mode
            result = apply_insert_before(
                full_path,
                edit["marker"],
                edit["insert_before"],
            )
        elif "old_string" in edit:
            # Traditional replace mode
            old_string = edit.get("old_string", "")
            new_string = edit.get("new_string", "")

            if not old_string:
                errors.append({"path": rel_path, "error": "Missing old_string in edit"})
                continue

            # new_string can be empty (for deletions)
            if new_string is None:
                new_string = ""

            result = apply_edit(full_path, old_string, new_string)
        else:
            errors.append({
                "path": rel_path,
                "error": "Edit must have either (old_string, new_string) or (marker, insert)",
            })
            continue

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
