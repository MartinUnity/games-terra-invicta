"""Shared utilities for mod balance checking scripts."""
from __future__ import annotations

import json
from itertools import chain
from pathlib import Path
from typing import Any

_WORKSPACE = Path(__file__).resolve().parent.parent.parent.parent
MODS_DIR = _WORKSPACE / "Mods"
GAME_DIR = _WORKSPACE / "Game-ModsDir"


def parse_num(value: Any) -> float:
    """Parse a numeric value, handling comma-separated strings."""
    if value is None:
        return 0.0
    s = str(value).replace(",", "")
    return float(s)


def load_templates(directory: Path) -> dict[str, dict]:
    """Load all project/tech templates from a directory."""
    result: dict[str, dict] = {}
    for fp in chain(
        directory.glob("*ProjectTemplate.json"),
        directory.glob("*TechTemplate.json"),
    ):
        try:
            with fp.open("r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "dataName" in item:
                        result[item["dataName"]] = item
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return result


def build_registry() -> dict[str, dict]:
    """Merge game and mod templates (mod takes priority)."""
    registry: dict[str, dict] = {}
    registry.update(load_templates(GAME_DIR))
    registry.update(load_templates(MODS_DIR))
    return registry


def get_all_prereqs(
    name: str, registry: dict[str, dict], visited: set[str] | None = None
) -> set[str]:
    """Recursively collect all transitive prereqs (including altPrereq*)."""
    if visited is None:
        visited = set()
    if name in visited:
        return set()
    visited.add(name)
    item = registry.get(name)
    if not item:
        return set()
    prereqs: set[str] = set()
    for p in item.get("prereqs", []):
        prereqs.add(p)
        prereqs.update(get_all_prereqs(p, registry, visited))
    for k, v in item.items():
        if k.startswith("altPrereq") and isinstance(v, str):
            prereqs.add(v)
            prereqs.update(get_all_prereqs(v, registry, visited))
    return prereqs


def total_prereq_cost(name: str, registry: dict[str, dict]) -> int:
    """Calculate total research cost including all transitive prereqs."""
    prereqs = get_all_prereqs(name, registry)
    total = 0
    for p in prereqs:
        item = registry.get(p)
        if item:
            total += item.get("researchCost", 0)
    self_item = registry.get(name)
    if self_item:
        total += self_item.get("researchCost", 0)
    return total


def load_drive_templates(directory: Path, source: str) -> list[dict]:
    """Load all drive templates from a directory."""
    drives: list[dict] = []
    for fp in directory.glob("*DriveTemplate.json"):
        try:
            with fp.open("r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "dataName" in item:
                        item["_source"] = source
                        drives.append(item)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return drives


def load_armor_templates(directory: Path, source: str) -> list[dict]:
    """Load all armor templates from a directory."""
    armors: list[dict] = []
    for fp in directory.glob("*ArmorTemplate.json"):
        try:
            with fp.open("r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "dataName" in item:
                        item["_source"] = source
                        armors.append(item)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return armors
