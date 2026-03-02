"""Rule Unit validator (G1 precursor).

Checks:
1. source_ref.document exists in sources/_sources.yaml
2. source_ref.version exists for that document
3. rule_id uniqueness across all Rule Units
4. JSON Schema validation against rule-unit.schema.yaml
"""

import sys
from pathlib import Path

import yaml

# jsonschema is optional — degrade gracefully
try:
    import jsonschema as _jsonschema_check  # noqa: F401

    HAS_JSONSCHEMA = True
    del _jsonschema_check
except ImportError:
    HAS_JSONSCHEMA = False

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources() -> dict:
    """Load source registry and return {doc_id: {version: [...]}}."""
    path = ROOT / "sources" / "_sources.yaml"
    if not path.exists():
        print(f"FAIL: source registry not found: {path}")
        sys.exit(1)
    data = load_yaml(path)
    sources = {}
    for doc_id, info in data.get("sources", {}).items():
        versions = [v["version"] for v in info.get("versions", [])]
        sources[doc_id] = versions
    return sources


def load_schema() -> dict | None:
    path = ROOT / "schemas" / "rule-unit.schema.yaml"
    if not path.exists():
        return None
    return load_yaml(path)


def find_rule_files() -> list[Path]:
    """Find all YAML files under rules/ excluding _-prefixed files."""
    rules_dir = ROOT / "rules"
    if not rules_dir.exists():
        return []
    return [
        p
        for p in rules_dir.rglob("*.yaml")
        if not p.name.startswith("_")
    ]


def validate() -> bool:
    sources = load_sources()
    schema = load_schema()
    rule_files = find_rule_files()

    if not rule_files:
        print("WARN: no rule files found under rules/")
        return True

    errors: list[str] = []
    seen_ids: dict[str, Path] = {}

    for path in sorted(rule_files):
        rel = path.relative_to(ROOT)
        data = load_yaml(path)

        if data is None:
            errors.append(f"{rel}: empty or invalid YAML")
            continue

        rule_id = data.get("rule_id")
        if not rule_id:
            errors.append(f"{rel}: missing rule_id")
            continue

        # Uniqueness
        if rule_id in seen_ids:
            errors.append(
                f"{rel}: duplicate rule_id '{rule_id}' "
                f"(first seen in {seen_ids[rule_id]})"
            )
        else:
            seen_ids[rule_id] = rel

        # Source ref validation
        src_ref = data.get("source_ref", {})
        doc_id = src_ref.get("document")
        version = src_ref.get("version")

        if doc_id and doc_id not in sources:
            errors.append(
                f"{rel}: source_ref.document '{doc_id}' "
                f"not found in _sources.yaml"
            )
        elif doc_id and version and version not in sources.get(doc_id, []):
            errors.append(
                f"{rel}: version '{version}' not found for "
                f"document '{doc_id}' in _sources.yaml"
            )

        # JSON Schema validation
        if HAS_JSONSCHEMA and schema:
            import jsonschema as js

            try:
                js.validate(data, schema)
            except js.ValidationError as e:
                errors.append(f"{rel}: schema error — {e.message}")

    # Report
    total = len(rule_files)
    failed = len(errors)
    passed = total - len({e.split(":")[0] for e in errors})

    print(f"\n{'='*60}")
    print(f"Validation Report: {total} files scanned")
    print(f"{'='*60}")

    if errors:
        print(f"\nFAILED ({failed} error(s)):\n")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print(f"\nALL PASSED ({passed}/{total})")

    print(f"\n{'='*60}")
    print(f"Source registry: {len(sources)} document(s)")
    print(f"Rule units:      {len(seen_ids)} unique ID(s)")
    if not HAS_JSONSCHEMA:
        print("WARN: jsonschema not installed — schema validation skipped")
    print(f"{'='*60}\n")

    return len(errors) == 0


if __name__ == "__main__":
    ok = validate()
    sys.exit(0 if ok else 1)
