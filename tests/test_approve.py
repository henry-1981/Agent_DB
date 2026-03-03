"""Tests for G2 approval workflow."""

import copy
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from approve import apply_approval, validate_g2_checklist, batch_approve, _sample_size


def test_valid_checklist_passes():
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    errors = validate_g2_checklist(checklist)
    assert errors == []


def test_checklist_with_fail_is_valid():
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "fail",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    errors = validate_g2_checklist(checklist)
    assert errors == []


def test_missing_checklist_item_fails():
    checklist = {"semantic_accuracy": "pass"}
    errors = validate_g2_checklist(checklist)
    assert len(errors) > 0


def test_apply_approval_to_verified_rule(sample_rule):
    sample_rule["status"] = "verified"
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    result = apply_approval(sample_rule, "HB", checklist)
    assert result["status"] == "approved"
    assert result["approval"]["reviewer"] == "HB"
    assert "timestamp" in result["approval"]


def test_apply_approval_rejects_if_checklist_has_fail(sample_rule):
    sample_rule["status"] = "verified"
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "fail",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    result = apply_approval(sample_rule, "HB", checklist)
    assert result["status"] == "rejected"
    assert "scope_completeness" in result.get("rejection_reason", "")


def test_apply_approval_only_verified(sample_rule):
    sample_rule["status"] = "draft"
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    result = apply_approval(sample_rule, "HB", checklist)
    assert result["status"] == "draft"  # unchanged


# --- Domain-aware G2 checklist tests ---


def test_g2_checklist_loads_from_domain_config(root):
    """When domain is specified, loads checklist from domain config."""
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    errors = validate_g2_checklist(checklist, domain="ra", root=root)
    assert errors == []


def test_g2_checklist_falls_back_to_default():
    """Without domain, uses default checklist items."""
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    errors = validate_g2_checklist(checklist, domain=None)
    assert errors == []


# --- Sample size policy tests ---


class TestSampleSize:
    def test_small_group_reviews_all(self):
        assert _sample_size(3) == 3
        assert _sample_size(5) == 5

    def test_ten_percent_or_min_five(self):
        assert _sample_size(100) == 10  # 10%
        assert _sample_size(30) == 5    # 10%=3, min 5 wins
        assert _sample_size(60) == 6    # 10%=6 > 5

    def test_single_rule(self):
        assert _sample_size(1) == 1


# --- Batch approve policy tests ---


def _make_verified_rules(tmpdir, doc_name, count):
    """Helper: create N verified rules under a temp rules dir."""
    tmp = Path(tmpdir)
    rules_dir = tmp / "rules"
    rules_dir.mkdir(exist_ok=True)
    (rules_dir / "_domain.yaml").write_text("domain: ra\n")
    for i in range(count):
        rule = {
            "rule_id": f"{doc_name}-rule-{i}",
            "text": f"규칙 텍스트 {i}번",
            "source_ref": {"document": doc_name, "version": "1.0", "location": f"제{i+1}조"},
            "scope": [f"적용범위 {i}"],
            "authority": "regulation",
            "status": "verified",
        }
        (rules_dir / f"{doc_name}-rule-{i}.yaml").write_text(
            yaml.dump(rule, allow_unicode=True)
        )
    return tmp


class TestBatchApprove:
    def test_groups_by_document(self):
        """Rules are grouped by source_ref.document."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            rules_dir = tmp / "rules"
            rules_dir.mkdir()
            (rules_dir / "_domain.yaml").write_text("domain: ra\n")
            for doc in ["doc-A", "doc-B"]:
                for i in range(2):
                    rule = {
                        "rule_id": f"{doc}-{i}",
                        "text": f"텍스트 {doc} {i}",
                        "source_ref": {"document": doc, "version": "1.0", "location": f"{i}조"},
                        "scope": ["범위"],
                        "authority": "regulation",
                        "status": "verified",
                    }
                    (rules_dir / f"{doc}-{i}.yaml").write_text(
                        yaml.dump(rule, allow_unicode=True)
                    )
            results = batch_approve("HB", root=tmp)
            assert "doc-A" in results
            assert "doc-B" in results
            assert results["doc-A"]["total"] == 2
            assert results["doc-B"]["total"] == 2
            assert results["doc-A"]["approved"] == 2
            assert results["doc-B"]["approved"] == 2

    def test_skips_below_threshold(self):
        """Bundles with pass rate < 90% are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = _make_verified_rules(tmpdir, "low-quality-doc", 3)
            results = batch_approve(
                "HB",
                root=tmp,
                sample_pass_rates={"low-quality-doc": 0.80},
            )
            assert results["low-quality-doc"]["skipped"] is True
            assert results["low-quality-doc"]["approved"] == 0

    def test_approves_above_threshold(self):
        """Bundles with pass rate >= 90% are approved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = _make_verified_rules(tmpdir, "good-doc", 3)
            results = batch_approve(
                "HB",
                root=tmp,
                sample_pass_rates={"good-doc": 0.95},
            )
            assert results["good-doc"]["skipped"] is False
            assert results["good-doc"]["approved"] == 3

    def test_sample_required_field(self):
        """Result includes correct sample_required per bundle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = _make_verified_rules(tmpdir, "big-doc", 50)
            results = batch_approve("HB", root=tmp)
            # 50 rules → 10% = 5
            assert results["big-doc"]["sample_required"] == 5
            assert results["big-doc"]["total"] == 50

    def test_empty_returns_empty(self):
        """No verified rules → empty result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            rules_dir = tmp / "rules"
            rules_dir.mkdir()
            (rules_dir / "_domain.yaml").write_text("domain: ra\n")
            results = batch_approve("HB", root=tmp)
            assert results == {}
