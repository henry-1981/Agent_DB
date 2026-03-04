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

import jsonschema
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


def _load_relation_schema(root: Path) -> dict:
    """Load rule-relation JSON Schema."""
    schema_path = root / "schemas" / "rule-relation.schema.yaml"
    with open(schema_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _find_relation_file(relation_id: str, root: Path) -> Path | None:
    """Find the YAML file for a given relation_id."""
    rel_dir = root / "relations"
    if not rel_dir.exists():
        return None
    for path in rel_dir.glob("*.yaml"):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and data.get("relation_id") == relation_id:
            return path
    return None


def validate_relation(
    relation_id: str,
    root: Path | None = None,
) -> dict:
    """Validate a relation against the JSON Schema.

    Returns:
        {"valid": bool, "errors": list[str], "relation": dict | None}
    """
    base = root or ROOT
    path = _find_relation_file(relation_id, base)
    if path is None:
        return {"valid": False, "errors": [f"Relation not found: {relation_id}"], "relation": None}

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    schema = _load_relation_schema(base)
    errors = []
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        errors.append(e.message)
    except jsonschema.SchemaError as e:
        errors.append(f"Schema error: {e.message}")

    return {"valid": len(errors) == 0, "errors": errors, "relation": data}


def create_relation(
    relation_id: str,
    rel_type: str,
    source_rule: str,
    target_rule: str,
    condition: str,
    resolution: str,
    authority_basis: str,
    registered_by: str,
    root: Path | None = None,
) -> Path:
    """Create a new relation YAML file with schema validation.

    Creates with status=draft. Use approve_relation() to approve.

    Raises:
        ValueError: if relation_id already exists.
        jsonschema.ValidationError: if data fails schema validation.
    """
    base = root or ROOT
    rel_dir = base / "relations"
    rel_dir.mkdir(parents=True, exist_ok=True)

    # Check duplicate
    existing = _find_relation_file(relation_id, base)
    if existing is not None:
        raise ValueError(f"Relation '{relation_id}' already exists: {existing}")

    data = {
        "relation_id": relation_id,
        "type": rel_type,
        "source_rule": source_rule,
        "target_rule": target_rule,
        "condition": condition,
        "resolution": resolution,
        "authority_basis": authority_basis,
        "registered_by": registered_by,
        "status": "draft",
    }

    # Validate against schema before writing
    schema = _load_relation_schema(base)
    jsonschema.validate(data, schema)

    filepath = rel_dir / f"{relation_id}.yaml"
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return filepath
