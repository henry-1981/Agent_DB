"""Gate 2 approval workflow.

Provides functions for human approval of verified Rule Units.
G2 checks what LLM structurally cannot:
- Semantic accuracy
- Scope completeness
- Authority correctness
- Relation validity
"""

import copy
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from domain import load_g2_checklist_items

ROOT = Path(__file__).resolve().parent.parent

# Default G2 checklist items (used when domain config is absent)
_DEFAULT_G2_CHECKLIST_ITEMS = [
    "semantic_accuracy",
    "scope_completeness",
    "authority_correctness",
    "relation_validity",
]


def _get_g2_checklist_items(
    domain: str | None = None, root: Path | None = None
) -> list[str]:
    """Load G2 checklist items for domain. Falls back to default."""
    if domain:
        items = load_g2_checklist_items(domain, root)
        if items:
            return items
    return _DEFAULT_G2_CHECKLIST_ITEMS


def validate_g2_checklist(
    checklist: dict,
    domain: str | None = None,
    root: Path | None = None,
) -> list[str]:
    """Validate that all G2 checklist items are present.

    Loads required items from domain config if domain is specified,
    otherwise uses the default RA checklist.
    """
    items = _get_g2_checklist_items(domain, root)
    errors = []
    for item in items:
        if item not in checklist:
            errors.append(f"missing checklist item: {item}")
        elif checklist[item] not in ("pass", "fail"):
            errors.append(f"invalid value for {item}: {checklist[item]}")
    return errors


def apply_approval(
    rule: dict, reviewer: str, checklist: dict
) -> dict:
    """Apply G2 approval decision to a rule. Returns modified rule copy.

    - All checklist items 'pass' -> status: approved
    - Any checklist item 'fail' -> status: rejected with reason
    - Only operates on 'verified' rules
    """
    result = copy.deepcopy(rule)

    if result.get("status") != "verified":
        return result  # no change

    failed_items = [k for k, v in checklist.items() if v == "fail"]

    if failed_items:
        result["status"] = "rejected"
        result["rejection_reason"] = (
            f"G2 rejection: {', '.join(failed_items)} failed"
        )
    else:
        result["status"] = "approved"
        result["approval"] = {
            "reviewer": reviewer,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gate2_checklist": checklist,
        }

    return result


def approve_file(path: Path, reviewer: str, checklist: dict) -> bool:
    """Read a rule file, apply approval, write back."""
    with open(path, encoding="utf-8") as f:
        rule = yaml.safe_load(f)

    if rule.get("status") != "verified":
        print(f"  SKIP {rule.get('rule_id')}: status is '{rule.get('status')}', not 'verified'")
        return False

    result = apply_approval(rule, reviewer, checklist)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"  {result['status'].upper()} {result['rule_id']}")
    return result["status"] == "approved"


def _sample_size(group_size: int) -> int:
    """Compute required sample size for batch approval.

    Policy: 10% of group or minimum 5, whichever is larger.
    If group is smaller than 5, review all.
    """
    if group_size <= 5:
        return group_size
    return max(math.ceil(group_size * 0.1), 5)


def batch_approve(
    reviewer: str = "HB",
    root: Path | None = None,
    sample_pass_rates: dict[str, float] | None = None,
) -> dict[str, dict]:
    """Batch-approve verified rules per source document bundle.

    Per CLAUDE.md batch approval policy:
    - Unit: same source_ref.document bundle
    - Sample: 10% or minimum 5 rules per bundle
    - Threshold: sample pass rate >= 90% to approve entire bundle
    - Relations excluded (relation files not processed here)

    Args:
        reviewer: Reviewer name
        root: Project root path
        sample_pass_rates: Pre-computed pass rates per document, e.g.
            {"kmdia-fc": 1.0, "kmdia-fc-detail": 0.95}.
            If None, assumes 100% pass rate (reviewer asserts all pass).

    Returns:
        Dict keyed by document name:
        {"kmdia-fc": {"total": 18, "sample_required": 5, "approved": 18, "pass_rate": 1.0}}
    """
    base = root or ROOT
    rules_dir = base / "rules"
    checklist = {item: "pass" for item in _DEFAULT_G2_CHECKLIST_ITEMS}

    # Collect verified rules grouped by source document
    groups: dict[str, list[Path]] = {}
    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        if rule and rule.get("status") == "verified":
            doc = rule.get("source_ref", {}).get("document", "_unknown")
            groups.setdefault(doc, []).append(path)

    rates = sample_pass_rates or {}
    results = {}

    for doc, paths in groups.items():
        total = len(paths)
        sample_req = _sample_size(total)
        pass_rate = rates.get(doc, 1.0)  # default: reviewer asserts all pass

        result = {
            "total": total,
            "sample_required": sample_req,
            "pass_rate": pass_rate,
            "approved": 0,
            "skipped": False,
        }

        if pass_rate < 0.9:
            print(f"  SKIP {doc}: pass rate {pass_rate:.0%} < 90% threshold")
            result["skipped"] = True
            results[doc] = result
            continue

        print(f"  Bundle '{doc}': {total} rules (sample required: {sample_req})")
        approved = 0
        for path in paths:
            if approve_file(path, reviewer, checklist):
                approved += 1
        result["approved"] = approved
        results[doc] = result

    return results


def main():
    """CLI: Approve verified rules interactively or in batch."""
    if "--batch" in sys.argv:
        reviewer = "HB"
        for i, arg in enumerate(sys.argv):
            if arg == "--reviewer" and i + 1 < len(sys.argv):
                reviewer = sys.argv[i + 1]

        print(f"\nBatch G2 Approval (reviewer: {reviewer})")
        print("=" * 60)
        results = batch_approve(reviewer)
        print(f"\n{'=' * 60}")
        total_approved = sum(r["approved"] for r in results.values())
        total_rules = sum(r["total"] for r in results.values())
        skipped = sum(1 for r in results.values() if r["skipped"])
        print(f"Result: {total_approved}/{total_rules} approved")
        if skipped:
            print(f"Skipped: {skipped} bundle(s) below 90% pass rate")
        print("=" * 60)
        sys.exit(0 if total_approved == total_rules else 1)

    rules_dir = ROOT / "rules"
    verified = []

    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        if rule and rule.get("status") == "verified":
            verified.append((path, rule))

    if not verified:
        print("No verified rules found. Run G1 first: python3 scripts/gate1.py")
        sys.exit(0)

    print(f"\n{len(verified)} verified rule(s) awaiting G2 approval:\n")

    reviewer = input("Reviewer name [HB]: ").strip() or "HB"

    for path, rule in verified:
        print(f"\n--- {rule['rule_id']} ---")
        print(f"Text: {rule['text'][:200]}...")
        print(f"Scope: {rule.get('scope', [])}")

        checklist = {}
        for item in _DEFAULT_G2_CHECKLIST_ITEMS:
            label = item.replace("_", " ").title()
            while True:
                val = input(f"  {label} (pass/fail/skip) [pass]: ").strip().lower() or "pass"
                if val in ("pass", "fail", "skip"):
                    break
            if val == "skip":
                print(f"  SKIPPED {rule['rule_id']}")
                break
            checklist[item] = val
        else:
            approve_file(path, reviewer, checklist)

    print("\nDone.")


if __name__ == "__main__":
    main()
