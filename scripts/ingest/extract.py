"""Extract phase: RuleCandidate → dict with 6 required Rule Unit fields.

Converts format-agnostic RuleCandidates into field dictionaries ready
for YAML serialization as draft Rule Units.
"""

from __future__ import annotations

import json
import os
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


# ── LLM scope extraction (Phase 2) ──────────────────────────────────


def _load_scope_vocabulary(root: Path) -> dict:
    """Load scope vocabulary from config/scope-vocabulary.yaml."""
    vocab_path = root / "config" / "scope-vocabulary.yaml"
    if not vocab_path.exists():
        return {}
    with open(vocab_path) as f:
        return yaml.safe_load(f) or {}


def _build_scope_prompt(text: str, location: str, few_shot_examples: str) -> str:
    """Build the scope extraction prompt (RFC Section 5.2)."""
    return (
        "You are extracting scope (application conditions) from a Korean regulatory rule.\n"
        "\n"
        "Rule text:\n"
        f"{text}\n"
        "\n"
        f"Source: {location}\n"
        "\n"
        "Extract 3-7 scope items. Each item should describe:\n"
        "- WHEN or WHERE this rule applies\n"
        "- WHO is affected\n"
        "- WHAT conditions trigger this rule\n"
        "\n"
        "Rules:\n"
        "1. Use Korean language for scope items\n"
        "2. Each scope item should be a concise phrase (not a sentence)\n"
        "3. DO NOT summarize or paraphrase the rule text\n"
        "4. DO NOT generate new content — only extract conditions already present in the text\n"
        "5. If the text contains enumerated conditions, list each as a separate scope item\n"
        "6. Use vocabulary consistent with these reference examples:\n"
        f"{few_shot_examples}\n"
        "\n"
        'Return JSON:\n'
        '{"scope": ["item1", "item2", ...], "reasoning": "..."}'
    )


def _format_few_shot_examples(vocabulary: dict) -> str:
    """Format vocabulary patterns as few-shot examples for the prompt."""
    patterns = vocabulary.get("patterns", {})
    if not patterns:
        return "(no reference examples available)"
    lines = []
    for category, items in patterns.items():
        lines.append(f"  {category}: {items}")
    return "\n".join(lines)


def extract_scope_llm(
    text: str, doc_id: str, location: str, root: Path | None = None
) -> list[str]:
    """Extract scope items from rule text using LLM (anthropic API).

    Uses claude-haiku-4-5-20251001 model.
    Gracefully returns [] if anthropic not installed or API key missing.
    Loads few-shot examples from config/scope-vocabulary.yaml.
    """
    try:
        import anthropic
    except ImportError:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    if root is None:
        root = Path(__file__).resolve().parent.parent.parent

    vocabulary = _load_scope_vocabulary(root)
    few_shot = _format_few_shot_examples(vocabulary)
    prompt = _build_scope_prompt(text, location, few_shot)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        resp_text = message.content[0].text.strip()
        # Handle markdown code blocks in response
        if resp_text.startswith("```"):
            resp_text = resp_text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(resp_text)

        scope = data.get("scope", [])
        if isinstance(scope, list) and all(isinstance(s, str) for s in scope):
            return scope
        return []
    except Exception:
        return []


def check_scope_vocabulary_consistency(
    generated_scope: list[str], vocabulary: dict
) -> float:
    """Measure consistency with established vocabulary. Returns 0.0~1.0.

    Checks how many generated scope items share substrings with
    vocabulary patterns. Warning if < 0.6.
    """
    patterns = vocabulary.get("patterns", {})
    if not patterns or not generated_scope:
        return 0.0

    # Collect all known vocabulary items
    known_items: list[str] = []
    for items in patterns.values():
        known_items.extend(items)

    if not known_items:
        return 0.0

    matches = 0
    for scope_item in generated_scope:
        for known in known_items:
            # Check bidirectional substring overlap (3+ char tokens)
            scope_tokens = {t for t in scope_item.split() if len(t) >= 3}
            known_tokens = {t for t in known.split() if len(t) >= 3}
            if scope_tokens & known_tokens:
                matches += 1
                break

    return matches / len(generated_scope)


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
    if root is None:
        root = Path(__file__).resolve().parent.parent.parent
    return {
        "rule_id": generate_rule_id(doc_id, candidate, domain),
        "text": candidate.section.text,
        "source_ref": {
            "document": doc_id,
            "version": version,
            "location": candidate.section.location,
        },
        "scope": extract_scope_llm(
            candidate.section.text, doc_id, candidate.section.location, root
        ),
        "authority": determine_authority(doc_id, root),
        "status": "draft",
    }
