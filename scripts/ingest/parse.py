"""Phase 1: Parse — convert source documents to format-agnostic IR.

Supported formats:
- PDF (pymupdf) — Korean legal documents with Article/Paragraph/Item hierarchy
- Markdown — heading-based hierarchy (useful for testing without PDF dependency)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from ingest.ir import DocumentIR, Section


# --- Korean legal document patterns ---

ARTICLE_PATTERN = re.compile(r'^제(\d+)조\s*[\(（]')
PARAGRAPH_PATTERN = re.compile(r'^([①②③④⑤⑥⑦⑧⑨⑩])')
ITEM_PATTERN = re.compile(r'^(\d+)\.\s')
SUB_ITEM_PATTERN = re.compile(r'^([가나다라마바사아자차카타파하])\.\s')

CIRCLED_NUMBERS = '①②③④⑤⑥⑦⑧⑨⑩'


def circled_to_int(char: str) -> int:
    """Convert a circled number character to its integer value."""
    idx = CIRCLED_NUMBERS.index(char)
    return idx + 1


# --- Parser Protocol ---

@runtime_checkable
class Parser(Protocol):
    """All parsers implement this interface."""

    def parse(self, source: Path | str, doc_id: str, version: str) -> DocumentIR:
        """Parse a source document into the intermediate representation."""
        ...


# --- PDF Parser ---

class PDFParser:
    """Parse Korean legal PDF documents using pymupdf.

    Detects hierarchy from textual patterns:
      제{N}조  → level 1 (Article)
      ①②③...  → level 2 (Paragraph)
      1. 2. 3. → level 3 (Item)
      가. 나. 다. → level 3 (merged into parent item)
    """

    def parse(self, source: Path | str, doc_id: str, version: str) -> DocumentIR:
        try:
            import pymupdf  # noqa: F811
        except ImportError:
            raise ImportError("pymupdf is required for PDF parsing: pip install pymupdf")

        path = Path(source)
        doc = pymupdf.open(str(path))
        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n"
        doc.close()

        title = path.stem
        sections = self._build_sections(full_text)
        return DocumentIR(doc_id=doc_id, version=version, title=title, sections=sections)

    def _build_sections(self, text: str) -> list[Section]:
        """Build hierarchical Section tree from raw text."""
        lines = text.split('\n')
        articles: list[Section] = []
        current_article: Section | None = None
        current_para: Section | None = None
        current_item: Section | None = None
        pending_lines: list[str] = []

        def flush_pending(target: Section | None) -> None:
            if target is not None and pending_lines:
                extra = '\n'.join(pending_lines).strip()
                if extra:
                    target.text = (target.text + '\n' + extra).strip() if target.text else extra
                pending_lines.clear()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if pending_lines:
                    pending_lines.append('')
                continue

            # Article: 제{N}조
            m = ARTICLE_PATTERN.match(stripped)
            if m:
                flush_pending(current_item or current_para or current_article)
                art_num = int(m.group(1))
                current_article = Section(
                    heading=stripped.split('\n')[0],
                    level=1, text=stripped,
                    location=f"제{art_num}조",
                    number=art_num,
                )
                articles.append(current_article)
                current_para = None
                current_item = None
                pending_lines = []
                continue

            # Paragraph: ①②③...
            m = PARAGRAPH_PATTERN.match(stripped)
            if m and current_article is not None:
                flush_pending(current_item or current_para)
                para_num = circled_to_int(m.group(1))
                current_para = Section(
                    heading=m.group(1),
                    level=2, text=stripped,
                    location=f"{current_article.location} 제{para_num}항",
                    number=para_num,
                )
                current_article.children.append(current_para)
                current_item = None
                pending_lines = []
                continue

            # Item: 1. 2. 3.
            m = ITEM_PATTERN.match(stripped)
            if m and current_para is not None:
                flush_pending(current_item or current_para)
                item_num = int(m.group(1))
                current_item = Section(
                    heading=f"{item_num}.",
                    level=3, text=stripped,
                    location=f"{current_para.location} 제{item_num}호",
                    number=item_num,
                )
                current_para.children.append(current_item)
                pending_lines = []
                continue

            # Sub-item: 가. 나. 다. → merge into parent item
            m = SUB_ITEM_PATTERN.match(stripped)
            if m and current_item is not None:
                flush_pending(current_item)
                current_item.text = current_item.text + '\n' + stripped
                continue

            # Continuation line: append to most recent element
            pending_lines.append(stripped)

        # Flush any remaining pending lines
        flush_pending(current_item or current_para or current_article)
        return articles


# --- Markdown Parser ---

class MarkdownParser:
    """Parse Markdown documents using heading levels for hierarchy.

    Useful for testing the pipeline without PDF dependencies.
    Heading mapping:
      # or ##  → level 1 (Article-equivalent)
      ###      → level 2 (Paragraph-equivalent)
      ####     → level 3 (Item-equivalent)
    Also detects Korean legal patterns within markdown content.
    """

    def parse(self, source: Path | str, doc_id: str, version: str) -> DocumentIR:
        path = Path(source)
        text = path.read_text(encoding='utf-8')
        title = path.stem
        sections = self._build_sections(text)
        return DocumentIR(doc_id=doc_id, version=version, title=title, sections=sections)

    def _build_sections(self, text: str) -> list[Section]:
        """Build Section tree from markdown headings + Korean legal patterns."""
        lines = text.split('\n')
        articles: list[Section] = []
        current_article: Section | None = None
        current_para: Section | None = None
        current_item: Section | None = None
        body_lines: list[str] = []

        def flush_body(target: Section | None) -> None:
            if target is not None and body_lines:
                extra = '\n'.join(body_lines).strip()
                if extra:
                    target.text = (target.text + '\n' + extra).strip() if target.text else extra
                body_lines.clear()

        for line in lines:
            stripped = line.strip()

            # Skip empty lines (preserve in body accumulation)
            if not stripped:
                if body_lines:
                    body_lines.append('')
                continue

            # Markdown heading detection
            heading_match = re.match(r'^(#{1,4})\s+(.*)', stripped)
            if heading_match:
                level_str = heading_match.group(1)
                heading_text = heading_match.group(2)
                md_level = len(level_str)

                if md_level <= 2:
                    flush_body(current_item or current_para or current_article)
                    art_num = len(articles) + 1
                    # Try to parse article number from heading
                    am = re.match(r'제(\d+)조', heading_text)
                    if am:
                        art_num = int(am.group(1))
                    current_article = Section(
                        heading=heading_text, level=1, text="",
                        location=f"제{art_num}조", number=art_num,
                    )
                    articles.append(current_article)
                    current_para = None
                    current_item = None
                    body_lines = []
                elif md_level == 3 and current_article is not None:
                    flush_body(current_item or current_para or current_article)
                    para_num = len(current_article.children) + 1
                    current_para = Section(
                        heading=heading_text, level=2, text="",
                        location=f"{current_article.location} 제{para_num}항",
                        number=para_num,
                    )
                    current_article.children.append(current_para)
                    current_item = None
                    body_lines = []
                elif md_level == 4 and current_para is not None:
                    flush_body(current_item or current_para)
                    item_num = len(current_para.children) + 1
                    current_item = Section(
                        heading=heading_text, level=3, text="",
                        location=f"{current_para.location} 제{item_num}호",
                        number=item_num,
                    )
                    current_para.children.append(current_item)
                    body_lines = []
                continue

            # Korean legal patterns within markdown content
            m = ARTICLE_PATTERN.match(stripped)
            if m:
                flush_body(current_item or current_para or current_article)
                art_num = int(m.group(1))
                current_article = Section(
                    heading=stripped, level=1, text=stripped,
                    location=f"제{art_num}조", number=art_num,
                )
                articles.append(current_article)
                current_para = None
                current_item = None
                body_lines = []
                continue

            m = PARAGRAPH_PATTERN.match(stripped)
            if m and current_article is not None:
                flush_body(current_item or current_para)
                para_num = circled_to_int(m.group(1))
                current_para = Section(
                    heading=m.group(1), level=2, text=stripped,
                    location=f"{current_article.location} 제{para_num}항",
                    number=para_num,
                )
                current_article.children.append(current_para)
                current_item = None
                body_lines = []
                continue

            m = ITEM_PATTERN.match(stripped)
            if m and current_para is not None:
                flush_body(current_item or current_para)
                item_num = int(m.group(1))
                current_item = Section(
                    heading=f"{item_num}.", level=3, text=stripped,
                    location=f"{current_para.location} 제{item_num}호",
                    number=item_num,
                )
                current_para.children.append(current_item)
                body_lines = []
                continue

            m = SUB_ITEM_PATTERN.match(stripped)
            if m and current_item is not None:
                flush_body(current_item)
                current_item.text = current_item.text + '\n' + stripped
                continue

            # Regular body text
            body_lines.append(stripped)

        flush_body(current_item or current_para or current_article)
        return articles


def get_parser(path: Path) -> Parser:
    """Return the appropriate parser for the given file type."""
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        return PDFParser()
    elif suffix in ('.md', '.markdown'):
        return MarkdownParser()
    else:
        raise ValueError(f"Unsupported file format: {suffix}")
