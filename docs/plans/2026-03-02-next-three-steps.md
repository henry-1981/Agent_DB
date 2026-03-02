# Agent-DB Phase B 전제 조건 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** G1 자동검증 → approved 규칙 20개+ → Agent 인용 end-to-end 1건을 달성하여 일반화 설계의 데이터 기반 검증을 완료한다.

**Architecture:** 기존 `scripts/validate.py`를 확장하여 G1 gate 파이프라인을 구축하고, G2 승인 CLI로 도메인 소유자의 승인 워크플로를 지원하며, 검색+인용 모듈로 Agent가 approved 규칙을 status 기반으로 인용할 수 있게 한다.

**Tech Stack:** Python 3.11+, PyYAML, jsonschema, difflib (stdlib), pytest

---

## Task 1: 프로젝트 기반 설정

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: pyproject.toml 생성**

```toml
[project]
name = "agent-db"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",
    "jsonschema>=4.20",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["scripts"]
```

**Step 2: 의존성 설치**

Run: `pip3 install -e ".[dev]"`
Expected: jsonschema, pytest 설치 완료

**Step 3: tests 디렉토리 초기화**

`tests/__init__.py`: 빈 파일
`tests/conftest.py`:

```python
"""Shared test fixtures for Agent-DB."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def root():
    return ROOT


@pytest.fixture
def load_yaml():
    def _load(path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return _load


@pytest.fixture
def sample_rule():
    """Minimal valid Rule Unit for testing."""
    return {
        "rule_id": "test-sample-rule",
        "text": "테스트용 규칙 텍스트입니다. 충분한 길이가 필요합니다.",
        "source_ref": {
            "document": "kmdia-fc",
            "version": "2022.04",
            "location": "제1조",
        },
        "scope": ["테스트 적용 범위"],
        "authority": "regulation",
        "status": "draft",
    }
```

**Step 4: pytest 실행 확인**

Run: `python3 -m pytest tests/ -v`
Expected: `no tests ran` (0 collected, no errors)

**Step 5: Commit**

```bash
git add pyproject.toml tests/
git commit -m "chore: 프로젝트 기반 설정 (pyproject.toml, pytest, jsonschema)"
```

---

## Task 2: G1 — JSON Schema 검증

**Files:**
- Create: `tests/test_gate1.py`
- Create: `scripts/gate1.py`

**Step 1: 실패하는 테스트 작성**

```python
"""Tests for Gate 1 auto-verification pipeline."""

import pytest
import yaml

from gate1 import check_schema


def test_valid_rule_passes_schema(sample_rule):
    errors = check_schema(sample_rule)
    assert errors == []


def test_missing_required_field_fails(sample_rule):
    del sample_rule["scope"]
    errors = check_schema(sample_rule)
    assert len(errors) == 1
    assert "scope" in errors[0].lower() or "required" in errors[0].lower()


def test_invalid_authority_fails(sample_rule):
    sample_rule["authority"] = "invalid_level"
    errors = check_schema(sample_rule)
    assert len(errors) >= 1


def test_empty_text_fails(sample_rule):
    sample_rule["text"] = "short"
    errors = check_schema(sample_rule)
    assert len(errors) >= 1


def test_invalid_rule_id_pattern_fails(sample_rule):
    sample_rule["rule_id"] = "INVALID_ID"
    errors = check_schema(sample_rule)
    assert len(errors) >= 1
```

**Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_gate1.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gate1'`

**Step 3: 최소 구현**

`scripts/gate1.py`:

```python
"""Gate 1 auto-verification pipeline.

Checks (draft → verified):
1. Schema completeness (JSON Schema validation)
2. Duplicate detection (text similarity >= 0.90 → reject)
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
```

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_gate1.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add scripts/gate1.py tests/test_gate1.py
git commit -m "feat: G1 스키마 검증 (check_schema + 테스트 5개)"
```

---

## Task 3: G1 — 중복 탐지

**Files:**
- Modify: `tests/test_gate1.py` (테스트 추가)
- Modify: `scripts/gate1.py` (check_duplicates 추가)

**Step 1: 실패하는 테스트 작성**

`tests/test_gate1.py`에 추가:

```python
from gate1 import check_duplicates


