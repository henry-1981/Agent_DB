"""Tests for ingest.parse — source document parsing."""

import pytest

from ingest.ir import DocumentIR, Section
from ingest.parse import (
    ARTICLE_PATTERN,
    ITEM_PATTERN,
    PARAGRAPH_PATTERN,
    SUB_ITEM_PATTERN,
    MarkdownParser,
    PDFParser,
    circled_to_int,
    get_parser,
)
from pathlib import Path


# --- Pattern matching tests ---

class TestKoreanLegalPatterns:
    def test_article_pattern(self):
        assert ARTICLE_PATTERN.match("제7조 (기부행위)")
        assert ARTICLE_PATTERN.match("제5조 (금품류 제공 금지)")
        assert ARTICLE_PATTERN.match("제12조（정의）")  # fullwidth parens
        assert not ARTICLE_PATTERN.match("제7조의2")  # no parens
        assert not ARTICLE_PATTERN.match("항 본문")

    def test_paragraph_pattern(self):
        assert PARAGRAPH_PATTERN.match("① 사업자는")
        assert PARAGRAPH_PATTERN.match("② 다음 각 호")
        assert PARAGRAPH_PATTERN.match("⑩ 마지막")
        assert not PARAGRAPH_PATTERN.match("1. 첫째")

    def test_item_pattern(self):
        assert ITEM_PATTERN.match("1. 첫째 호")
        assert ITEM_PATTERN.match("6. 여섯째")
        assert not ITEM_PATTERN.match("가. 서브아이템")

    def test_sub_item_pattern(self):
        assert SUB_ITEM_PATTERN.match("가. 의료법")
        assert SUB_ITEM_PATTERN.match("나. 기타")
        assert SUB_ITEM_PATTERN.match("하. 마지막")
        assert not SUB_ITEM_PATTERN.match("1. 아이템")


class TestCircledToInt:
    def test_all_circled_numbers(self):
        for i, char in enumerate("①②③④⑤⑥⑦⑧⑨⑩"):
            assert circled_to_int(char) == i + 1

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            circled_to_int("X")


# --- MarkdownParser tests ---

