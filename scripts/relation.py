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

from datetime import datetime, timezone

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


def approve_relation(
    relation_id: str,
    reviewer: str,
    root: Path | None = None,
) -> dict:
    """Approve a relation (draft/verified -> approved).

    Adds approval metadata and writes back to file.

    Raises:
        FileNotFoundError: if relation_id not found.
    """
    base = root or ROOT
    path = _find_relation_file(relation_id, base)
    if path is None:
        raise FileNotFoundError(f"Relation not found: {relation_id}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data.get("status") == "approved":
        return data  # already approved, no change

    data["status"] = "approved"
    data["approval"] = {
        "reviewer": reviewer,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return data


def format_relation_table(relations: list[dict]) -> str:
    """Format relations as a human-readable table."""
    if not relations:
        return "No relations found."

    lines = [f"{'ID':<20} {'Type':<12} {'Source':<30} {'Target':<30} {'Status':<10}"]
    lines.append("-" * 102)
    for rel in relations:
        lines.append(
            f"{rel['relation_id']:<20} "
            f"{rel.get('type', '?'):<12} "
            f"{rel.get('source_rule', '?'):<30} "
            f"{rel.get('target_rule', '?'):<30} "
            f"{rel.get('status', '?'):<10}"
        )
    lines.append(f"\nTotal: {len(relations)} relation(s)")
    return "\n".join(lines)


def main():
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage Rule Relations.")
    parser.add_argument("--list", action="store_true", help="List all relations")
    parser.add_argument("--status", help="Filter by status (for --list)")
    parser.add_argument("--validate", metavar="REL_ID", help="Validate a relation against schema")
    parser.add_argument("--create", action="store_true", help="Create a new relation")
    parser.add_argument("--approve", metavar="REL_ID", help="Approve a relation")
    parser.add_argument("--reviewer", default="HB", help="Reviewer name (default: HB)")

    # --create fields
    parser.add_argument("--id", help="Relation ID (for --create)")
    parser.add_argument("--type", help="Relation type: excepts|overrides|supersedes|unresolved")
    parser.add_argument("--source", help="Source rule_id")
    parser.add_argument("--target", help="Target rule_id")
    parser.add_argument("--condition", help="When this relation fires")
    parser.add_argument("--resolution", help="What Agent should do")
    parser.add_argument("--basis", help="Authority basis")

    args = parser.parse_args()

    if args.list:
        relations = list_relations(status_filter=args.status)
        print(format_relation_table(relations))
        return

    if args.validate:
        result = validate_relation(args.validate)
        if result["valid"]:
            print(f"VALID: {args.validate}")
        else:
            print(f"INVALID: {args.validate}")
            for err in result["errors"]:
                print(f"  - {err}")
            sys.exit(1)
        return

    if args.approve:
        try:
            data = approve_relation(args.approve, reviewer=args.reviewer)
            print(f"APPROVED: {args.approve} (reviewer: {data['approval']['reviewer']})")
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.create:
        missing = []
        for field in ("id", "type", "source", "target", "condition", "resolution", "basis"):
            if not getattr(args, field):
                missing.append(f"--{field}")
        if missing:
            parser.error(f"--create requires: {', '.join(missing)}")

        try:
            path = create_relation(
                relation_id=args.id,
                rel_type=args.type,
                source_rule=args.source,
                target_rule=args.target,
                condition=args.condition,
                resolution=args.resolution,
                authority_basis=args.basis,
                registered_by=args.reviewer,
            )
            print(f"Created: {path}")
            print("Status: draft (use --approve to approve)")
        except (ValueError, Exception) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
