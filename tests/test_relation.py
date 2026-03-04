"""Tests for relation management CLI (relation.py)."""

import shutil
from pathlib import Path

import pytest
import yaml

import jsonschema

from relation import approve_relation, create_relation, list_relations, validate_relation

SCHEMA_SRC = Path(__file__).resolve().parent.parent / "schemas" / "rule-relation.schema.yaml"


def _copy_schema(dest_root: Path):
    """Copy relation schema into an isolated test environment."""
    schema_dir = dest_root / "schemas"
    schema_dir.mkdir(exist_ok=True)
    shutil.copy(SCHEMA_SRC, schema_dir / "rule-relation.schema.yaml")


@pytest.fixture
def rel_env(tmp_path):
    """Isolated environment with sample relations + schema."""
    rel_dir = tmp_path / "relations"
    rel_dir.mkdir()
    _copy_schema(tmp_path)

    # 2 approved, 1 suspended
    for i, status in enumerate(["approved", "approved", "suspended"], 1):
        data = {
            "relation_id": f"rel-test-{i:03d}",
            "type": "excepts",
            "source_rule": f"doc-art{i}-p1-main",
            "target_rule": "doc-art1-p1-main",
            "condition": f"Test condition {i}",
            "resolution": f"Test resolution for relation {i}",
            "authority_basis": "Test basis",
            "registered_by": "HB",
            "status": status,
        }
        # approved relations need an approval object per schema
        if status == "approved":
            data["approval"] = {
                "reviewer": "HB",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        (rel_dir / f"rel-test-{i:03d}.yaml").write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8"
        )

    return tmp_path


class TestListRelations:
    def test_list_all(self, rel_env):
        result = list_relations(root=rel_env)
        assert len(result) == 3

    def test_list_filter_by_status(self, rel_env):
        result = list_relations(root=rel_env, status_filter="approved")
        assert len(result) == 2
        assert all(r["status"] == "approved" for r in result)

    def test_list_empty_dir(self, tmp_path):
        (tmp_path / "relations").mkdir()
        result = list_relations(root=tmp_path)
        assert result == []

    def test_list_no_dir(self, tmp_path):
        result = list_relations(root=tmp_path)
        assert result == []


class TestValidateRelation:
    def test_valid_relation(self, rel_env):
        result = validate_relation("rel-test-001", root=rel_env)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_missing_required_field(self, tmp_path):
        rel_dir = tmp_path / "relations"
        rel_dir.mkdir()
        _copy_schema(tmp_path)
        (rel_dir / "rel-bad-001.yaml").write_text(yaml.dump({
            "relation_id": "rel-bad-001",
            "type": "excepts",
            # missing: source_rule, target_rule, condition, resolution, etc.
        }, allow_unicode=True), encoding="utf-8")

        result = validate_relation("rel-bad-001", root=tmp_path)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_invalid_type(self, tmp_path):
        rel_dir = tmp_path / "relations"
        rel_dir.mkdir()
        _copy_schema(tmp_path)
        (rel_dir / "rel-bad-002.yaml").write_text(yaml.dump({
            "relation_id": "rel-bad-002",
            "type": "invalid_type",
            "source_rule": "a",
            "target_rule": "b",
            "condition": "test condition",
            "resolution": "test resolution here",
            "authority_basis": "test",
            "registered_by": "HB",
            "status": "draft",
        }, allow_unicode=True), encoding="utf-8")

        result = validate_relation("rel-bad-002", root=tmp_path)
        assert result["valid"] is False

    def test_relation_not_found(self, tmp_path):
        (tmp_path / "relations").mkdir()
        result = validate_relation("rel-ghost-001", root=tmp_path)
        assert result["valid"] is False
        assert "not found" in result["errors"][0].lower()

    def test_approved_without_approval_object(self, tmp_path):
        rel_dir = tmp_path / "relations"
        rel_dir.mkdir()
        _copy_schema(tmp_path)
        (rel_dir / "rel-bad-003.yaml").write_text(yaml.dump({
            "relation_id": "rel-bad-003",
            "type": "excepts",
            "source_rule": "a-art1-p1-main",
            "target_rule": "a-art2-p1-main",
            "condition": "test condition",
            "resolution": "test resolution here",
            "authority_basis": "test",
            "registered_by": "HB",
            "status": "approved",
            # missing: approval object
        }, allow_unicode=True), encoding="utf-8")

        result = validate_relation("rel-bad-003", root=tmp_path)
        assert result["valid"] is False


