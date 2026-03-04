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

import math
import sys
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path

import yaml

from domain import resolve_domain

ROOT = Path(__file__).resolve().parent.parent

# Scoring weights
WEIGHT_SCOPE = 0.6
WEIGHT_TEXT = 0.4
FUZZY_THRESHOLD = 0.75
FUZZY_DISCOUNT = 0.8
RELATION_BONUS_CAP = 0.1


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


def _keyword_match(kw: str, target: str) -> float:
    """Single keyword vs text matching with fuzzy fallback.

    Returns 1.0 for exact substring, ratio*FUZZY_DISCOUNT for fuzzy, 0.0 otherwise.
    """
    if not kw or not target:
        return 0.0
    if kw in target:
        return 1.0
    # Sliding window fuzzy match
    kw_len = len(kw)
    if kw_len > len(target):
        return 0.0
    best = 0.0
    for i in range(len(target) - kw_len + 1):
        window = target[i : i + kw_len]
        ratio = SequenceMatcher(None, kw, window).ratio()
        if ratio > best:
            best = ratio
    if best >= FUZZY_THRESHOLD:
        return best * FUZZY_DISCOUNT
    return 0.0


def _scope_score(keywords: list[str], rule: dict, idf: dict[str, float]) -> float:
    """Per-scope-item matching with IDF weighting."""
    scopes = rule.get("scope", [])
    if not keywords or not scopes:
        return 0.0
    total_weight = 0.0
    weighted_score = 0.0
    for kw in keywords:
        w = idf.get(kw, 1.0)
        # Best match across scope items
        best = max((_keyword_match(kw, item) for item in scopes), default=0.0)
        weighted_score += w * best
        total_weight += w
    return weighted_score / total_weight if total_weight > 0 else 0.0


def _text_score(keywords: list[str], rule: dict, idf: dict[str, float]) -> float:
    """Exact substring matching on text field, IDF-weighted.

    No fuzzy matching on text — long text + short keywords causes false positives.
    """
    text = rule.get("text", "")
    if not keywords or not text:
        return 0.0
    total_weight = 0.0
    weighted_score = 0.0
    for kw in keywords:
        w = idf.get(kw, 1.0)
        score = 1.0 if kw in text else 0.0
        weighted_score += w * score
        total_weight += w
    return weighted_score / total_weight if total_weight > 0 else 0.0


def _compute_idf(keywords: list[str], rules: list[dict]) -> dict[str, float]:
    """Compute IDF weights for keywords across entire corpus."""
    n = len(rules)
    if n == 0:
        return {kw: 1.0 for kw in keywords}
    idf = {}
    for kw in keywords:
        df = 0
        for rule in rules:
            scope_text = " ".join(rule.get("scope", []))
            text = rule.get("text", "")
            corpus = scope_text + " " + text
            if kw in corpus:
                df += 1
        if df > 0:
            idf[kw] = max(math.log(n / df), 0.1)
        else:
            idf[kw] = math.log(n + 1)
    return idf


def _load_relations(root: Path) -> list[dict]:
    """Load approved relations from relations/ directory."""
    rel_dir = root / "relations"
    relations = []
    if not rel_dir.is_dir():
        return relations
    for path in sorted(rel_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and data.get("status") == "approved":
            # condition is required (schema minLength: 5)
            condition = data.get("condition", "")
            if not condition or len(condition.strip()) < 5:
                continue
            relations.append(data)
    return relations


def _relation_bonus(
    rule_id: str, keywords: list[str], relations: list[dict]
) -> float:
    """Bonus score from matching keywords in related rule conditions."""
    if not rule_id or not keywords or not relations:
        return 0.0
    total_kw = len(keywords)
    hits = 0
    seen_pairs: set[frozenset[str]] = set()
    for rel in relations:
        src = rel.get("source_rule", "")
        tgt = rel.get("target_rule", "")
        if rule_id not in (src, tgt):
            continue
        pair = frozenset((src, tgt))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        condition = rel.get("condition", "")
        for kw in keywords:
            if kw in condition:
                hits += 1
                break  # one hit per relation
    return min((hits / total_kw) * RELATION_BONUS_CAP, RELATION_BONUS_CAP)


def _match_score(
    keywords: list[str],
    rule: dict,
    *,
    idf_weights: dict[str, float] | None = None,
    relations: list[dict] | None = None,
) -> float:
    """Multi-field scoring: scope (fuzzy+IDF) + text (exact+IDF) + relation bonus."""
    if not keywords:
        return 0.0
    idf = idf_weights or {kw: 1.0 for kw in keywords}
    s = _scope_score(keywords, rule, idf)
    t = _text_score(keywords, rule, idf)
    base = WEIGHT_SCOPE * s + WEIGHT_TEXT * t
    bonus = _relation_bonus(rule.get("rule_id", ""), keywords, relations or [])
    return base + bonus


def search_rules(
    query: str,
    root: Path | None = None,
    status_filter: StatusFilter = StatusFilter.VERIFIED_AND_ABOVE,
    threshold: float = 0.5,
    domain: str | None = None,
    include_relations: bool = True,
) -> list[dict]:
    """Search rules with multi-field scoring. Returns matched rules sorted by score."""
    if not (0.0 <= threshold <= 1.0):
        raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")
    base = root or ROOT
    rules = _load_rules(base)
    keywords = query.split()

    # IDF computed on full corpus before filtering
    idf_weights = _compute_idf(keywords, rules)

    # Load relations if requested
    relations = _load_relations(base) if include_relations else []

    results = []
    for rule in rules:
        if not status_filter.allows(rule.get("status", "")):
            continue
        # Domain filter
        if domain:
            rule_domain = rule.get("domain") or resolve_domain(rule, base)
            if rule_domain != domain:
                continue
        score = _match_score(
            keywords, rule, idf_weights=idf_weights, relations=relations
        )
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
    - superseded: "[대체됨: {rule_id}] → {superseded_by} 참조"
    - suspended: "[재검토중: {rule_id}] 현재 재검토 중"
    - draft/rejected: None (cannot cite, no redirect)
    """
    status = rule.get("status", "")
    rule_id = rule.get("rule_id", "unknown")

    if status == "superseded":
        successor = rule.get("superseded_by", "unknown")
        return f"[대체됨: {rule_id}] 이 규칙은 {successor} 규칙으로 대체되었습니다."

    if status == "suspended":
        return f"[재검토중: {rule_id}] 이 규칙은 현재 재검토 중입니다."

    if status in _NEVER_CITE:
        return None

    text = rule.get("text", "").strip()

    if status == "approved":
        return f"[근거: {rule_id}] {text}"
    if status == "verified":
        return f"[미승인] 자동검증 완료, 인간 승인 대기중. [근거: {rule_id}] {text}"

    return None


def main():
    """CLI: Search and cite rules.

    Flags:
      --domain <value>     Filter by domain (e.g., ra, test-legal)
      --threshold <float>  Minimum score threshold (default: 0.3)
    """
    # Parse flags
    domain_filter = None
    cli_threshold = 0.3  # CLI default lower than API (interactive search is broader)
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
        if a == "--threshold" and i + 1 < len(argv):
            cli_threshold = float(argv[i + 1])
            skip_next = True
            continue
        if not a.startswith("--"):
            args.append(a)

    if not args:
        print("Usage: python3 retrieve.py <query> [--domain <value>] [--threshold <float>]")
        print("Example: python3 retrieve.py '기부 금지 조건' --domain ra")
        sys.exit(1)

    query = " ".join(args)
    results = search_rules(
        query,
        status_filter=StatusFilter.VERIFIED_AND_ABOVE,
        threshold=cli_threshold,
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
