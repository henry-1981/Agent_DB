"""Tests for scope pollution monitoring."""

from scope_monitor import scope_metrics, check_warnings, THRESHOLDS


def test_normal_scope_no_warnings():
    rules = [
        {"rule_id": "r1", "scope": ["조건 A (20자 이내)", "조건 B"]},
        {"rule_id": "r2", "scope": ["조건 C", "조건 D", "조건 E"]},
    ]
    metrics = scope_metrics(rules)
    assert metrics["total_rules"] == 2
    assert metrics["single_scope_count"] == 0
    assert metrics["broad_scope_count"] == 0
    assert check_warnings(metrics) == []


def test_broad_scope_detected():
    long_item = "이것은 매우 넓은 범위의 적용 조건으로서 50자를 초과하는 scope 항목의 예시입니다 여기에 더 많은 텍스트가 추가됩니다"
    rules = [
        {"rule_id": "r1", "scope": [long_item]},
    ]
    metrics = scope_metrics(rules)
    assert metrics["broad_scope_count"] == 1
    assert metrics["broad_scope_rules"][0][0] == "r1"


def test_single_scope_detected():
    rules = [
        {"rule_id": "r1", "scope": ["단일 조건"]},
    ]
    metrics = scope_metrics(rules)
    assert metrics["single_scope_count"] == 1
    assert "r1" in metrics["single_scope_rules"]


def test_empty_rules_handles_gracefully():
    metrics = scope_metrics([])
    assert metrics["total_rules"] == 0
    assert metrics["avg_scope_char_length"] == 0
    assert check_warnings(metrics) == []
