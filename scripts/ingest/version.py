"""Version update handling for the ingestion pipeline.

When a source document has a new version, this module:
1. Suspends all Rule Units referencing the old version
2. Adds the new version to the source registry
3. Cascades suspension to affected Relations
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ingest.registry import add_version_to_existing_source


def _find_rules_for_version(
    doc_id: str, version: str, root: Path
) -> list[tuple[Path, dict]]:
    """Find all Rule Unit files matching doc_id and version.

    Scans rules/{doc_id}/*.yaml for files where
    source_ref.document == doc_id AND source_ref.version == version.
    """
    rules_dir = root / "rules" / doc_id
    if not rules_dir.exists():
        return []

    matched = []
    for path in sorted(rules_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data or "rule_id" not in data:
            continue
        src = data.get("source_ref", {})
        if src.get("document") == doc_id and src.get("version") == version:
            matched.append((path, data))
    return matched


def _suspend_rule(data: dict, old_version: str, new_version: str) -> dict | None:
    """Transition a rule to suspended status if it is currently approved.

    Returns modified dict if transitioned, None if no change needed.
    """
    if data.get("status") != "approved":
        return None

    data["status"] = "suspended"
    data["suspension_reason"] = (
        f"원천 문서 버전 변경: {old_version} → {new_version}"
    )
    return data


def version_update(
    doc_id: str,
    new_version: str,
    old_version: str,
    file_path: str,
    root: Path,
) -> dict:
    """Handle version change: suspend old rules, update registry, cascade relations.

    Args:
        doc_id: document identifier (must exist in _sources.yaml).
        new_version: new version string.
        old_version: version being superseded.
        file_path: source file path for the new version.
        root: project root directory.

    Returns:
        Summary dict with counts of affected rules and relations.

    Raises:
        FileNotFoundError: no rules found for the given doc_id and old_version.
    """
    # Import cascade here to avoid circular import at module level
    import cascade

    # Step 1: Find all rules for old version
    rules = _find_rules_for_version(doc_id, old_version, root)
    if not rules:
        raise FileNotFoundError(
            f"No Rule Units found for doc_id='{doc_id}' version='{old_version}'"
        )

    # Step 2: Suspend approved rules
    rules_suspended = 0
    for path, data in rules:
        updated = _suspend_rule(data, old_version, new_version)
        if updated is not None:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(
                    updated, f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            rules_suspended += 1

    # Step 3: Add new version to source registry
    add_version_to_existing_source(
        doc_id=doc_id,
        version=new_version,
        file_path=file_path,
        root=root,
        supersedes=old_version,
    )

    # Step 4: Cascade to relations
    orphans = cascade.find_orphan_relations(root)
    relations_cascaded = 0
    for rel_path, rel, reason in orphans:
        cascaded = cascade.cascade_relation(rel, reason)
        if cascaded.get("status") != rel.get("status"):
            with open(rel_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    cascaded, f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            relations_cascaded += 1

    return {
        "doc_id": doc_id,
        "old_version": old_version,
        "new_version": new_version,
        "rules_found": len(rules),
        "rules_suspended": rules_suspended,
        "relations_cascaded": relations_cascaded,
    }
