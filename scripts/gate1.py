"""Gate 1 auto-verification pipeline.

Checks (draft -> verified):
1. Schema completeness (JSON Schema validation)
2. source_ref integrity (document + version exist in registry)
3. Authority validation (value exists in domain config)
4. Duplicate detection (text similarity >= 0.90 -> reject)
5. Text fidelity (PDF re-extraction via pymupdf, warning only)
6. Scope-text coherence (LLM judgment via anthropic, warning only)
"""

import os
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import jsonschema
import yaml

from domain import resolve_domain, load_authority_levels

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "rule-unit.schema.yaml"


def _load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


_schema_cache: dict | None = None


def _get_schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = _load_schema()
    return _schema_cache


def check_schema(rule: dict) -> list[str]:
    """Validate rule against JSON Schema. Returns list of error messages."""
    schema = _get_schema()
    validator = jsonschema.Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(rule)]


DUPLICATE_THRESHOLD = 0.90


def check_duplicates(
    candidate: dict, existing_rules: list[dict]
) -> list[str]:
    """Detect near-duplicate text. Similarity >= 0.90 -> reject."""
    errors = []
    cand_text = candidate.get("text", "")
    cand_id = candidate.get("rule_id", "?")

    for rule in existing_rules:
        if rule.get("rule_id") == cand_id:
            continue
        ratio = SequenceMatcher(None, cand_text, rule.get("text", "")).ratio()
        if ratio >= DUPLICATE_THRESHOLD:
            errors.append(
                f"text similarity {ratio:.2f} with '{rule['rule_id']}' "
                f"(threshold: {DUPLICATE_THRESHOLD})"
            )
    return errors


def _load_sources(root: Path | None = None) -> dict[str, list[str]]:
    """Load source registry. Returns {doc_id: [versions]}."""
    base = root or ROOT
    path = base / "sources" / "_sources.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    sources = {}
    for doc_id, info in data.get("sources", {}).items():
        sources[doc_id] = [v["version"] for v in info.get("versions", [])]
    return sources


def check_authority(rule: dict, root: Path | None = None) -> list[str]:
    """Validate authority value against domain config."""
    domain = resolve_domain(rule, root)
    if domain is None:
        return ["cannot resolve domain for authority validation"]

    levels = load_authority_levels(domain, root)
    if not levels:
        return [f"no authority_levels.yaml found for domain '{domain}'"]

    authority = rule.get("authority", "")
    if authority not in levels:
        return [
            f"authority '{authority}' not valid for domain '{domain}'. "
            f"Valid levels: {levels}"
        ]
    return []


def check_source_ref(rule: dict, root: Path | None = None) -> list[str]:
    """Verify source_ref.document and version exist in registry."""
    sources = _load_sources(root)
    errors = []
    src = rule.get("source_ref", {})
    doc_id = src.get("document")
    version = src.get("version")

    if doc_id and doc_id not in sources:
        errors.append(f"source_ref.document '{doc_id}' not in _sources.yaml")
    elif doc_id and version and version not in sources.get(doc_id, []):
        errors.append(
            f"version '{version}' not found for document '{doc_id}'"
        )
    return errors


TEXT_FIDELITY_THRESHOLD = 0.95


def _load_source_files(root: Path | None = None) -> dict[str, dict[str, str]]:
    """Load source registry with file paths. Returns {doc_id: {version: filename}}."""
    base = root or ROOT
    path = base / "sources" / "_sources.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    result = {}
    for doc_id, info in data.get("sources", {}).items():
        ver_map = {}
        for v in info.get("versions", []):
            if "file" in v:
                ver_map[v["version"]] = v["file"]
        result[doc_id] = ver_map
    return result


def check_text_fidelity(rule: dict, root: Path | None = None) -> list[str]:
    """Compare rule.text against source PDF. Returns warnings (never errors).

    Algorithm:
    1. Locate PDF via source_ref -> _sources.yaml file mapping
    2. Extract full text with pymupdf
    3. Anchor search: find rule_text[:50] in PDF text
    4. Compare window around anchor with SequenceMatcher
    5. Warning if best ratio < 0.95
    """
    try:
        import pymupdf  # noqa: F811
    except ImportError:
        return ["[text_fidelity] pymupdf not installed, skipping"]

    base = root or ROOT
    src = rule.get("source_ref", {})
    doc_id = src.get("document", "")
    version = src.get("version", "")

    source_files = _load_source_files(root)
    doc_versions = source_files.get(doc_id, {})
    filename = doc_versions.get(version)
    if not filename:
        return [f"[text_fidelity] no PDF file mapped for {doc_id} v{version}, skipping"]

    pdf_path = base / "sources" / filename
    if not pdf_path.exists():
        return [f"[text_fidelity] PDF not found: {pdf_path.name}, skipping"]

    # Extract full text from PDF
    try:
        doc = pymupdf.open(str(pdf_path))
        full_text = " ".join(page.get_text() for page in doc)
        doc.close()
    except Exception as e:
        return [f"[text_fidelity] PDF extraction failed: {e}"]

    rule_text = rule.get("text", "")
    if not rule_text:
        return ["[text_fidelity] empty rule text, skipping"]

    # Normalize whitespace
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    rule_text_norm = norm(rule_text)
    full_text_norm = norm(full_text)

    # Anchor search: first 50 chars of rule text
    anchor = rule_text_norm[:50]
    anchor_pos = full_text_norm.find(anchor)

    if anchor_pos >= 0:
        # Extract window around anchor
        window_len = int(len(rule_text_norm) * 1.2)
        window = full_text_norm[anchor_pos : anchor_pos + window_len]
        best_ratio = SequenceMatcher(None, rule_text_norm, window).ratio()
    else:
        # Anchor not found; compare against entire text (fallback)
        best_ratio = SequenceMatcher(None, rule_text_norm, full_text_norm).ratio()

    if best_ratio < TEXT_FIDELITY_THRESHOLD:
        return [
            f"[text_fidelity] best match ratio {best_ratio:.3f} "
            f"< threshold {TEXT_FIDELITY_THRESHOLD} for {rule.get('rule_id', '?')}"
        ]
    return []


