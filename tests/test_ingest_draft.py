"""Tests for ingest/draft.py — YAML draft generation and duplicate handling."""

import yaml

from ingest.draft import write_all_drafts, write_draft


# ── Helpers ──────────────────────────────────────────────────────────


def _sample_fields(rule_id: str = "kmdia-fc-art7-p1-main", **overrides) -> dict:
    base = {
        "rule_id": rule_id,
        "doc_id": "kmdia-fc",
        "text": "제7조 ① 사업자는 의료기기의 거래와 관련하여 금전을 제공하여서는 아니 된다.",
        "source_ref": {
            "document": "kmdia-fc",
            "version": "2022.04",
            "location": "제7조 제1항 본문",
        },
        "scope": ["의료기기 거래 관련 경제적 이익 제공"],
        "authority": "regulation",
        "status": "draft",
    }
    base.update(overrides)
    return base


# ── write_draft: basic ───────────────────────────────────────────────


class TestWriteDraft:
    """Basic YAML file creation and content verification."""

    def test_creates_yaml_file(self, tmp_path):
        fields = _sample_fields()
        result = write_draft(fields, tmp_path)
        assert result is not None
        assert result.exists()
        assert result.name == "art7-p1-main.yaml"

    def test_yaml_content_roundtrip(self, tmp_path):
        fields = _sample_fields()
        path = write_draft(fields, tmp_path)
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded["rule_id"] == "kmdia-fc-art7-p1-main"
        assert loaded["text"] == fields["text"]
        assert loaded["source_ref"] == fields["source_ref"]
        assert loaded["scope"] == fields["scope"]
        assert loaded["authority"] == "regulation"
        assert loaded["status"] == "draft"

    def test_field_order(self, tmp_path):
        """YAML keys should follow the defined order."""
        fields = _sample_fields()
        path = write_draft(fields, tmp_path)
        content = path.read_text(encoding="utf-8")
        keys = [line.split(":")[0] for line in content.splitlines() if not line.startswith(" ") and not line.startswith("-") and ":" in line]
        expected = ["rule_id", "text", "source_ref", "scope", "authority", "status"]
        assert keys == expected

    def test_doc_id_not_in_output(self, tmp_path):
        """doc_id is metadata for filename, not written to YAML."""
        fields = _sample_fields()
        path = write_draft(fields, tmp_path)
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "doc_id" not in loaded

    def test_text_preserved_with_special_chars(self, tmp_path):
        """Text with special characters and newlines must be preserved."""
        text = "제5조 ③ 다음 각 호에 해당하는 경우:\n1. 본사 또는 지사\n2. 판매업자 등"
        fields = _sample_fields(text=text)
        path = write_draft(fields, tmp_path)
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded["text"] == text

    def test_filename_without_doc_id(self, tmp_path):
        """If doc_id is empty, use rule_id as filename."""
        fields = _sample_fields(doc_id="")
        path = write_draft(fields, tmp_path)
        assert path.name == "kmdia-fc-art7-p1-main.yaml"


# ── write_draft: duplicate handling ─────────────────────────────────


class TestDuplicateHandling:
    """Duplicate detection and force overwrite."""

    def test_duplicate_returns_none(self, tmp_path):
        fields = _sample_fields()
        write_draft(fields, tmp_path)
        result = write_draft(fields, tmp_path)
        assert result is None

    def test_force_overwrites(self, tmp_path):
        fields = _sample_fields()
        write_draft(fields, tmp_path)
        # Change text and force overwrite
        fields["text"] = "updated text"
        result = write_draft(fields, tmp_path, force=True)
        assert result is not None
        loaded = yaml.safe_load(result.read_text(encoding="utf-8"))
        assert loaded["text"] == "updated text"

    def test_duplicate_warns(self, tmp_path, caplog):
        fields = _sample_fields()
        write_draft(fields, tmp_path)
        import logging
        with caplog.at_level(logging.WARNING):
            write_draft(fields, tmp_path)
        assert "Skipping duplicate" in caplog.text


# ── write_draft: domain field ────────────────────────────────────────


class TestDomainField:
    """Conditional domain inclusion based on default_domain."""

    def test_default_domain_excluded(self, tmp_path):
        """domain='ra' (default) should not appear in YAML."""
        fields = _sample_fields(domain="ra")
        path = write_draft(fields, tmp_path, default_domain="ra")
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "domain" not in loaded

    def test_non_default_domain_included(self, tmp_path):
        """domain='test-legal' should appear in YAML when default is 'ra'."""
        fields = _sample_fields(domain="test-legal")
        path = write_draft(fields, tmp_path, default_domain="ra")
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded["domain"] == "test-legal"

    def test_domain_before_status_in_output(self, tmp_path):
        """When included, domain must appear before status."""
        fields = _sample_fields(domain="test-legal")
        path = write_draft(fields, tmp_path)
        content = path.read_text(encoding="utf-8")
        keys = [line.split(":")[0] for line in content.splitlines() if not line.startswith(" ") and not line.startswith("-") and ":" in line]
        assert "domain" in keys
        assert keys.index("domain") < keys.index("status")

    def test_no_domain_field_at_all(self, tmp_path):
        """No domain key in fields → no domain in output."""
        fields = _sample_fields()
        assert "domain" not in fields
        path = write_draft(fields, tmp_path)
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "domain" not in loaded


# ── write_all_drafts ─────────────────────────────────────────────────


class TestWriteAllDrafts:
    """Batch writing via write_all_drafts."""

    def test_creates_directory_and_files(self, tmp_path):
        rules = [
            _sample_fields("kmdia-fc-art5-p1-main"),
            _sample_fields("kmdia-fc-art5-p2-main"),
            _sample_fields("kmdia-fc-art5-p3-main"),
        ]
        paths = write_all_drafts(rules, "kmdia-fc", tmp_path)
        assert len(paths) == 3
        assert (tmp_path / "rules" / "kmdia-fc").is_dir()
        assert all(p.exists() for p in paths)

    def test_filenames_correct(self, tmp_path):
        rules = [
            _sample_fields("kmdia-fc-art7-p1-main"),
            _sample_fields("kmdia-fc-art7-p1-item1"),
        ]
        paths = write_all_drafts(rules, "kmdia-fc", tmp_path)
        names = sorted(p.name for p in paths)
        assert names == ["art7-p1-item1.yaml", "art7-p1-main.yaml"]

    def test_skips_duplicates_returns_only_written(self, tmp_path):
        rules = [_sample_fields("kmdia-fc-art5-p1-main")]
        # First batch
        write_all_drafts(rules, "kmdia-fc", tmp_path)
        # Second batch — should skip duplicate
        paths = write_all_drafts(rules, "kmdia-fc", tmp_path)
        assert len(paths) == 0

    def test_force_writes_all(self, tmp_path):
        rules = [_sample_fields("kmdia-fc-art5-p1-main")]
        write_all_drafts(rules, "kmdia-fc", tmp_path)
        paths = write_all_drafts(rules, "kmdia-fc", tmp_path, force=True)
        assert len(paths) == 1

    def test_default_domain_propagated(self, tmp_path):
        rules = [
            _sample_fields("test-doc-art1-main", doc_id="test-doc", domain="test-legal"),
        ]
        paths = write_all_drafts(rules, "test-doc", tmp_path, default_domain="ra")
        loaded = yaml.safe_load(paths[0].read_text(encoding="utf-8"))
        assert loaded["domain"] == "test-legal"

    def test_empty_rules_returns_empty(self, tmp_path):
        paths = write_all_drafts([], "kmdia-fc", tmp_path)
        assert paths == []