def test_no_duplicates_passes():
    rules = [
        {"rule_id": "a", "text": "완전히 다른 내용의 규칙 텍스트입니다."},
        {"rule_id": "b", "text": "이것은 전혀 관련 없는 별도의 규칙입니다."},
    ]
    errors = check_duplicates(
        {"rule_id": "c", "text": "새로운 고유한 규칙 텍스트입니다."}, rules
    )
    assert errors == []


def test_near_duplicate_rejected():
    existing = [
        {"rule_id": "a", "text": "사업자는 기부금품 전달이 완료된 후 협회에 통보하여야 한다."},
    ]
    candidate = {
        "rule_id": "b",
        "text": "사업자는 기부금품 전달이 완료된 후 협회에 통보하여야 한다.",
    }
    errors = check_duplicates(candidate, existing)
    assert len(errors) == 1
    assert "a" in errors[0]  # references the duplicate rule_id


def test_similar_but_below_threshold_passes():
    existing = [
        {"rule_id": "a", "text": "사업자는 기부행위를 할 수 있다."},
    ]
    candidate = {
        "rule_id": "b",
        "text": "사업자는 기부금품의 회계처리 시 증빙자료를 첨부하여야 한다.",
    }
    errors = check_duplicates(candidate, existing)
    assert errors == []
```

**Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_gate1.py::test_no_duplicates_passes -v`
Expected: FAIL — `ImportError: cannot import name 'check_duplicates'`

**Step 3: 구현**

`scripts/gate1.py`에 추가:

```python
from difflib import SequenceMatcher

DUPLICATE_THRESHOLD = 0.90


def check_duplicates(
    candidate: dict, existing_rules: list[dict]
) -> list[str]:
    """Detect near-duplicate text. Similarity >= 0.90 → reject."""
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
```

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_gate1.py -v`
Expected: 8 passed

**Step 5: Commit**

```bash
git add scripts/gate1.py tests/test_gate1.py
git commit -m "feat: G1 중복 탐지 (check_duplicates, threshold 0.90)"
```

---

## Task 4: G1 — source_ref 무결성 + Gate 오케스트레이터

**Files:**
- Modify: `tests/test_gate1.py` (테스트 추가)
- Modify: `scripts/gate1.py` (check_source_ref, run_gate1 추가)

**Step 1: 실패하는 테스트 작성**

```python
from gate1 import check_source_ref, run_gate1


def test_valid_source_ref_passes():
    rule = {
        "source_ref": {"document": "kmdia-fc", "version": "2022.04", "location": "제1조"},
    }
    errors = check_source_ref(rule)
    assert errors == []


def test_unknown_document_fails():
    rule = {
        "source_ref": {"document": "nonexistent", "version": "2022.04", "location": "제1조"},
    }
    errors = check_source_ref(rule)
    assert len(errors) == 1
    assert "nonexistent" in errors[0]


def test_unknown_version_fails():
    rule = {
        "source_ref": {"document": "kmdia-fc", "version": "9999.99", "location": "제1조"},
    }
    errors = check_source_ref(rule)
    assert len(errors) == 1


def test_run_gate1_passes_valid_draft(sample_rule, root):
    result = run_gate1(sample_rule, root)
    assert result["passed"] is True
    assert result["new_status"] == "verified"
    assert result["errors"] == []


def test_run_gate1_rejects_invalid(sample_rule, root):
    del sample_rule["scope"]
    result = run_gate1(sample_rule, root)
    assert result["passed"] is False
    assert result["new_status"] == "rejected"
    assert len(result["errors"]) > 0


def test_run_gate1_skips_non_draft(sample_rule, root):
    sample_rule["status"] = "approved"
    result = run_gate1(sample_rule, root)
    assert result["passed"] is False
    assert "draft" in result["errors"][0].lower()
```

**Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_gate1.py::test_valid_source_ref_passes -v`
Expected: FAIL

**Step 3: 구현**

`scripts/gate1.py`에 추가:

