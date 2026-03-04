"""Tests for ingest/extract.py — field extraction from RuleCandidates."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ingest.ir import Section, RuleCandidate
from ingest.extract import (
    parse_article_number,
    parse_paragraph_number,
    generate_rule_id,
    determine_authority,
    extract_fields,
    extract_scope_llm,
    extract_scope_heuristic,
    _build_scope_prompt,
    _load_scope_vocabulary,
    _vocabulary_item_matches_text,
    check_scope_vocabulary_consistency,
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
        assert isinstance(result["scope"], list)
        assert len(result["scope"]) >= 1  # heuristic always produces scope
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


# ── LLM scope extraction ────────────────────────────────────────────

class TestExtractScopeLlm:
    def test_no_anthropic(self, monkeypatch, tmp_path):
        """Returns [] when anthropic is not installed."""
        import ingest.extract as mod
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("no anthropic")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        result = mod.extract_scope_llm("text", "doc", "제7조", root=tmp_path)
        assert result == []

    def test_no_api_key(self, monkeypatch, tmp_path):
        """Returns [] when ANTHROPIC_API_KEY is not set."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Provide a mock anthropic module so import succeeds
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            from ingest.extract import extract_scope_llm as fn
            result = fn("text", "doc", "제7조", root=tmp_path)
        assert result == []

    def test_mock_success(self, monkeypatch, tmp_path):
        """Returns scope list from mocked API response."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        scope_items = ["금품류 제공 금지 원칙", "사업자 의무"]
        resp_json = json.dumps({"scope": scope_items, "reasoning": "test"})

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=resp_json)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            from ingest.extract import extract_scope_llm as fn
            result = fn("사업자는 금품류를 제공하여서는 아니된다.",
                        "kmdia-fc", "제5조 제1항", root=tmp_path)

        assert result == scope_items
        mock_client.messages.create.assert_called_once()

    def test_mock_success_with_markdown_block(self, monkeypatch, tmp_path):
        """Handles response wrapped in markdown code block."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        scope_items = ["기부행위 허용 원칙"]
        resp_text = '```json\n{"scope": ' + json.dumps(scope_items) + ', "reasoning": "ok"}\n```'

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=resp_text)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            from ingest.extract import extract_scope_llm as fn
            result = fn("text", "doc", "제7조", root=tmp_path)

        assert result == scope_items

    def test_api_error(self, monkeypatch, tmp_path):
        """Returns [] when API call raises an exception."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("API error")
        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            from ingest.extract import extract_scope_llm as fn
            result = fn("text", "doc", "제7조", root=tmp_path)

        assert result == []


class TestBuildScopePrompt:
    def test_contains_text_and_examples(self):
        prompt = _build_scope_prompt(
            "사업자는 금품류를 제공하여서는 아니된다.",
            "제5조 제1항",
            "principle: ['금품류 제공 금지 원칙']",
        )
        assert "사업자는 금품류를 제공하여서는 아니된다." in prompt
        assert "제5조 제1항" in prompt
        assert "금품류 제공 금지 원칙" in prompt
        assert "3-7 scope items" in prompt

    def test_contains_instruction_rules(self):
        prompt = _build_scope_prompt("text", "loc", "examples")
        assert "DO NOT summarize" in prompt
        assert "Korean language" in prompt


class TestLoadScopeVocabulary:
    def test_loads_existing_file(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        vocab = {"patterns": {"principle": ["테스트 원칙"]}}
        with open(config_dir / "scope-vocabulary.yaml", "w") as f:
            yaml.dump(vocab, f)
        result = _load_scope_vocabulary(tmp_path)
        assert result["patterns"]["principle"] == ["테스트 원칙"]

    def test_missing_file_returns_empty(self, tmp_path):
        result = _load_scope_vocabulary(tmp_path)
        assert result == {}


class TestScopeVocabularyConsistency:
    def test_full_match(self):
        vocab = {"patterns": {"principle": ["금품류 제공 금지 원칙"]}}
        score = check_scope_vocabulary_consistency(
            ["금품류 제공 금지 원칙"], vocab
        )
        assert score == 1.0

    def test_partial_match(self):
        vocab = {"patterns": {
            "principle": ["금품류 제공 금지 원칙"],
            "condition": ["사회통념상 인정 범위"],
        }}
        score = check_scope_vocabulary_consistency(
            ["금품류 관련 규정", "완전히 새로운 항목"], vocab
        )
        # "금품류 관련 규정" shares token "금품류" with known → 1 match / 2 items = 0.5
        assert 0.0 < score < 1.0

    def test_no_match(self):
        vocab = {"patterns": {"principle": ["가나다라"]}}
        score = check_scope_vocabulary_consistency(
            ["완전히 다른 것"], vocab
        )
        assert score == 0.0

    def test_empty_scope(self):
        vocab = {"patterns": {"principle": ["원칙"]}}
        assert check_scope_vocabulary_consistency([], vocab) == 0.0

    def test_empty_vocabulary(self):
        assert check_scope_vocabulary_consistency(["아이템"], {}) == 0.0


# ── Heuristic scope extraction ─────────────────────────────────────


class TestVocabularyItemMatchesText:
    def test_exact_tokens_match(self):
        assert _vocabulary_item_matches_text(
            "금품류 제공 금지 원칙",
            "사업자는 금품류를 제공하거나 금지 사항을 위반할 수 없다.",
        )

    def test_partial_token_match_above_threshold(self):
        # 4 tokens: 금품류, 제공, 금지, 원칙. Need >=2. Text has 금품류, 제공.
        assert _vocabulary_item_matches_text(
            "금품류 제공 금지 원칙",
            "금품류 제공에 관한 규정",
        )

    def test_no_match(self):
        assert not _vocabulary_item_matches_text(
            "금품류 제공 금지 원칙",
            "학술대회 참가 지원에 관한 사항",
        )

    def test_single_token_item(self):
        # "위탁 판매" has 2 tokens of len>=2
        assert _vocabulary_item_matches_text(
            "위탁 판매",
            "위탁 판매를 통한 거래",
        )

    def test_short_tokens_ignored(self):
        # Single-char tokens should not count as matches
        assert not _vocabulary_item_matches_text(
            "A B 가",
            "A B 가 나 다",
        )


class TestExtractScopeHeuristic:
    def _setup_vocab(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        vocab = {
            "patterns": {
                "principle": ["금품류 제공 금지 원칙", "기부행위 허용 원칙"],
                "target": ["보건의료인 정의"],
                "mechanism": ["위탁 판매", "마케팅 대행사"],
            }
        }
        with open(config_dir / "scope-vocabulary.yaml", "w") as f:
            yaml.dump(vocab, f, allow_unicode=True)

    def test_matches_vocabulary(self, tmp_path):
        self._setup_vocab(tmp_path)
        result = extract_scope_heuristic(
            "사업자는 금품류를 제공하여서는 아니된다. 금지 원칙.",
            "제5조 제1항", "제5조 (금품류 제공의 제한)", root=tmp_path,
        )
        assert len(result) >= 1
        assert any("금품류" in item for item in result)

    def test_multiple_category_matches(self, tmp_path):
        self._setup_vocab(tmp_path)
        result = extract_scope_heuristic(
            "금품류 제공을 금지하며, 위탁 판매를 통한 거래도 불가하다.",
            "제5조 제1항", "", root=tmp_path,
        )
        assert len(result) >= 2

    def test_no_vocab_match_uses_heading(self, tmp_path):
        self._setup_vocab(tmp_path)
        result = extract_scope_heuristic(
            "완전히 새로운 주제에 대한 규정입니다.",
            "제99조 제1항", "제99조 (신규 조항)", root=tmp_path,
        )
        assert len(result) >= 1
        assert any("신규 조항" in item for item in result)

    def test_no_vocab_no_heading_uses_location(self, tmp_path):
        self._setup_vocab(tmp_path)
        result = extract_scope_heuristic(
            "완전히 새로운 텍스트.",
            "제99조 제1항", "", root=tmp_path,
        )
        assert len(result) >= 1
        assert any("제99조" in item for item in result)

    def test_empty_vocab_file_still_produces_scope(self, tmp_path):
        # No vocab file at all
        result = extract_scope_heuristic(
            "사업자는 학술대회를 지원할 수 있다.",
            "제8조 제1항", "제8조 (학술대회의 지원)", root=tmp_path,
        )
        assert len(result) >= 1

    def test_never_returns_empty(self, tmp_path):
        """Heuristic must always return at least 1 scope item."""
        result = extract_scope_heuristic(".", "제1조", "", root=tmp_path)
        assert len(result) >= 1


class TestExtractFieldsCallsScope:
    """Verify extract_fields integrates LLM scope extraction."""

    def _setup_env(self, tmp_path, doc_id="kmdia-fc"):
        src_dir = tmp_path / "sources"
        src_dir.mkdir()
        with open(src_dir / "_sources.yaml", "w") as f:
            yaml.dump({"sources": {doc_id: {"authority_level": "regulation"}}}, f)

    def test_uses_llm_scope(self, tmp_path, monkeypatch):
        """extract_fields calls extract_scope_llm (mocked)."""
        self._setup_env(tmp_path)
        expected_scope = ["기부행위 허용 원칙", "목적 제한"]
        monkeypatch.setattr(
            "ingest.extract.extract_scope_llm",
            lambda text, doc_id, location, root=None: expected_scope,
        )
        section = Section(
            heading="제7조", level=2,
            text="사업자는 기부행위를 할 수 있다.",
            location="제7조 제1항",
        )
        candidate = RuleCandidate(section=section, suffix="main")
        result = extract_fields(candidate, "kmdia-fc", "2022.04", root=tmp_path)
        assert result["scope"] == expected_scope

    def test_heuristic_fallback_when_llm_unavailable(self, tmp_path, monkeypatch):
        """extract_fields uses heuristic scope when LLM returns empty."""
        self._setup_env(tmp_path)
        monkeypatch.setattr(
            "ingest.extract.extract_scope_llm",
            lambda text, doc_id, location, root=None: [],
        )
        section = Section(
            heading="제5조 (금품류 제공의 제한)", level=1,
            text="사업자는 금품류를 제공하여서는 아니 된다.",
            location="제5조 제1항",
        )
        candidate = RuleCandidate(section=section, suffix="main")
        result = extract_fields(candidate, "kmdia-fc", "2022.04", root=tmp_path)
        assert len(result["scope"]) >= 1  # heuristic fallback provides scope
        assert set(result.keys()) == {
            "rule_id", "text", "source_ref", "scope", "authority", "status",
        }
