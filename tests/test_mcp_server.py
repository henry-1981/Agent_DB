"""Tests for MCP server tools."""

from pathlib import Path

import pytest
import yaml

# Import the module under test — sys.path includes scripts/ via pyproject.toml
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from server import (  # noqa: E402
    _HIDDEN_STATUSES,
    _PUBLIC_FIELDS,
    _PUBLIC_RELATION_FIELDS,  # noqa: F401 (used in assertions)
    _filter_relation,
    _filter_rule,
    cite_rule_tool,
    get_context_tool,
    get_rule_tool,
    search_rules_tool,
)


def _make_rule(tmp_path: Path, rule_id: str, status: str = "approved", **overrides):
    """Write a minimal rule YAML and return its path."""
    rules_dir = tmp_path / "rules" / "test"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule = {
        "rule_id": rule_id,
        "text": overrides.pop("text", f"테스트 규칙 텍스트 {rule_id}"),
        "source_ref": {"document": "test-doc", "version": "1.0", "location": "제1조"},
        "scope": overrides.pop("scope", ["테스트 적용 범위"]),
        "authority": "regulation",
        "status": status,
        # Internal field that should be filtered out
        "approval": {"reviewer": "test", "timestamp": "2026-01-01"},
    }
    rule.update(overrides)
    path = rules_dir / f"{rule_id}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(rule, f, allow_unicode=True)
    return path


def _make_domain_config(tmp_path: Path, domain: str = "ra"):
    """Create domain config so resolve_domain works."""
    domain_dir = tmp_path / "domains" / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    with open(domain_dir / "authority_levels.yaml", "w") as f:
        yaml.dump({"levels": {"regulation": 1}}, f)
    # Default domain marker
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    with open(rules_dir / "_domain.yaml", "w") as f:
        yaml.dump({"default_domain": domain}, f)


class TestPublicFieldsFilter:
    """Verify _PUBLIC_FIELDS strips internal metadata."""

    def test_public_fields_set(self):
        assert "rule_id" in _PUBLIC_FIELDS
        assert "text" in _PUBLIC_FIELDS
        assert "source_ref" in _PUBLIC_FIELDS
        assert "scope" in _PUBLIC_FIELDS
        assert "authority" in _PUBLIC_FIELDS
        assert "status" in _PUBLIC_FIELDS

    def test_internal_fields_excluded(self):
        assert "_score" not in _PUBLIC_FIELDS
        assert "approval" not in _PUBLIC_FIELDS

    def test_filter_removes_extra_fields(self):
        rule = {
            "rule_id": "test-1",
            "text": "some text",
            "source_ref": {},
            "scope": [],
            "authority": "regulation",
            "status": "approved",
            "_score": 0.95,
            "approval": {"reviewer": "HB"},
        }
        filtered = {k: v for k, v in rule.items() if k in _PUBLIC_FIELDS}
        assert "_score" not in filtered
        assert "approval" not in filtered
        assert len(filtered) == 6


class TestLimitGuard:
    """Verify limit clamping to [1, 20]."""

    def test_limit_clamp_zero(self, tmp_path, monkeypatch):
        _make_rule(tmp_path, "r1", scope=["검색 키워드"])
        _make_domain_config(tmp_path)
        monkeypatch.setenv("RULE_DB_ROOT", str(tmp_path))
        # Patch _DB_ROOT at module level
        import server
        monkeypatch.setattr(server, "_DB_ROOT", tmp_path)
        results = search_rules_tool(query="검색 키워드", limit=0)
        # limit=0 → clamped to 1, so at most 1 result
        assert len(results) <= 1

    def test_limit_clamp_high(self, tmp_path, monkeypatch):
        _make_domain_config(tmp_path)
        # Create 25 rules
        for i in range(25):
            _make_rule(tmp_path, f"r{i}", scope=["공통 키워드"])
        import server
        monkeypatch.setattr(server, "_DB_ROOT", tmp_path)
        results = search_rules_tool(query="공통 키워드", limit=100)
        # limit=100 → clamped to 20
        assert len(results) <= 20


