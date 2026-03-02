"""Tests for Gate 1 auto-verification pipeline."""

import pytest
import yaml

from gate1 import check_schema, check_duplicates


def test_valid_rule_passes_schema(sample_rule):
    errors = check_schema(sample_rule)
    assert errors == []


def test_missing_required_field_fails(sample_rule):
    del sample_rule["scope"]
    errors = check_schema(sample_rule)
    assert len(errors) == 1
    assert "scope" in errors[0].lower() or "required" in errors[0].lower()


def test_invalid_authority_fails(sample_rule):
    sample_rule["authority"] = "invalid_level"
    errors = check_schema(sample_rule)
    assert len(errors) >= 1


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
