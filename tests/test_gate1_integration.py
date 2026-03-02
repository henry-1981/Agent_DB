"""Integration tests: run G1 on actual rule files."""

from pathlib import Path

import yaml

from gate1 import run_gate1

ROOT = Path(__file__).resolve().parent.parent


def test_all_existing_rules_pass_gate1():
    """Every rule in rules/ should pass G1 (or have already advanced past draft)."""
    rules_dir = ROOT / "rules"
    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        # Rules that already passed G1 (verified/approved) are not re-checked
        if rule.get("status") != "draft":
            continue
        result = run_gate1(rule, ROOT)
        assert result["passed"], (
            f"{path.name}: G1 failed — {result['errors']}"
        )
