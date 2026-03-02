"""Tests for domain resolution and configuration loader."""

from domain import resolve_domain, load_authority_levels, load_g2_checklist_items


def test_resolve_domain_from_marker(root):
    """Resolves domain from rules/_domain.yaml when rule has no domain field."""
    rule = {"rule_id": "test", "text": "test", "authority": "regulation"}
    domain = resolve_domain(rule, root)
    assert domain == "ra"


def test_resolve_domain_explicit_field(root):
    """Explicit domain field on rule takes priority over marker file."""
    rule = {"rule_id": "test", "domain": "legal"}
    domain = resolve_domain(rule, root)
    assert domain == "legal"


def test_load_authority_levels_ra(root):
    """Loads RA authority levels from domains/ra/authority_levels.yaml."""
    levels = load_authority_levels("ra", root)
    assert levels == ["law", "regulation", "sop", "guideline", "precedent"]


def test_load_authority_levels_unknown_domain(root):
    """Returns empty list for unknown domain."""
    levels = load_authority_levels("nonexistent", root)
    assert levels == []


def test_load_g2_checklist_items_ra(root):
    """Loads RA G2 checklist item IDs."""
    items = load_g2_checklist_items("ra", root)
    assert items == [
        "semantic_accuracy",
        "scope_completeness",
        "authority_correctness",
        "relation_validity",
    ]