class TestCreateRelation:
    def test_create_valid_relation(self, tmp_path):
        rel_dir = tmp_path / "relations"
        rel_dir.mkdir()
        _copy_schema(tmp_path)

        path = create_relation(
            relation_id="rel-new-001",
            rel_type="excepts",
            source_rule="doc-art2-p1-main",
            target_rule="doc-art1-p1-main",
            condition="Test condition for new relation",
            resolution="Apply source rule when condition is met",
            authority_basis="Art2 delegates from Art1",
            registered_by="HB",
            root=tmp_path,
        )

        assert path is not None
        assert path.exists()

        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["relation_id"] == "rel-new-001"
        assert data["type"] == "excepts"
        assert data["status"] == "draft"

    def test_create_duplicate_relation_id_fails(self, rel_env):
        with pytest.raises(ValueError, match="already exists"):
            create_relation(
                relation_id="rel-test-001",
                rel_type="excepts",
                source_rule="x",
                target_rule="y",
                condition="Duplicate test condition",
                resolution="Duplicate test resolution here",
                authority_basis="test",
                registered_by="HB",
                root=rel_env,
            )

    def test_create_invalid_type_fails(self, tmp_path):
        rel_dir = tmp_path / "relations"
        rel_dir.mkdir()
        _copy_schema(tmp_path)

        with pytest.raises(jsonschema.ValidationError):
            create_relation(
                relation_id="rel-bad-type",
                rel_type="invalid",
                source_rule="x",
                target_rule="y",
                condition="Test condition here",
                resolution="Test resolution text here",
                authority_basis="test",
                registered_by="HB",
                root=tmp_path,
            )


class TestApproveRelation:
    def _make_draft_rel(self, tmp_path):
        """Create a draft relation for approval testing."""
        rel_dir = tmp_path / "relations"
        rel_dir.mkdir(exist_ok=True)
        _copy_schema(tmp_path)
        data = {
            "relation_id": "rel-approve-001",
            "type": "excepts",
            "source_rule": "doc-art2-p1-main",
            "target_rule": "doc-art1-p1-main",
            "condition": "Test condition for approval",
            "resolution": "Apply source rule when condition met",
            "authority_basis": "Test basis",
            "registered_by": "HB",
            "status": "draft",
        }
        path = rel_dir / "rel-approve-001.yaml"
        path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        return tmp_path

    def test_approve_draft_relation(self, tmp_path):
        env = self._make_draft_rel(tmp_path)
        result = approve_relation("rel-approve-001", reviewer="HB", root=env)
        assert result["status"] == "approved"
        assert "approval" in result
        assert result["approval"]["reviewer"] == "HB"

        # Verify file was updated
        path = env / "relations" / "rel-approve-001.yaml"
        with open(path) as f:
            saved = yaml.safe_load(f)
        assert saved["status"] == "approved"

    def test_approve_already_approved_skips(self, rel_env):
        # rel-test-001 is already approved
        result = approve_relation("rel-test-001", reviewer="HB", root=rel_env)
        assert result["status"] == "approved"  # unchanged

    def test_approve_not_found(self, tmp_path):
        (tmp_path / "relations").mkdir()
        with pytest.raises(FileNotFoundError):
            approve_relation("rel-ghost-001", reviewer="HB", root=tmp_path)
