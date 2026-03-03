"""Batch ingestion config loader and runner.

Supports processing multiple documents from a single YAML config file.
Each document entry runs through the standard ingestion pipeline.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Module-level reference to run_pipeline — resolved lazily at runtime.
# Tests patch this via @patch("ingest.batch.run_pipeline").
run_pipeline = None


def _resolve_run_pipeline():
    """Lazy-resolve run_pipeline from the sibling CLI module (scripts/ingest.py).

    The CLI module shares its name with this package, so standard import fails.
    Uses importlib to load the specific file.
    """
    global run_pipeline
    if run_pipeline is not None:
        return run_pipeline

    cli_path = Path(__file__).resolve().parent.parent / "ingest.py"
    if not cli_path.exists():
        raise ImportError(f"Cannot find CLI module: {cli_path}")

    spec = importlib.util.spec_from_file_location("_ingest_cli", cli_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load CLI module: {cli_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    run_pipeline = mod.run_pipeline
    return run_pipeline


def load_batch_config(config_path: Path) -> dict:
    """Parse ingest-config.yaml and validate required fields.

    Expected format:
        documents:
          - file: "docs/file.pdf"
            doc_id: "doc-id"
            version: "2025.01"
            domain: ra               # optional
            supersedes_version: "2022.04"  # optional

    Returns:
        Parsed config dict with 'documents' key.

    Raises:
        FileNotFoundError: config file does not exist.
        ValueError: missing required fields or invalid structure.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "documents" not in data:
        raise ValueError("Config must have a 'documents' key at top level")

    documents = data["documents"]
    if not isinstance(documents, list):
        raise ValueError("'documents' must be a list")

    if len(documents) == 0:
        raise ValueError("'documents' list is empty")

    required_fields = ("file", "doc_id", "version")
    for i, doc in enumerate(documents):
        if not isinstance(doc, dict):
            raise ValueError(f"Document entry {i} must be a mapping")
        missing = [f for f in required_fields if f not in doc]
        if missing:
            raise ValueError(
                f"Document entry {i} (doc_id={doc.get('doc_id', '?')}) "
                f"missing required fields: {', '.join(missing)}"
            )

    return data


def run_batch(
    config_path: Path,
    root: Path,
    dry_run: bool = False,
    force: bool = False,
) -> list[dict]:
    """Run ingestion pipeline for each document in config.

    For each document entry:
    1. If supersedes_version is set, attempt version_update() (if available).
    2. Call run_pipeline(file, doc_id, version, domain, dry_run, force, root).
    3. Collect results.

    Continues on individual document errors (logs and skips).

    Returns:
        List of summary dicts, one per document entry.
    """
    pipeline_fn = run_pipeline or _resolve_run_pipeline()

    config = load_batch_config(config_path)
    documents = config["documents"]

    # version_update is available as ingest.version.version_update
    version_update_fn = None
    try:
        from ingest.version import version_update as _vu
        version_update_fn = _vu
    except ImportError:
        pass

    results: list[dict] = []
    for doc in documents:
        doc_id = doc["doc_id"]
        version = doc["version"]
        file_path = doc["file"]
        domain = doc.get("domain")
        supersedes_version = doc.get("supersedes_version")

        try:
            # Step 1: Handle version supersession if requested
            if supersedes_version and version_update_fn is not None:
                logger.info(
                    "Running version_update for %s: %s → %s",
                    doc_id, supersedes_version, version,
                )
                version_update_fn(
                    doc_id=doc_id,
                    new_version=version,
                    old_version=supersedes_version,
                    file_path=file_path,
                    root=root,
                )

            # Step 2: Run pipeline
            summary = pipeline_fn(
                file_path=file_path,
                doc_id=doc_id,
                version=version,
                domain=domain,
                dry_run=dry_run,
                force=force,
                root=root,
            )
            summary["success"] = True
            results.append(summary)

        except Exception as e:
            logger.error("Failed to process %s: %s", doc_id, e)
            results.append({
                "doc_id": doc_id,
                "success": False,
                "error": str(e),
            })

    return results


def format_batch_summary(results: list[dict]) -> str:
    """Format batch results as a human-readable summary.

    Args:
        results: list of summary dicts from run_batch().

    Returns:
        Formatted summary string.
    """
    total = len(results)
    succeeded = sum(1 for r in results if r.get("success"))
    failed = total - succeeded

    lines = [
        "=== Batch Ingestion Summary ===",
        f"  Total: {total} documents",
        f"  Succeeded: {succeeded}",
        f"  Failed: {failed}",
        "",
    ]

    for i, result in enumerate(results, 1):
        doc_id = result.get("doc_id", "unknown")
        if result.get("success"):
            source = result.get("source", "?")
            candidates = result.get("rule_candidates", 0)
            files_created = result.get("files_created", 0)
            lines.append(f"  [{i}] {doc_id}: OK — {candidates} candidates, {files_created} files created")
            lines.append(f"      Source: {source}")
        else:
            error = result.get("error", "unknown error")
            lines.append(f"  [{i}] {doc_id}: FAILED — {error}")

    if succeeded > 0:
        lines.append("")
        lines.append("Next step: python3 scripts/gate1.py --apply")

    return "\n".join(lines)
