"""Integration tests for gdrive_sync.py — mock connector + real pipeline env."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from connector.gdrive import DriveFile
from gdrive_sync import (
    parse_folder_url,
    load_sync_config,
    run_sync,
    format_sync_summary,
)


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def pipeline_env(tmp_path):
    """Set up isolated pipeline environment (reuses test_ingest_e2e pattern)."""
    # sources/_sources.yaml
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "_sources.yaml").write_text(yaml.dump({
        "sources": {
            "test-doc": {
                "title": "테스트 문서",
                "versions": [{"version": "1.0", "file": "test.md"}],
                "publisher": "테스트",
                "authority_level": "regulation",
                "notes": "",
            }
        }
    }))
    # rules/_domain.yaml
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "_domain.yaml").write_text("domain: ra\n")
    # domains/ra/authority_levels.yaml
    domain_dir = tmp_path / "domains" / "ra"
    domain_dir.mkdir(parents=True)
    (domain_dir / "authority_levels.yaml").write_text(yaml.dump({
        "levels": {
            "regulation": {"rank": 1, "label": "규약"},
            "guideline": {"rank": 2, "label": "지침"},
            "sop": {"rank": 3, "label": "SOP"},
        }
    }))
    # staging/
    (tmp_path / "staging").mkdir()
    return tmp_path


@pytest.fixture
def mock_drive_files():
    """Sample DriveFile list."""
    return [
        DriveFile(
            file_id="gd_file_1",
            name="공정경쟁규약.pdf",
            mime_type="application/pdf",
            modified_time="2026-03-01T00:00:00Z",
        ),
    ]


# -- TestFolderUrlParsing ----------------------------------------------------


class TestFolderUrlParsing:
    """parse_folder_url() extracts folder ID from various URL formats."""

    def test_standard_url(self):
        url = "https://drive.google.com/drive/folders/1ABCdef_ghiJKLmnop"
        assert parse_folder_url(url) == "1ABCdef_ghiJKLmnop"

    def test_url_with_query_params(self):
        url = "https://drive.google.com/drive/folders/1ABC?resourcekey=0-xyz"
        assert parse_folder_url(url) == "1ABC"

    def test_url_with_user_prefix(self):
        url = "https://drive.google.com/drive/u/0/folders/1ABC_DEF-ghi"
        assert parse_folder_url(url) == "1ABC_DEF-ghi"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Cannot extract folder ID"):
            parse_folder_url("https://drive.google.com/file/d/1ABC/view")

    def test_non_drive_url_raises(self):
        with pytest.raises(ValueError, match="Cannot extract folder ID"):
            parse_folder_url("https://example.com/folder/123")


# -- TestConfigBatch ---------------------------------------------------------


class TestConfigBatch:
    """load_sync_config() validation."""

    def test_valid_config(self, tmp_path):
        config = {
            "folders": [
                {
                    "folder_id": "1ABC",
                    "doc_id": "test-doc",
                    "version": "1.0",
                }
            ]
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config))

        result = load_sync_config(config_path)
        assert len(result["folders"]) == 1
        assert result["folders"][0]["doc_id"] == "test-doc"

    def test_missing_folders_key(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("documents: []")

        with pytest.raises(ValueError, match="'folders' key"):
            load_sync_config(config_path)

    def test_missing_required_field(self, tmp_path):
        config = {
            "folders": [
                {"folder_id": "1ABC", "doc_id": "test"}
                # missing 'version'
            ]
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config))

        with pytest.raises(ValueError, match="version"):
            load_sync_config(config_path)

    def test_empty_folders_list(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("folders: []")

        with pytest.raises(ValueError, match="empty"):
            load_sync_config(config_path)

    def test_nonexistent_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_sync_config(tmp_path / "nonexistent.yaml")

    def test_config_with_optional_fields(self, tmp_path):
        config = {
            "folders": [
                {
                    "folder_id": "1ABC",
                    "doc_id": "new-doc",
                    "version": "2025.01",
                    "domain": "ra",
                    "export_format": "md",
                    "authority_level": "regulation",
                    "publisher": "식약처",
                    "title": "의료기기 가이드라인",
                }
            ]
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config))

        result = load_sync_config(config_path)
        entry = result["folders"][0]
        assert entry["publisher"] == "식약처"
        assert entry["export_format"] == "md"


# -- TestGDriveSyncE2E -------------------------------------------------------


class TestGDriveSyncE2E:
    """End-to-end: mock GDrive → real pipeline env."""

    @patch("gdrive_sync.sync_folder")
    @patch("gdrive_sync.list_folder")
    @patch("gdrive_sync.run_pipeline", None)
    def test_download_only(self, mock_list, mock_sync, pipeline_env, mock_drive_files):
        """--download-only skips pipeline, returns empty results."""
        mock_list.return_value = mock_drive_files
        dest = pipeline_env / "staging"
        local_path = dest / "공정경쟁규약.pdf"
        local_path.write_bytes(b"fake pdf")
        mock_sync.return_value = [(mock_drive_files[0], local_path)]

        results = run_sync(
            folder_id="folder123",
            doc_id="test-doc",
            version="1.0",
            root=pipeline_env,
            download_only=True,
            service=MagicMock(),
        )
        assert results == []

    @patch("gdrive_sync.sync_folder")
    @patch("gdrive_sync.list_folder")
    def test_dry_run_no_download(self, mock_list, mock_sync, pipeline_env, mock_drive_files):
        """--dry-run lists files but doesn't download."""
        mock_list.return_value = mock_drive_files

        results = run_sync(
            folder_id="folder123",
            doc_id="test-doc",
            version="1.0",
            root=pipeline_env,
            dry_run=True,
            service=MagicMock(),
        )
        assert results == []
        mock_sync.assert_not_called()

    @patch("gdrive_sync.sync_folder")
    @patch("gdrive_sync.list_folder")
    @patch("gdrive_sync.run_pipeline")
    def test_sync_runs_pipeline(self, mock_pipeline, mock_list, mock_sync,
                                pipeline_env, mock_drive_files):
        """Normal sync calls run_pipeline for each downloaded file."""
        mock_list.return_value = mock_drive_files
        dest = pipeline_env / "staging"
        local_path = dest / "공정경쟁규약.pdf"
        local_path.write_bytes(b"fake pdf")
        mock_sync.return_value = [(mock_drive_files[0], local_path)]

        mock_pipeline.return_value = {
            "source": "테스트 문서 v1.0",
            "rule_candidates": 5,
            "files_created": 5,
            "doc_id": "test-doc",
        }

        results = run_sync(
            folder_id="folder123",
            doc_id="test-doc",
            version="1.0",
            root=pipeline_env,
            service=MagicMock(),
        )
        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["rule_candidates"] == 5

    @patch("gdrive_sync.sync_folder")
    @patch("gdrive_sync.list_folder")
    @patch("gdrive_sync.run_pipeline")
    def test_pipeline_error_continues(self, mock_pipeline, mock_list, mock_sync,
                                      pipeline_env, mock_drive_files):
        """Pipeline error for one file doesn't stop processing."""
        # Two files, first fails
        file2 = DriveFile(
            file_id="gd_file_2", name="지침.pdf",
            mime_type="application/pdf", modified_time="2026-03-01T00:00:00Z",
        )
        mock_list.return_value = mock_drive_files + [file2]

        dest = pipeline_env / "staging"
        path1 = dest / "공정경쟁규약.pdf"
        path2 = dest / "지침.pdf"
        path1.write_bytes(b"fake")
        path2.write_bytes(b"fake")
        mock_sync.return_value = [
            (mock_drive_files[0], path1),
            (file2, path2),
        ]

        mock_pipeline.side_effect = [
            ValueError("Parse error"),
            {"source": "지침 v1.0", "rule_candidates": 3,
             "files_created": 3, "doc_id": "test-doc"},
        ]

        results = run_sync(
            folder_id="folder123",
            doc_id="test-doc",
            version="1.0",
            root=pipeline_env,
            service=MagicMock(),
        )
        assert len(results) == 2
        assert results[0]["success"] is False
        assert "Parse error" in results[0]["error"]
        assert results[1]["success"] is True

    @patch("gdrive_sync.sync_folder")
    @patch("gdrive_sync.list_folder")
    @patch("gdrive_sync.run_pipeline")
    def test_auto_register_new_source(self, mock_pipeline, mock_list, mock_sync,
                                      pipeline_env):
        """Unregistered doc_id triggers auto-registration with confirm."""
        new_file = DriveFile(
            file_id="gd_new", name="새규정.pdf",
            mime_type="application/pdf", modified_time="2026-03-01T00:00:00Z",
        )
        mock_list.return_value = [new_file]
        dest = pipeline_env / "staging"
        local_path = dest / "새규정.pdf"
        local_path.write_bytes(b"fake")
        mock_sync.return_value = [(new_file, local_path)]

        mock_pipeline.return_value = {
            "source": "새규정 v1.0",
            "rule_candidates": 1,
            "files_created": 1,
            "doc_id": "new-doc",
        }

        results = run_sync(
            folder_id="folder123",
            doc_id="new-doc",
            version="1.0",
            root=pipeline_env,
            domain="ra",
            service=MagicMock(),
            confirm_fn=lambda: True,  # Auto-confirm registration
        )
        assert len(results) == 1
        assert results[0]["success"] is True

        # Verify source was registered
        sources = yaml.safe_load(
            (pipeline_env / "sources" / "_sources.yaml").read_text()
        )
        assert "new-doc" in sources["sources"]

    @patch("gdrive_sync.sync_folder")
    @patch("gdrive_sync.list_folder")
    @patch("gdrive_sync.run_pipeline")
    def test_provenance_recorded(self, mock_pipeline, mock_list, mock_sync,
                                 pipeline_env, mock_drive_files):
        """GDrive file_id recorded in _sources.yaml notes."""
        mock_list.return_value = mock_drive_files
        dest = pipeline_env / "staging"
        local_path = dest / "공정경쟁규약.pdf"
        local_path.write_bytes(b"fake pdf")
        mock_sync.return_value = [(mock_drive_files[0], local_path)]

        mock_pipeline.return_value = {
            "source": "테스트 v1.0",
            "rule_candidates": 1,
            "files_created": 1,
            "doc_id": "test-doc",
        }

        run_sync(
            folder_id="folder123",
            doc_id="test-doc",
            version="1.0",
            root=pipeline_env,
            service=MagicMock(),
        )

        sources = yaml.safe_load(
            (pipeline_env / "sources" / "_sources.yaml").read_text()
        )
        notes = sources["sources"]["test-doc"]["notes"]
        assert "gdrive_file_id: gd_file_1" in notes


# -- TestFormatSyncSummary ---------------------------------------------------


class TestFormatSyncSummary:
    """format_sync_summary() output."""

    def test_success_format(self):
        results = [{
            "success": True,
            "gdrive_file": "규약.pdf",
            "doc_id": "test",
            "rule_candidates": 5,
            "files_created": 5,
        }]
        output = format_sync_summary(results)
        assert "Succeeded: 1" in output
        assert "규약.pdf" in output
        assert "gate1.py" in output

    def test_failure_format(self):
        results = [{
            "success": False,
            "gdrive_file": "broken.pdf",
            "doc_id": "test",
            "error": "Parse failed",
        }]
        output = format_sync_summary(results)
        assert "Failed: 1" in output
        assert "Parse failed" in output

    def test_mixed_results(self):
        results = [
            {"success": True, "gdrive_file": "a.pdf", "doc_id": "d1",
             "rule_candidates": 3, "files_created": 3},
            {"success": False, "gdrive_file": "b.pdf", "doc_id": "d2",
             "error": "error"},
        ]
        output = format_sync_summary(results)
        assert "Succeeded: 1" in output
        assert "Failed: 1" in output
        assert "Total files processed: 2" in output
