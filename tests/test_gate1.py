"""Tests for Gate 1 auto-verification pipeline."""

import pytest
import yaml

from gate1 import check_schema


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
