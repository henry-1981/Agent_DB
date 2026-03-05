"""Rule DB MCP Server — read-only search interface for Agent-DB.

Exposes search_rules as an MCP tool so Claude Code can search
regulatory rules directly without CLI invocation.
"""

import os
import sys
from pathlib import Path

# Allow importing scripts/ modules (retrieve, domain, etc.)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fastmcp import FastMCP  # noqa: E402
from retrieve import (  # noqa: E402
    ROOT as RETRIEVE_ROOT,
    StatusFilter,
    format_citation,
    get_rule_by_id,
    load_relations,
    search_rules,
)
from context import get_context  # noqa: E402

_DB_ROOT = (
    Path(os.environ["RULE_DB_ROOT"])
    if os.environ.get("RULE_DB_ROOT")
    else None
)

# Only expose fields that are part of the Rule Unit schema
_PUBLIC_FIELDS = {"rule_id", "text", "source_ref", "scope", "authority", "status"}

_PUBLIC_RELATION_FIELDS = {
    "relation_id", "type", "source_rule", "target_rule",
    "condition", "resolution", "authority_basis", "status",
}

_HIDDEN_STATUSES = {"draft", "rejected"}


def _filter_rule(rule: dict) -> dict | None:
    """Return public-fields-only rule, or None if status is hidden."""
    if rule.get("status") in _HIDDEN_STATUSES:
        return None
    return {k: v for k, v in rule.items() if k in _PUBLIC_FIELDS}


def _filter_relation(rel: dict) -> dict:
    """Return public-fields-only relation."""
    return {k: v for k, v in rel.items() if k in _PUBLIC_RELATION_FIELDS}


mcp = FastMCP(name="rule-db")


@mcp.tool(name="search_rules")
def search_rules_tool(
    query: str,
    domain: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search regulatory rules in Agent-DB.

    Finds rules matching the query using multi-field IDF scoring
    across scope and text fields with relation bonuses.

    Args:
        query: Korean search terms (e.g. "의료기기 거래 경제적 이익 제공 금지")
        domain: Optional domain filter (e.g. "ra")
        limit: Max results to return (1-20, default 5)

    Returns:
        List of matching rules with fields: rule_id, text, source_ref,
        scope, authority, status. Sorted by relevance score (highest first).

    Citation rules by status:
        - approved: authoritative, cite as "[근거: rule_id]"
        - verified: cite with warning "[미승인] 자동검증 완료, 인간 승인 대기중"
        - draft/rejected/suspended/superseded: never returned
    """
    limit = max(1, min(limit, 20))
    results = search_rules(
        query,
        root=_DB_ROOT,
        status_filter=StatusFilter.VERIFIED_AND_ABOVE,
        threshold=0.3,
        domain=domain,
    )
    return [fr for r in results[:limit] if (fr := _filter_rule(r)) is not None]


@mcp.tool(name="get_rule")
def get_rule_tool(rule_id: str) -> dict | None:
    """Get a single rule by its rule_id.

    Args:
        rule_id: The unique identifier of the rule (e.g. "kmdia-fc-art7-1")

    Returns:
        Rule dict with public fields, or None if not found.

    Visibility rules (per CLAUDE.md):
        - draft/rejected: None (existence must not be disclosed)
        - suspended: returned with status="suspended" — do NOT cite, inform user
          "이 규칙은 현재 재검토 중입니다"
        - superseded: returned with status="superseded" — do NOT cite, redirect
          to successor rule
        - verified/approved: returned normally
    """
    rule = get_rule_by_id(rule_id, root=_DB_ROOT)
    if rule is None:
        return None
    return _filter_rule(rule)


@mcp.tool(name="get_context")
def get_context_tool(rule_id: str) -> dict:
    """Get full context for a rule: the rule itself, hierarchy, and relations.

    Args:
        rule_id: The unique identifier of the rule

    Returns:
        Dict with:
        - rule: Rule dict (public fields) or None if not found/not citable
        - hierarchy: parent, children, siblings, hierarchy_type from traceability
        - relations: List of related relations (public fields only)
    """
    # Rule (filtered same as get_rule)
    rule = get_rule_by_id(rule_id, root=_DB_ROOT)
    rule_pub = _filter_rule(rule) if rule else None

    # Hierarchy from traceability
    hierarchy = get_context(rule_id)

    # Relations involving this rule
    rel_root = _DB_ROOT or RETRIEVE_ROOT
    all_rels = load_relations(rel_root)
    related = []
    for rel in all_rels:
        if rel.get("source_rule") == rule_id or rel.get("target_rule") == rule_id:
            related.append(_filter_relation(rel))

    return {
        "rule": rule_pub,
        "hierarchy": hierarchy,
        "relations": related,
    }


@mcp.tool(name="cite_rule")
def cite_rule_tool(rule_id: str) -> dict:
    """Get a formatted citation for a rule, respecting status-based citation rules.

    Args:
        rule_id: The unique identifier of the rule

    Returns:
        Dict with:
        - rule_id: The requested rule_id
        - status: Rule status or None if not found
        - citation: Formatted citation string or None if not citable
        - citable: Boolean indicating if the rule can be cited

    Citation formats by status:
        - approved: "[근거: rule_id] text"
        - verified: "[미승인] 자동검증 완료, 인간 승인 대기중. [근거: rule_id] text"
        - suspended: "[재검토중: rule_id] 이 규칙은 현재 재검토 중입니다."
        - superseded: "[대체됨: rule_id] → successor 참조"
        - draft/rejected: None (cannot cite)
    """
    rule = get_rule_by_id(rule_id, root=_DB_ROOT)
    if rule is None:
        return {"rule_id": rule_id, "status": None, "citation": None, "citable": False}

    status = rule.get("status", "")
    citation = format_citation(rule)
    citable = citation is not None and status in ("approved", "verified")

    return {
        "rule_id": rule_id,
        "status": status,
        "citation": citation,
        "citable": citable,
    }


if __name__ == "__main__":
    mcp.run()
