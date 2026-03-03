"""Tests for Gate 1 auto-verification pipeline."""

import pytest
import yaml

from gate1 import (
    check_schema,
    check_duplicates,
    check_source_ref,
    check_authority,
    check_text_fidelity,
    check_scope_text_coherence,
    run_gate1,
)


def test_valid_rule_passes_schema(sample_rule):
    errors = check_schema(sample_rule)
    assert errors == []


def test_missing_required_field_fails(sample_rule):
    del sample_rule["scope"]
    errors = check_schema(sample_rule)
    assert len(errors) == 1
    assert "scope" in errors[0].lower() or "required" in errors[0].lower()


def test_invalid_authority_passes_schema(sample_rule):
    """Authority is validated at runtime (check_authority), not schema level."""
    sample_rule["authority"] = "invalid_level"
    errors = check_schema(sample_rule)
    assert errors == []


def test_invalid_authority_fails_runtime(sample_rule, root):
    """Runtime check_authority catches invalid values via domain config."""
    sample_rule["authority"] = "invalid_level"
    errors = check_authority(sample_rule, root)
    assert len(errors) >= 1
    assert "invalid_level" in errors[0]


def test_valid_ra_authority_passes_runtime(sample_rule, root):
    """Valid RA authority value passes runtime check."""
    sample_rule["authority"] = "regulation"
    errors = check_authority(sample_rule, root)
    assert errors == []


def test_empty_text_fails(sample_rule):
    sample_rule["text"] = "short"
    errors = check_schema(sample_rule)
    assert len(errors) >= 1


def test_invalid_rule_id_pattern_fails(sample_rule):
    sample_rule["rule_id"] = "INVALID_ID"
    errors = check_schema(sample_rule)
    assert len(errors) >= 1


# --- Duplicate detection tests ---


def test_no_duplicates_passes():
    rules = [
        {"rule_id": "a", "text": "완전히 다른 내용의 규칙 텍스트입니다."},
        {"rule_id": "b", "text": "이것은 전혀 관련 없는 별도의 규칙입니다."},
    ]
    errors = check_duplicates(
        {"rule_id": "c", "text": "새로운 고유한 규칙 텍스트입니다."}, rules
    )
    assert errors == []


def test_near_duplicate_rejected():
    existing = [
        {"rule_id": "a", "text": "사업자는 기부금품 전달이 완료된 후 협회에 통보하여야 한다."},
    ]
    candidate = {
        "rule_id": "b",
        "text": "사업자는 기부금품 전달이 완료된 후 협회에 통보하여야 한다.",
    }
    errors = check_duplicates(candidate, existing)
    assert len(errors) == 1
    assert "a" in errors[0]  # references the duplicate rule_id


def test_similar_but_below_threshold_passes():
    existing = [
        {"rule_id": "a", "text": "사업자는 기부행위를 할 수 있다."},
    ]
    candidate = {
        "rule_id": "b",
        "text": "사업자는 기부금품의 회계처리 시 증빙자료를 첨부하여야 한다.",
    }
    errors = check_duplicates(candidate, existing)
    assert errors == []


# --- source_ref integrity tests ---


def test_valid_source_ref_passes():
    rule = {
        "source_ref": {"document": "kmdia-fc", "version": "2022.04", "location": "제1조"},
    }
    errors = check_source_ref(rule)
    assert errors == []


def test_unknown_document_fails():
    rule = {
        "source_ref": {"document": "nonexistent", "version": "2022.04", "location": "제1조"},
    }
    errors = check_source_ref(rule)
    assert len(errors) == 1
    assert "nonexistent" in errors[0]


def test_unknown_version_fails():
    rule = {
        "source_ref": {"document": "kmdia-fc", "version": "9999.99", "location": "제1조"},
    }
    errors = check_source_ref(rule)
    assert len(errors) == 1


# --- Gate orchestrator tests ---


def test_run_gate1_passes_valid_draft(sample_rule, root):
    result = run_gate1(sample_rule, root)
    assert result["passed"] is True
    assert result["new_status"] == "verified"
    assert result["errors"] == []


def test_run_gate1_rejects_invalid(sample_rule, root):
    del sample_rule["scope"]
    result = run_gate1(sample_rule, root)
    assert result["passed"] is False
    assert result["new_status"] == "rejected"
    assert len(result["errors"]) > 0


def test_run_gate1_skips_non_draft(sample_rule, root):
    sample_rule["status"] = "approved"
    result = run_gate1(sample_rule, root)
    assert result["passed"] is False
    assert "draft" in result["errors"][0].lower()


# --- Text fidelity tests ---


def test_text_fidelity_skips_when_no_pymupdf(monkeypatch, sample_rule):
    """Graceful skip when pymupdf is not installed."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("mocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    warnings = check_text_fidelity(sample_rule)
    assert len(warnings) == 1
    assert "pymupdf not installed" in warnings[0]


def test_text_fidelity_skips_when_pdf_not_found(sample_rule, root):
    """Warning when PDF file does not exist on disk."""
    # source_ref points to kmdia-fc v2022.04 which has a file entry
    # but the actual PDF won't exist in the repo
    warnings = check_text_fidelity(sample_rule, root)
    assert len(warnings) >= 1
    # Either pymupdf not installed or PDF not found — both are acceptable skips
    assert any(
        "pymupdf" in w or "PDF not found" in w or "skipping" in w
        for w in warnings
    )


# --- Scope-text coherence tests ---


def test_scope_coherence_skips_when_no_anthropic(monkeypatch, sample_rule):
    """Graceful skip when anthropic is not installed."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("mocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    warnings = check_scope_text_coherence(sample_rule)
    assert len(warnings) == 1
    assert "anthropic not installed" in warnings[0]


def test_scope_coherence_skips_when_no_api_key(monkeypatch, sample_rule):
    """Graceful skip when ANTHROPIC_API_KEY is not set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Ensure anthropic import works but API key is missing
    try:
        import anthropic  # noqa: F401

        warnings = check_scope_text_coherence(sample_rule)
        assert len(warnings) == 1
        assert "ANTHROPIC_API_KEY not set" in warnings[0]
    except ImportError:
        # anthropic not installed — also acceptable in test env
        warnings = check_scope_text_coherence(sample_rule)
        assert "anthropic not installed" in warnings[0]


# --- Warning isolation test ---


def test_run_gate1_warnings_dont_block_pass(sample_rule, root):
    """Warnings from text_fidelity/scope_coherence don't affect passed status."""
    result = run_gate1(sample_rule, root)
    assert result["passed"] is True
    # Warnings should exist (pymupdf/anthropic likely not installed in test env)
    assert len(result["warnings"]) >= 1
    assert result["errors"] == []
