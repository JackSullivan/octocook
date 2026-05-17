"""Kitchen preset loader.

A kitchen preset is a directory under server/presets/ containing
`inventory.yaml` and `substitutions.yaml`. The directory name is the
preset key the API surfaces.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml


_PRESETS_DIR = Path(__file__).parent / "presets"

_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass(frozen=True)
class KitchenPreset:
    name: str
    inventory_path: Path
    substitutions_path: Path


def _validate_name(name: str) -> None:
    if not name:
        raise ValueError("Kitchen name cannot be empty.")
    if not _NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid kitchen name {name!r}. Use letters, numbers, dash, underscore."
        )


def _kitchen_dir(name: str) -> Path:
    _validate_name(name)
    return _PRESETS_DIR / name


def list_kitchens() -> list[KitchenPreset]:
    presets: list[KitchenPreset] = []
    if not _PRESETS_DIR.exists():
        return presets
    for entry in sorted(_PRESETS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        inv = entry / "inventory.yaml"
        subs = entry / "substitutions.yaml"
        if not inv.is_file() or not subs.is_file():
            continue
        presets.append(KitchenPreset(name=entry.name, inventory_path=inv, substitutions_path=subs))
    return presets


def get_kitchen(name: str) -> KitchenPreset:
    for p in list_kitchens():
        if p.name == name:
            return p
    raise KeyError(f"No kitchen preset named {name!r}.")


def read_kitchen(name: str) -> dict:
    """Return the kitchen's parsed inventory + raw substitutions YAML text.

    The substitutions file is returned as text (rather than parsed) so the UI
    editor preserves the user's comments and formatting on round-trip.
    """
    p = get_kitchen(name)
    with open(p.inventory_path) as f:
        inventory = yaml.safe_load(f) or {}
    with open(p.substitutions_path) as f:
        substitutions_yaml = f.read()
    return {"name": name, "inventory": inventory, "substitutions_yaml": substitutions_yaml}


def _validate_inventory(inventory: dict) -> dict[str, int]:
    """Normalize inventory to {tool: int}. Raises ValueError on bad input."""
    if not isinstance(inventory, dict):
        raise ValueError("inventory must be a mapping of tool -> count.")
    cleaned: dict[str, int] = {}
    for tool, count in inventory.items():
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError(f"Invalid tool name {tool!r}.")
        try:
            n = int(count)
        except (TypeError, ValueError):
            raise ValueError(f"Tool {tool!r} count must be an integer, got {count!r}.")
        if n < 0:
            raise ValueError(f"Tool {tool!r} count must be >= 0.")
        cleaned[tool.strip()] = n
    return cleaned


def _validate_substitutions(subs: dict) -> dict[str, list[dict]]:
    """Validate the substitutions structure: tool -> [{tool|null, time_multiplier, note}]."""
    if not isinstance(subs, dict):
        raise ValueError("substitutions must be a mapping of tool -> rule list.")
    cleaned: dict[str, list[dict]] = {}
    for tool, chain in subs.items():
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError(f"Invalid substitution key {tool!r}.")
        if not isinstance(chain, list):
            raise ValueError(f"Substitutions for {tool!r} must be a list.")
        cleaned_chain: list[dict] = []
        for entry in chain:
            if not isinstance(entry, dict):
                raise ValueError(f"Each rule for {tool!r} must be a mapping.")
            sub_tool = entry.get("tool")
            if sub_tool is not None and not isinstance(sub_tool, str):
                raise ValueError(f"Rule.tool for {tool!r} must be a string or null.")
            mult = entry.get("time_multiplier", 1.0)
            try:
                mult = float(mult)
            except (TypeError, ValueError):
                raise ValueError(f"Rule.time_multiplier for {tool!r} must be a number.")
            note = entry.get("note", "")
            if not isinstance(note, str):
                raise ValueError(f"Rule.note for {tool!r} must be a string.")
            cleaned_chain.append({"tool": sub_tool, "time_multiplier": mult, "note": note})
        cleaned[tool.strip()] = cleaned_chain
    return cleaned


def write_kitchen(name: str, inventory: dict, substitutions_yaml: str) -> None:
    """Persist a kitchen. inventory is structured; substitutions is raw YAML text.

    The text is parsed for validation but written verbatim, preserving comments.
    """
    d = _kitchen_dir(name)
    inv = _validate_inventory(inventory)
    try:
        subs_parsed = yaml.safe_load(substitutions_yaml) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Substitutions YAML parse error: {e}")
    _validate_substitutions(subs_parsed)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "inventory.yaml", "w") as f:
        yaml.safe_dump(inv, f, sort_keys=True, default_flow_style=False)
    with open(d / "substitutions.yaml", "w") as f:
        f.write(substitutions_yaml)


def kitchen_exists(name: str) -> bool:
    try:
        d = _kitchen_dir(name)
    except ValueError:
        return False
    return d.is_dir()


def delete_kitchen(name: str) -> None:
    d = _kitchen_dir(name)
    if not d.is_dir():
        raise KeyError(f"Kitchen {name!r} not found.")
    shutil.rmtree(d)
