"""E2E tests for test-legal domain onboarding.

Validates that the domain plugin model correctly isolates
domain-specific configuration (authority levels, G2 checklists)
while sharing core Rule Unit infrastructure.

Each test builds a complete tempdir environment (via tmp_path)
to ensure zero impact on existing 23 approved Rule Units.
"""

import copy
from pathlib import Path

import yaml

from domain import resolve_domain, load_authority_levels, load_g2_checklist_items
from gate1 import run_gate1, check_authority
from approve import apply_approval, validate_g2_checklist
from retrieve import search_rules, format_citation, StatusFilter


# --- Test data constants ---

_TEST_LEGAL_AUTHORITY = {
    "levels": ["statute", "regulation", "corporate_policy", "guideline", "practice"]
}

_TEST_LEGAL_G2 = {
    "items": [
        {"id": "legal_validity"},
        {"id": "precedent_check"},
        {"id": "scope_completeness"},
    ]
}

_RA_AUTHORITY = {
    "levels": ["law", "regulation", "sop", "guideline", "precedent"]
}

_RA_G2 = {
    "items": [
        {"id": "semantic_accuracy"},
        {"id": "scope_completeness"},
        {"id": "authority_correctness"},
        {"id": "relation_validity"},
    ]
}

_SOURCES = {
    "sources": {
        "test-legal-compliance": {
            "title": "Test Legal Compliance Manual",
            "versions": [{"version": "2024.01", "file": "test-legal-compliance.pdf"}],
            "publisher": "Test Legal Department",
            "authority_level": "statute",
        }
    }
}


def _make_rule(
    rule_id: str,
    text: str,
    location: str,
    scope: list[str],
    authority: str,
    status: str = "draft",
    domain: str | None = "test-legal",
) -> dict:
    """Create a test rule dict with test-legal-compliance source."""
    rule = {
        "rule_id": rule_id,
        "text": text,
        "source_ref": {
            "document": "test-legal-compliance",
            "version": "2024.01",
            "location": location,
        },
        "scope": scope,
        "authority": authority,
        "status": status,
    }
    if domain:
        rule["domain"] = domain
    return rule


_DRAFT_RULES = [
    _make_rule(
        "tl-compliance-sec1-main",
        "모든 법무 계약서는 법무팀 검토를 거쳐야 한다. 계약 금액과 무관하게 필수적으로 적용된다.",
        "Section 1",
        ["법무 계약서 검토 의무"],
        "statute",
    ),
    _make_rule(
        "tl-compliance-sec2-main",
        "외부 법률자문 비용은 분기별 예산 한도 내에서 집행하여야 하며, 초과 시 법무이사 승인이 필요하다.",
        "Section 2",
        ["외부 법률자문 비용 예산 한도", "분기별 예산 초과 시 승인"],
        "regulation",
    ),
    _make_rule(
        "tl-compliance-sec3-main",
        "내부 고발 접수 시 법무팀은 72시간 이내에 초기 조사를 개시하여야 한다.",
        "Section 3",
        ["내부 고발 초기 조사 기한"],
        "corporate_policy",
    ),
]