```python
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
```

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_gate1.py -v`
Expected: 14 passed

**Step 5: Commit**

```bash
git add scripts/gate1.py tests/test_gate1.py
git commit -m "feat: G1 source_ref 검증 + Gate 오케스트레이터 (run_gate1)"
```

---

## Task 5: G1 CLI — 실제 Rule Unit에 대해 G1 실행

**Files:**
- Modify: `scripts/gate1.py` (CLI main 추가)
- Create: `tests/test_gate1_integration.py`

**Step 1: 통합 테스트 작성**

```python
"""Integration tests: run G1 on actual rule files."""

from pathlib import Path

import yaml

from gate1 import run_gate1

ROOT = Path(__file__).resolve().parent.parent


def test_all_existing_rules_pass_gate1():
    """Every rule in rules/ should pass G1."""
    rules_dir = ROOT / "rules"
    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        result = run_gate1(rule, ROOT)
        assert result["passed"], (
            f"{path.name}: G1 failed — {result['errors']}"
        )
```

**Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_gate1_integration.py -v`
Expected: 어쩌면 통과, 어쩌면 실패 (실제 규칙 파일 상태에 따라). 실패 시 규칙 파일 수정.

**Step 3: gate1.py에 CLI 추가**

```python
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


def _print_result(rule_id: str, result: dict):
    status = "PASS" if result["passed"] else "FAIL"
    print(f"  [{status}] {rule_id} → {result['new_status']}")
    for e in result["errors"]:
        print(f"         error: {e}")
    for w in result["warnings"]:
        print(f"         warn:  {w}")


if __name__ == "__main__":
    main()
```

**Step 4: CLI 실행 확인**

Run: `python3 scripts/gate1.py`
Expected:
```
  [PASS] kmdia-fc-art7-p1-main → verified
  [PASS] kmdia-fc-art7-p1-item1 → verified
  ...
G1 Summary: 7/7 passed, 0 failed
```

**Step 5: Commit**

```bash
git add scripts/gate1.py tests/test_gate1_integration.py
git commit -m "feat: G1 CLI + 통합 테스트 (기존 7개 규칙 전수 검증)"
```

---

## Task 6: G2 승인 CLI

**Files:**
- Create: `scripts/approve.py`
- Create: `tests/test_approve.py`

**Step 1: 실패하는 테스트 작성**

```python
"""Tests for G2 approval workflow."""

import copy
from datetime import datetime, timezone

from approve import apply_approval, validate_g2_checklist


def test_valid_checklist_passes():
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    errors = validate_g2_checklist(checklist)
    assert errors == []


def test_checklist_with_fail_is_valid():
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "fail",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    errors = validate_g2_checklist(checklist)
    assert errors == []


def test_missing_checklist_item_fails():
    checklist = {"semantic_accuracy": "pass"}
    errors = validate_g2_checklist(checklist)
    assert len(errors) > 0


def test_apply_approval_to_verified_rule(sample_rule):
    sample_rule["status"] = "verified"
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    result = apply_approval(sample_rule, "HB", checklist)
    assert result["status"] == "approved"
    assert result["approval"]["reviewer"] == "HB"
    assert "timestamp" in result["approval"]


def test_apply_approval_rejects_if_checklist_has_fail(sample_rule):
    sample_rule["status"] = "verified"
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "fail",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    result = apply_approval(sample_rule, "HB", checklist)
    assert result["status"] == "rejected"
    assert "scope_completeness" in result.get("rejection_reason", "")


def test_apply_approval_only_verified(sample_rule):
    sample_rule["status"] = "draft"
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    result = apply_approval(sample_rule, "HB", checklist)
    assert result["status"] == "draft"  # unchanged
```

**Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_approve.py -v`
Expected: FAIL — module not found

**Step 3: 구현**

`scripts/approve.py`:

```python
"""Gate 2 approval workflow.

Provides functions for human approval of verified Rule Units.
G2 checks what LLM structurally cannot:
- Semantic accuracy
- Scope completeness
- Authority correctness
- Relation validity
"""

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

G2_CHECKLIST_ITEMS = [
    "semantic_accuracy",
    "scope_completeness",
    "authority_correctness",
    "relation_validity",
]


def validate_g2_checklist(checklist: dict) -> list[str]:
    """Validate that all 4 G2 checklist items are present."""
    errors = []
    for item in G2_CHECKLIST_ITEMS:
        if item not in checklist:
            errors.append(f"missing checklist item: {item}")
        elif checklist[item] not in ("pass", "fail"):
            errors.append(f"invalid value for {item}: {checklist[item]}")
    return errors


