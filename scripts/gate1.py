"""Gate 1 auto-verification pipeline.

Checks (draft -> verified):
1. Schema completeness (JSON Schema validation)
2. Duplicate detection (text similarity >= 0.90 -> reject)
3. source_ref integrity (document + version exist in registry)
4. [Stub] Text fidelity (PDF re-extraction, requires pipeline integration)
5. [Stub] scope-text consistency (LLM judgment, flags for G2)
"""

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
