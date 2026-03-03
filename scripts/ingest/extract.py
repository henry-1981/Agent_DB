"""Extract phase: RuleCandidate → dict with 6 required Rule Unit fields.

Converts format-agnostic RuleCandidates into field dictionaries ready
for YAML serialization as draft Rule Units.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ingest.ir import RuleCandidate

_ARTICLE_RE = re.compile(r"제(\d+)조")
_PARAGRAPH_RE = re.compile(r"제(\d+)항")


def parse_article_number(location: str) -> int:
    """Extract article number from a location string.

    >>> parse_article_number("제7조 제1항")
    7
    """
    m = _ARTICLE_RE.search(location)
    if not m:
        raise ValueError(f"No article number found in: {location!r}")
    return int(m.group(1))


def parse_paragraph_number(location: str) -> int:
    """Extract paragraph number from a location string. Default: 1.

    >>> parse_paragraph_number("제5조 제3항")
    3
    >>> parse_paragraph_number("제7조")
    1
    """
    m = _PARAGRAPH_RE.search(location)
    return int(m.group(1)) if m else 1


def generate_rule_id(
    doc_id: str, candidate: RuleCandidate, domain: str = "ra"
) -> str:
    """Generate a rule_id following RA naming convention.

    Format: {doc_id}-art{N}-p{N}-{suffix}
    Examples:
      location="제7조 제1항", suffix="main"  → "kmdia-fc-art7-p1-main"
      location="제7조 제1항", suffix="item3" → "kmdia-fc-art7-p1-item3"
    """
    loc = candidate.section.location
    art = parse_article_number(loc)
    para = parse_paragraph_number(loc)
    return f"{doc_id}-art{art}-p{para}-{candidate.suffix}"


def determine_authority(
    doc_id: str, root: Path | None = None
) -> str:
    """Look up authority_level for a doc_id from sources/_sources.yaml."""
    if root is None:
        # scripts/ingest/extract.py → scripts/ → project root
        root = Path(__file__).resolve().parent.parent.parent
    sources_path = root / "sources" / "_sources.yaml"
    with open(sources_path) as f:
        data = yaml.safe_load(f)
    sources = data.get("sources", {})
    if doc_id not in sources:
        raise KeyError(f"Unknown doc_id: {doc_id!r} (not in _sources.yaml)")
    return sources[doc_id]["authority_level"]


def extract_fields(
    candidate: RuleCandidate,
    doc_id: str,
    version: str,
    domain: str = "ra",
    root: Path | None = None,
) -> dict:
    """Extract all 6 required fields from a RuleCandidate.

    Returns dict ready for YAML serialization as a draft Rule Unit.
    """
    return {
        "rule_id": generate_rule_id(doc_id, candidate, domain),
        "text": candidate.section.text,
        "source_ref": {
            "document": doc_id,
            "version": version,
            "location": candidate.section.location,
        },
        "scope": [],  # MVP: empty, Phase 2 adds LLM extraction
        "authority": determine_authority(doc_id, root),
        "status": "draft",
    }