def apply_approval(
    rule: dict, reviewer: str, checklist: dict
) -> dict:
    """Apply G2 approval decision to a rule. Returns modified rule copy.

    - All checklist items 'pass' → status: approved
    - Any checklist item 'fail' → status: rejected with reason
    - Only operates on 'verified' rules
    """
    result = copy.deepcopy(rule)

    if result.get("status") != "verified":
        return result  # no change

    failed_items = [k for k, v in checklist.items() if v == "fail"]

    if failed_items:
        result["status"] = "rejected"
        result["rejection_reason"] = (
            f"G2 rejection: {', '.join(failed_items)} failed"
        )
    else:
        result["status"] = "approved"
        result["approval"] = {
            "reviewer": reviewer,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gate2_checklist": checklist,
        }

    return result


def approve_file(path: Path, reviewer: str, checklist: dict) -> bool:
    """Read a rule file, apply approval, write back."""
    with open(path, encoding="utf-8") as f:
        rule = yaml.safe_load(f)

    if rule.get("status") != "verified":
        print(f"  SKIP {rule.get('rule_id')}: status is '{rule.get('status')}', not 'verified'")
        return False

    result = apply_approval(rule, reviewer, checklist)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"  {result['status'].upper()} {result['rule_id']}")
    return result["status"] == "approved"


def main():
    """CLI: Approve verified rules interactively."""
    rules_dir = ROOT / "rules"
    verified = []

    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        if rule and rule.get("status") == "verified":
            verified.append((path, rule))

    if not verified:
        print("No verified rules found. Run G1 first: python3 scripts/gate1.py")
        sys.exit(0)

    print(f"\n{len(verified)} verified rule(s) awaiting G2 approval:\n")

    reviewer = input("Reviewer name [HB]: ").strip() or "HB"

    for path, rule in verified:
        print(f"\n--- {rule['rule_id']} ---")
        print(f"Text: {rule['text'][:200]}...")
        print(f"Scope: {rule.get('scope', [])}")

        checklist = {}
        for item in G2_CHECKLIST_ITEMS:
            label = item.replace("_", " ").title()
            while True:
                val = input(f"  {label} (pass/fail/skip) [pass]: ").strip().lower() or "pass"
                if val in ("pass", "fail", "skip"):
                    break
            if val == "skip":
                print(f"  SKIPPED {rule['rule_id']}")
                break
            checklist[item] = val
        else:
            approve_file(path, reviewer, checklist)

    print("\nDone.")


if __name__ == "__main__":
    main()
```

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_approve.py -v`
Expected: 6 passed

**Step 5: Commit**

```bash
git add scripts/approve.py tests/test_approve.py
git commit -m "feat: G2 승인 CLI (approve.py + 테스트 6개)"
```

---

## Task 7: Agent 인용 모듈

**Files:**
- Create: `scripts/retrieve.py`
- Create: `tests/test_retrieve.py`

**Step 1: 실패하는 테스트 작성**

```python
"""Tests for Agent retrieval and citation module."""

from retrieve import search_rules, format_citation, StatusFilter


def test_search_returns_matching_rules(root, load_yaml):
    results = search_rules("기부 금지", root=root)
    rule_ids = [r["rule_id"] for r in results]
    assert "kmdia-fc-art7-p1-item1" in rule_ids


def test_search_returns_empty_for_unrelated_query(root):
    results = search_rules("회계 감사 기준", root=root)
    assert len(results) == 0 or all(
        r.get("_score", 0) < 0.5 for r in results
    )


def test_status_filter_approved_only():
    f = StatusFilter.APPROVED_ONLY
    assert f.allows("approved") is True
    assert f.allows("verified") is False
    assert f.allows("draft") is False


def test_status_filter_verified_and_above():
    f = StatusFilter.VERIFIED_AND_ABOVE
    assert f.allows("approved") is True
    assert f.allows("verified") is True
    assert f.allows("draft") is False


def test_format_citation_approved():
    rule = {
        "rule_id": "test-rule-1",
        "text": "테스트 규칙 텍스트입니다.",
        "status": "approved",
    }
    citation = format_citation(rule)
    assert "[근거: test-rule-1]" in citation
    assert "테스트 규칙 텍스트입니다." in citation


def test_format_citation_verified_has_warning():
    rule = {
        "rule_id": "test-rule-1",
        "text": "테스트 규칙 텍스트입니다.",
        "status": "verified",
    }
    citation = format_citation(rule)
    assert "[미승인]" in citation


def test_format_citation_draft_blocked():
    rule = {
        "rule_id": "test-rule-1",
        "text": "테스트 규칙 텍스트입니다.",
        "status": "draft",
    }
    citation = format_citation(rule)
    assert citation is None
```

