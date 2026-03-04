"""CLI entrypoint for Google Drive → Ingestion Pipeline sync.

Downloads files from a Google Drive folder into local staging,
then feeds them through the existing ingestion pipeline.

Usage:
  # First-time authentication
  python3 scripts/gdrive_sync.py --auth-only

  # Sync folder and run pipeline
  python3 scripts/gdrive_sync.py \\
    --folder-url "https://drive.google.com/drive/folders/1ABC..." \\
    --doc-id "kmdia-fc" --version "2024.01"

  # Download only (no pipeline, for inspection)
  python3 scripts/gdrive_sync.py \\
    --folder-id "1ABC..." --download-only --dest staging/

  # Batch mode from config
  python3 scripts/gdrive_sync.py --config config/gdrive-sync.yaml
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import re
import sys
from pathlib import Path

import yaml

from connector.gdrive import (
    authenticate,
    list_folder,
    sync_folder,
    DriveFile,
)
from ingest.registry import (
    UserAbortError,
    load_sources_registry,
    register_new_source,
)

logger = logging.getLogger(__name__)

# Default paths relative to project root
_DEFAULT_CREDENTIALS = Path("config/gdrive-credentials.json")
_DEFAULT_TOKEN = Path("config/gdrive-token.json")
_DEFAULT_STAGING = Path("staging")

# Folder URL regex: extract folder ID from Google Drive URL
_FOLDER_URL_RE = re.compile(
    r"https?://drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)"
)

# Module-level reference to run_pipeline — resolved lazily.
run_pipeline = None


def _resolve_run_pipeline():
    """Lazy-resolve run_pipeline from scripts/ingest.py (same as batch.py pattern)."""
    global run_pipeline
    if run_pipeline is not None:
        return run_pipeline

    cli_path = Path(__file__).resolve().parent / "ingest.py"
    if not cli_path.exists():
        raise ImportError(f"Cannot find CLI module: {cli_path}")

    spec = importlib.util.spec_from_file_location("_ingest_cli", cli_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load CLI module: {cli_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    run_pipeline = mod.run_pipeline
    return run_pipeline


def parse_folder_url(url: str) -> str:
    """Extract folder ID from a Google Drive folder URL.

    Supports:
      https://drive.google.com/drive/folders/1ABC...
      https://drive.google.com/drive/u/0/folders/1ABC...?resourcekey=...

    Args:
        url: Google Drive folder URL.

    Returns:
        Folder ID string.

    Raises:
        ValueError: URL format not recognized.
    """
    match = _FOLDER_URL_RE.search(url)
    if not match:
        raise ValueError(
            f"Cannot extract folder ID from URL: {url}\n"
            "Expected format: https://drive.google.com/drive/folders/<FOLDER_ID>"
        )
    return match.group(1)


def load_sync_config(config_path: Path) -> dict:
    """Parse gdrive-sync.yaml and validate required fields.

    Expected format:
        folders:
          - folder_id: "1ABC..."
            doc_id: "kmdia-fc"
            version: "2024.01"
            domain: ra               # optional
            export_format: pdf        # optional
            # Auto-register fields (used if doc_id not in _sources.yaml):
            authority_level: regulation  # optional
            publisher: "..."            # optional
            title: "..."               # optional

    Returns:
        Parsed config dict.

    Raises:
        FileNotFoundError: config file not found.
        ValueError: invalid structure or missing required fields.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "folders" not in data:
        raise ValueError("Config must have a 'folders' key at top level")

    folders = data["folders"]
    if not isinstance(folders, list):
        raise ValueError("'folders' must be a list")

    if len(folders) == 0:
        raise ValueError("'folders' list is empty")

    required_fields = ("folder_id", "doc_id", "version")
    for i, entry in enumerate(folders):
        if not isinstance(entry, dict):
            raise ValueError(f"Folder entry {i} must be a mapping")
        missing = [f for f in required_fields if f not in entry]
        if missing:
            raise ValueError(
                f"Folder entry {i} (doc_id={entry.get('doc_id', '?')}) "
                f"missing required fields: {', '.join(missing)}"
            )

    return data


def _format_file_list(files: list[DriveFile]) -> str:
    """Format file list for display."""
    lines = []
    for i, f in enumerate(files, 1):
        ftype = "Google Doc" if f.is_google_doc else "PDF"
        lines.append(f"  [{i}] {f.name} ({ftype}, {f.modified_time})")
    return "\n".join(lines)


