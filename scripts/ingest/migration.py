"""Relation Migration Guide Generator.

When a source document version changes, existing Relations referencing
the old-version Rule Units become suspended (via cascade.py).
This module generates a migration guide that:
  1. Finds suspended Relations for a given doc_id
  2. Finds new Rule Units (new version)
  3. Matches old rule references to new rule candidates by ID pattern
  4. Outputs a human-readable migration guide

Usage (called from ingest.py --version-update):
  guide = generate_relation_migration_guide(doc_id, old_ver, new_ver, root)
  print(format_migration_guide(guide))
"""

from pathlib import Path

import yaml

# Relation types that require mandatory human review
_HUMAN_REVIEW_TYPES = {"excepts", "overrides", "unresolved"}


def _load_relations(root: Path) -> list[dict]:
    """Load all relation YAML files from relations/ directory."""
    rel_dir = root / "relations"
    if not rel_dir.exists():
        return []
    relations = []
    for path in sorted(rel_dir.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            relations.append(data)
    return relations


def _load_rules(root: Path) -> list[dict]:
    """Load all rule YAML files from rules/ directory."""
    rules_dir = root / "rules"
    if not rules_dir.exists():
        return []
    rules = []
    for path in rules_dir.rglob("*.yaml"):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "rule_id" in data:
            rules.append(data)
    return rules


def _extract_suffix(rule_id: str, doc_id: str) -> str | None:
    """Extract the suffix portion after doc_id prefix.

    E.g., "kmdia-fc-art6-p1-main" with doc_id "kmdia-fc"
    returns "art6-p1-main".
    """
    prefix = doc_id + "-"
    if rule_id.startswith(prefix):
        return rule_id[len(prefix):]
    return None


def find_suspended_relations(doc_id: str, root: Path) -> list[dict]:
    """Find suspended relations where source_rule or target_rule matches doc_id.

    A relation matches if its source_rule or target_rule starts with
    the doc_id prefix (e.g., "kmdia-fc-").
    """
    prefix = doc_id + "-"
    relations = _load_relations(root)
    return [
        rel for rel in relations
        if rel.get("status") == "suspended"
        and (
            rel.get("source_rule", "").startswith(prefix)
            or rel.get("target_rule", "").startswith(prefix)
        )
    ]


def find_rules_by_doc_and_version(
    doc_id: str, version: str, root: Path
) -> list[dict]:
    """Find rule units matching doc_id and source_ref.version."""
    prefix = doc_id + "-"
    rules = _load_rules(root)
    return [
        rule for rule in rules
        if rule["rule_id"].startswith(prefix)
        and rule.get("source_ref", {}).get("version") == version
    ]


def match_rule_id_pattern(
    relation: dict, new_rules: list[dict], doc_id: str
) -> list[str]:
    """Match suspended relation's rule references to new rule candidates.

    For each rule referenced in the relation (source_rule, target_rule),
    extract the suffix (e.g., "art6-p1-main") and find new rules with
    the same suffix.

    Returns deduplicated list of matching new rule_ids.
    """
    candidates = []
    new_suffixes: dict[str, str] = {}  # suffix -> rule_id
    for rule in new_rules:
        suffix = _extract_suffix(rule["rule_id"], doc_id)
        if suffix:
            new_suffixes[suffix] = rule["rule_id"]

    for field in ("source_rule", "target_rule"):
        old_rule_id = relation.get(field, "")
        old_suffix = _extract_suffix(old_rule_id, doc_id)
        if old_suffix and old_suffix in new_suffixes:
            candidates.append(new_suffixes[old_suffix])

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def generate_relation_migration_guide(
    doc_id: str,
    old_version: str,
    new_version: str,
    root: Path,
) -> list[dict]:
    """Generate migration guide for relations affected by version change.

    Returns list of dicts with:
      - suspended_relation: relation_id
      - type: relation type
      - original_pair: (source_rule, target_rule)
      - candidate_new_rules: list of matching new rule_ids
      - action_required: "human_review" (always, per RFC)
      - version_change: (old_version, new_version)
    """
    suspended = find_suspended_relations(doc_id, root)
    new_rules = find_rules_by_doc_and_version(doc_id, new_version, root)

    guide = []
    for rel in suspended:
        candidates = match_rule_id_pattern(rel, new_rules, doc_id)
        guide.append({
            "suspended_relation": rel["relation_id"],
            "type": rel.get("type", "unknown"),
            "original_pair": (
                rel.get("source_rule", ""),
                rel.get("target_rule", ""),
            ),
            "candidate_new_rules": candidates,
            "action_required": "human_review",
            "version_change": (old_version, new_version),
        })

    return guide


def format_migration_guide(guide: list[dict]) -> str:
    """Format migration guide as human-readable output.

    Output format per RFC 8.2.1.
    """
    if not guide:
        return "=== Relation Migration Guide ===\nNo suspended relations found. Nothing to migrate."

    lines = ["=== Relation Migration Guide ==="]

    for entry in guide:
        rel_id = entry["suspended_relation"]
        rel_type = entry["type"]
        source, target = entry["original_pair"]
        candidates = entry["candidate_new_rules"]

        # Extract short suffixes for display
        lines.append(f"{rel_id} ({rel_type}): {source} → {target}")

        if candidates:
            candidates_str = ", ".join(candidates)
            lines.append(f"  → 신규 후보: {candidates_str}")
        else:
            lines.append("  → 신규 후보: 없음 (수동 매핑 필요)")

        # Action guidance based on relation type
        if rel_type in _HUMAN_REVIEW_TYPES:
            lines.append(
                f"  → ACTION: 인간 검토 필요 ({rel_type} 관계는 자동 승인 불가)"
            )
        else:
            lines.append(
                f"  → ACTION: 인간 검토 필요 (관계 재등록)"
            )

    count = len(guide)
    lines.append("")
    lines.append(
        f"{count} relation(s) need re-registration. "
        "Use scripts/approve.py for each."
    )

    return "\n".join(lines)
