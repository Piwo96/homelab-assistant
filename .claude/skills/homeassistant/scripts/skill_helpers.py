"""Shared helpers for skill *_api.py scripts.

Currently provides --help-json introspection so the TypeScript agent loader
can derive Zod schemas from argparse subparsers without parsing --help text.

Convention:
- Every script adds: parser.add_argument("--help-json", action="store_true")
- Subparsers that mutate state set: subparser.set_defaults(_is_write=True)
- main() checks args.help_json and calls emit_help_json(parser) before normal dispatch.
"""

import argparse
import json
import sys
from typing import Any


def _arg_to_dict(action: argparse.Action) -> dict[str, Any]:
    py_type = getattr(action, "type", None)
    type_name = "str"
    if py_type is int:
        type_name = "int"
    elif py_type is float:
        type_name = "float"
    elif py_type is bool:
        type_name = "bool"
    if isinstance(action, argparse._StoreTrueAction) or isinstance(action, argparse._StoreFalseAction):
        type_name = "bool"
    name = action.dest
    is_flag = bool(action.option_strings)
    required = action.required if is_flag else (action.default is None and action.nargs is None)
    out: dict[str, Any] = {
        "name": name,
        "type": type_name,
        "required": required,
        "description": action.help or "",
    }
    if action.choices is not None:
        out["choices"] = list(action.choices)
    if action.default is not argparse.SUPPRESS and action.default is not None:
        out["default"] = action.default
    if action.nargs in ("+", "*"):
        out["nargs"] = action.nargs
    return out


def emit_help_json(parser: argparse.ArgumentParser) -> None:
    """Walk subparsers and emit a JSON description of all commands to stdout."""
    commands: dict[str, Any] = {}
    subparsers_action = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers_action = action
            break
    if subparsers_action is None:
        json.dump({"description": parser.description or "", "commands": {}}, sys.stdout)
        sys.stdout.write("\n")
        return
    for cmd_name, sub in subparsers_action.choices.items():
        defaults = getattr(sub, "_defaults", {})
        is_write = bool(defaults.get("_is_write", False))
        args = []
        for action in sub._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if action.dest == "help_json":
                continue
            if action.dest.startswith("_"):
                continue
            args.append(_arg_to_dict(action))
        commands[cmd_name] = {
            "description": (subparsers_action.choices[cmd_name].description
                            or subparsers_action._choices_actions[
                                list(subparsers_action.choices.keys()).index(cmd_name)
                            ].help
                            or ""),
            "is_write": is_write,
            "args": args,
        }
    payload = {"description": parser.description or "", "commands": commands}
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
