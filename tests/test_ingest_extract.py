"""Tests for ingest/extract.py — field extraction from RuleCandidates."""

import pytest
import yaml

from ingest.ir import Section, RuleCandidate
from ingest.extract import (
    parse_article_number,
    parse_paragraph_number,
    generate_rule_id,
    determine_authority,
    extract_fields,
)


# ── parse_article_number ─────────────────────────────────────────────

class TestParseArticleNumber:
    def test_simple(self):
        assert parse_article_number("제7조") == 7

    def test_with_paragraph(self):
        assert parse_article_number("제5조 제3항") == 5

    def test_with_item(self):
        assert parse_article_number("제12조 제1항 제3호") == 12

    def test_with_title(self):
        assert parse_article_number("제7조 (기부행위)") == 7

    def test_single_digit(self):
        assert parse_article_number("제1조") == 1

    def test_no_article_raises(self):
        with pytest.raises(ValueError, match="No article number"):
            parse_article_number("본문")


# ── parse_paragraph_number ───────────────────────────────────────────

class TestParseParagraphNumber:
    def test_with_paragraph(self):
        assert parse_paragraph_number("제5조 제3항") == 3

    def test_no_paragraph_defaults_to_1(self):
        assert parse_paragraph_number("제7조") == 1

    def test_article_and_item_no_paragraph(self):
        # "제7조 제3호" has no 항 → default 1
        assert parse_paragraph_number("제7조 제3호") == 1

    def test_multi_digit(self):
        assert parse_paragraph_number("제1조 제12항") == 12


# ── generate_rule_id ─────────────────────────────────────────────────

def _make_candidate(location: str, suffix: str) -> RuleCandidate:
    """Helper to create a minimal RuleCandidate."""
    section = Section(
        heading="",
        level=1,
        text="dummy",
        location=location,
    )
    return RuleCandidate(section=section, suffix=suffix)


class TestGenerateRuleId:
    def test_main(self):
        c = _make_candidate("제7조 제1항", "main")
        assert generate_rule_id("kmdia-fc", c) == "kmdia-fc-art7-p1-main"

    def test_item(self):
        c = _make_candidate("제7조 제1항", "item3")
        assert generate_rule_id("kmdia-fc", c) == "kmdia-fc-art7-p1-item3"

    def test_detail_doc(self):
        c = _make_candidate("제3조 제2항", "main")
        assert generate_rule_id("kmdia-fc-detail", c) == "kmdia-fc-detail-art3-p2-main"

    def test_no_paragraph(self):
        c = _make_candidate("제5조", "main")
        assert generate_rule_id("kmdia-fc", c) == "kmdia-fc-art5-p1-main"

    def test_matches_existing_pattern(self):
        """Verify generated IDs match the regex pattern of existing 23 rules."""
        pattern = r"^[\w-]+-art\d+-p\d+-(main|item\d+)$"
        cases = [
            ("kmdia-fc", "제7조 제1항", "main"),
            ("kmdia-fc", "제5조 제3항", "item2"),
            ("kmdia-fc-detail", "제2조 제1항", "main"),
        ]
        for doc_id, loc, suffix in cases:
            c = _make_candidate(loc, suffix)
            rid = generate_rule_id(doc_id, c)
            assert re.match(pattern, rid), f"{rid} does not match pattern"


# ── determine_authority ──────────────────────────────────────────────

import re


class TestDetermineAuthority:
    def _write_sources(self, tmp_path, sources_dict):
        """Write a mock _sources.yaml under tmp_path/sources/."""
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        with open(src_dir / "_sources.yaml", "w") as f:
            yaml.dump({"sources": sources_dict}, f)

    def test_known_doc(self, tmp_path):
        self._write_sources(tmp_path, {
            "test-doc": {"authority_level": "guideline"},
        })
        assert determine_authority("test-doc", root=tmp_path) == "guideline"

    def test_unknown_doc_raises(self, tmp_path):
        self._write_sources(tmp_path, {
            "test-doc": {"authority_level": "regulation"},
        })
        with pytest.raises(KeyError, match="Unknown doc_id"):
            determine_authority("nonexistent", root=tmp_path)

    def test_multiple_sources(self, tmp_path):
        self._write_sources(tmp_path, {
            "doc-a": {"authority_level": "regulation"},
            "doc-b": {"authority_level": "sop"},
        })
        assert determine_authority("doc-a", root=tmp_path) == "regulation"
        assert determine_authority("doc-b", root=tmp_path) == "sop"


# ── extract_fields ───────────────────────────────────────────────────

class TestExtractFields:
    def _setup_sources(self, tmp_path, doc_id="kmdia-fc", authority="regulation"):
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        with open(src_dir / "_sources.yaml", "w") as f:
            yaml.dump({"sources": {doc_id: {"authority_level": authority}}}, f)

    def test_full_extraction(self, tmp_path):
        self._setup_sources(tmp_path)
        section = Section(
            heading="제7조 (기부행위)",
            level=2,
            text="사업자는 기부행위를 할 수 있다.",
            location="제7조 제1항",
        )
        candidate = RuleCandidate(section=section, suffix="main")
        result = extract_fields(candidate, "kmdia-fc", "2022.04", root=tmp_path)

        assert result["rule_id"] == "kmdia-fc-art7-p1-main"
        assert result["text"] == "사업자는 기부행위를 할 수 있다."
        assert result["source_ref"] == {
            "document": "kmdia-fc",
            "version": "2022.04",
            "location": "제7조 제1항",
        }
        assert result["scope"] == []
        assert result["authority"] == "regulation"
        assert result["status"] == "draft"

    def test_has_exactly_six_fields(self, tmp_path):
        self._setup_sources(tmp_path)
        section = Section(
            heading="제5조",
            level=1,
            text="text",
            location="제5조 제1항",
        )
        candidate = RuleCandidate(section=section, suffix="main")
        result = extract_fields(candidate, "kmdia-fc", "2022.04", root=tmp_path)
        assert set(result.keys()) == {
            "rule_id", "text", "source_ref", "scope", "authority", "status",
        }

    def test_item_suffix(self, tmp_path):
        self._setup_sources(tmp_path)
        section = Section(
            heading="제7조",
            level=3,
            text="item text",
            location="제7조 제1항 제3호",
        )
        candidate = RuleCandidate(section=section, suffix="item3")
        result = extract_fields(candidate, "kmdia-fc", "2022.04", root=tmp_path)
        assert result["rule_id"] == "kmdia-fc-art7-p1-item3"

    def test_detail_doc(self, tmp_path):
        self._setup_sources(tmp_path, doc_id="kmdia-fc-detail", authority="regulation")
        section = Section(
            heading="제3조",
            level=2,
            text="detail text",
            location="제3조 제2항",
        )
        candidate = RuleCandidate(section=section, suffix="main")
        result = extract_fields(
            candidate, "kmdia-fc-detail", "2022.04", root=tmp_path
        )
        assert result["rule_id"] == "kmdia-fc-detail-art3-p2-main"
        assert result["authority"] == "regulation"

    def test_unknown_doc_id_raises(self, tmp_path):
        self._setup_sources(tmp_path)
        section = Section(heading="", level=1, text="t", location="제1조")
        candidate = RuleCandidate(section=section, suffix="main")
        with pytest.raises(KeyError, match="Unknown doc_id"):
            extract_fields(candidate, "unknown-doc", "1.0", root=tmp_path)
