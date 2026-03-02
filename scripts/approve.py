"""Gate 2 approval workflow.

Provides functions for human approval of verified Rule Units.
G2 checks what LLM structurally cannot:
- Semantic accuracy
- Scope completeness
- Authority correctness
- Relation validity
"""

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

G2_CHECKLIST_ITEMS = [
    "semantic_accuracy",
    "scope_completeness",
    "authority_correctness",
    "relation_validity",
]


def validate_g2_checklist(checklist: dict) -> list[str]:
    """Validate that all 4 G2 checklist items are present."""
    errors = []
    for item in G2_CHECKLIST_ITEMS:
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


def main():
    """CLI: Approve verified rules interactively."""
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
        for item in G2_CHECKLIST_ITEMS:
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
