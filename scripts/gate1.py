"""Gate 1 auto-verification pipeline.

Checks (draft -> verified):
1. Schema completeness (JSON Schema validation)
2. Duplicate detection (text similarity >= 0.90 -> reject)
3. source_ref integrity (document + version exist in registry)
4. [Stub] Text fidelity (PDF re-extraction, requires pipeline integration)
5. [Stub] scope-text consistency (LLM judgment, flags for G2)
"""

from difflib import SequenceMatcher
from pathlib import Path

import jsonschema
import yaml

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

    # Check 3: Duplicates
    existing = _load_existing_rules(root)
    errors.extend(check_duplicates(rule, existing))

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


def main():
    """CLI: Run G1 on all draft rules or a specific file."""
    import sys

    if len(sys.argv) > 1:
        # Single file mode
        path = Path(sys.argv[1])
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        result = run_gate1(rule, ROOT)
        _print_result(rule.get("rule_id", path.name), result)
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
        else:
            failed += 1

    print(f"\nG1 Summary: {passed}/{total} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
