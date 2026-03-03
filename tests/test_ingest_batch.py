"""Tests for batch ingestion config (ingest/batch.py).

All tests use tmp_path for isolation — no production data touched.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ingest.batch import format_batch_summary, load_batch_config, run_batch


# -- Helpers -----------------------------------------------------------------


def _write_config(path: Path, data: dict) -> Path:
    """Write a YAML config file and return its path."""
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _make_sources_yaml(root: Path) -> None:
    """Set up minimal sources/_sources.yaml for pipeline validation."""
    sources_dir = root / "sources"
    sources_dir.mkdir(exist_ok=True)
    (sources_dir / "_sources.yaml").write_text(yaml.dump({
        "sources": {
            "doc-a": {
                "title": "문서 A",
                "versions": [{"version": "1.0", "file": "a.pdf"}],
                "publisher": "테스트",
                "authority_level": "regulation",
                "notes": "",
            },
            "doc-b": {
                "title": "문서 B",
                "versions": [{"version": "1.0", "file": "b.pdf"}],
                "publisher": "테스트",
                "authority_level": "sop",
                "notes": "",
            },
        }
    }, allow_unicode=True), encoding="utf-8")


def _make_domain_yaml(root: Path) -> None:
    """Set up rules/_domain.yaml for default domain resolution."""
    rules_dir = root / "rules"
    rules_dir.mkdir(exist_ok=True)
    (rules_dir / "_domain.yaml").write_text(
        yaml.dump({"domain": "ra"}), encoding="utf-8",
    )


@pytest.fixture
def batch_env(tmp_path):
    """Minimal environment for batch ingestion tests."""
    _make_sources_yaml(tmp_path)
    _make_domain_yaml(tmp_path)
    return tmp_path


# -- Test: load_batch_config ------------------------------------------------


class TestLoadBatchConfig:
    """Config YAML parsing and validation."""

    def test_valid_config(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {
            "documents": [
                {"file": "a.pdf", "doc_id": "doc-a", "version": "1.0"},
                {"file": "b.pdf", "doc_id": "doc-b", "version": "2.0"},
            ]
        })
        result = load_batch_config(config)
        assert "documents" in result
        assert len(result["documents"]) == 2

    def test_config_with_optional_fields(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {
            "documents": [
                {
                    "file": "a.pdf",
                    "doc_id": "doc-a",
                    "version": "2025.01",
                    "domain": "ra",
                    "supersedes_version": "2022.04",
                },
            ]
        })
        result = load_batch_config(config)
        doc = result["documents"][0]
        assert doc["domain"] == "ra"
        assert doc["supersedes_version"] == "2022.04"

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_batch_config(tmp_path / "nonexistent.yaml")

    def test_missing_documents_key(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {"other": []})
        with pytest.raises(ValueError, match="'documents' key"):
            load_batch_config(config)

    def test_documents_not_a_list(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {"documents": "bad"})
        with pytest.raises(ValueError, match="must be a list"):
            load_batch_config(config)

    def test_empty_documents_list(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {"documents": []})
        with pytest.raises(ValueError, match="empty"):
            load_batch_config(config)

    def test_missing_required_field_file(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {
            "documents": [{"doc_id": "x", "version": "1.0"}]
        })
        with pytest.raises(ValueError, match="missing required fields.*file"):
            load_batch_config(config)

    def test_missing_required_field_doc_id(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {
            "documents": [{"file": "x.pdf", "version": "1.0"}]
        })
        with pytest.raises(ValueError, match="missing required fields.*doc_id"):
            load_batch_config(config)

    def test_missing_required_field_version(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {
            "documents": [{"file": "x.pdf", "doc_id": "x"}]
        })
        with pytest.raises(ValueError, match="missing required fields.*version"):
            load_batch_config(config)

    def test_missing_multiple_required_fields(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {
            "documents": [{"file": "x.pdf"}]
        })
        with pytest.raises(ValueError, match="missing required fields"):
            load_batch_config(config)

    def test_entry_not_a_mapping(self, tmp_path):
        config = _write_config(tmp_path / "config.yaml", {
            "documents": ["just a string"]
        })
        with pytest.raises(ValueError, match="must be a mapping"):
            load_batch_config(config)

    def test_non_dict_top_level(self, tmp_path):
        """Config file with non-dict top level (e.g. a list)."""
        config = tmp_path / "config.yaml"
        config.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="'documents' key"):
            load_batch_config(config)


# -- Test: run_batch --------------------------------------------------------


class TestRunBatch:
    """Batch execution with mocked pipeline."""

    def _make_config(self, tmp_path, documents):
        """Write a batch config and return its path."""
        return _write_config(tmp_path / "config.yaml", {"documents": documents})

    @patch("ingest.batch.run_pipeline")
    def test_single_document(self, mock_pipeline, batch_env):
        mock_pipeline.return_value = {
            "source": "문서 A v1.0",
            "parser": "PdfParser",
            "sections_found": 5,
            "rule_candidates": 3,
            "deterministic_count": 2,
            "llm_count": 1,
            "files_created": 3,
            "status": "all draft",
            "doc_id": "doc-a",
        }

        config = self._make_config(batch_env, [
            {"file": "a.pdf", "doc_id": "doc-a", "version": "1.0"},
        ])

        results = run_batch(config, root=batch_env)

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["doc_id"] == "doc-a"
        mock_pipeline.assert_called_once_with(
            file_path="a.pdf",
            doc_id="doc-a",
            version="1.0",
            domain=None,
            dry_run=False,
            force=False,
            root=batch_env,
        )

    @patch("ingest.batch.run_pipeline")
    def test_multiple_documents(self, mock_pipeline, batch_env):
        def side_effect(**kwargs):
            return {
                "source": f"{kwargs['doc_id']} v{kwargs['version']}",
                "rule_candidates": 2,
                "files_created": 2,
                "doc_id": kwargs["doc_id"],
            }
        mock_pipeline.side_effect = side_effect

        config = self._make_config(batch_env, [
            {"file": "a.pdf", "doc_id": "doc-a", "version": "1.0"},
            {"file": "b.pdf", "doc_id": "doc-b", "version": "1.0", "domain": "ra"},
        ])

        results = run_batch(config, root=batch_env)

        assert len(results) == 2
        assert all(r.get("success") for r in results)
        assert mock_pipeline.call_count == 2

        # Verify domain passthrough
        second_call = mock_pipeline.call_args_list[1]
        assert second_call.kwargs["domain"] == "ra"

    @patch("ingest.batch.run_pipeline")
    def test_error_in_one_does_not_stop_others(self, mock_pipeline, batch_env):
        """First doc fails, second doc succeeds — batch continues."""
        def side_effect(**kwargs):
            if kwargs["doc_id"] == "doc-a":
                raise ValueError("Parse error for doc-a")
            return {
                "source": "문서 B v1.0",
                "rule_candidates": 4,
                "files_created": 4,
                "doc_id": "doc-b",
            }
        mock_pipeline.side_effect = side_effect

        config = self._make_config(batch_env, [
            {"file": "a.pdf", "doc_id": "doc-a", "version": "1.0"},
            {"file": "b.pdf", "doc_id": "doc-b", "version": "1.0"},
        ])

        results = run_batch(config, root=batch_env)

        assert len(results) == 2
        assert results[0]["success"] is False
        assert "Parse error" in results[0]["error"]
        assert results[1]["success"] is True

    @patch("ingest.batch.run_pipeline")
    def test_dry_run_passthrough(self, mock_pipeline, batch_env):
        mock_pipeline.return_value = {
            "doc_id": "doc-a",
            "rule_candidates": 3,
            "files_created": 0,
        }

        config = self._make_config(batch_env, [
            {"file": "a.pdf", "doc_id": "doc-a", "version": "1.0"},
        ])

        run_batch(config, root=batch_env, dry_run=True)

        call_kwargs = mock_pipeline.call_args.kwargs
        assert call_kwargs["dry_run"] is True

    @patch("ingest.batch.run_pipeline")
    def test_force_passthrough(self, mock_pipeline, batch_env):
        mock_pipeline.return_value = {
            "doc_id": "doc-a",
            "rule_candidates": 3,
            "files_created": 3,
        }

        config = self._make_config(batch_env, [
            {"file": "a.pdf", "doc_id": "doc-a", "version": "1.0"},
        ])

        run_batch(config, root=batch_env, force=True)

        call_kwargs = mock_pipeline.call_args.kwargs
        assert call_kwargs["force"] is True

    @patch("ingest.batch.run_pipeline")
    def test_supersedes_version_with_version_update(self, mock_pipeline, batch_env):
        """When version_update module is available, it's called before pipeline."""
        mock_pipeline.return_value = {
            "doc_id": "doc-a",
            "rule_candidates": 2,
            "files_created": 2,
        }

        mock_vu = MagicMock()

        config = self._make_config(batch_env, [
            {
                "file": "a-v2.pdf",
                "doc_id": "doc-a",
                "version": "2.0",
                "supersedes_version": "1.0",
            },
        ])

        # Mock version_update import via ingest.version module
        with patch("ingest.version.version_update", mock_vu):
            results = run_batch(config, root=batch_env)

        assert len(results) == 1
        assert results[0]["success"] is True
        mock_vu.assert_called_once_with(
            doc_id="doc-a",
            new_version="2.0",
            old_version="1.0",
            file_path="a-v2.pdf",
            root=batch_env,
        )
        mock_pipeline.assert_called_once()

    @patch("ingest.batch.run_pipeline")
    def test_supersedes_version_without_version_update_module(self, mock_pipeline, batch_env):
        """When version_update is not available, pipeline still runs without error."""
        mock_pipeline.return_value = {
            "doc_id": "doc-a",
            "rule_candidates": 2,
            "files_created": 2,
        }

        config = self._make_config(batch_env, [
            {
                "file": "a-v2.pdf",
                "doc_id": "doc-a",
                "version": "2.0",
                "supersedes_version": "1.0",
            },
        ])

        # Simulate version_update not available by making import fail
        with patch.dict("sys.modules", {"ingest.version": None}):
            results = run_batch(config, root=batch_env)

        assert len(results) == 1
        assert results[0]["success"] is True
        mock_pipeline.assert_called_once()

    @patch("ingest.batch.run_pipeline")
    def test_all_documents_fail(self, mock_pipeline, batch_env):
        mock_pipeline.side_effect = RuntimeError("total failure")

        config = self._make_config(batch_env, [
            {"file": "a.pdf", "doc_id": "doc-a", "version": "1.0"},
            {"file": "b.pdf", "doc_id": "doc-b", "version": "1.0"},
        ])

        results = run_batch(config, root=batch_env)

        assert len(results) == 2
        assert all(not r["success"] for r in results)

    @patch("ingest.batch.run_pipeline")
    def test_domain_none_when_not_specified(self, mock_pipeline, batch_env):
        """Domain should be None when not specified in config entry."""
        mock_pipeline.return_value = {"doc_id": "doc-a", "rule_candidates": 1, "files_created": 1}

        config = self._make_config(batch_env, [
            {"file": "a.pdf", "doc_id": "doc-a", "version": "1.0"},
        ])

        run_batch(config, root=batch_env)
        assert mock_pipeline.call_args.kwargs["domain"] is None