class TestSearchRulesTool:
    """Integration tests for search_rules_tool with tmp_path isolation."""

    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path, monkeypatch):
        _make_domain_config(tmp_path)
        import server
        monkeypatch.setattr(server, "_DB_ROOT", tmp_path)
        self.tmp_path = tmp_path

    def test_basic_search(self):
        _make_rule(self.tmp_path, "test-art1", scope=["의료기기 거래 금지"])
        results = search_rules_tool(query="의료기기 거래")
        assert len(results) >= 1
        assert results[0]["rule_id"] == "test-art1"

    def test_output_fields_only_public(self):
        _make_rule(self.tmp_path, "test-art2", scope=["경제적 이익 제공"])
        results = search_rules_tool(query="경제적 이익")
        assert len(results) >= 1
        for r in results:
            assert set(r.keys()).issubset(_PUBLIC_FIELDS)
            assert "_score" not in r
            assert "approval" not in r

    def test_draft_excluded(self):
        _make_rule(self.tmp_path, "draft-rule", status="draft", scope=["드래프트 규칙"])
        results = search_rules_tool(query="드래프트 규칙")
        assert len(results) == 0

    def test_suspended_excluded(self):
        _make_rule(self.tmp_path, "susp-rule", status="suspended", scope=["정지된 규칙"])
        results = search_rules_tool(query="정지된 규칙")
        assert len(results) == 0

    def test_verified_included(self):
        _make_rule(self.tmp_path, "ver-rule", status="verified", scope=["검증된 규칙"])
        results = search_rules_tool(query="검증된 규칙")
        assert len(results) >= 1
        assert results[0]["status"] == "verified"

    def test_limit_respected(self):
        for i in range(10):
            _make_rule(self.tmp_path, f"bulk-{i}", scope=["공통 검색어"])
        results = search_rules_tool(query="공통 검색어", limit=3)
        assert len(results) <= 3

    def test_empty_query_returns_empty(self):
        _make_rule(self.tmp_path, "any-rule", scope=["아무 범위"])
        results = search_rules_tool(query="")
        assert len(results) == 0


# --- Helpers for new tools ---


def _make_traceability(tmp_path: Path, parent: str, children: list[str]):
    """Write a traceability link YAML."""
    trace_dir = tmp_path / "traceability"
    trace_dir.mkdir(parents=True, exist_ok=True)
    link = {
        "parent": parent,
        "children": children,
        "hierarchy_type": "article-paragraph",
    }
    path = trace_dir / f"{parent}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(link, f, allow_unicode=True)
    return path


def _make_relation(
    tmp_path: Path,
    relation_id: str,
    source_rule: str,
    target_rule: str,
    rel_type: str = "excepts",
    status: str = "approved",
):
    """Write a relation YAML."""
    rel_dir = tmp_path / "relations"
    rel_dir.mkdir(parents=True, exist_ok=True)
    rel = {
        "relation_id": relation_id,
        "type": rel_type,
        "source_rule": source_rule,
        "target_rule": target_rule,
        "condition": "테스트 조건이 충족되는 경우에 한하여 적용",
        "resolution": "조건 충족 시 source 인용",
        "authority_basis": "테스트 근거",
        "status": status,
        "registered_by": "test",
    }
    path = rel_dir / f"{relation_id}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(rel, f, allow_unicode=True)
    return path


def _patch_context_cache(monkeypatch, tmp_path):
    """Reset context.py module-level cache to use tmp_path."""
    import context

    monkeypatch.setattr(context, "ROOT", tmp_path)
    monkeypatch.setattr(context, "TRACE_DIR", tmp_path / "traceability")
    # Reset lazy cache so it reloads from new TRACE_DIR
    monkeypatch.setattr(context, "_links", None)
    monkeypatch.setattr(context, "_parent_of", None)
    monkeypatch.setattr(context, "_children_of", None)
    monkeypatch.setattr(context, "_hierarchy_type_of", None)


# --- TestGetRuleTool ---


