"""Deterministic splitting of document sections into rule candidates.

Splits a DocumentIR into RuleCandidates using structural hierarchy:
  Article (level 1) → Paragraph (level 2) → Item (level 3)

MVP treats all items as independent obligations (LLM judgment deferred to Phase 2).
"""

from __future__ import annotations

from ingest.ir import DocumentIR, RuleCandidate, Section


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
    """MVP stub — always returns False. Phase 2 will implement real logic."""
    return False


def split_document(ir: DocumentIR) -> list[RuleCandidate]:
    """Split all top-level sections in a DocumentIR into RuleCandidates."""
    candidates: list[RuleCandidate] = []
    for section in ir.sections:
        candidates.extend(deterministic_split(section))
    return candidates
