"""Tests for ingest/split.py — deterministic splitting of sections."""

from ingest.ir import DocumentIR, RuleCandidate, Section
from ingest.split import deterministic_split, needs_llm_judgment, split_document


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
