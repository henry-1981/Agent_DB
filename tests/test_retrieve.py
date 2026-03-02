"""Tests for Agent retrieval and citation module."""

from retrieve import search_rules, format_citation, StatusFilter


def test_search_returns_matching_rules(root, load_yaml):
    # All existing rules are draft; use ALL filter to test search logic
    results = search_rules("기부 금지", root=root, status_filter=StatusFilter.ALL)
    rule_ids = [r["rule_id"] for r in results]
    assert "kmdia-fc-art7-p1-item1" in rule_ids


def test_search_returns_empty_for_unrelated_query(root):
    results = search_rules("회계 감사 기준", root=root, status_filter=StatusFilter.ALL)
    assert len(results) == 0 or all(
        r.get("_score", 0) < 0.5 for r in results
    )


def test_status_filter_approved_only():
    f = StatusFilter.APPROVED_ONLY
    assert f.allows("approved") is True
    assert f.allows("verified") is False
    assert f.allows("draft") is False


def test_status_filter_verified_and_above():
    f = StatusFilter.VERIFIED_AND_ABOVE
    assert f.allows("approved") is True
    assert f.allows("verified") is True
    assert f.allows("draft") is False


def test_format_citation_approved():
    rule = {
        "rule_id": "test-rule-1",
        "text": "테스트 규칙 텍스트입니다.",
        "status": "approved",
    }
    citation = format_citation(rule)
    assert "[근거: test-rule-1]" in citation
    assert "테스트 규칙 텍스트입니다." in citation


def test_format_citation_verified_has_warning():
    rule = {
        "rule_id": "test-rule-1",
        "text": "테스트 규칙 텍스트입니다.",
        "status": "verified",
    }
    citation = format_citation(rule)
    assert "[미승인]" in citation


def test_format_citation_draft_blocked():
    rule = {
        "rule_id": "test-rule-1",
        "text": "테스트 규칙 텍스트입니다.",
        "status": "draft",
    }
    citation = format_citation(rule)
    assert citation is None
