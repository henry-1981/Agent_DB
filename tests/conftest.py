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
