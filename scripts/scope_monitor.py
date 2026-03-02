"""Scope pollution monitoring.

Detects overly broad or under-specified scope in Rule Units.
Provides early warning metrics per the design document's criteria.

Metrics:
1. Average scope item character length
2. Rules with single-item scope (potential under-specification)
3. Rules with scope items > 50 chars (potential over-breadth)

Usage:
  python3 scope_monitor.py              # print report
  python3 scope_monitor.py --warn       # exit 1 if any metric in warning zone
"""

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parent.parent

# Warning thresholds (from design doc early warning indicators)
THRESHOLDS = {
    "avg_scope_char_length_warn": 50,
    "broad_scope_pct_warn": 0.20,  # >20% rules with broad scope items
}

BROAD_SCOPE_CHAR_LIMIT = 50


def _load_approved_rules(root: Path | None = None) -> list[dict]:
    """Load all approved rules for scope analysis."""
    base = root or ROOT
    rules_dir = base / "rules"
    rules = []
    if not rules_dir.exists():
        return rules
    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and data.get("status") == "approved":
            rules.append(data)
    return rules


def scope_metrics(rules: list[dict]) -> dict:
    """Compute scope health metrics."""
    all_lengths: list[int] = []
    single_scope_rules: list[str] = []
    broad_scope_rules: list[tuple[str, str]] = []

    for rule in rules:
        scopes = rule.get("scope", [])
        if len(scopes) == 1:
            single_scope_rules.append(rule.get("rule_id", "?"))
        for item in scopes:
            length = len(item)
            all_lengths.append(length)
            if length > BROAD_SCOPE_CHAR_LIMIT:
                broad_scope_rules.append((rule.get("rule_id", "?"), item))

    avg_len = sum(all_lengths) / max(len(all_lengths), 1)
    broad_pct = len(broad_scope_rules) / max(len(rules), 1)

    return {
        "total_rules": len(rules),
        "total_scope_items": len(all_lengths),
        "avg_scope_char_length": round(avg_len, 1),
        "single_scope_count": len(single_scope_rules),
        "single_scope_rules": single_scope_rules,
        "broad_scope_count": len(broad_scope_rules),
        "broad_scope_pct": round(broad_pct, 3),
        "broad_scope_rules": broad_scope_rules,
    }


def check_warnings(metrics: dict) -> list[str]:
    """Check metrics against warning thresholds. Returns list of warnings."""
    warnings = []
    if metrics["avg_scope_char_length"] > THRESHOLDS["avg_scope_char_length_warn"]:
        warnings.append(
            f"avg scope char length {metrics['avg_scope_char_length']} "
            f"> threshold {THRESHOLDS['avg_scope_char_length_warn']}"
        )
    if metrics["broad_scope_pct"] > THRESHOLDS["broad_scope_pct_warn"]:
        warnings.append(
            f"broad scope percentage {metrics['broad_scope_pct']:.1%} "
            f"> threshold {THRESHOLDS['broad_scope_pct_warn']:.0%}"
        )
    return warnings


def main():
    """CLI: Print scope metrics report."""
    warn_mode = "--warn" in sys.argv
    rules = _load_approved_rules()

    if not rules:
        print("No approved rules found.")
        sys.exit(0)

    metrics = scope_metrics(rules)

    print(f"\nScope Health Report")
    print(f"{'='*50}")
    print(f"Total approved rules:    {metrics['total_rules']}")
    print(f"Total scope items:       {metrics['total_scope_items']}")
    print(f"Avg scope char length:   {metrics['avg_scope_char_length']}")
    print(f"Single-scope rules:      {metrics['single_scope_count']}")
    print(f"Broad scope (>{BROAD_SCOPE_CHAR_LIMIT} chars): {metrics['broad_scope_count']}")
    print(f"{'='*50}")

    if metrics["single_scope_rules"]:
        print(f"\nSingle-scope rules (consider adding more scope items):")
        for rid in metrics["single_scope_rules"]:
            print(f"  - {rid}")

    if metrics["broad_scope_rules"]:
        print(f"\nBroad scope items (>{BROAD_SCOPE_CHAR_LIMIT} chars):")
        for rid, item in metrics["broad_scope_rules"]:
            print(f"  - {rid}: \"{item[:80]}...\"" if len(item) > 80 else f"  - {rid}: \"{item}\"")

    warnings = check_warnings(metrics)
    if warnings:
        print(f"\nWARNINGS:")
        for w in warnings:
            print(f"  ! {w}")

    if warn_mode and warnings:
        sys.exit(1)


if __name__ == "__main__":
    main()
