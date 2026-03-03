"""Tests for scripts/ingest/migration.py — Relation migration guide."""

from pathlib import Path

import pytest
import yaml

from ingest.migration import (
    _extract_suffix,
    find_rules_by_doc_and_version,
    find_suspended_relations,
    format_migration_guide,
    generate_relation_migration_guide,
    match_rule_id_pattern,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


@pytest.fixture
def env(tmp_path: Path) -> Path:
    """Create a minimal environment with old rules, new rules, and relations."""
    # Old rules (v2022.04) — will be suspended after version update
    old_rules = [
        {
            "rule_id": "kmdia-fc-art5-p1-main",
            "text": "Old art5 text",
            "source_ref": {"document": "kmdia-fc", "version": "2022.04", "location": "제5조 제1항"},
            "scope": ["금품류 제공 금지"],
            "authority": "regulation",
            "status": "suspended",
        },
        {
            "rule_id": "kmdia-fc-art6-p1-main",
            "text": "Old art6 text",
            "source_ref": {"document": "kmdia-fc", "version": "2022.04", "location": "제6조 제1항"},
            "scope": ["견본품 제공"],
            "authority": "regulation",
            "status": "suspended",
        },
    ]
    for rule in old_rules:
        suffix = rule["rule_id"].replace("kmdia-fc-", "")
        _write_yaml(tmp_path / f"rules/kmdia-fc/{suffix}.yaml", rule)

    # New rules (v2025.01) — freshly ingested
    new_rules = [
        {
            "rule_id": "kmdia-fc-art5-p1-main",
            "text": "New art5 text (2025)",
            "source_ref": {"document": "kmdia-fc", "version": "2025.01", "location": "제5조 제1항"},
            "scope": ["금품류 제공 금지"],
            "authority": "regulation",
            "status": "draft",
        },
        {
            "rule_id": "kmdia-fc-art6-p1-main",
            "text": "New art6 text (2025)",
            "source_ref": {"document": "kmdia-fc", "version": "2025.01", "location": "제6조 제1항"},
            "scope": ["견본품 제공"],
            "authority": "regulation",
            "status": "draft",
        },
        {
            "rule_id": "kmdia-fc-art8-p1-main",
            "text": "Entirely new rule in 2025",
            "source_ref": {"document": "kmdia-fc", "version": "2025.01", "location": "제8조 제1항"},
            "scope": ["새 조항"],
            "authority": "regulation",
            "status": "draft",
        },
    ]
    # Use versioned filenames to avoid overwriting old rules
    for rule in new_rules:
        suffix = rule["rule_id"].replace("kmdia-fc-", "")
        _write_yaml(tmp_path / f"rules/kmdia-fc/{suffix}-v2025.yaml", rule)

    # Suspended relations (cascade already applied)
    relations = [
        {
            "relation_id": "rel-fc-001",
            "type": "excepts",
            "source_rule": "kmdia-fc-art6-p1-main",
            "target_rule": "kmdia-fc-art5-p1-main",
            "condition": "견본품 조건",
            "resolution": "art6 인용하여 허용",
            "status": "suspended",
            "suspension_reason": "source_rule suspended",
        },
        {
            "relation_id": "rel-fc-002",
            "type": "overrides",
            "source_rule": "kmdia-fc-art5-p1-main",
            "target_rule": "other-doc-art1-main",
            "condition": "some condition",
            "resolution": "some resolution",
            "status": "suspended",
            "suspension_reason": "source_rule suspended",
        },
        {
            "relation_id": "rel-fc-003",
            "type": "excepts",
            "source_rule": "other-doc-art1-main",
            "target_rule": "other-doc-art2-main",
            "condition": "unrelated",
            "resolution": "unrelated",
            "status": "approved",
        },
    ]
    for rel in relations:
        _write_yaml(tmp_path / f"relations/{rel['relation_id']}.yaml", rel)

    return tmp_path


# ---------------------------------------------------------------------------
# _extract_suffix
# ---------------------------------------------------------------------------

class TestExtractSuffix:
    def test_normal(self):
        assert _extract_suffix("kmdia-fc-art5-p1-main", "kmdia-fc") == "art5-p1-main"

    def test_complex_suffix(self):
        assert _extract_suffix("kmdia-fc-art7-p1-item3", "kmdia-fc") == "art7-p1-item3"

    def test_no_match(self):
        assert _extract_suffix("other-doc-art1", "kmdia-fc") is None

    def test_exact_prefix_no_suffix(self):
        # "kmdia-fc" with doc_id "kmdia-fc" → empty suffix
        assert _extract_suffix("kmdia-fc-", "kmdia-fc") == ""


# ---------------------------------------------------------------------------
# find_suspended_relations
# ---------------------------------------------------------------------------

class TestFindSuspendedRelations:
    def test_finds_matching(self, env: Path):
        result = find_suspended_relations("kmdia-fc", env)
        ids = [r["relation_id"] for r in result]
        assert "rel-fc-001" in ids
        assert "rel-fc-002" in ids

    def test_excludes_approved(self, env: Path):
        result = find_suspended_relations("kmdia-fc", env)
        ids = [r["relation_id"] for r in result]
        # rel-fc-003 is approved, not suspended
        assert "rel-fc-003" not in ids

    def test_excludes_other_doc(self, env: Path):
        result = find_suspended_relations("other-doc", env)
        # rel-fc-002 has target_rule other-doc-art1-main but is suspended
        # and source_rule is kmdia-fc, target is other-doc → match
        # rel-fc-003 is approved → excluded
        ids = [r["relation_id"] for r in result]
        assert "rel-fc-002" in ids
        assert "rel-fc-003" not in ids

    def test_empty_relations_dir(self, tmp_path: Path):
        result = find_suspended_relations("kmdia-fc", tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# find_rules_by_doc_and_version
# ---------------------------------------------------------------------------

class TestFindRulesByDocAndVersion:
    def test_finds_new_version(self, env: Path):
        result = find_rules_by_doc_and_version("kmdia-fc", "2025.01", env)
        ids = [r["rule_id"] for r in result]
        assert "kmdia-fc-art5-p1-main" in ids
        assert "kmdia-fc-art6-p1-main" in ids
        assert "kmdia-fc-art8-p1-main" in ids

    def test_finds_old_version(self, env: Path):
        result = find_rules_by_doc_and_version("kmdia-fc", "2022.04", env)
        ids = [r["rule_id"] for r in result]
        assert "kmdia-fc-art5-p1-main" in ids
        assert "kmdia-fc-art6-p1-main" in ids

    def test_no_matching_version(self, env: Path):
        result = find_rules_by_doc_and_version("kmdia-fc", "9999.99", env)
        assert result == []

    def test_no_matching_doc(self, env: Path):
        result = find_rules_by_doc_and_version("nonexistent", "2025.01", env)
        assert result == []

    def test_empty_rules_dir(self, tmp_path: Path):
        result = find_rules_by_doc_and_version("kmdia-fc", "2025.01", tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# match_rule_id_pattern
# ---------------------------------------------------------------------------

class TestMatchRuleIdPattern:
    def test_both_rules_match(self):
        relation = {
            "source_rule": "kmdia-fc-art6-p1-main",
            "target_rule": "kmdia-fc-art5-p1-main",
        }
        new_rules = [
            {"rule_id": "kmdia-fc-art5-p1-main"},
            {"rule_id": "kmdia-fc-art6-p1-main"},
            {"rule_id": "kmdia-fc-art8-p1-main"},
        ]
        result = match_rule_id_pattern(relation, new_rules, "kmdia-fc")
        assert "kmdia-fc-art6-p1-main" in result
        assert "kmdia-fc-art5-p1-main" in result

    def test_partial_match(self):
        relation = {
            "source_rule": "kmdia-fc-art6-p1-main",
            "target_rule": "other-doc-art1-main",
        }
        new_rules = [
            {"rule_id": "kmdia-fc-art6-p1-main"},
        ]
        result = match_rule_id_pattern(relation, new_rules, "kmdia-fc")
        assert result == ["kmdia-fc-art6-p1-main"]

    def test_no_match(self):
        relation = {
            "source_rule": "kmdia-fc-art99-p1-main",
            "target_rule": "other-doc-art1-main",
        }
        new_rules = [
            {"rule_id": "kmdia-fc-art5-p1-main"},
        ]
        result = match_rule_id_pattern(relation, new_rules, "kmdia-fc")
        assert result == []

    def test_deduplication(self):
        # If source and target point to the same rule
        relation = {
            "source_rule": "kmdia-fc-art5-p1-main",
            "target_rule": "kmdia-fc-art5-p1-main",
        }
        new_rules = [
            {"rule_id": "kmdia-fc-art5-p1-main"},
        ]
        result = match_rule_id_pattern(relation, new_rules, "kmdia-fc")
        assert result == ["kmdia-fc-art5-p1-main"]


# ---------------------------------------------------------------------------
# generate_relation_migration_guide
# ---------------------------------------------------------------------------

class TestGenerateRelationMigrationGuide:
    def test_full_guide(self, env: Path):
        guide = generate_relation_migration_guide(
            "kmdia-fc", "2022.04", "2025.01", env
        )
        assert len(guide) == 2

        # rel-fc-001: excepts, both rules in kmdia-fc
        entry_001 = next(e for e in guide if e["suspended_relation"] == "rel-fc-001")
        assert entry_001["type"] == "excepts"
        assert entry_001["original_pair"] == (
            "kmdia-fc-art6-p1-main", "kmdia-fc-art5-p1-main"
        )
        assert "kmdia-fc-art6-p1-main" in entry_001["candidate_new_rules"]
        assert "kmdia-fc-art5-p1-main" in entry_001["candidate_new_rules"]
        assert entry_001["action_required"] == "human_review"
        assert entry_001["version_change"] == ("2022.04", "2025.01")

        # rel-fc-002: overrides, source in kmdia-fc, target in other-doc
        entry_002 = next(e for e in guide if e["suspended_relation"] == "rel-fc-002")
        assert entry_002["type"] == "overrides"
        assert "kmdia-fc-art5-p1-main" in entry_002["candidate_new_rules"]
        assert entry_002["action_required"] == "human_review"

    def test_no_new_rules(self, env: Path):
        guide = generate_relation_migration_guide(
            "kmdia-fc", "2022.04", "9999.99", env
        )
        # Relations still found, but no candidates
        assert len(guide) == 2
        for entry in guide:
            assert entry["candidate_new_rules"] == []

    def test_no_suspended_relations(self, tmp_path: Path):
        # Only approved relation
        _write_yaml(tmp_path / "relations/rel-ok.yaml", {
            "relation_id": "rel-ok",
            "type": "excepts",
            "source_rule": "kmdia-fc-art5-p1-main",
            "target_rule": "kmdia-fc-art6-p1-main",
            "status": "approved",
        })
        guide = generate_relation_migration_guide(
            "kmdia-fc", "2022.04", "2025.01", tmp_path
        )
        assert guide == []

    def test_empty_env(self, tmp_path: Path):
        guide = generate_relation_migration_guide(
            "kmdia-fc", "2022.04", "2025.01", tmp_path
        )
        assert guide == []


# ---------------------------------------------------------------------------
# format_migration_guide
# ---------------------------------------------------------------------------

class TestFormatMigrationGuide:
    def test_empty_guide(self):
        output = format_migration_guide([])
        assert "No suspended relations found" in output
        assert "=== Relation Migration Guide ===" in output

    def test_with_candidates(self):
        guide = [
            {
                "suspended_relation": "rel-fc-001",
                "type": "excepts",
                "original_pair": ("kmdia-fc-art6-p1-main", "kmdia-fc-art5-p1-main"),
                "candidate_new_rules": [
                    "kmdia-fc-art6-p1-main",
                    "kmdia-fc-art5-p1-main",
                ],
                "action_required": "human_review",
            }
        ]
        output = format_migration_guide(guide)
        assert "=== Relation Migration Guide ===" in output
        assert "rel-fc-001 (excepts)" in output
        assert "kmdia-fc-art6-p1-main → kmdia-fc-art5-p1-main" in output
        assert "신규 후보:" in output
        assert "인간 검토 필요" in output
        assert "1 relation(s) need re-registration" in output

    def test_without_candidates(self):
        guide = [
            {
                "suspended_relation": "rel-fc-010",
                "type": "overrides",
                "original_pair": ("kmdia-fc-art99-p1-main", "kmdia-fc-art5-p1-main"),
                "candidate_new_rules": [],
                "action_required": "human_review",
            }
        ]
        output = format_migration_guide(guide)
        assert "신규 후보: 없음 (수동 매핑 필요)" in output

    def test_multiple_entries(self):
        guide = [
            {
                "suspended_relation": "rel-fc-001",
                "type": "excepts",
                "original_pair": ("a", "b"),
                "candidate_new_rules": ["x"],
                "action_required": "human_review",
            },
            {
                "suspended_relation": "rel-fc-002",
                "type": "unresolved",
                "original_pair": ("c", "d"),
                "candidate_new_rules": [],
                "action_required": "human_review",
            },
        ]
        output = format_migration_guide(guide)
        assert "rel-fc-001" in output
        assert "rel-fc-002" in output
        assert "2 relation(s) need re-registration" in output

    def test_supersedes_type(self):
        """supersedes type also gets human review action."""
        guide = [
            {
                "suspended_relation": "rel-001",
                "type": "supersedes",
                "original_pair": ("a", "b"),
                "candidate_new_rules": ["x"],
                "action_required": "human_review",
            }
        ]
        output = format_migration_guide(guide)
        # supersedes is NOT in _HUMAN_REVIEW_TYPES, gets generic message
        assert "인간 검토 필요 (관계 재등록)" in output
