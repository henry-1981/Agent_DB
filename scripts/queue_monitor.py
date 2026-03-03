"""G2 approval queue monitor.

Shows verified rules awaiting human approval (G2).
Provides queue size, age metrics, and threshold warnings.

Usage:
  python3 queue_monitor.py                    # full queue report
  python3 queue_monitor.py --domain ra        # filter by domain
  python3 queue_monitor.py --json             # JSON output for automation
  python3 queue_monitor.py --warn             # exit 1 if thresholds exceeded
"""

import json as json_mod
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from domain import resolve_domain

ROOT = Path(__file__).resolve().parent.parent

# Warning thresholds
QUEUE_SIZE_WARN = 10
QUEUE_AGE_WARN_DAYS = 14


def _load_verified_rules(root: Path | None = None) -> list[dict]:
    """Load all rules with status=verified."""
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
        if data and data.get("status") == "verified":
            data["_path"] = str(path)
            rules.append(data)
    return rules


def _age_days(rule: dict, path: str) -> float:
    """Calculate days since verification.

    Uses verified_at timestamp if available, otherwise falls back to file mtime.
    """
    verified_at = rule.get("verified_at")
    if verified_at:
        if isinstance(verified_at, str):
            # Handle ISO format timestamps
            ts = datetime.fromisoformat(verified_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ts
            return delta.total_seconds() / 86400
    # Fallback: file modification time
    try:
        mtime = Path(path).stat().st_mtime
        delta = datetime.now(timezone.utc).timestamp() - mtime
        return delta / 86400
    except OSError:
        return 0.0


def queue_report(
    root: Path | None = None,
    domain: str | None = None,
) -> list[dict]:
    """Build queue entries for verified rules awaiting G2 approval."""
    base = root or ROOT
    rules = _load_verified_rules(root)

    entries = []
    for rule in rules:
        # Domain filter
        if domain:
            rule_domain = rule.get("domain") or resolve_domain(rule, base)
            if rule_domain != domain:
                continue

        rule_domain = rule.get("domain") or resolve_domain(rule, base)
        age = _age_days(rule, rule.get("_path", ""))
        text = rule.get("text", "")
        snippet = text[:80] + "..." if len(text) > 80 else text

        entries.append({
            "rule_id": rule.get("rule_id", "?"),
            "domain": rule_domain or "unknown",
            "authority": rule.get("authority", "?"),
            "text_snippet": snippet,
            "age_days": round(age, 1),
        })

    # Sort by age descending (oldest first)
    entries.sort(key=lambda e: e["age_days"], reverse=True)
    return entries


def check_warnings(entries: list[dict]) -> list[str]:
    """Check queue against warning thresholds."""
    warnings = []
    if len(entries) > QUEUE_SIZE_WARN:
        warnings.append(
            f"queue size {len(entries)} > threshold {QUEUE_SIZE_WARN}"
        )
    old_entries = [e for e in entries if e["age_days"] > QUEUE_AGE_WARN_DAYS]
    if old_entries:
        warnings.append(
            f"{len(old_entries)} rule(s) waiting > {QUEUE_AGE_WARN_DAYS} days: "
            + ", ".join(e["rule_id"] for e in old_entries)
        )
    return warnings


def main():
    """CLI: Show G2 approval queue."""
    argv = sys.argv[1:]
    warn_mode = "--warn" in argv
    json_mode = "--json" in argv

    # Parse --domain
    domain_filter = None
    for i, a in enumerate(argv):
        if a == "--domain" and i + 1 < len(argv):
            domain_filter = argv[i + 1]

    entries = queue_report(domain=domain_filter)

    if json_mode:
        print(json_mod.dumps(entries, ensure_ascii=False, indent=2))
    else:
        if not entries:
            print("G2 approval queue is empty.")
            sys.exit(0)

        print(f"\nG2 Approval Queue")
        print(f"{'=' * 60}")
        if domain_filter:
            print(f"Domain filter: {domain_filter}")
        print(f"Total pending: {len(entries)}")
        print()

        for e in entries:
            print(f"  [{e['domain']}] {e['rule_id']}")
            print(f"    authority: {e['authority']}")
            print(f"    waiting: {e['age_days']} days")
            print(f"    text: {e['text_snippet']}")
            print()

        warnings = check_warnings(entries)
        if warnings:
            print("WARNINGS:")
            for w in warnings:
                print(f"  ! {w}")

    if warn_mode:
        warnings = check_warnings(entries)
        if warnings:
            sys.exit(1)


if __name__ == "__main__":
    main()
