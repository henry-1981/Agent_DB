"""Tests for ingest.ir — Intermediate Representation data structures."""

from ingest.ir import DocumentIR, Section, RuleCandidate


class TestSection:
    def test_basic_creation(self):
        s = Section(heading="제7조 (기부행위)", level=1, text="본문", location="제7조")
        assert s.heading == "제7조 (기부행위)"
        assert s.level == 1
        assert s.text == "본문"
        assert s.location == "제7조"
        assert s.children == []
        assert s.number is None

    def test_with_number(self):
        s = Section(heading="제7조", level=1, text="t", location="l", number=7)
        assert s.number == 7

    def test_tree_structure(self):
        item1 = Section(heading="1.", level=3, text="첫째", location="제5조 제3항 제1호", number=1)
        item2 = Section(heading="2.", level=3, text="둘째", location="제5조 제3항 제2호", number=2)
        para = Section(heading="③", level=2, text="항 본문", location="제5조 제3항", number=3, children=[item1, item2])
        art = Section(heading="제5조", level=1, text="조 본문", location="제5조", number=5, children=[para])

        assert len(art.children) == 1
        assert len(art.children[0].children) == 2
        assert art.children[0].children[1].text == "둘째"


class TestDocumentIR:
    def test_basic_creation(self):
        ir = DocumentIR(doc_id="kmdia-fc", version="2022.04", title="공정경쟁규약")
        assert ir.doc_id == "kmdia-fc"
        assert ir.version == "2022.04"
        assert ir.title == "공정경쟁규약"
        assert ir.sections == []

    def test_with_sections(self):
        s1 = Section(heading="제1조", level=1, text="목적", location="제1조", number=1)
        s2 = Section(heading="제2조", level=1, text="정의", location="제2조", number=2)
        ir = DocumentIR(doc_id="test", version="1.0", title="테스트", sections=[s1, s2])
        assert len(ir.sections) == 2


class TestRuleCandidate:
    def test_defaults(self):
        s = Section(heading="h", level=1, text="t", location="l")
        rc = RuleCandidate(section=s, suffix="main")
        assert rc.split_method == "deterministic"
        assert rc.llm_reasoning is None
        assert rc.needs_review is False
        assert rc.review_reason is None

    def test_llm_split(self):
        s = Section(heading="h", level=2, text="t", location="l")
        rc = RuleCandidate(
            section=s, suffix="item1",
            split_method="llm", llm_reasoning="Independent obligation",
        )
        assert rc.split_method == "llm"
        assert rc.llm_reasoning == "Independent obligation"

    def test_needs_review_flag(self):
        s = Section(heading="h", level=2, text="t", location="l")
        rc = RuleCandidate(
            section=s, suffix="main",
            needs_review=True, review_reason="LLM unavailable for split judgment",
        )
        assert rc.needs_review is True
        assert rc.review_reason == "LLM unavailable for split judgment"
