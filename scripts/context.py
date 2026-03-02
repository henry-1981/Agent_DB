"""Traceability context helper.

Loads traceability/*.yaml and provides structural hierarchy queries:
- get_parent(rule_id)   -> parent rule_id or None
- get_children(rule_id) -> list of child rule_ids
- get_siblings(rule_id) -> list of sibling rule_ids (excluding self)
- get_context(rule_id)  -> dict with parent, children, siblings
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "traceability"


def load_traceability() -> list[dict]:
    """Load all traceability link files."""
    if not TRACE_DIR.exists():
        return []
    links = []
    for path in sorted(TRACE_DIR.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            links.append(data)
    return links


def _build_index(links: list[dict]) -> tuple[dict, dict]:
    """Build parent->children and child->parent indexes."""
    parent_of: dict[str, str] = {}
    children_of: dict[str, list[str]] = {}

    for link in links:
        parent = link.get("parent")
        children = link.get("children", [])
        if parent:
            children_of[parent] = children
            for child in children:
                parent_of[child] = parent

    return parent_of, children_of


# Module-level lazy cache
_links = None
_parent_of = None
_children_of = None


def _ensure_loaded():
    global _links, _parent_of, _children_of
    if _links is None:
        _links = load_traceability()
        _parent_of, _children_of = _build_index(_links)


def get_parent(rule_id: str) -> str | None:
    _ensure_loaded()
    assert _parent_of is not None
    return _parent_of.get(rule_id)


def get_children(rule_id: str) -> list[str]:
    _ensure_loaded()
    assert _children_of is not None
    return _children_of.get(rule_id, [])


def get_siblings(rule_id: str) -> list[str]:
    _ensure_loaded()
    assert _parent_of is not None and _children_of is not None
    parent = _parent_of.get(rule_id)
    if not parent:
        return []
    return [c for c in _children_of.get(parent, []) if c != rule_id]


def get_context(rule_id: str) -> dict:
    return {
        "rule_id": rule_id,
        "parent": get_parent(rule_id),
        "children": get_children(rule_id),
        "siblings": get_siblings(rule_id),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python context.py <rule_id>")
        print("Example: python context.py kmdia-fc-art7-p1-item5")
        sys.exit(1)

    rule_id = sys.argv[1]
    ctx = get_context(rule_id)

    print(f"\nContext for: {rule_id}")
    print(f"{'='*50}")
    print(f"  Parent:   {ctx['parent'] or '(none)'}")
    print(f"  Children: {ctx['children'] or '(none)'}")
    print(f"  Siblings: {ctx['siblings'] or '(none)'}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
