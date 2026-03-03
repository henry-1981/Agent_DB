"""Tests for version update handling (ingest/version.py).

All tests use tmp_path for isolation — no production data touched.
"""

from pathlib import Path

import pytest
import yaml

from ingest.version import (
    _find_rules_for_version,
    _suspend_rule,
    version_update,
)


# -- Helpers -----------------------------------------------------------------


def _write_yaml(path: Path, data: dict) -> None:
    """Write a YAML file with standard settings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _read_yaml(path: Path) -> dict:
    """Read a YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def version_env(tmp_path):
    """Set up a complete isolated environment for version update testing.

    Creates:
    - sources/_sources.yaml with one doc (test-doc, version 1.0)
    - rules/test-doc/ with 3 approved rules
    - relations/ with 2 approved relations referencing those rules
    - domains/ra/authority_levels.yaml
    """
    # Source registry
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    _write_yaml(sources_dir / "_sources.yaml", {
        "sources": {
            "test-doc": {
                "title": "테스트 문서",
                "versions": [{"version": "1.0", "file": "test-v1.pdf"}],
                "publisher": "테스트 출판사",
                "authority_level": "regulation",
                "notes": "버전 업데이트 테스트용",
            }
        }
    })

    # Rule Units
    rules_dir = tmp_path / "rules" / "test-doc"
    rules_dir.mkdir(parents=True)
    for i in range(1, 4):
        _write_yaml(rules_dir / f"art{i}-main.yaml", {
            "rule_id": f"test-doc-art{i}-main",
            "text": f"제{i}조 테스트 규칙 원문",
            "source_ref": {
                "document": "test-doc",
                "version": "1.0",
                "location": f"제{i}조",
            },
            "scope": [f"테스트 scope {i}"],
            "authority": "regulation",
            "status": "approved",
        })

    # Relations
    rel_dir = tmp_path / "relations"
    rel_dir.mkdir()
    _write_yaml(rel_dir / "rel-test-001.yaml", {
        "relation_id": "rel-test-001",
        "type": "excepts",
        "source_rule": "test-doc-art2-main",
        "target_rule": "test-doc-art1-main",
        "condition": "조건 A",
        "resolution": "A 적용",
        "authority_basis": "제2조가 제1조의 예외",
        "registered_by": "HB",
        "status": "approved",
    })
    _write_yaml(rel_dir / "rel-test-002.yaml", {
        "relation_id": "rel-test-002",
        "type": "excepts",
        "source_rule": "test-doc-art3-main",
        "target_rule": "test-doc-art1-main",
        "condition": "조건 B",
        "resolution": "B 적용",
        "authority_basis": "제3조가 제1조의 예외",
        "registered_by": "HB",
        "status": "approved",
    })

    # Domain config
    domain_dir = tmp_path / "domains" / "ra"
    domain_dir.mkdir(parents=True)
    _write_yaml(domain_dir / "authority_levels.yaml", {
        "levels": ["law", "regulation", "sop", "guideline", "precedent"],
    })

    return tmp_path


