"""Dynamic module import for skill scripts.

Loads skill scripts via importlib so the agent can call execute()
directly instead of spawning subprocesses.
"""

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_module_cache: dict[str, ModuleType] = {}


def load_skill_module(script_path: Path) -> Optional[ModuleType]:
    """Dynamically import a skill script as a Python module.

    Modules are cached after first import. The script's parent directory
    is added to sys.path to support cross-skill imports (e.g. protect → network).

    Args:
        script_path: Absolute path to the Python script

    Returns:
        Loaded module, or None on failure
    """
    cache_key = str(script_path)
    if cache_key in _module_cache:
        return _module_cache[cache_key]

    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return None

    try:
        # Ensure script directory is in sys.path for relative imports
        script_dir = str(script_path.parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)

        module_name = f"skill_{script_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _module_cache[cache_key] = module
        return module
    except Exception as e:
        logger.error(f"Failed to import {script_path}: {e}")
        return None


def get_execute_fn(script_path: Path) -> Optional[Callable]:
    """Get the execute() function from a skill module.

    Args:
        script_path: Absolute path to the skill script

    Returns:
        The execute function, or None if not found
    """
    module = load_skill_module(script_path)
    if module and hasattr(module, "execute"):
        return module.execute
    return None
