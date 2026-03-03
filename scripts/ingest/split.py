"""Deterministic and LLM-assisted splitting of document sections into rule candidates.

Splits a DocumentIR into RuleCandidates using structural hierarchy:
  Article (level 1) → Paragraph (level 2) → Item (level 3)

Deterministic splitting handles clear cases. LLM judgment resolves
ambiguous enumerated sections (e.g., shared decision point detection).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from ingest.ir import DocumentIR, RuleCandidate, Section

# Enumeration markers indicating items might share a decision point
_ENUM_MARKERS = ("다음 각 호", "다음 각 목", "다음 사항")

SPLIT_JUDGMENT_PROMPT = """\
You are analyzing a Korean legal/regulatory document section.
Determine whether these enumerated items share a single decision point.

Section text:
{text}

Items:
{items}

Answer ONLY one of:
- MERGE: Items share one decision point (e.g., listing examples of the same concept)
- SPLIT: Items are independent obligations/prohibitions requiring separate rules

Provide your answer as JSON:
{{"decision": "MERGE" or "SPLIT", "reasoning": "..."}}

DO NOT generate, summarize, or paraphrase any text. Only classify."""


def deterministic_split(section: Section) -> list[RuleCandidate]:
    """Level-based splitting for clear hierarchical structures.

    Rules:
    - Article (level 1) with children → recurse into children
    - Article (level 1) without children → single RuleCandidate(suffix="main")
    - Paragraph (level 2) → always create main + each child item
    - Item (level 3) → RuleCandidate(suffix="item{N}")
    """
    if section.level == 1:
        if section.children:
            # Recurse into paragraphs
            candidates: list[RuleCandidate] = []
            for child in section.children:
                candidates.extend(deterministic_split(child))
            return candidates
        # Leaf article — single rule
        return [RuleCandidate(section=section, suffix="main")]

    if section.level == 2:
        # Paragraph always produces a main candidate
        candidates = [RuleCandidate(section=section, suffix="main")]
        # Each child item becomes a separate candidate
        for child in section.children:
            candidates.extend(deterministic_split(child))
        return candidates

    if section.level == 3:
        # Item — use its ordinal number for suffix
        n = section.number if section.number is not None else 1
        return [RuleCandidate(section=section, suffix=f"item{n}")]

    return []


def needs_llm_judgment(section: Section) -> bool:
    """Determine if a section needs LLM judgment for splitting.

    A paragraph (level 2) needs LLM judgment when:
    - It has 2+ children at level 3
    - Its text or children's text contains enumeration markers
      like "다음 각 호", "다음 각 목", "다음 사항"
    """
    if section.level != 2:
        return False

    level3_children = [c for c in section.children if c.level == 3]
    if len(level3_children) < 2:
        return False

    # Check for enumeration markers in section text and children text
    all_text = section.text + " " + " ".join(c.text for c in section.children)
    return any(marker in all_text for marker in _ENUM_MARKERS)


def llm_assisted_split(section: Section) -> list[RuleCandidate]:
    """Use LLM to determine split strategy for ambiguous sections.

    Asks: "Do these enumerated items share a single decision point?"
    Answer: MERGE (combine) or SPLIT (separate rules)

    Uses claude-haiku-4-5-20251001.
    Returns RuleCandidates with split_method="llm" and llm_reasoning set.
    Records metadata: model, prompt_hash, timestamp.
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic not installed")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    items_text = "\n".join(f"- {c.text}" for c in section.children if c.level == 3)
    prompt = SPLIT_JUDGMENT_PROMPT.format(text=section.text, items=items_text)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:8]

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract JSON from response (may be wrapped in markdown code block)
    resp_text = message.content[0].text.strip()
    if resp_text.startswith("```"):
        resp_text = resp_text.split("\n", 1)[1].rsplit("```", 1)[0]

    data = json.loads(resp_text)
    decision = data.get("decision", "SPLIT")
    reasoning = data.get("reasoning", "")

    timestamp = datetime.now(timezone.utc).isoformat()
    meta = (
        f"(model=claude-haiku-4-5-20251001, "
        f"prompt_hash={prompt_hash}, ts={timestamp})"
    )
    llm_reasoning = f"{reasoning} {meta}"

    if decision == "MERGE":
        # Combine paragraph + all items into single rule
        return [RuleCandidate(
            section=section,
            suffix="main",
            split_method="llm",
            llm_reasoning=llm_reasoning,
        )]
    else:
        # SPLIT: use deterministic behavior but mark as LLM-decided
        candidates = deterministic_split(section)
        for c in candidates:
            c.split_method = "llm"
            c.llm_reasoning = llm_reasoning
        return candidates


def split_with_fallback(section: Section) -> list[RuleCandidate]:
    """Split section, falling back to deterministic if LLM unavailable.

    If needs_llm_judgment():
        try llm_assisted_split()
        on failure: use deterministic + set needs_review=True
    else:
        use deterministic_split()
    """
    # Level 1 articles with children: recurse so child paragraphs get LLM check
    if section.level == 1 and section.children:
        candidates: list[RuleCandidate] = []
        for child in section.children:
            candidates.extend(split_with_fallback(child))
        return candidates

    if not needs_llm_judgment(section):
        return deterministic_split(section)

    try:
        return llm_assisted_split(section)
    except Exception:
        candidates = deterministic_split(section)
        for c in candidates:
            c.needs_review = True
            c.review_reason = "LLM unavailable for split judgment"
        return candidates


def split_document(ir: DocumentIR) -> list[RuleCandidate]:
    """Split all top-level sections in a DocumentIR into RuleCandidates."""
    candidates: list[RuleCandidate] = []
    for section in ir.sections:
        candidates.extend(split_with_fallback(section))
    return candidates