@pytest.fixture
def mixed_status_env(tmp_path):
    """Environment with rules in mixed statuses (not all approved)."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    _write_yaml(sources_dir / "_sources.yaml", {
        "sources": {
            "mixed-doc": {
                "title": "혼합 상태 문서",
                "versions": [{"version": "1.0", "file": "mixed-v1.pdf"}],
                "publisher": "테스트",
                "authority_level": "regulation",
                "notes": "",
            }
        }
    })

    rules_dir = tmp_path / "rules" / "mixed-doc"
    rules_dir.mkdir(parents=True)

    # One approved, one draft, one verified
    for status, idx in [("approved", 1), ("draft", 2), ("verified", 3)]:
        _write_yaml(rules_dir / f"art{idx}-main.yaml", {
            "rule_id": f"mixed-doc-art{idx}-main",
            "text": f"제{idx}조 혼합 테스트",
            "source_ref": {
                "document": "mixed-doc",
                "version": "1.0",
                "location": f"제{idx}조",
            },
            "scope": [f"scope {idx}"],
            "authority": "regulation",
            "status": status,
        })

    # Empty relations dir
    (tmp_path / "relations").mkdir()

    return tmp_path


# -- Test: _find_rules_for_version ------------------------------------------


class TestFindRulesForVersion:
    """Rule discovery by doc_id and version."""

    def test_finds_matching_rules(self, version_env):
        rules = _find_rules_for_version("test-doc", "1.0", version_env)
        assert len(rules) == 3
        rule_ids = {r[1]["rule_id"] for _, r in enumerate(rules)}
        # Flatten: rules is list of (path, dict)
        rule_ids = {data["rule_id"] for _, data in rules}
        assert rule_ids == {
            "test-doc-art1-main",
            "test-doc-art2-main",
            "test-doc-art3-main",
        }

    def test_no_match_wrong_version(self, version_env):
        rules = _find_rules_for_version("test-doc", "99.99", version_env)
        assert len(rules) == 0

    def test_no_match_wrong_doc_id(self, version_env):
        rules = _find_rules_for_version("nonexistent-doc", "1.0", version_env)
        assert len(rules) == 0

    def test_skips_underscore_files(self, version_env):
        """Files starting with _ (like _domain.yaml) should be skipped."""
        domain_file = version_env / "rules" / "test-doc" / "_domain.yaml"
        _write_yaml(domain_file, {"domain": "ra"})
        rules = _find_rules_for_version("test-doc", "1.0", version_env)
        assert len(rules) == 3  # unchanged


# -- Test: _suspend_rule ----------------------------------------------------


class TestSuspendRule:
    """Unit tests for the suspension logic."""

    def test_suspend_approved_rule(self):
        data = {"status": "approved", "rule_id": "test-1"}
        result = _suspend_rule(data, "1.0", "2.0")
        assert result is not None
        assert result["status"] == "suspended"
        assert "1.0" in result["suspension_reason"]
        assert "2.0" in result["suspension_reason"]

    def test_skip_non_approved_rule(self):
        for status in ("draft", "verified", "rejected", "suspended", "superseded"):
            data = {"status": status, "rule_id": "test-1"}
            result = _suspend_rule(data, "1.0", "2.0")
            assert result is None


# -- Test: version_update (integration) -------------------------------------


class TestVersionUpdate:
    """Integration tests for the full version update flow."""

    def test_basic_version_update(self, version_env):
        summary = version_update(
            doc_id="test-doc",
            new_version="2.0",
            old_version="1.0",
            file_path="test-v2.pdf",
            root=version_env,
        )

        assert summary["doc_id"] == "test-doc"
        assert summary["old_version"] == "1.0"
        assert summary["new_version"] == "2.0"
        assert summary["rules_found"] == 3
        assert summary["rules_suspended"] == 3
        assert summary["relations_cascaded"] == 2

    def test_rules_actually_suspended(self, version_env):
        """Verify YAML files on disk are updated."""
        version_update(
            doc_id="test-doc",
            new_version="2.0",
            old_version="1.0",
            file_path="test-v2.pdf",
            root=version_env,
        )

        rules_dir = version_env / "rules" / "test-doc"
        for yaml_file in rules_dir.glob("*.yaml"):
            data = _read_yaml(yaml_file)
            assert data["status"] == "suspended"
            assert data["suspension_reason"] == "원천 문서 버전 변경: 1.0 → 2.0"

    def test_registry_updated(self, version_env):
        """Verify _sources.yaml has the new version with supersedes."""
        version_update(
            doc_id="test-doc",
            new_version="2.0",
            old_version="1.0",
            file_path="test-v2.pdf",
            root=version_env,
        )

        data = _read_yaml(version_env / "sources" / "_sources.yaml")
        versions = data["sources"]["test-doc"]["versions"]
        assert len(versions) == 2
        new_ver = versions[1]
        assert new_ver["version"] == "2.0"
        assert new_ver["file"] == "test-v2.pdf"
        assert new_ver["supersedes"] == "1.0"

    def test_relations_cascaded(self, version_env):
        """Verify relation files are updated to suspended."""
        version_update(
            doc_id="test-doc",
            new_version="2.0",
            old_version="1.0",
            file_path="test-v2.pdf",
            root=version_env,
        )

        rel_dir = version_env / "relations"
        for yaml_file in sorted(rel_dir.glob("*.yaml")):
            data = _read_yaml(yaml_file)
            assert data["status"] == "suspended"
            assert "suspension_reason" in data

    def test_suspension_reason_format(self, version_env):
        """Verify the suspension reason includes both version strings."""
        version_update(
            doc_id="test-doc",
            new_version="2025.01",
            old_version="1.0",
            file_path="test-new.pdf",
            root=version_env,
        )

        rule = _read_yaml(version_env / "rules" / "test-doc" / "art1-main.yaml")
        assert rule["suspension_reason"] == "원천 문서 버전 변경: 1.0 → 2025.01"

    def test_no_rules_found_raises(self, version_env):
        """Error when no rules match the specified doc_id + version."""
        with pytest.raises(FileNotFoundError, match="No Rule Units found"):
            version_update(
                doc_id="test-doc",
                new_version="3.0",
                old_version="99.99",
                file_path="ghost.pdf",
                root=version_env,
            )

    def test_nonexistent_doc_id_raises(self, version_env):
        """Error when doc_id doesn't exist in registry."""
        # Create rules dir so _find_rules_for_version doesn't return empty
        # But doc_id won't match in registry
        rules_dir = version_env / "rules" / "ghost-doc"
        rules_dir.mkdir(parents=True)
        _write_yaml(rules_dir / "art1.yaml", {
            "rule_id": "ghost-doc-art1",
            "text": "텍스트",
            "source_ref": {"document": "ghost-doc", "version": "1.0", "location": "제1조"},
            "scope": ["scope"],
            "authority": "regulation",
            "status": "approved",
        })
        # This will fail at registry step (KeyError from add_version_to_existing_source)
        with pytest.raises(KeyError, match="not in registry"):
            version_update(
                doc_id="ghost-doc",
                new_version="2.0",
                old_version="1.0",
                file_path="ghost.pdf",
                root=version_env,
            )

    def test_only_approved_rules_suspended(self, mixed_status_env):
        """Only approved rules transition to suspended; draft/verified stay."""
        version_update(
            doc_id="mixed-doc",
            new_version="2.0",
            old_version="1.0",
            file_path="mixed-v2.pdf",
            root=mixed_status_env,
        )

        summary_dir = mixed_status_env / "rules" / "mixed-doc"
        art1 = _read_yaml(summary_dir / "art1-main.yaml")
        art2 = _read_yaml(summary_dir / "art2-main.yaml")
        art3 = _read_yaml(summary_dir / "art3-main.yaml")

        assert art1["status"] == "suspended"  # was approved
        assert art2["status"] == "draft"       # unchanged
        assert art3["status"] == "verified"    # unchanged

    def test_mixed_status_summary_counts(self, mixed_status_env):
        """Summary should reflect only approved rules as suspended."""
        summary = version_update(
            doc_id="mixed-doc",
            new_version="2.0",
            old_version="1.0",
            file_path="mixed-v2.pdf",
            root=mixed_status_env,
        )

        assert summary["rules_found"] == 3
        assert summary["rules_suspended"] == 1  # only 1 approved
        assert summary["relations_cascaded"] == 0  # no relations

    def test_idempotent_cascade(self, version_env):
        """Running version_update twice shouldn't double-cascade."""
        version_update(
            doc_id="test-doc",
            new_version="2.0",
            old_version="1.0",
            file_path="test-v2.pdf",
            root=version_env,
        )

        # Add another version entry so the second call doesn't fail on duplicate
        # Manually reset one rule to approved to simulate partial re-run
        rule_path = version_env / "rules" / "test-doc" / "art1-main.yaml"
        data = _read_yaml(rule_path)
        data["status"] = "approved"
        del data["suspension_reason"]
        _write_yaml(rule_path, data)

        # Second version update (different new version)
        # Already has 2.0, now do 3.0 superseding 1.0 (for the one reset rule)
        summary = version_update(
            doc_id="test-doc",
            new_version="3.0",
            old_version="1.0",
            file_path="test-v3.pdf",
            root=version_env,
        )

        # Only the one reset rule should be found (others already suspended, wrong version match?)
        # Actually, all 3 rules still have version "1.0" in source_ref
        assert summary["rules_suspended"] == 1  # only the reset one is still approved

    def test_relation_with_draft_status_gets_rejected(self, version_env):
        """A draft relation referencing suspended rules should become rejected."""
        # Add a draft relation
        _write_yaml(version_env / "relations" / "rel-test-003.yaml", {
            "relation_id": "rel-test-003",
            "type": "overrides",
            "source_rule": "test-doc-art3-main",
            "target_rule": "test-doc-art2-main",
            "condition": "조건 C",
            "resolution": "C 적용",
            "authority_basis": "테스트",
            "registered_by": "HB",
            "status": "draft",
        })

        version_update(
            doc_id="test-doc",
            new_version="2.0",
            old_version="1.0",
            file_path="test-v2.pdf",
            root=version_env,
        )

        rel3 = _read_yaml(version_env / "relations" / "rel-test-003.yaml")
        assert rel3["status"] == "rejected"
        assert "rejection_reason" in rel3
