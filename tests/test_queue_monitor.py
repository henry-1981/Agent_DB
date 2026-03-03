"""Tests for G2 approval queue monitor."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from queue_monitor import _load_verified_rules, _age_days, queue_report, check_warnings


def _write_rule(rules_dir: Path, filename: str, rule: dict):
    """Helper to write a rule YAML file."""
    (rules_dir / filename).write_text(yaml.dump(rule, allow_unicode=True))


def _make_rule(rule_id: str, status: str, domain: str = "ra", **kwargs) -> dict:
    """Helper to create a minimal rule dict."""
    rule = {
        "rule_id": rule_id,
        "text": f"테스트 규칙 텍스트입니다 — {rule_id}.",
        "source_ref": {"document": "test", "version": "1.0", "location": "1조"},
        "scope": ["테스트 적용 범위"],
        "authority": "regulation",
        "status": status,
        "domain": domain,
    }
    rule.update(kwargs)
    return rule


def test_queue_lists_verified_rules():
    """Only verified rules are collected; approved/draft excluded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rules_dir = tmp / "rules"
        rules_dir.mkdir()
        (rules_dir / "_domain.yaml").write_text("domain: ra\n")

        _write_rule(rules_dir, "r1.yaml", _make_rule("r1", "verified"))
        _write_rule(rules_dir, "r2.yaml", _make_rule("r2", "approved"))
        _write_rule(rules_dir, "r3.yaml", _make_rule("r3", "draft"))
        _write_rule(rules_dir, "r4.yaml", _make_rule("r4", "verified"))

        rules = _load_verified_rules(tmp)
        ids = [r["rule_id"] for r in rules]
        assert "r1" in ids
        assert "r4" in ids
        assert "r2" not in ids
        assert "r3" not in ids


def test_queue_domain_filter():
    """Domain filter returns only matching domain rules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rules_dir = tmp / "rules"
        rules_dir.mkdir()
        (rules_dir / "_domain.yaml").write_text("domain: ra\n")

        _write_rule(rules_dir, "r1.yaml", _make_rule("r1", "verified", domain="ra"))
        _write_rule(rules_dir, "r2.yaml", _make_rule("r2", "verified", domain="test-legal"))

        entries = queue_report(root=tmp, domain="ra")
        assert len(entries) == 1
        assert entries[0]["rule_id"] == "r1"


def test_queue_empty():
    """Empty queue when no verified rules exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rules_dir = tmp / "rules"
        rules_dir.mkdir()
        (rules_dir / "_domain.yaml").write_text("domain: ra\n")

        _write_rule(rules_dir, "r1.yaml", _make_rule("r1", "approved"))

        entries = queue_report(root=tmp)
        assert entries == []


def test_warnings_queue_size():
    """Warning when queue size exceeds threshold."""
    entries = [{"rule_id": f"r{i}", "age_days": 1.0} for i in range(15)]
    warnings = check_warnings(entries)
    assert any("queue size" in w for w in warnings)


def test_warnings_age():
    """Warning when rules wait longer than threshold."""
    entries = [
        {"rule_id": "r1", "age_days": 20.0},
        {"rule_id": "r2", "age_days": 5.0},
    ]
    warnings = check_warnings(entries)
    assert any("waiting" in w or "days" in w for w in warnings)


def test_age_with_verified_at():
    """Age calculation uses verified_at timestamp."""
    ts = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rule = _make_rule("r1", "verified", verified_at=ts)
    age = _age_days(rule, "/nonexistent")
    assert 6.5 < age < 7.5