def _auto_register_source(
    doc_id: str,
    file_path: str,
    version: str,
    root: Path,
    domain: str | None,
    drive_file: DriveFile,
    config_entry: dict | None = None,
    confirm_fn=None,
) -> None:
    """Register a new source if doc_id not in _sources.yaml.

    Uses metadata from config entry or Drive file name as fallback.
    """
    data = load_sources_registry(root)
    sources = data.get("sources", {})
    if doc_id in sources:
        return  # Already registered

    # Resolve domain for registration
    resolved_domain = domain
    if resolved_domain is None:
        domain_path = root / "rules" / "_domain.yaml"
        with open(domain_path) as f:
            resolved_domain = yaml.safe_load(f).get("domain", "ra")

    # Get registration metadata from config or defaults
    title = (config_entry or {}).get("title", drive_file.name)
    authority_level = (config_entry or {}).get("authority_level", "guideline")
    publisher = (config_entry or {}).get("publisher", "")
    notes = f"gdrive_file_id: {drive_file.file_id}"

    print(f"\nNew source detected: {doc_id}")
    register_new_source(
        doc_id=doc_id,
        title=title,
        version=version,
        authority_level=authority_level,
        file_path=file_path,
        publisher=publisher,
        notes=notes,
        domain=resolved_domain,
        root=root,
        confirm_fn=confirm_fn,
    )


def _update_source_notes_with_provenance(
    doc_id: str,
    drive_file: DriveFile,
    root: Path,
) -> None:
    """Append GDrive file_id to source notes if not already present."""
    from ingest.registry import load_sources_registry, save_sources_registry

    data = load_sources_registry(root)
    sources = data.get("sources", {})
    entry = sources.get(doc_id)
    if not entry:
        return

    notes = entry.get("notes", "")
    marker = f"gdrive_file_id: {drive_file.file_id}"
    if marker not in notes:
        sep = ", " if notes else ""
        entry["notes"] = notes + sep + marker
        save_sources_registry(data, root)


def run_sync(
    folder_id: str,
    doc_id: str,
    version: str,
    root: Path,
    domain: str | None = None,
    export_format: str = "pdf",
    dest_dir: Path | None = None,
    download_only: bool = False,
    dry_run: bool = False,
    force: bool = False,
    credentials_path: Path | None = None,
    token_path: Path | None = None,
    confirm_fn=None,
    service=None,
) -> list[dict]:
    """Sync a Google Drive folder and run ingestion pipeline.

    Args:
        folder_id: Google Drive folder ID.
        doc_id: document identifier for the pipeline.
        version: document version string.
        root: project root directory.
        domain: override domain (defaults to rules/_domain.yaml).
        export_format: "pdf" or "md".
        dest_dir: local staging directory.
        download_only: if True, skip pipeline.
        dry_run: if True, skip YAML writing.
        force: re-download + overwrite.
        credentials_path: OAuth credentials file.
        token_path: OAuth token cache file.
        confirm_fn: callable for source registration confirm (testing).
        service: pre-built Drive API service (testing).

    Returns:
        List of pipeline result dicts.
    """
    if dest_dir is None:
        dest_dir = root / _DEFAULT_STAGING
    if credentials_path is None:
        credentials_path = root / _DEFAULT_CREDENTIALS
    if token_path is None:
        token_path = root / _DEFAULT_TOKEN

    # Step 1: Authenticate (or use injected service)
    if service is None:
        service = authenticate(credentials_path, token_path)

    # Step 2: List files
    drive_files = list_folder(service, folder_id)
    print(f"\nFound {len(drive_files)} files in folder:")
    print(_format_file_list(drive_files))

    if dry_run:
        print("\n[DRY RUN] Would download and process the above files.")
        return []

    # Step 3: Sync (download changed files)
    downloaded = sync_folder(
        service, folder_id, dest_dir,
        export_format=export_format, force=force,
    )
    print(f"\nDownloaded {len(downloaded)} files to {dest_dir}/")

    if download_only:
        for df, path in downloaded:
            print(f"  {df.name} → {path}")
        return []

    # Step 4: Run pipeline on each downloaded file
    pipeline_fn = run_pipeline or _resolve_run_pipeline()

    # Resolve domain
    if domain is None:
        domain_path = root / "rules" / "_domain.yaml"
        with open(domain_path) as f:
            domain = yaml.safe_load(f).get("domain", "ra")

    results: list[dict] = []
    for drive_file, local_path in downloaded:
        try:
            # Auto-register source if needed
            _auto_register_source(
                doc_id=doc_id,
                file_path=str(local_path),
                version=version,
                root=root,
                domain=domain,
                drive_file=drive_file,
                confirm_fn=confirm_fn,
            )

            # Record provenance
            _update_source_notes_with_provenance(doc_id, drive_file, root)

            # Run pipeline
            summary = pipeline_fn(
                file_path=str(local_path),
                doc_id=doc_id,
                version=version,
                domain=domain,
                dry_run=False,
                force=force,
                root=root,
            )
            summary["success"] = True
            summary["gdrive_file"] = drive_file.name
            results.append(summary)

        except Exception as e:
            logger.error("Failed to process %s: %s", drive_file.name, e)
            results.append({
                "doc_id": doc_id,
                "success": False,
                "error": str(e),
                "gdrive_file": drive_file.name,
            })

    return results