**Step 2: 실패 확인**

Run: `python3 -m pytest tests/test_retrieve.py -v`
Expected: FAIL

**Step 3: 구현**

`scripts/retrieve.py`:

```python
"""Agent retrieval and citation module.

Provides:
- search_rules(query) → matching rules with scores
- format_citation(rule) → status-aware citation string
- StatusFilter → controls which statuses are citable

Citation rules per CLAUDE.md:
- draft/rejected: never cite
- verified: cite with warning "[미승인]"
- approved: cite as authoritative "[근거: rule_id]"
- suspended/superseded: never cite
"""

import sys
from enum import Enum
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class StatusFilter(Enum):
    APPROVED_ONLY = "approved_only"
    VERIFIED_AND_ABOVE = "verified_and_above"

    def allows(self, status: str) -> bool:
        if self == StatusFilter.APPROVED_ONLY:
            return status == "approved"
        if self == StatusFilter.VERIFIED_AND_ABOVE:
            return status in ("approved", "verified")
        return False


# Statuses that can never be cited
_NEVER_CITE = {"draft", "rejected", "suspended", "superseded"}


def _load_rules(root: Path) -> list[dict]:
    rules_dir = root / "rules"
    rules = []
    for path in sorted(rules_dir.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            rules.append(data)
    return rules


def _match_score(keywords: list[str], rule: dict) -> float:
    """Keyword-based scope matching. Returns 0~1."""
    scopes = rule.get("scope", [])
    scope_text = " ".join(scopes)
    if not keywords:
        return 0
    hits = sum(1 for kw in keywords if kw in scope_text)
    return hits / len(keywords)


def search_rules(
    query: str,
    root: Path | None = None,
    status_filter: StatusFilter = StatusFilter.VERIFIED_AND_ABOVE,
    threshold: float = 0.5,
) -> list[dict]:
    """Search rules by scope matching. Returns matched rules sorted by score."""
    base = root or ROOT
    rules = _load_rules(base)
    keywords = query.split()

    results = []
    for rule in rules:
        if not status_filter.allows(rule.get("status", "")):
            continue
        score = _match_score(keywords, rule)
        if score >= threshold:
            rule_copy = dict(rule)
            rule_copy["_score"] = score
            results.append(rule_copy)

    results.sort(key=lambda r: r["_score"], reverse=True)
    return results


def format_citation(rule: dict) -> str | None:
    """Format a rule as a citation string. Returns None if uncitable.

    - approved: "[근거: {rule_id}] {text}"
    - verified: "[미승인] [근거: {rule_id}] {text}"
    - others: None (cannot cite)
    """
    status = rule.get("status", "")
    if status in _NEVER_CITE:
        return None

    rule_id = rule.get("rule_id", "unknown")
    text = rule.get("text", "").strip()

    if status == "approved":
        return f"[근거: {rule_id}] {text}"
    if status == "verified":
        return f"[미승인] [근거: {rule_id}] {text}"

    return None


def main():
    """CLI: Search and cite rules."""
    if len(sys.argv) < 2:
        print("Usage: python3 retrieve.py <query>")
        print("Example: python3 retrieve.py '기부 금지 조건'")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    # For demo: use VERIFIED_AND_ABOVE to show current draft rules too
    # In production: use APPROVED_ONLY
    results = search_rules(query, status_filter=StatusFilter.VERIFIED_AND_ABOVE)

    if not results:
        print(f'No citable rules found for: "{query}"')
        print("(All rules may be in draft status. Run G1 + G2 first.)")
        sys.exit(0)

    print(f'\nQuery: "{query}"')
    print(f"Found {len(results)} citable rule(s):\n")

    for rule in results:
        citation = format_citation(rule)
        if citation:
            print(f"  {citation[:200]}")
            print()


if __name__ == "__main__":
    main()
```