# -- Test: format_batch_summary ---------------------------------------------


class TestFormatBatchSummary:
    """Human-readable summary formatting."""

    def test_all_succeeded(self):
        results = [
            {
                "doc_id": "doc-a",
                "success": True,
                "source": "문서 A v1.0",
                "rule_candidates": 3,
                "files_created": 3,
            },
            {
                "doc_id": "doc-b",
                "success": True,
                "source": "문서 B v2.0",
                "rule_candidates": 5,
                "files_created": 5,
            },
        ]
        summary = format_batch_summary(results)
        assert "Total: 2" in summary
        assert "Succeeded: 2" in summary
        assert "Failed: 0" in summary
        assert "doc-a: OK" in summary
        assert "doc-b: OK" in summary
        assert "gate1.py" in summary

    def test_mixed_results(self):
        results = [
            {
                "doc_id": "doc-a",
                "success": True,
                "source": "문서 A v1.0",
                "rule_candidates": 3,
                "files_created": 3,
            },
            {
                "doc_id": "doc-b",
                "success": False,
                "error": "File not found",
            },
        ]
        summary = format_batch_summary(results)
        assert "Succeeded: 1" in summary
        assert "Failed: 1" in summary
        assert "doc-a: OK" in summary
        assert "doc-b: FAILED" in summary
        assert "File not found" in summary

    def test_all_failed(self):
        results = [
            {"doc_id": "doc-x", "success": False, "error": "bad doc"},
        ]
        summary = format_batch_summary(results)
        assert "Succeeded: 0" in summary
        assert "Failed: 1" in summary
        # No "Next step" when all failed
        assert "gate1.py" not in summary

    def test_empty_results(self):
        summary = format_batch_summary([])
        assert "Total: 0" in summary
        assert "Succeeded: 0" in summary
