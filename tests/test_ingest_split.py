"""Tests for ingest/split.py — deterministic and LLM-assisted splitting."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

from ingest.ir import DocumentIR, RuleCandidate, Section
from ingest.split import (
    deterministic_split,
    llm_assisted_split,
    needs_llm_judgment,
    split_document,
    split_with_fallback,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _article(num: int, children: list[Section] | None = None, text: str = "") -> Section:
    return Section(
        heading=f"제{num}조",
        level=1,
        text=text or f"제{num}조 본문",
        location=f"제{num}조",
        children=children or [],
        number=num,
    )


def _paragraph(num: int, children: list[Section] | None = None, text: str = "") -> Section:
    return Section(
        heading=f"제{num}항",
        level=2,
        text=text or f"제{num}항 본문",
        location=f"제{num}항",
        children=children or [],
        number=num,
    )


def _item(num: int, text: str = "") -> Section:
    return Section(
        heading=f"제{num}호",
        level=3,
        text=text or f"제{num}호 본문",
        location=f"제{num}호",
        number=num,
    )


# ── deterministic_split ─────────────────────────────────────────────


class TestArticleOnly:
    """Article without children → 1 main."""

    def test_leaf_article_produces_one_main(self):
        sec = _article(4, text="단독 조문")
        result = deterministic_split(sec)
        assert len(result) == 1
        assert result[0].suffix == "main"
        assert result[0].section is sec
        assert result[0].split_method == "deterministic"

    def test_leaf_article_no_items(self):
        sec = _article(10)
        result = deterministic_split(sec)
        assert all(c.suffix == "main" for c in result)


class TestArticleWithParagraphs:
    """Article with N paragraphs → N rules (each para becomes main)."""

    def test_three_paragraphs(self):
        paras = [_paragraph(i) for i in range(1, 4)]
        sec = _article(5, children=paras)
        result = deterministic_split(sec)
        assert len(result) == 3
        assert all(c.suffix == "main" for c in result)

    def test_article_itself_not_in_output(self):
        """Article with children should not produce its own candidate."""
        sec = _article(5, children=[_paragraph(1)])
        result = deterministic_split(sec)
        assert all(c.section.level == 2 for c in result)


class TestParagraphWithItems:
    """Paragraph with items → 1 main + N items."""

    def test_para_with_two_items(self):
        items = [_item(1), _item(2)]
        sec = _paragraph(1, children=items)
        result = deterministic_split(sec)
        assert len(result) == 3  # 1 main + 2 items
        assert result[0].suffix == "main"
        assert result[1].suffix == "item1"
        assert result[2].suffix == "item2"

    def test_item_sections_are_level3(self):
        items = [_item(1)]
        sec = _paragraph(1, children=items)
        result = deterministic_split(sec)
        item_candidates = [c for c in result if c.suffix.startswith("item")]
        assert all(c.section.level == 3 for c in item_candidates)

    def test_all_split_method_deterministic(self):
        items = [_item(1), _item(2), _item(3)]
        sec = _paragraph(2, children=items)
        result = deterministic_split(sec)
        assert all(c.split_method == "deterministic" for c in result)


class TestItemDirect:
    """Item (level 3) → single RuleCandidate with item{N} suffix."""

    def test_single_item(self):
        sec = _item(3)
        result = deterministic_split(sec)
        assert len(result) == 1
        assert result[0].suffix == "item3"

    def test_item_without_number_defaults_to_1(self):
        sec = Section(heading="호", level=3, text="text", location="loc", number=None)
        result = deterministic_split(sec)
        assert result[0].suffix == "item1"


# ── Full document patterns (matching existing 23 Rule Units) ────────


class TestExistingPatterns:
    """Verify split output matches existing rule unit file patterns."""

    @staticmethod
    def _build_art5() -> Section:
        """art5: 4 paragraphs, p3 has 2 items → 6 rules."""
        return _article(5, children=[
            _paragraph(1),
            _paragraph(2),
            _paragraph(3, children=[_item(1), _item(2)]),
            _paragraph(4),
        ])

    @staticmethod
    def _build_art6() -> Section:
        """art6: 3 paragraphs, p2 has 2 items → 5 rules."""
        return _article(6, children=[
            _paragraph(1),
            _paragraph(2, children=[_item(1), _item(2)]),
            _paragraph(3),
        ])

    @staticmethod
    def _build_art7() -> Section:
        """art7: 1 paragraph, p1 has 6 items → 7 rules."""
        return _article(7, children=[
            _paragraph(1, children=[_item(i) for i in range(1, 7)]),
        ])

    def test_art5_six_rules(self):
        result = deterministic_split(self._build_art5())
        assert len(result) == 6
        suffixes = [c.suffix for c in result]
        assert suffixes == ["main", "main", "main", "item1", "item2", "main"]

    def test_art6_five_rules(self):
        result = deterministic_split(self._build_art6())
        assert len(result) == 5
        suffixes = [c.suffix for c in result]
        assert suffixes == ["main", "main", "item1", "item2", "main"]

    def test_art7_seven_rules(self):
        result = deterministic_split(self._build_art7())
        assert len(result) == 7
        suffixes = [c.suffix for c in result]
        assert suffixes == ["main", "item1", "item2", "item3", "item4", "item5", "item6"]


# ── needs_llm_judgment ──────────────────────────────────────────────


class TestNeedsLlmJudgment:
    """MVP stub: always False."""

    def test_always_false_for_article(self):
        assert needs_llm_judgment(_article(1)) is False

    def test_always_false_for_paragraph(self):
        assert needs_llm_judgment(_paragraph(1)) is False

    def test_always_false_for_item(self):
        assert needs_llm_judgment(_item(1)) is False


# ── split_document ──────────────────────────────────────────────────


class TestSplitDocument:
    """End-to-end: DocumentIR → list[RuleCandidate]."""

    def test_full_document(self):
        ir = DocumentIR(
            doc_id="kmdia-fc",
            version="2022.04",
            title="KMDIA 공정경쟁규약",
            sections=[
                _article(5, children=[
                    _paragraph(1),
                    _paragraph(2),
                    _paragraph(3, children=[_item(1), _item(2)]),
                    _paragraph(4),
                ]),
                _article(6, children=[
                    _paragraph(1),
                    _paragraph(2, children=[_item(1), _item(2)]),
                    _paragraph(3),
                ]),
                _article(7, children=[
                    _paragraph(1, children=[_item(i) for i in range(1, 7)]),
                ]),
            ],
        )
        result = split_document(ir)
        assert len(result) == 18  # 6 + 5 + 7
        assert all(isinstance(c, RuleCandidate) for c in result)

    def test_empty_document(self):
        ir = DocumentIR(doc_id="empty", version="1.0", title="Empty")
        assert split_document(ir) == []

    def test_single_leaf_article(self):
        ir = DocumentIR(
            doc_id="simple",
            version="1.0",
            title="Simple",
            sections=[_article(1, text="단독 조문")],
        )
        result = split_document(ir)
        assert len(result) == 1
        assert result[0].suffix == "main"


# ── needs_llm_judgment (Phase 2) ──────────────────────────────────


class TestNeedsLlmJudgmentPhase2:
    """Phase 2: real heuristic based on enumeration markers + child count."""

    def test_needs_llm_judgment_with_enum_markers(self):
        """Paragraph with '다음 각 호' + 2+ items → True."""
        items = [_item(1, text="금전 제공"), _item(2, text="물품 제공")]
        sec = _paragraph(
            1, children=items,
            text="회원사는 다음 각 호의 행위를 하여서는 아니 된다.",
        )
        assert needs_llm_judgment(sec) is True

    def test_needs_llm_judgment_simple_paragraph(self):
        """No markers → False."""
        sec = _paragraph(1, text="단순 본문 텍스트")
        assert needs_llm_judgment(sec) is False

    def test_needs_llm_judgment_single_item(self):
        """Only 1 item → False even with marker."""
        items = [_item(1)]
        sec = _paragraph(1, children=items, text="다음 각 호의 사항을 준수한다.")
        assert needs_llm_judgment(sec) is False

    def test_needs_llm_judgment_marker_in_child(self):
        """Marker in child text triggers judgment."""
        items = [
            _item(1, text="다음 각 목에 해당하는 경우"),
            _item(2, text="기타 사항"),
        ]
        sec = _paragraph(1, children=items, text="기부행위 금지")
        assert needs_llm_judgment(sec) is True

    def test_needs_llm_judgment_article_always_false(self):
        """Level 1 sections never trigger LLM judgment."""
        sec = _article(1, children=[_paragraph(1), _paragraph(2)])
        assert needs_llm_judgment(sec) is False

    def test_needs_llm_judgment_다음_사항_marker(self):
        """'다음 사항' marker also triggers."""
        items = [_item(1), _item(2)]
        sec = _paragraph(1, children=items, text="다음 사항을 준수하여야 한다.")
        assert needs_llm_judgment(sec) is True


# ── llm_assisted_split ─────────────────────────────────────────────


def _enum_paragraph() -> Section:
    """Paragraph with enumeration markers and 3 items."""
    items = [
        _item(1, text="금전 제공"),
        _item(2, text="물품 제공"),
        _item(3, text="향응 제공"),
    ]
    return _paragraph(
        1, children=items,
        text="회원사는 다음 각 호의 행위를 하여서는 아니 된다.",
    )


def _mock_llm_response(decision: str, reasoning: str) -> MagicMock:
    """Create a mock anthropic module that returns a given decision."""
    mock_msg = MagicMock()
    mock_msg.content = [
        MagicMock(text=json.dumps({"decision": decision, "reasoning": reasoning}))
    ]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    mock_module = MagicMock()
    mock_module.Anthropic.return_value = mock_client
    return mock_module


class TestLlmAssistedSplit:
    """LLM-assisted split with mocked API."""

    def test_llm_assisted_split_merge(self):
        """MERGE decision → single candidate."""
        sec = _enum_paragraph()
        mock_mod = _mock_llm_response("MERGE", "Items list examples of prohibited benefits")

        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                result = llm_assisted_split(sec)

        assert len(result) == 1
        assert result[0].suffix == "main"
        assert result[0].split_method == "llm"
        assert result[0].section is sec

    def test_llm_assisted_split_split(self):
        """SPLIT decision → main + item candidates."""
        sec = _enum_paragraph()
        mock_mod = _mock_llm_response("SPLIT", "Items are independent obligations")

        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                result = llm_assisted_split(sec)

        # main + 3 items = 4 candidates
        assert len(result) == 4
        assert result[0].suffix == "main"
        assert result[1].suffix == "item1"
        assert result[2].suffix == "item2"
        assert result[3].suffix == "item3"
        assert all(c.split_method == "llm" for c in result)

    def test_llm_assisted_split_metadata(self):
        """Verify split_method='llm' and llm_reasoning contains model info."""
        sec = _enum_paragraph()
        mock_mod = _mock_llm_response("MERGE", "Shared decision point")

        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                result = llm_assisted_split(sec)

        assert result[0].split_method == "llm"
        assert "claude-haiku-4-5-20251001" in result[0].llm_reasoning
        assert "prompt_hash=" in result[0].llm_reasoning
        assert "ts=" in result[0].llm_reasoning

    def test_llm_assisted_split_markdown_response(self):
        """Handle LLM response wrapped in markdown code block."""
        sec = _enum_paragraph()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(
            text='```json\n{"decision": "MERGE", "reasoning": "wrapped"}\n```'
        )]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_mod = MagicMock()
        mock_mod.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                result = llm_assisted_split(sec)

        assert len(result) == 1
        assert result[0].split_method == "llm"

    def test_llm_assisted_split_no_api_key(self):
        """Missing API key raises RuntimeError."""
        sec = _enum_paragraph()
        mock_mod = MagicMock()

        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            with patch.dict(os.environ, {}, clear=False):
                # Remove ANTHROPIC_API_KEY if present
                env = os.environ.copy()
                env.pop("ANTHROPIC_API_KEY", None)
                with patch.dict(os.environ, env, clear=True):
                    try:
                        llm_assisted_split(sec)
                        assert False, "Should have raised RuntimeError"
                    except RuntimeError as e:
                        assert "ANTHROPIC_API_KEY" in str(e)


# ── split_with_fallback ───────────────────────────────────────────


class TestSplitWithFallback:
    """Fallback behavior when LLM is unavailable."""

    def test_split_with_fallback_no_anthropic(self):
        """Graceful degradation when anthropic not installed."""
        sec = _enum_paragraph()

        with patch.dict(sys.modules, {"anthropic": None}):
            result = split_with_fallback(sec)

        assert len(result) > 0
        assert all(c.needs_review is True for c in result)
        assert all(
            c.review_reason == "LLM unavailable for split judgment"
            for c in result
        )
        assert all(c.split_method == "deterministic" for c in result)

    def test_split_with_fallback_api_error(self):
        """Graceful degradation on API error."""
        sec = _enum_paragraph()
        mock_mod = MagicMock()
        mock_mod.Anthropic.return_value.messages.create.side_effect = Exception(
            "Connection timeout"
        )

        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                result = split_with_fallback(sec)

        assert len(result) > 0
        assert all(c.needs_review is True for c in result)
        assert all(
            c.review_reason == "LLM unavailable for split judgment"
            for c in result
        )

    def test_split_with_fallback_no_markers(self):
        """Sections without markers use deterministic directly."""
        sec = _paragraph(1, children=[_item(1), _item(2)], text="일반 본문")
        result = split_with_fallback(sec)

        assert len(result) == 3  # main + 2 items
        assert all(c.split_method == "deterministic" for c in result)
        assert all(c.needs_review is False for c in result)

    def test_split_document_uses_fallback(self):
        """Verify split_document delegates to split_with_fallback."""
        ir = DocumentIR(
            doc_id="test",
            version="1.0",
            title="Test",
            sections=[_article(1, text="단독 조문")],
        )
        with patch(
            "ingest.split.split_with_fallback", wraps=split_with_fallback
        ) as mock_swf:
            result = split_document(ir)

        mock_swf.assert_called_once()
        assert len(result) == 1

    def test_existing_patterns_unchanged(self):
        """Regression: 18 rules pattern still works with split_with_fallback."""
        ir = DocumentIR(
            doc_id="kmdia-fc",
            version="2022.04",
            title="KMDIA 공정경쟁규약",
            sections=[
                _article(5, children=[
                    _paragraph(1),
                    _paragraph(2),
                    _paragraph(3, children=[_item(1), _item(2)]),
                    _paragraph(4),
                ]),
                _article(6, children=[
                    _paragraph(1),
                    _paragraph(2, children=[_item(1), _item(2)]),
                    _paragraph(3),
                ]),
                _article(7, children=[
                    _paragraph(1, children=[_item(i) for i in range(1, 7)]),
                ]),
            ],
        )
        result = split_document(ir)
        assert len(result) == 18  # 6 + 5 + 7
        assert all(isinstance(c, RuleCandidate) for c in result)
        # No enum markers in default text → all deterministic
        assert all(c.split_method == "deterministic" for c in result)
        assert all(c.needs_review is False for c in result)
