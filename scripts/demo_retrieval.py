"""Token savings demo: before (monolithic) vs after (atomic) retrieval.

Demonstrates that splitting a single Rule Unit into atomic units allows
precise scope-based matching, returning only the relevant text instead
of the entire article. Also shows traceability-based context restoration.
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import context as ctx  # noqa: E402


def load_rule(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_all_rules() -> tuple[list[dict], dict[str, dict]]:
    """Load all rule YAML files. Returns (list, {rule_id: rule})."""
    rules_dir = ROOT / "rules"
    rules = []
    by_id: dict[str, dict] = {}
    for path in sorted(rules_dir.rglob("*.yaml")):
        if not path.name.startswith("_"):
            rule = load_rule(path)
            rules.append(rule)
            by_id[rule["rule_id"]] = rule
    return rules, by_id


def load_monolithic() -> str:
    """Reconstruct the original monolithic text for comparison."""
    rules, _ = load_all_rules()
    return "\n\n".join(r["text"] for r in rules)


def count_tokens_approx(text: str) -> int:
    """Approximate token count for Korean text.

    Korean chars count as ~1 token each, ASCII words count separately.
    Not exact, but consistent for before/after comparison.
    """
    count = 0
    for char in text:
        if "\uac00" <= char <= "\ud7a3":  # Hangul syllables
            count += 1
        elif "\u3131" <= char <= "\u318e":  # Hangul jamo
            count += 1
        elif "\u4e00" <= char <= "\u9fff":  # CJK ideographs
            count += 1
    ascii_words = "".join(
        c if c.isascii() and c.isalnum() else " " for c in text
    ).split()
    count += len(ascii_words)
    return max(count, 1)


def match_scope(query_keywords: list[str], rule: dict) -> float:
    """Keyword-based scope matching. Returns match score 0~1."""
    scopes = rule.get("scope", [])
    scope_text = " ".join(scopes)
    hits = sum(1 for kw in query_keywords if kw in scope_text)
    return hits / len(query_keywords) if query_keywords else 0


def retrieve(
    query: str,
    rules: list[dict],
    rules_by_id: dict[str, dict],
    threshold: float = 0.5,
) -> tuple[list[dict], list[dict]]:
    """Retrieve matching rules + optional parent context via traceability.

    Returns (primary_matches, context_rules).
    """
    keywords = query.split()
    scored = []
    for rule in rules:
        score = match_scope(keywords, rule)
        if score >= threshold:
            scored.append((score, rule))
    scored.sort(key=lambda x: x[0], reverse=True)
    primary = [r for _, r in scored]

    # Context restoration: add parent if not already in primary matches
    context_rules = []
    primary_ids = {r["rule_id"] for r in primary}
    for rule in primary:
        parent_id = ctx.get_parent(rule["rule_id"])
        if parent_id and parent_id not in primary_ids:
            parent_rule = rules_by_id.get(parent_id)
            if parent_rule and parent_rule["rule_id"] not in {
                c["rule_id"] for c in context_rules
            }:
                context_rules.append(parent_rule)

    return primary, context_rules


def demo_query(
    query: str,
    rules: list[dict],
    rules_by_id: dict[str, dict],
    monolithic_text: str,
) -> tuple[int, int]:
    """Run a single demo query and show before/after comparison."""
    print(f'\nQuery: "{query}"')
    print(f"{'-'*60}")

    before_tokens = count_tokens_approx(monolithic_text)

    primary, context_rules = retrieve(query, rules, rules_by_id)

    primary_ids = [r["rule_id"] for r in primary]
    context_ids = [r["rule_id"] for r in context_rules]
    print(f"  Primary matches: {primary_ids}")
    if context_ids:
        print(f"  Context (parent): {context_ids}")

    primary_text = "\n\n".join(r["text"] for r in primary)
    context_text = "\n\n".join(r["text"] for r in context_rules)
    after_text = primary_text + ("\n\n" + context_text if context_text else "")
    after_tokens = count_tokens_approx(after_text)

    print(f"\n  Before (monolithic): ~{before_tokens} tokens (entire article)")
    print(f"  After  (atomic):     ~{after_tokens} tokens "
          f"({len(primary)} primary + {len(context_rules)} context)")

    if before_tokens > 0:
        savings = (1 - after_tokens / before_tokens) * 100
        print(f"  Savings:             {savings:.1f}%")

    return before_tokens, after_tokens


def main():
    rules, rules_by_id = load_all_rules()
    monolithic_text = load_monolithic()

    print("=" * 60)
    print("Token Savings Demo: Monolithic vs Atomic Rule Units")
    print("=" * 60)
    print(f"\nLoaded {len(rules)} atomic rule unit(s)")
    print(f"Monolithic text: ~{count_tokens_approx(monolithic_text)} tokens")

    queries = [
        "기부 금지 조건",
        "기부 신고 의무",
    ]

    total_before = 0
    total_after = 0

    for query in queries:
        b, a = demo_query(query, rules, rules_by_id, monolithic_text)
        total_before += b
        total_after += a

    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"  Total before: ~{total_before} tokens")
    print(f"  Total after:  ~{total_after} tokens")
    if total_before > 0:
        print(f"  Overall savings: {(1 - total_after / total_before) * 100:.1f}%")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
