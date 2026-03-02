"""Tests for orphan relation cascade."""

import tempfile
from pathlib import Path

import yaml

from cascade import find_orphan_relations, cascade_relation


def _setup_test_data(tmp: Path, rules: list[dict], relations: list[dict]):
    """Create temp rule and relation files for testing."""
    rules_dir = tmp / "rules"
    rules_dir.mkdir(parents=True)
    for rule in rules:
        path = rules_dir / f"{rule['rule_id']}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(rule, f, allow_unicode=True)

    rel_dir = tmp / "relations"
    rel_dir.mkdir(parents=True)
    for rel in relations:
        path = rel_dir / f"{rel['relation_id']}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(rel, f, allow_unicode=True)


def test_find_orphan_with_suspended_rule():
    """Relation referencing a suspended Rule Unit is flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _setup_test_data(
            tmp_path,
            rules=[
                {"rule_id": "rule-a", "status": "suspended"},
                {"rule_id": "rule-b", "status": "approved"},
            ],
            relations=[
                {
                    "relation_id": "rel-001",
                    "source_rule": "rule-a",
                    "target_rule": "rule-b",
                    "status": "approved",
                },
            ],
        )
        orphans = find_orphan_relations(tmp_path)
        assert len(orphans) == 1
        assert "suspended" in orphans[0][2]


def test_find_orphan_with_superseded_rule():
    """Relation referencing a superseded Rule Unit is flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _setup_test_data(
            tmp_path,
            rules=[
                {"rule_id": "rule-a", "status": "approved"},
                {"rule_id": "rule-b", "status": "superseded"},
            ],
            relations=[
                {
                    "relation_id": "rel-001",
                    "source_rule": "rule-a",
                    "target_rule": "rule-b",
                    "status": "approved",
                },
            ],
        )
        orphans = find_orphan_relations(tmp_path)
        assert len(orphans) == 1
        assert "superseded" in orphans[0][2]


def test_find_orphan_clean_state():
    """No orphans when all referenced rules are active."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _setup_test_data(
            tmp_path,
            rules=[
                {"rule_id": "rule-a", "status": "approved"},
                {"rule_id": "rule-b", "status": "approved"},
            ],
            relations=[
                {
                    "relation_id": "rel-001",
                    "source_rule": "rule-a",
                    "target_rule": "rule-b",
                    "status": "approved",
                },
            ],
        )
        orphans = find_orphan_relations(tmp_path)
        assert len(orphans) == 0


def test_cascade_approved_to_suspended():
    """Approved relation cascades to suspended with reason."""
    rel = {"relation_id": "rel-001", "status": "approved"}
    result = cascade_relation(rel, "target_rule 'x' is suspended")
    assert result["status"] == "suspended"
    assert "suspended" in result["suspension_reason"]


def test_cascade_draft_to_rejected():
    """Draft relation cascades to rejected with reason."""
    rel = {"relation_id": "rel-001", "status": "draft"}
    result = cascade_relation(rel, "source_rule 'y' is superseded")
    assert result["status"] == "rejected"
    assert "superseded" in result["rejection_reason"]


def test_cascade_already_suspended_unchanged():
    """Already suspended relation is not changed (idempotent)."""
    rel = {
        "relation_id": "rel-001",
        "status": "suspended",
        "suspension_reason": "previous cascade",
    }
    result = cascade_relation(rel, "new reason")
    assert result["status"] == "suspended"
    assert result["suspension_reason"] == "previous cascade"  # unchanged
