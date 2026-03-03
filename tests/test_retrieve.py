"""Tests for Agent retrieval and citation module."""

import tempfile
from pathlib import Path

import yaml

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


def test_search_with_domain_filter():
    """Domain filter returns only matching domain rules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rules_dir = tmp / "rules"
        rules_dir.mkdir()
        # _domain.yaml fallback
        (rules_dir / "_domain.yaml").write_text("domain: ra\n")
        # RA domain rule
        rule_ra = {
            "rule_id": "ra-rule-1",
            "text": "RA 도메인 기부 금지 규칙 텍스트입니다.",
            "source_ref": {"document": "test", "version": "1.0", "location": "1조"},
            "scope": ["기부 금지"],
            "authority": "regulation",
            "status": "approved",
            "domain": "ra",
        }
        (rules_dir / "ra-rule.yaml").write_text(
            yaml.dump(rule_ra, allow_unicode=True)
        )
        # Other domain rule
        rule_other = {
            "rule_id": "legal-rule-1",
            "text": "법률 도메인 기부 금지 규칙 텍스트입니다.",
            "source_ref": {"document": "test", "version": "1.0", "location": "1조"},
            "scope": ["기부 금지"],
            "authority": "statute",
            "status": "approved",
            "domain": "test-legal",
        }
        (rules_dir / "legal-rule.yaml").write_text(
            yaml.dump(rule_other, allow_unicode=True)
        )

        # With domain filter
        results = search_rules(
            "기부 금지", root=tmp, status_filter=StatusFilter.ALL, domain="ra"
        )
        assert len(results) == 1
        assert results[0]["rule_id"] == "ra-rule-1"


def test_search_without_domain_returns_all():
    """domain=None returns all matching rules regardless of domain."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rules_dir = tmp / "rules"
        rules_dir.mkdir()
        (rules_dir / "_domain.yaml").write_text("domain: ra\n")

        for i, dom in enumerate(["ra", "test-legal"]):
            rule = {
                "rule_id": f"rule-{dom}-{i}",
                "text": f"도메인 {dom} 기부 금지 규칙 텍스트입니다.",
                "source_ref": {"document": "t", "version": "1.0", "location": "1조"},
                "scope": ["기부 금지"],
                "authority": "regulation",
                "status": "approved",
                "domain": dom,
            }
            (rules_dir / f"rule-{dom}.yaml").write_text(
                yaml.dump(rule, allow_unicode=True)
            )

        results = search_rules(
            "기부 금지", root=tmp, status_filter=StatusFilter.ALL, domain=None
        )
        assert len(results) == 2