class TestGetRuleTool:
    """Tests for get_rule tool."""

    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path, monkeypatch):
        _make_domain_config(tmp_path)
        import server

        monkeypatch.setattr(server, "_DB_ROOT", tmp_path)
        self.tmp_path = tmp_path

    def test_approved_rule(self):
        _make_rule(self.tmp_path, "app-rule", status="approved")
        result = get_rule_tool(rule_id="app-rule")
        assert result is not None
        assert result["rule_id"] == "app-rule"
        assert result["status"] == "approved"

    def test_verified_rule(self):
        _make_rule(self.tmp_path, "ver-rule", status="verified")
        result = get_rule_tool(rule_id="ver-rule")
        assert result is not None
        assert result["status"] == "verified"

    def test_draft_returns_none(self):
        _make_rule(self.tmp_path, "draft-rule", status="draft")
        result = get_rule_tool(rule_id="draft-rule")
        assert result is None

    def test_rejected_returns_none(self):
        _make_rule(self.tmp_path, "rej-rule", status="rejected")
        result = get_rule_tool(rule_id="rej-rule")
        assert result is None

    def test_not_found_returns_none(self):
        result = get_rule_tool(rule_id="nonexistent")
        assert result is None

    def test_suspended_returned_with_status(self):
        """suspended rules are visible (not hidden) but must not be cited."""
        _make_rule(self.tmp_path, "susp-rule", status="suspended")
        result = get_rule_tool(rule_id="susp-rule")
        assert result is not None
        assert result["status"] == "suspended"

    def test_superseded_returned_with_status(self):
        """superseded rules are visible (for redirect) but must not be cited."""
        _make_rule(self.tmp_path, "super-rule", status="superseded")
        result = get_rule_tool(rule_id="super-rule")
        assert result is not None
        assert result["status"] == "superseded"

    def test_internal_fields_excluded(self):
        _make_rule(self.tmp_path, "field-rule", status="approved")
        result = get_rule_tool(rule_id="field-rule")
        assert result is not None
        assert "approval" not in result
        assert set(result.keys()).issubset(_PUBLIC_FIELDS)


# --- TestGetContextTool ---


class TestGetContextTool:
    """Tests for get_context tool."""

    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path, monkeypatch):
        _make_domain_config(tmp_path)
        import server

        monkeypatch.setattr(server, "_DB_ROOT", tmp_path)
        _patch_context_cache(monkeypatch, tmp_path)
        self.tmp_path = tmp_path

    def test_full_context(self):
        _make_rule(self.tmp_path, "parent-1", status="approved")
        _make_rule(self.tmp_path, "child-1", status="approved")
        _make_rule(self.tmp_path, "child-2", status="approved")
        _make_traceability(self.tmp_path, "parent-1", ["child-1", "child-2"])

        result = get_context_tool(rule_id="parent-1")
        assert result["rule"] is not None
        assert result["rule"]["rule_id"] == "parent-1"
        assert result["hierarchy"]["children"] == ["child-1", "child-2"]

    def test_context_with_relations(self):
        _make_rule(self.tmp_path, "src-rule", status="approved")
        _make_rule(self.tmp_path, "tgt-rule", status="approved")
        _make_relation(self.tmp_path, "rel-1", "src-rule", "tgt-rule")

        result = get_context_tool(rule_id="src-rule")
        assert len(result["relations"]) == 1
        rel = result["relations"][0]
        assert rel["relation_id"] == "rel-1"
        assert rel["source_rule"] == "src-rule"
        # Internal field excluded
        assert "registered_by" not in rel
        assert set(rel.keys()).issubset(_PUBLIC_RELATION_FIELDS)

    def test_nonexistent_rule(self):
        result = get_context_tool(rule_id="nonexistent")
        assert result["rule"] is None
        assert result["hierarchy"]["parent"] is None
        assert result["hierarchy"]["children"] == []
        assert result["relations"] == []

    def test_no_traceability(self):
        _make_rule(self.tmp_path, "lone-rule", status="approved")
        result = get_context_tool(rule_id="lone-rule")
        assert result["rule"] is not None
        assert result["hierarchy"]["parent"] is None
        assert result["hierarchy"]["children"] == []
        assert result["hierarchy"]["siblings"] == []


