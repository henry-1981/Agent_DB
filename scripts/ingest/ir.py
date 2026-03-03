"""Intermediate Representation for the ingestion pipeline.

Defines format-agnostic data structures used between pipeline phases:
  Parse → IR (DocumentIR, Section)
  Split → RuleCandidate
  Extract → dict (6 required fields)
  Draft → YAML file
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    """A structural unit within a source document.

    Represents a node in the document hierarchy (Article → Paragraph → Item).
    """

    heading: str        # e.g. "제7조 (기부행위)"
    level: int          # 1=Article, 2=Paragraph, 3=Item
    text: str           # verbatim text from source
    location: str       # human-readable coordinate, e.g. "제7조 제1항"
    children: list[Section] = field(default_factory=list)
    number: int | None = None  # parsed ordinal (7 for 제7조, 1 for ①)


@dataclass
class DocumentIR:
    """Format-agnostic intermediate representation of a source document."""

    doc_id: str              # key in sources/_sources.yaml (e.g. "kmdia-fc")
    version: str             # document version (e.g. "2022.04")
    title: str               # document title
    sections: list[Section] = field(default_factory=list)


@dataclass
class RuleCandidate:
    """Output of the split phase. Input to the extract phase."""

    section: Section
    suffix: str                      # "main" | "item{N}"
    split_method: str = "deterministic"  # "deterministic" | "llm"
    llm_reasoning: str | None = None
    needs_review: bool = False
    review_reason: str | None = None
