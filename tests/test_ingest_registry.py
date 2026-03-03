"""Tests for source registry management (ingest/registry.py).

All tests use tmp_path for isolation — no production data touched.
"""

from pathlib import Path

import pytest
import yaml

from ingest.registry import (
    UserAbortError,
    add_version_to_existing_source,
    load_sources_registry,
    register_new_source,
    save_sources_registry,
)


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def registry_env(tmp_path):
    """Set up isolated registry environment with mock data."""
    # Create sources/_sources.yaml with one existing entry
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "_sources.yaml").write_text(yaml.dump({
        "sources": {
            "existing-doc": {
                "title": "기존 문서",
                "versions": [{"version": "1.0", "file": "existing.pdf"}],
                "publisher": "테스트 출판사",
                "authority_level": "regulation",
                "notes": "테스트용 기존 문서",
            }
        }
    }, allow_unicode=True), encoding="utf-8")

    # Create domains/ra/authority_levels.yaml
    domain_dir = tmp_path / "domains" / "ra"
    domain_dir.mkdir(parents=True)
    (domain_dir / "authority_levels.yaml").write_text(yaml.dump({
        "levels": ["law", "regulation", "sop", "guideline", "precedent"],
    }), encoding="utf-8")

    return tmp_path


# -- Test: load / save roundtrip ---------------------------------------------


class TestRegistryIO:
    """Basic load and save operations."""

    def test_load_sources_registry(self, registry_env):
        data = load_sources_registry(registry_env)
        assert "sources" in data
        assert "existing-doc" in data["sources"]

    def test_save_sources_registry_roundtrip(self, registry_env):
        data = load_sources_registry(registry_env)
        data["sources"]["roundtrip-doc"] = {
            "title": "왕복 테스트",
            "versions": [{"version": "0.1", "file": "rt.pdf"}],
            "publisher": "테스트",
            "authority_level": "sop",
            "notes": "",
        }
        save_sources_registry(data, registry_env)

        reloaded = load_sources_registry(registry_env)
        assert "roundtrip-doc" in reloaded["sources"]
        assert reloaded["sources"]["roundtrip-doc"]["title"] == "왕복 테스트"


# -- Test: register_new_source -----------------------------------------------


class TestRegisterNewSource:
    """New source registration with authority validation and confirm."""

    def test_register_new_source_success(self, registry_env):
        register_new_source(
            doc_id="new-doc",
            title="새 문서",
            version="2026.01",
            authority_level="regulation",
            file_path="new.pdf",
            publisher="식약처",
            notes="테스트 등록",
            domain="ra",
            root=registry_env,
            confirm_fn=lambda: True,
        )
        data = load_sources_registry(registry_env)
        assert "new-doc" in data["sources"]
        entry = data["sources"]["new-doc"]
        assert entry["title"] == "새 문서"
        assert entry["authority_level"] == "regulation"
        assert entry["publisher"] == "식약처"
        assert len(entry["versions"]) == 1
        assert entry["versions"][0]["version"] == "2026.01"

    def test_register_new_source_invalid_authority(self, registry_env):
        with pytest.raises(ValueError, match="not valid for domain"):
            register_new_source(
                doc_id="bad-auth",
                title="잘못된 등급",
                version="1.0",
                authority_level="supreme-law",
                file_path="bad.pdf",
                publisher="테스트",
                notes="",
                domain="ra",
                root=registry_env,
                confirm_fn=lambda: True,
            )

    def test_register_new_source_duplicate_doc_id(self, registry_env):
        with pytest.raises(ValueError, match="already exists"):
            register_new_source(
                doc_id="existing-doc",
                title="중복 문서",
                version="1.0",
                authority_level="regulation",
                file_path="dup.pdf",
                publisher="테스트",
                notes="",
                domain="ra",
                root=registry_env,
                confirm_fn=lambda: True,
            )

    def test_register_new_source_user_abort(self, registry_env):
        with pytest.raises(UserAbortError, match="cancelled"):
            register_new_source(
                doc_id="abort-doc",
                title="취소 문서",
                version="1.0",
                authority_level="regulation",
                file_path="abort.pdf",
                publisher="테스트",
                notes="",
                domain="ra",
                root=registry_env,
                confirm_fn=lambda: False,
            )
        # Verify nothing was saved
        data = load_sources_registry(registry_env)
        assert "abort-doc" not in data["sources"]

    def test_register_new_source_validates_domain_config(self, registry_env):
        """Checks against domains/ra/authority_levels.yaml specifically."""
        # Valid levels for ra: law, regulation, sop, guideline, precedent
        for level in ["law", "sop", "guideline", "precedent"]:
            register_new_source(
                doc_id=f"domain-check-{level}",
                title=f"도메인 검증 {level}",
                version="1.0",
                authority_level=level,
                file_path=f"{level}.pdf",
                publisher="테스트",
                notes="",
                domain="ra",
                root=registry_env,
                confirm_fn=lambda: True,
            )
        data = load_sources_registry(registry_env)
        for level in ["law", "sop", "guideline", "precedent"]:
            assert f"domain-check-{level}" in data["sources"]


# -- Test: add_version_to_existing_source ------------------------------------


class TestAddVersion:
    """Version addition to existing sources."""

    def test_add_version_success(self, registry_env):
        add_version_to_existing_source(
            doc_id="existing-doc",
            version="2.0",
            file_path="existing-v2.pdf",
            root=registry_env,
        )
        data = load_sources_registry(registry_env)
        versions = data["sources"]["existing-doc"]["versions"]
        assert len(versions) == 2
        assert versions[1]["version"] == "2.0"
        assert versions[1]["file"] == "existing-v2.pdf"

    def test_add_version_unknown_doc_id(self, registry_env):
        with pytest.raises(KeyError, match="not in registry"):
            add_version_to_existing_source(
                doc_id="ghost-doc",
                version="1.0",
                file_path="ghost.pdf",
                root=registry_env,
            )

    def test_add_version_duplicate_version(self, registry_env):
        with pytest.raises(ValueError, match="already exists"):
            add_version_to_existing_source(
                doc_id="existing-doc",
                version="1.0",
                file_path="dup-version.pdf",
                root=registry_env,
            )

    def test_add_version_with_supersedes(self, registry_env):
        add_version_to_existing_source(
            doc_id="existing-doc",
            version="3.0",
            file_path="existing-v3.pdf",
            root=registry_env,
            supersedes="1.0",
        )
        data = load_sources_registry(registry_env)
        versions = data["sources"]["existing-doc"]["versions"]
        new_ver = [v for v in versions if v["version"] == "3.0"][0]
        assert new_ver["supersedes"] == "1.0"