**Step 4: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_retrieve.py -v`
Expected: 7 passed

**Step 5: Commit**

```bash
git add scripts/retrieve.py tests/test_retrieve.py
git commit -m "feat: Agent 인용 모듈 (retrieve.py — 검색 + status별 인용 포맷)"
```

---

## Task 8: End-to-End 통합 — G1→G2→인용 파이프라인

**Files:**
- Create: `tests/test_e2e.py`

**Step 1: end-to-end 테스트 작성**

```python
"""End-to-end test: G1 → G2 → Agent citation pipeline."""

import copy

from gate1 import run_gate1
from approve import apply_approval
from retrieve import format_citation


def test_full_pipeline_draft_to_citation(sample_rule, root):
    """A rule goes from draft → verified → approved → citable."""
    rule = copy.deepcopy(sample_rule)
    assert rule["status"] == "draft"

    # Step 1: G1
    g1_result = run_gate1(rule, root)
    assert g1_result["passed"], f"G1 failed: {g1_result['errors']}"
    rule["status"] = g1_result["new_status"]
    assert rule["status"] == "verified"

    # Step 2: G2
    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "pass",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    rule = apply_approval(rule, "HB", checklist)
    assert rule["status"] == "approved"
    assert rule["approval"]["reviewer"] == "HB"

    # Step 3: Citation
    citation = format_citation(rule)
    assert citation is not None
    assert "[근거: test-sample-rule]" in citation
    assert "[미승인]" not in citation


def test_rejected_rule_is_not_citable(sample_rule, root):
    """A rule rejected at G2 cannot be cited."""
    rule = copy.deepcopy(sample_rule)
    rule["status"] = "verified"

    checklist = {
        "semantic_accuracy": "pass",
        "scope_completeness": "fail",
        "authority_correctness": "pass",
        "relation_validity": "pass",
    }
    rule = apply_approval(rule, "HB", checklist)
    assert rule["status"] == "rejected"

    citation = format_citation(rule)
    assert citation is None


def test_verified_rule_has_warning(sample_rule, root):
    """A verified but unapproved rule is cited with warning."""
    rule = copy.deepcopy(sample_rule)

    g1_result = run_gate1(rule, root)
    rule["status"] = g1_result["new_status"]

    citation = format_citation(rule)
    assert citation is not None
    assert "[미승인]" in citation
```

**Step 2: 테스트 통과 확인**

Run: `python3 -m pytest tests/test_e2e.py -v`
Expected: 3 passed

**Step 3: 전체 테스트 스위트 실행**

Run: `python3 -m pytest tests/ -v`
Expected: 모든 테스트 통과 (약 20개+)

**Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: G1→G2→인용 end-to-end 파이프라인 통합 테스트"
```

---

## 실행 순서 요약

```
Task 1: 프로젝트 기반 설정          ← pytest, jsonschema 설치
Task 2: G1 스키마 검증              ← check_schema
Task 3: G1 중복 탐지                ← check_duplicates
Task 4: G1 source_ref + 오케스트레이터 ← run_gate1 (draft → verified)
Task 5: G1 CLI + 통합 테스트         ← 기존 7개 규칙 전수 검증
Task 6: G2 승인 CLI                 ← approve.py (verified → approved)
Task 7: Agent 인용 모듈              ← retrieve.py (검색 + 인용)
Task 8: E2E 통합 테스트             ← draft → verified → approved → 인용
```

**Task 8 완료 후 HB 수동 작업:**
1. `python3 scripts/gate1.py` → 7개 규칙 verified로 전이
2. `python3 scripts/approve.py` → HB가 G2 체크리스트 수행, approved로 전이
3. KMDIA 안내서에서 제5조, 제6조, 제8조 등 추가 추출 (수동)
4. 추가 규칙에 G1→G2 수행 → 20개+ approved 달성
5. `python3 scripts/retrieve.py "기부 금지 조건"` → Agent 인용 end-to-end 증명
