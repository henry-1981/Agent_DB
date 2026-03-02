"""Tests for G2 approval workflow."""

import copy
from datetime import datetime, timezone

from approve import apply_approval, validate_g2_checklist


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