# --- TestCiteRuleTool ---


class TestCiteRuleTool:
    """Tests for cite_rule tool."""

    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path, monkeypatch):
        _make_domain_config(tmp_path)
        import server

        monkeypatch.setattr(server, "_DB_ROOT", tmp_path)
        self.tmp_path = tmp_path

    def test_approved_citable(self):
        _make_rule(self.tmp_path, "app-r", status="approved", text="공식 근거 텍스트")
        result = cite_rule_tool(rule_id="app-r")
        assert result["citable"] is True
        assert result["status"] == "approved"
        assert "[근거: app-r]" in result["citation"]
        assert "공식 근거 텍스트" in result["citation"]

    def test_verified_citable_with_warning(self):
        _make_rule(self.tmp_path, "ver-r", status="verified", text="미승인 텍스트")
        result = cite_rule_tool(rule_id="ver-r")
        assert result["citable"] is True
        assert result["status"] == "verified"
        assert "[미승인]" in result["citation"]

    def test_draft_not_citable(self):
        _make_rule(self.tmp_path, "draft-r", status="draft")
        result = cite_rule_tool(rule_id="draft-r")
        assert result["citable"] is False
        assert result["citation"] is None

    def test_suspended_not_citable(self):
        _make_rule(self.tmp_path, "susp-r", status="suspended")
        result = cite_rule_tool(rule_id="susp-r")
        assert result["citable"] is False
        assert result["status"] == "suspended"
        assert "재검토" in result["citation"]

    def test_not_found(self):
        result = cite_rule_tool(rule_id="ghost")
        assert result["citable"] is False
        assert result["status"] is None
        assert result["citation"] is None


# --- TestVisibilityHelpers ---


class TestVisibilityHelpers:
    """Tests for _filter_rule, _filter_relation, and _HIDDEN_STATUSES."""

    def test_filter_rule_approved(self):
        rule = {
            "rule_id": "r1",
            "text": "텍스트",
            "source_ref": {"document": "d", "version": "1.0", "location": "1조"},
            "scope": ["범위"],
            "authority": "regulation",
            "status": "approved",
            "approval": {"reviewer": "HB"},
            "_score": 0.95,
        }
        result = _filter_rule(rule)
        assert result is not None
        assert set(result.keys()) == _PUBLIC_FIELDS
        assert "approval" not in result
        assert "_score" not in result

    def test_filter_rule_draft_returns_none(self):
        rule = {"rule_id": "r2", "status": "draft", "text": "x"}
        assert _filter_rule(rule) is None

    def test_filter_rule_rejected_returns_none(self):
        rule = {"rule_id": "r3", "status": "rejected", "text": "x"}
        assert _filter_rule(rule) is None

    def test_filter_rule_suspended_visible(self):
        rule = {
            "rule_id": "r4",
            "text": "정지 규칙",
            "source_ref": {},
            "scope": [],
            "authority": "regulation",
            "status": "suspended",
        }
        result = _filter_rule(rule)
        assert result is not None
        assert result["status"] == "suspended"

    def test_filter_relation_strips_internal(self):
        rel = {
            "relation_id": "rel-1",
            "type": "excepts",
            "source_rule": "a",
            "target_rule": "b",
            "condition": "조건 충족 시",
            "resolution": "허용",
            "authority_basis": "근거",
            "status": "approved",
            "registered_by": "test",
            "extra_field": "should be removed",
        }
        result = _filter_relation(rel)
        assert "registered_by" not in result
        assert "extra_field" not in result
        assert set(result.keys()).issubset(_PUBLIC_RELATION_FIELDS)
        assert result["relation_id"] == "rel-1"

    def test_hidden_statuses_constant(self):
        assert _HIDDEN_STATUSES == {"draft", "rejected"}