def format_sync_summary(results: list[dict]) -> str:
    """Format sync results as human-readable summary.

    Reuses the batch.py format_batch_summary pattern.
    """
    total = len(results)
    succeeded = sum(1 for r in results if r.get("success"))
    failed = total - succeeded

    lines = [
        "=== GDrive Sync Summary ===",
        f"  Total files processed: {total}",
        f"  Succeeded: {succeeded}",
        f"  Failed: {failed}",
        "",
    ]

    for i, result in enumerate(results, 1):
        gdrive_name = result.get("gdrive_file", "unknown")
        doc_id = result.get("doc_id", "unknown")
        if result.get("success"):
            candidates = result.get("rule_candidates", 0)
            files_created = result.get("files_created", 0)
            lines.append(
                f"  [{i}] {gdrive_name} → {doc_id}: "
                f"OK — {candidates} candidates, {files_created} files created"
            )
        else:
            error = result.get("error", "unknown error")
            lines.append(f"  [{i}] {gdrive_name}: FAILED — {error}")

    if succeeded > 0:
        lines.append("")
        lines.append("Next step: python3 scripts/gate1.py --apply")

    return "\n".join(lines)


def main() -> None:
    """CLI entrypoint with argparse."""
    parser = argparse.ArgumentParser(
        description="Sync Google Drive folder to local staging and run ingestion pipeline.",
    )

    # Source selection (mutually exclusive group)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--folder-url", help="Google Drive folder URL")
    source.add_argument("--folder-id", help="Google Drive folder ID")
    source.add_argument("--config", help="Batch config YAML file (gdrive-sync.yaml)")

    # Pipeline parameters
    parser.add_argument("--doc-id", help="Document ID (for _sources.yaml)")
    parser.add_argument("--version", help="Document version")
    parser.add_argument("--domain", default=None, help="Override domain")

    # Behavior options
    parser.add_argument("--auth-only", action="store_true", help="Only authenticate (no sync)")
    parser.add_argument("--download-only", action="store_true", help="Download without running pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Preview without downloading or writing")
    parser.add_argument("--force", action="store_true", help="Re-download + overwrite existing")

    # Export and paths
    parser.add_argument("--export-format", default="pdf", choices=["pdf", "md"],
                        help="Export format for Google Docs (default: pdf)")
    parser.add_argument("--dest", default=None, help="Staging directory (default: staging/)")
    parser.add_argument("--credentials", default=None, help="OAuth credentials JSON path")
    parser.add_argument("--token", default=None, help="OAuth token cache path")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    root = Path(__file__).resolve().parent.parent

    credentials_path = Path(args.credentials) if args.credentials else root / _DEFAULT_CREDENTIALS
    token_path = Path(args.token) if args.token else root / _DEFAULT_TOKEN

    # Mode: --auth-only
    if args.auth_only:
        try:
            authenticate(credentials_path, token_path)
            print("Authentication successful. Token saved.")
        except Exception as e:
            print(f"Authentication failed: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Mode: --config (batch)
    if args.config:
        try:
            config = load_sync_config(Path(args.config))
        except (ValueError, FileNotFoundError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        service = authenticate(credentials_path, token_path)
        all_results: list[dict] = []

        for entry in config["folders"]:
            fid = entry["folder_id"]
            did = entry["doc_id"]
            ver = entry["version"]
            dom = entry.get("domain", args.domain)
            efmt = entry.get("export_format", args.export_format)

            print(f"\n--- Syncing: {did} (folder: {fid[:12]}...) ---")
            results = run_sync(
                folder_id=fid,
                doc_id=did,
                version=ver,
                root=root,
                domain=dom,
                export_format=efmt,
                download_only=args.download_only,
                dry_run=args.dry_run,
                force=args.force,
                service=service,
            )
            all_results.extend(results)

        if not args.download_only:
            print("\n" + format_sync_summary(all_results))
        return

    # Mode: single folder sync
    folder_id = None
    if args.folder_url:
        try:
            folder_id = parse_folder_url(args.folder_url)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.folder_id:
        folder_id = args.folder_id

    if not folder_id:
        parser.error("One of --folder-url, --folder-id, or --config is required")

    if not args.download_only:
        if not args.doc_id:
            parser.error("--doc-id is required (unless --download-only)")
        if not args.version:
            parser.error("--version is required (unless --download-only)")

    dest_dir = Path(args.dest) if args.dest else None

    try:
        results = run_sync(
            folder_id=folder_id,
            doc_id=args.doc_id or "",
            version=args.version or "",
            root=root,
            domain=args.domain,
            export_format=args.export_format,
            dest_dir=dest_dir,
            download_only=args.download_only,
            dry_run=args.dry_run,
            force=args.force,
            credentials_path=credentials_path,
            token_path=token_path,
        )
    except (ImportError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except UserAbortError as e:
        print(f"Aborted: {e}", file=sys.stderr)
        sys.exit(1)

    if results:
        print("\n" + format_sync_summary(results))


if __name__ == "__main__":
    main()