def check_scope_text_coherence(rule: dict, root: Path | None = None) -> list[str]:
    """Check if scope items are derivable from rule text via LLM.

    Returns warnings (never errors). Gracefully skips if anthropic
    is not installed or ANTHROPIC_API_KEY is not set.
    """
    try:
        import anthropic  # noqa: F811
    except ImportError:
        return ["[scope_coherence] anthropic not installed, skipping"]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return ["[scope_coherence] ANTHROPIC_API_KEY not set, skipping"]

    rule_text = rule.get("text", "")
    scope = rule.get("scope", [])
    if not scope or not rule_text:
        return []

    prompt = (
        "You are a regulatory document analyst. Given a rule text and its scope items, "
        "determine if each scope item can be logically derived from the rule text.\n\n"
        f"Rule text:\n{rule_text}\n\n"
        f"Scope items:\n"
        + "\n".join(f"- {s}" for s in scope)
        + "\n\nRespond in JSON format: "
        '{"results": [{"scope": "<item>", "derivable": true/false, "reason": "<brief>"}]}'
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        import json

        # Extract JSON from response
        resp_text = message.content[0].text
        # Try to parse JSON (may be wrapped in markdown code block)
        resp_text = resp_text.strip()
        if resp_text.startswith("```"):
            resp_text = resp_text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(resp_text)

        warnings = []
        for item in data.get("results", []):
            if not item.get("derivable", True):
                warnings.append(
                    f"[scope_coherence] scope '{item['scope']}' may not be derivable "
                    f"from text: {item.get('reason', 'no reason')}"
                )
        return warnings
    except Exception as e:
        return [f"[scope_coherence] LLM check failed: {e}"]


def _load_existing_rules(root: Path | None = None) -> list[dict]:
    """Load all existing rule files for duplicate checking."""
    base = root or ROOT
    rules_dir = base / "rules"
    rules = []
    if not rules_dir.exists():
        return rules
    for path in rules_dir.rglob("*.yaml"):
        if not path.name.startswith("_"):
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data:
                rules.append(data)
    return rules


def run_gate1(rule: dict, root: Path | None = None) -> dict:
    """Run full G1 pipeline. Returns {passed, new_status, errors, warnings}.

    Checks:
    1. Status must be 'draft'
    2. JSON Schema validation
    3. source_ref integrity
    4. Duplicate detection
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Pre-check: only draft rules
    if rule.get("status") != "draft":
        return {
            "passed": False,
            "new_status": rule.get("status"),
            "errors": [f"G1 only processes draft rules (current: {rule.get('status')})"],
            "warnings": [],
        }

    # Check 1: Schema
    errors.extend(check_schema(rule))

    # Check 2: source_ref
    errors.extend(check_source_ref(rule, root))

    # Check 3: Authority against domain config
    errors.extend(check_authority(rule, root))

    # Check 4: Duplicates
    existing = _load_existing_rules(root)
    errors.extend(check_duplicates(rule, existing))

    # Check 5: Text fidelity (warning only)
    warnings.extend(check_text_fidelity(rule, root))

    # Check 6: Scope-text coherence (warning only)
    warnings.extend(check_scope_text_coherence(rule, root))

    passed = len(errors) == 0
    return {
        "passed": passed,
        "new_status": "verified" if passed else "rejected",
        "errors": errors,
        "warnings": warnings,
    }


def _print_result(rule_id: str, result: dict):
    status = "PASS" if result["passed"] else "FAIL"
    print(f"  [{status}] {rule_id} -> {result['new_status']}")
    for e in result["errors"]:
        print(f"         error: {e}")
    for w in result["warnings"]:
        print(f"         warn:  {w}")


def apply_gate1(path: Path, root: Path | None = None) -> bool:
    """Run G1 on a file and write the status change back if passed."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    rule = yaml.safe_load(raw)
    if rule.get("status") != "draft":
        return False

    result = run_gate1(rule, root)
    if result["passed"]:
        # Preserve YAML comments by doing minimal replacement
        updated = raw.replace("status: draft", "status: verified", 1)
        # Append verified_at timestamp
        ts = datetime.now(timezone.utc).isoformat()
        updated = updated.rstrip() + f"\nverified_at: '{ts}'\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated)
    return result["passed"]


def main():
    """CLI: Run G1 on all draft rules or a specific file.

    Flags:
      --apply  Write status changes to files (draft -> verified)
    """
    import sys

    do_apply = "--apply" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        # Single file mode
        path = Path(args[0])
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        result = run_gate1(rule, ROOT)
        _print_result(rule.get("rule_id", path.name), result)
        if do_apply and result["passed"]:
            apply_gate1(path, ROOT)
        sys.exit(0 if result["passed"] else 1)

    # All draft rules
    rules_dir = ROOT / "rules"
    total, passed, failed = 0, 0, 0
    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        if rule.get("status") != "draft":
            continue
        total += 1
        result = run_gate1(rule, ROOT)
        _print_result(rule["rule_id"], result)
        if result["passed"]:
            passed += 1
            if do_apply:
                apply_gate1(path, ROOT)
        else:
            failed += 1

    suffix = " (applied)" if do_apply else " (dry-run, use --apply to persist)"
    print(f"\nG1 Summary: {passed}/{total} passed, {failed} failed{suffix}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
