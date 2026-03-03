"""Agent retrieval and citation module.

Provides:
- search_rules(query) -> matching rules with scores
- format_citation(rule) -> status-aware citation string
- StatusFilter -> controls which statuses are citable

Citation rules per CLAUDE.md:
- draft/rejected: never cite
- verified: cite with warning "[미승인]"
- approved: cite as authoritative "[근거: rule_id]"
- suspended/superseded: never cite
"""

import sys
from enum import Enum
from pathlib import Path

import yaml

from domain import resolve_domain

ROOT = Path(__file__).resolve().parent.parent


class StatusFilter(Enum):
    APPROVED_ONLY = "approved_only"
    VERIFIED_AND_ABOVE = "verified_and_above"
    ALL = "all"  # for dev/testing — includes draft

    def allows(self, status: str) -> bool:
        if self == StatusFilter.APPROVED_ONLY:
            return status == "approved"
        if self == StatusFilter.VERIFIED_AND_ABOVE:
            return status in ("approved", "verified")
        if self == StatusFilter.ALL:
            return True
        return False


# Statuses that can never be cited
_NEVER_CITE = {"draft", "rejected", "suspended", "superseded"}


def _load_rules(root: Path) -> list[dict]:
    rules_dir = root / "rules"
    rules = []
    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            rules.append(data)
    return rules


def _match_score(keywords: list[str], rule: dict) -> float:
    """Keyword-based scope matching. Returns 0~1."""
    scopes = rule.get("scope", [])
    scope_text = " ".join(scopes)
    if not keywords:
        return 0
    hits = sum(1 for kw in keywords if kw in scope_text)
    return hits / len(keywords)


def search_rules(
    query: str,
    root: Path | None = None,
    status_filter: StatusFilter = StatusFilter.VERIFIED_AND_ABOVE,
    threshold: float = 0.5,
    domain: str | None = None,
) -> list[dict]:
    """Search rules by scope matching. Returns matched rules sorted by score."""
    base = root or ROOT
    rules = _load_rules(base)
    keywords = query.split()

    results = []
    for rule in rules:
        if not status_filter.allows(rule.get("status", "")):
            continue
        # Domain filter
        if domain:
            rule_domain = rule.get("domain") or resolve_domain(rule, base)
            if rule_domain != domain:
                continue
        score = _match_score(keywords, rule)
        if score >= threshold:
            rule_copy = dict(rule)
            rule_copy["_score"] = score
            results.append(rule_copy)

    results.sort(key=lambda r: r["_score"], reverse=True)
    return results


def format_citation(rule: dict) -> str | None:
    """Format a rule as a citation string. Returns None if uncitable.

    - approved: "[근거: {rule_id}] {text}"
    - verified: "[미승인] [근거: {rule_id}] {text}"
    - others: None (cannot cite)
    """
    status = rule.get("status", "")
    if status in _NEVER_CITE:
        return None

    rule_id = rule.get("rule_id", "unknown")
    text = rule.get("text", "").strip()

    if status == "approved":
        return f"[근거: {rule_id}] {text}"
    if status == "verified":
        return f"[미승인] [근거: {rule_id}] {text}"

    return None


def main():
    """CLI: Search and cite rules.

    Flags:
      --domain <value>  Filter by domain (e.g., ra, test-legal)
    """
    # Parse --domain flag
    domain_filter = None
    argv = sys.argv[1:]
    skip_next = False
    args = []
    for i, a in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if a == "--domain" and i + 1 < len(argv):
            domain_filter = argv[i + 1]
            skip_next = True
            continue
        if not a.startswith("--"):
            args.append(a)

    if not args:
        print("Usage: python3 retrieve.py <query> [--domain <value>]")
        print("Example: python3 retrieve.py '기부 금지 조건' --domain ra")
        sys.exit(1)

    query = " ".join(args)
    results = search_rules(
        query,
        status_filter=StatusFilter.VERIFIED_AND_ABOVE,
        domain=domain_filter,
    )

    if not results:
        print(f'No citable rules found for: "{query}"')
        print("(All rules may be in draft status. Run G1 + G2 first.)")
        sys.exit(0)

    print(f'\nQuery: "{query}"')
    print(f"Found {len(results)} citable rule(s):\n")

    for rule in results:
        citation = format_citation(rule)
        if citation:
            print(f"  {citation[:200]}")
            print()


if __name__ == "__main__":
    main()
