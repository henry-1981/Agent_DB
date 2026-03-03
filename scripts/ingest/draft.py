"""Draft YAML files from extracted rule fields.

Generates Rule Unit YAML files with controlled field ordering,
duplicate detection, and conditional domain inclusion.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Field order for YAML output (domain inserted conditionally before status)
_FIELD_ORDER = ["rule_id", "text", "source_ref", "scope", "authority", "status"]


def write_draft(
    fields: dict,
    output_dir: Path,
    force: bool = False,
    default_domain: str = "ra",
) -> Path | None:
    """Write a single Rule Unit YAML draft file.

    Args:
        fields: dict with rule_id, text, source_ref, scope, authority, status,
                and optionally doc_id & domain.
        output_dir: directory to write the YAML file into.
        force: overwrite existing file if True.
        default_domain: domain value to suppress from output (matches _domain.yaml).

    Returns:
        Path of written file, or None if skipped (duplicate).
    """
    rule_id = fields["rule_id"]
    doc_id = fields.get("doc_id", "")

    # Derive filename: strip doc_id prefix from rule_id
    if doc_id and rule_id.startswith(doc_id + "-"):
        filename = rule_id.removeprefix(doc_id + "-") + ".yaml"
    else:
        filename = rule_id + ".yaml"

    filepath = output_dir / filename

    # Duplicate check
    if filepath.exists() and not force:
        logger.warning("Skipping duplicate: %s already exists", filepath)
        return None

    # Build ordered output dict
    ordered: dict = {}
    for key in _FIELD_ORDER:
        if key == "status":
            # Insert domain before status if non-default
            domain = fields.get("domain")
            if domain and domain != default_domain:
                ordered["domain"] = domain
        if key in fields:
            ordered[key] = fields[key]

    output_dir.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        ordered,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    filepath.write_text(content, encoding="utf-8")
    return filepath


def write_all_drafts(
    rules: list[dict],
    doc_id: str,
    root: Path,
    force: bool = False,
    default_domain: str = "ra",
) -> list[Path]:
    """Write multiple Rule Unit YAML drafts under rules/{doc_id}/.

    Args:
        rules: list of field dicts (each must have rule_id).
        doc_id: document identifier, used for subdirectory and filename prefix.
        root: project root (rules/ directory parent).
        force: overwrite existing files if True.
        default_domain: domain value to suppress from output.

    Returns:
        List of paths for successfully written files.
    """
    output_dir = root / "rules" / doc_id
    paths: list[Path] = []
    for fields in rules:
        result = write_draft(
            fields, output_dir, force=force, default_domain=default_domain,
        )
        if result is not None:
            paths.append(result)
    return paths
