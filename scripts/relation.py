"""Relation management CLI.

Create, list, validate, and approve Rule Relations.

Usage:
  python3 relation.py --list [--status approved|suspended|...]
  python3 relation.py --create --type excepts --source RULE --target RULE ...
  python3 relation.py --validate REL_ID
  python3 relation.py --approve REL_ID --reviewer HB
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def list_relations(
    root: Path | None = None,
    status_filter: str | None = None,
) -> list[dict]:
    """Load and optionally filter relations.

    Args:
        root: project root directory.
        status_filter: if set, only return relations with this status.

    Returns:
        List of relation dicts sorted by relation_id.
    """
    base = root or ROOT
    rel_dir = base / "relations"
    if not rel_dir.exists():
        return []

    relations = []
    for path in sorted(rel_dir.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "relation_id" in data:
            if status_filter and data.get("status") != status_filter:
                continue
            relations.append(data)

    return relations
