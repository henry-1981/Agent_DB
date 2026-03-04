"""Tests for relation management CLI (relation.py)."""

from pathlib import Path

import pytest
import yaml

from relation import list_relations


@pytest.fixture
def rel_env(tmp_path):
    """Isolated environment with sample relations."""
    rel_dir = tmp_path / "relations"
    rel_dir.mkdir()

    # 2 approved, 1 suspended
    for i, status in enumerate(["approved", "approved", "suspended"], 1):
        (rel_dir / f"rel-test-{i:03d}.yaml").write_text(yaml.dump({
            "relation_id": f"rel-test-{i:03d}",
            "type": "excepts",
            "source_rule": f"doc-art{i}-p1-main",
            "target_rule": "doc-art1-p1-main",
            "condition": f"Test condition {i}",
            "resolution": f"Test resolution for relation {i}",
            "authority_basis": "Test basis",
            "registered_by": "HB",
            "status": status,
        }, allow_unicode=True), encoding="utf-8")

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