class TestMarkdownParser:
    """Test MarkdownParser with Korean legal document content."""

    def _write_md(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "test.md"
        p.write_text(content, encoding='utf-8')
        return p

    def test_basic_article(self, tmp_path):
        content = "제5조 (금품류 제공 금지)\n① 본문 내용입니다."
        path = self._write_md(tmp_path, content)
        ir = MarkdownParser().parse(path, "test-doc", "1.0")

        assert ir.doc_id == "test-doc"
        assert ir.version == "1.0"
        assert len(ir.sections) == 1
        art = ir.sections[0]
        assert art.level == 1
        assert art.number == 5
        assert art.location == "제5조"
        assert len(art.children) == 1
        para = art.children[0]
        assert para.level == 2
        assert para.number == 1
        assert "본문 내용" in para.text

    def test_article_paragraph_item_hierarchy(self, tmp_path):
        """Full hierarchy: Article → Paragraph → Item."""
        content = (
            "제7조 (기부행위)\n"
            "① 사업자는 기부행위를 할 수 있다.\n"
            "1. 금지되는 기부행위\n"
            "2. 허용되는 기부행위\n"
        )
        path = self._write_md(tmp_path, content)
        ir = MarkdownParser().parse(path, "doc", "1.0")

        art = ir.sections[0]
        assert art.number == 7
        assert len(art.children) == 1
        para = art.children[0]
        assert para.number == 1
        assert len(para.children) == 2
        assert para.children[0].number == 1
        assert para.children[0].level == 3
        assert para.children[1].number == 2

    def test_sub_items_merged_into_parent(self, tmp_path):
        """Sub-items (가. 나. 다.) should merge into parent item."""
        content = (
            "제5조 (정의)\n"
            "① 항 본문\n"
            "1. 아이템 본문\n"
            "가. 첫번째 서브\n"
            "나. 두번째 서브\n"
        )
        path = self._write_md(tmp_path, content)
        ir = MarkdownParser().parse(path, "doc", "1.0")

        para = ir.sections[0].children[0]
        item = para.children[0]
        # Sub-items should be merged into item text
        assert "가. 첫번째 서브" in item.text
        assert "나. 두번째 서브" in item.text
        # No separate children for sub-items
        assert len(para.children) == 1

    def test_multiple_articles(self, tmp_path):
        content = (
            "제5조 (금품류)\n"
            "① 본문\n"
            "제6조 (견본품)\n"
            "① 내용\n"
            "제7조 (기부행위)\n"
            "① 기부\n"
        )
        path = self._write_md(tmp_path, content)
        ir = MarkdownParser().parse(path, "doc", "1.0")

        assert len(ir.sections) == 3
        assert ir.sections[0].number == 5
        assert ir.sections[1].number == 6
        assert ir.sections[2].number == 7

    def test_multiple_paragraphs(self, tmp_path):
        content = (
            "제5조 (금품류 제공 금지)\n"
            "① 첫째 항\n"
            "② 둘째 항\n"
            "③ 셋째 항\n"
        )
        path = self._write_md(tmp_path, content)
        ir = MarkdownParser().parse(path, "doc", "1.0")

        art = ir.sections[0]
        assert len(art.children) == 3
        assert art.children[0].number == 1
        assert art.children[1].number == 2
        assert art.children[2].number == 3

    def test_location_format(self, tmp_path):
        """Verify location string format matches existing Rule Unit patterns."""
        content = (
            "제5조 (금품류)\n"
            "① 항 본문\n"
            "1. 첫째 호\n"
        )
        path = self._write_md(tmp_path, content)
        ir = MarkdownParser().parse(path, "doc", "1.0")

        assert ir.sections[0].location == "제5조"
        assert ir.sections[0].children[0].location == "제5조 제1항"
        assert ir.sections[0].children[0].children[0].location == "제5조 제1항 제1호"

    def test_markdown_heading_based_parsing(self, tmp_path):
        """Markdown headings create hierarchy without Korean legal patterns."""
        content = (
            "## Section A\n"
            "Body of section A\n"
            "### Subsection A1\n"
            "Body of A1\n"
            "#### Item A1-1\n"
            "Item body\n"
        )
        path = self._write_md(tmp_path, content)
        ir = MarkdownParser().parse(path, "doc", "1.0")

        assert len(ir.sections) == 1
        assert ir.sections[0].heading == "Section A"
        assert ir.sections[0].level == 1
        assert "Body of section A" in ir.sections[0].text
        assert len(ir.sections[0].children) == 1
        sub = ir.sections[0].children[0]
        assert sub.heading == "Subsection A1"
        assert sub.level == 2
        assert len(sub.children) == 1
        item = sub.children[0]
        assert item.heading == "Item A1-1"
        assert item.level == 3

    def test_empty_document(self, tmp_path):
        path = self._write_md(tmp_path, "")
        ir = MarkdownParser().parse(path, "doc", "1.0")
        assert ir.sections == []

    def test_continuation_lines(self, tmp_path):
        """Lines without pattern markers should append to the current section."""
        content = (
            "제5조 (금품류 제공 금지)\n"
            "① 사업자는 의료기관 등 또는 보건의료인에게\n"
            "금전, 물품, 향응 등을 제공하여서는 아니 된다.\n"
        )
        path = self._write_md(tmp_path, content)
        ir = MarkdownParser().parse(path, "doc", "1.0")

        para = ir.sections[0].children[0]
        assert "금전, 물품, 향응" in para.text


# --- PDFParser tests ---

class TestPDFParser:
    def test_implements_protocol(self):
        assert isinstance(PDFParser(), PDFParser)

    def test_build_sections_from_text(self):
        """Test internal _build_sections with raw text."""
        parser = PDFParser()
        text = (
            "제5조 (금품류 제공 금지)\n"
            "① 사업자는 금품류를 제공하여서는 아니 된다.\n"
            "② 제1항에도 불구하고 다음 각 호의 경우는 제외한다.\n"
            "1. 견본품 제공\n"
            "2. 학술대회 후원\n"
            "가. 참가비\n"
            "나. 교통비\n"
        )
        sections = parser._build_sections(text)
        assert len(sections) == 1
        art = sections[0]
        assert art.number == 5
        assert len(art.children) == 2

        p1 = art.children[0]
        assert p1.number == 1
        assert len(p1.children) == 0  # no items under p1

        p2 = art.children[1]
        assert p2.number == 2
        assert len(p2.children) == 2  # two items
        assert p2.children[0].number == 1
        assert p2.children[1].number == 2
        # Sub-items merged into item2
        assert "가. 참가비" in p2.children[1].text
        assert "나. 교통비" in p2.children[1].text


# --- get_parser tests ---

class TestGetParser:
    def test_pdf_parser(self):
        p = get_parser(Path("test.pdf"))
        assert isinstance(p, PDFParser)

    def test_markdown_parser(self):
        p = get_parser(Path("test.md"))
        assert isinstance(p, MarkdownParser)

    def test_unsupported_format(self):
        with pytest.raises(ValueError, match="Unsupported"):
            get_parser(Path("test.xlsx"))