def _setup_test_env(tmp: Path) -> Path:
    """Build complete dual-domain environment in tempdir.

    Structure:
        tmp/
        ├── domains/
        │   ├── test-legal/  (authority + checklist)
        │   └── ra/          (authority + checklist, for cross-domain tests)
        ├── sources/_sources.yaml
        └── rules/
            ├── _domain.yaml  (domain: ra — global fallback)
            └── test-legal/   (3 draft rules)
    """
    # domains/test-legal/
    tl_dir = tmp / "domains" / "test-legal"
    tl_dir.mkdir(parents=True)
    with open(tl_dir / "authority_levels.yaml", "w", encoding="utf-8") as f:
        yaml.dump(_TEST_LEGAL_AUTHORITY, f, allow_unicode=True)
    with open(tl_dir / "gate2_checklist.yaml", "w", encoding="utf-8") as f:
        yaml.dump(_TEST_LEGAL_G2, f, allow_unicode=True)

    # domains/ra/ (for cross-domain isolation tests)
    ra_dir = tmp / "domains" / "ra"
    ra_dir.mkdir(parents=True)
    with open(ra_dir / "authority_levels.yaml", "w", encoding="utf-8") as f:
        yaml.dump(_RA_AUTHORITY, f, allow_unicode=True)
    with open(ra_dir / "gate2_checklist.yaml", "w", encoding="utf-8") as f:
        yaml.dump(_RA_G2, f, allow_unicode=True)

    # sources/_sources.yaml
    src_dir = tmp / "sources"
    src_dir.mkdir(parents=True)
    with open(src_dir / "_sources.yaml", "w", encoding="utf-8") as f:
        yaml.dump(_SOURCES, f, allow_unicode=True)

    # rules/_domain.yaml (global fallback: ra)
    rules_dir = tmp / "rules"
    rules_dir.mkdir(parents=True)
    with open(rules_dir / "_domain.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"domain": "ra"}, f, allow_unicode=True)

    # rules/test-legal/*.yaml (3 draft rules)
    tl_rules_dir = rules_dir / "test-legal"
    tl_rules_dir.mkdir(parents=True)
    for rule in _DRAFT_RULES:
        path = tl_rules_dir / f"{rule['rule_id']}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(rule, f, allow_unicode=True)

    return tmp


# ===========================================================================
# TestDomainResolution — domain config loading and fallback behavior
# ===========================================================================


class TestDomainResolution:
    """Domain resolution with explicit field and fallback."""

    def test_explicit_domain_resolved(self, tmp_path):
        """Rule with explicit domain='test-legal' resolves correctly."""
        root = _setup_test_env(tmp_path)
        rule = {"domain": "test-legal"}
        assert resolve_domain(rule, root) == "test-legal"

    def test_authority_levels_loaded(self, tmp_path):
        """test-legal authority levels load with correct hierarchy."""
        root = _setup_test_env(tmp_path)
        levels = load_authority_levels("test-legal", root)
        assert levels == [
            "statute", "regulation", "corporate_policy", "guideline", "practice"
        ]

    def test_g2_checklist_loaded(self, tmp_path):
        """test-legal G2 checklist loads 3 items (not RA's 4)."""
        root = _setup_test_env(tmp_path)
        items = load_g2_checklist_items("test-legal", root)
        assert items == ["legal_validity", "precedent_check", "scope_completeness"]
        assert len(items) == 3

    def test_fallback_to_domain_marker(self, tmp_path):
        """Rule without domain field falls back to _domain.yaml (ra)."""
        root = _setup_test_env(tmp_path)
        rule = {"rule_id": "some-rule"}  # no domain field
        assert resolve_domain(rule, root) == "ra"


# ===========================================================================
# TestDomainIsolation — cross-domain authority boundary enforcement
# ===========================================================================


class TestDomainIsolation:
    """Cross-domain authority isolation."""

    def test_ra_authority_invalid_in_test_legal(self, tmp_path):
        """'sop' (RA-only) is rejected in test-legal domain."""
        root = _setup_test_env(tmp_path)
        rule = _make_rule(
            "tl-test-sop",
            "SOP 테스트용 규칙 텍스트입니다. 충분한 길이가 필요합니다.",
            "Section 99",
            ["테스트"],
            "sop",
            domain="test-legal",
        )
        errors = check_authority(rule, root)
        assert len(errors) == 1
        assert "sop" in errors[0]
        assert "test-legal" in errors[0]

    def test_test_legal_authority_invalid_in_ra(self, tmp_path):
        """'statute' (test-legal-only) is rejected in RA domain."""
        root = _setup_test_env(tmp_path)
        rule = _make_rule(
            "ra-test-statute",
            "Statute 테스트용 규칙 텍스트입니다. 충분한 길이가 필요합니다.",
            "Section 99",
            ["테스트"],
            "statute",
            domain="ra",
        )
        errors = check_authority(rule, root)
        assert len(errors) == 1
        assert "statute" in errors[0]
        assert "ra" in errors[0]

    def test_shared_authority_both_valid(self, tmp_path):
        """'regulation' exists in both domains — valid in each."""
        root = _setup_test_env(tmp_path)
        rule_tl = {"authority": "regulation", "domain": "test-legal"}
        rule_ra = {"authority": "regulation", "domain": "ra"}
        assert check_authority(rule_tl, root) == []
        assert check_authority(rule_ra, root) == []


# ===========================================================================
# TestE2EPipeline — full G1 -> G2 -> citation with test-legal domain
# ===========================================================================


class TestE2EPipeline:
    """Full G1 -> G2 -> citation pipeline for test-legal domain."""

    def test_full_pipeline(self, tmp_path):
        """draft -> verified -> approved -> citable for test-legal."""
        root = _setup_test_env(tmp_path)
        rule = copy.deepcopy(_DRAFT_RULES[0])  # statute authority

        # G1
        result = run_gate1(rule, root)
        assert result["passed"], f"G1 failed: {result['errors']}"
        rule["status"] = result["new_status"]
        assert rule["status"] == "verified"

        # G2 with test-legal checklist
        checklist = {
            "legal_validity": "pass",
            "precedent_check": "pass",
            "scope_completeness": "pass",
        }
        rule = apply_approval(rule, "TestReviewer", checklist)
        assert rule["status"] == "approved"
        assert rule["approval"]["reviewer"] == "TestReviewer"

        # Citation
        citation = format_citation(rule)
        assert citation is not None
        assert "[근거: tl-compliance-sec1-main]" in citation
        assert "[미승인]" not in citation

    def test_statute_authority_passes_g1(self, tmp_path):
        """'statute' is valid for test-legal, passes G1 authority check."""
        root = _setup_test_env(tmp_path)
        rule = copy.deepcopy(_DRAFT_RULES[0])
        assert rule["authority"] == "statute"

        result = run_gate1(rule, root)
        assert result["passed"], f"G1 failed: {result['errors']}"
        assert result["new_status"] == "verified"

    def test_g2_checklist_cross_domain_ra_on_test_legal(self, tmp_path):
        """RA checklist items applied to test-legal domain -> missing items error."""
        root = _setup_test_env(tmp_path)
        ra_checklist = {
            "semantic_accuracy": "pass",
            "scope_completeness": "pass",
            "authority_correctness": "pass",
            "relation_validity": "pass",
        }
        errors = validate_g2_checklist(ra_checklist, domain="test-legal", root=root)
        # test-legal requires: legal_validity, precedent_check, scope_completeness
        # RA checklist has scope_completeness but missing legal_validity and precedent_check
        assert len(errors) == 2
        combined = " ".join(errors)
        assert "legal_validity" in combined
        assert "precedent_check" in combined

    def test_g2_checklist_cross_domain_test_legal_on_ra(self, tmp_path):
        """test-legal checklist items applied to RA domain -> missing items error."""
        root = _setup_test_env(tmp_path)
        tl_checklist = {
            "legal_validity": "pass",
            "precedent_check": "pass",
            "scope_completeness": "pass",
        }
        errors = validate_g2_checklist(tl_checklist, domain="ra", root=root)
        # RA requires: semantic_accuracy, scope_completeness, authority_correctness, relation_validity
        # test-legal checklist has scope_completeness but missing 3 others
        assert len(errors) == 3
        combined = " ".join(errors)
        assert "semantic_accuracy" in combined
        assert "authority_correctness" in combined
        assert "relation_validity" in combined

    def test_invalid_authority_rejected_at_g1(self, tmp_path):
        """'sop' authority on test-legal rule -> G1 reject."""
        root = _setup_test_env(tmp_path)
        rule = _make_rule(
            "tl-invalid-auth",
            "SOP 테스트용 규칙 텍스트입니다. 충분한 길이가 필요합니다.",
            "Section 99",
            ["테스트 적용 범위"],
            "sop",
            domain="test-legal",
        )
        result = run_gate1(rule, root)
        assert not result["passed"]
        assert result["new_status"] == "rejected"
        assert any("sop" in e for e in result["errors"])


# ===========================================================================
# TestRetrieval — search and citation for test-legal rules
# ===========================================================================


class TestRetrieval:
    """Search and citation for test-legal rules."""

    def _approve_rule_in_tempdir(self, root: Path, rule_id: str):
        """Helper: manually set a rule to approved status in tempdir."""
        rule_path = root / "rules" / "test-legal" / f"{rule_id}.yaml"
        with open(rule_path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        rule["status"] = "approved"
        rule["approval"] = {
            "reviewer": "TestReviewer",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "gate2_checklist": {
                "legal_validity": "pass",
                "precedent_check": "pass",
                "scope_completeness": "pass",
            },
        }
        with open(rule_path, "w", encoding="utf-8") as f:
            yaml.dump(rule, f, allow_unicode=True)

    def test_search_finds_approved_rules(self, tmp_path):
        """Approved test-legal rules are discoverable via scope search."""
        root = _setup_test_env(tmp_path)
        self._approve_rule_in_tempdir(root, "tl-compliance-sec1-main")

        results = search_rules(
            "계약서 검토", root=root, status_filter=StatusFilter.APPROVED_ONLY,
        )
        assert len(results) >= 1
        assert results[0]["rule_id"] == "tl-compliance-sec1-main"

    def test_draft_excluded_by_default_filter(self, tmp_path):
        """Draft rules are not returned by VERIFIED_AND_ABOVE filter."""
        root = _setup_test_env(tmp_path)
        # All 3 rules are draft
        results = search_rules(
            "계약서", root=root, status_filter=StatusFilter.VERIFIED_AND_ABOVE,
        )
        assert len(results) == 0

    def test_citation_format_approved(self, tmp_path):
        """Approved test-legal rule gets standard citation format."""
        rule = copy.deepcopy(_DRAFT_RULES[0])
        rule["status"] = "approved"
        citation = format_citation(rule)
        assert citation is not None
        assert citation.startswith("[근거: tl-compliance-sec1-main]")
        assert "법무 계약서" in citation
