"""End-to-end test: G1 -> G2 -> Agent citation pipeline."""

import copy

from gate1 import run_gate1
from approve import apply_approval
from retrieve import format_citation


def test_full_pipeline_draft_to_citation(sample_rule, root):
    """A rule goes from draft -> verified -> approved -> citable."""
    rule = copy.deepcopy(sample_rule)
    assert rule["status"] == "draft"

    # Step 1: G1
    g1_result = run_gate1(rule, root)
    assert g1_result["passed"], f"G1 failed: {g1_result['errors']}"
    rule["status"] = g1_result["new_status"]
    assert rule["status"] == "verified"

    # Step 2: G2
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    rule = apply_approval(rule, "HB", checklist)
    assert rule["status"] == "approved"
    assert rule["approval"]["reviewer"] == "HB"

    # Step 3: Citation
    citation = format_citation(rule)
    assert citation is not None
    assert "[근거: test-sample-rule]" in citation
    assert "[미승인]" not in citation


def test_rejected_rule_is_not_citable(sample_rule, root):
    """A rule rejected at G2 cannot be cited."""
    rule = copy.deepcopy(sample_rule)
    rule["status"] = "verified"

    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "fail",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    rule = apply_approval(rule, "HB", checklist)
    assert rule["status"] == "rejected"

    citation = format_citation(rule)
    assert citation is None


def test_verified_rule_has_warning(sample_rule, root):
    """A verified but unapproved rule is cited with warning."""
    rule = copy.deepcopy(sample_rule)

    g1_result = run_gate1(rule, root)
    rule["status"] = g1_result["new_status"]

    citation = format_citation(rule)
    assert citation is not None
    assert "[미승인]" in citation
