"""Orphan Relation Cascade.

When a Rule Unit status changes to suspended/superseded,
find all Relations that reference it (as source_rule or target_rule)
and transition their status:
  - approved -> suspended (with suspension_reason)
  - draft/verified -> rejected (with rejection_reason)

Usage:
  python3 cascade.py --check        # dry-run: list orphaned relations
  python3 cascade.py --apply        # apply cascade to files
"""

import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# Rule Unit statuses that trigger cascade on referencing Relations
_CASCADE_TRIGGERS = {"suspended", "superseded"}


def _load_all_rules(root: Path | None = None) -> dict[str, str]:
    """Load all rules. Returns {rule_id: status}."""
    base = root or ROOT
    rules_dir = base / "rules"
    index: dict[str, str] = {}
    if not rules_dir.exists():
        return index
    for path in rules_dir.rglob("*.yaml"):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "rule_id" in data:
            index[data["rule_id"]] = data.get("status", "")
    return index


def _load_all_relations(root: Path | None = None) -> list[tuple[Path, dict]]:
    """Load all relations with their file paths."""
    base = root or ROOT
    rel_dir = base / "relations"
    relations = []
    if not rel_dir.exists():
        return relations
    for path in sorted(rel_dir.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            relations.append((path, data))
    return relations


def find_orphan_relations(root: Path | None = None) -> list[tuple[Path, dict, str]]:
    """Find relations referencing suspended/superseded Rule Units.

    Returns list of (path, relation, reason) tuples.
    """
    rule_index = _load_all_rules(root)
    relations = _load_all_relations(root)
    orphans = []

    for path, rel in relations:
        status = rel.get("status", "")
        if status in ("rejected", "suspended"):
            continue  # already handled

        source_id = rel.get("source_rule", "")
        target_id = rel.get("target_rule", "")

        source_status = rule_index.get(source_id, "")
        target_status = rule_index.get(target_id, "")

        reasons = []
        if source_status in _CASCADE_TRIGGERS:
            reasons.append(f"source_rule '{source_id}' is {source_status}")
        if target_status in _CASCADE_TRIGGERS:
            reasons.append(f"target_rule '{target_id}' is {target_status}")

        if reasons:
            reason = "; ".join(reasons)
            orphans.append((path, rel, reason))

    return orphans


def cascade_relation(relation: dict, reason: str) -> dict:
    """Apply cascade status transition to a relation.

    - approved -> suspended + suspension_reason
    - draft/verified -> rejected + rejection_reason
    - already suspended/rejected -> no change (idempotent)
    """
    result = copy.deepcopy(relation)
    current = result.get("status")

    if current == "approved":
        result["status"] = "suspended"
        result["suspension_reason"] = reason
        # Remove approval metadata (no longer valid)
    elif current in ("draft", "verified"):
        result["status"] = "rejected"
        result["rejection_reason"] = reason

    return result


def main():
    """CLI: Check or apply orphan relation cascade."""
    do_apply = "--apply" in sys.argv
    do_check = "--check" in sys.argv or not do_apply

    orphans = find_orphan_relations(ROOT)

    if not orphans:
        print("No orphan relations found. All relations reference active Rule Units.")
        sys.exit(0)

    print(f"\n{len(orphans)} orphan relation(s) found:\n")

    for path, rel, reason in orphans:
        rel_id = rel.get("relation_id", path.name)
        current_status = rel.get("status", "?")
        cascaded = cascade_relation(rel, reason)
        new_status = cascaded.get("status", "?")
        print(f"  {rel_id}: {current_status} -> {new_status}")
        print(f"    reason: {reason}")

    if do_check and not do_apply:
        print(f"\nDry-run complete. Use --apply to persist changes.")
        sys.exit(0)

    if do_apply:
        applied = 0
        for path, rel, reason in orphans:
            cascaded = cascade_relation(rel, reason)
            if cascaded.get("status") != rel.get("status"):
                with open(path, "w", encoding="utf-8") as f:
                    yaml.dump(
                        cascaded, f,
                        allow_unicode=True,
                        default_flow_style=False,
                        sort_keys=False,
                    )
                applied += 1
        print(f"\nApplied cascade to {applied} relation(s).")


if __name__ == "__main__":
    main()
