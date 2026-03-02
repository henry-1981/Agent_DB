"""Domain resolution and configuration loader.

Resolves domain for a Rule Unit by:
1. Explicit 'domain' field in the rule
2. rules/_domain.yaml marker (global default)
3. Fallback: None (triggers validation error in gate1)
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def resolve_domain(
    rule: dict, root: Path | None = None
) -> str | None:
    """Resolve domain for a rule.

    Priority:
    1. Explicit 'domain' field on the rule
    2. rules/_domain.yaml global default
    """
    # 1. Explicit field
    if rule.get("domain"):
        return rule["domain"]

    # 2. Global default marker
    base = root or ROOT
    marker = base / "rules" / "_domain.yaml"
    if marker.exists():
        with open(marker, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and data.get("domain"):
            return data["domain"]

    return None


def load_authority_levels(
    domain: str, root: Path | None = None
) -> list[str]:
    """Load authority levels for a domain. Returns list strongest->weakest."""
    base = root or ROOT
    path = base / "domains" / domain / "authority_levels.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("levels", []) if data else []


def load_g2_checklist_items(
    domain: str, root: Path | None = None
) -> list[str]:
    """Load G2 checklist item IDs for a domain."""
    base = root or ROOT
    path = base / "domains" / domain / "gate2_checklist.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    return [item["id"] for item in data.get("items", [])]
