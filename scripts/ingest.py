"""CLI entrypoint for the ingestion pipeline.

Orchestrates: Parse → Split → Extract → Draft
Converts source documents (PDF/Markdown) into draft Rule Unit YAML files.

Phase 3 additions:
  --version-update: version change detection + suspended transition + migration guide
  --config: batch processing via ingest-config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from ingest.parse import get_parser
from ingest.split import split_document
from ingest.extract import extract_fields
from ingest.draft import write_all_drafts
from ingest.registry import (
    UserAbortError,
    register_new_source,
)
from ingest.version import version_update
from ingest.migration import generate_relation_migration_guide, format_migration_guide
from ingest.batch import load_batch_config, run_batch, format_batch_summary


def _load_sources(root: Path) -> dict:
    """Load sources/_sources.yaml and return the sources dict."""
    sources_path = root / "sources" / "_sources.yaml"
    with open(sources_path) as f:
        data = yaml.safe_load(f)
    return data.get("sources", {})


def _load_default_domain(root: Path) -> str:
    """Load default domain from rules/_domain.yaml."""
    domain_path = root / "rules" / "_domain.yaml"
    with open(domain_path) as f:
        data = yaml.safe_load(f)
    return data.get("domain", "ra")


def run_pipeline(
    file_path: str | Path,
    doc_id: str,
    version: str,
    domain: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    root: Path | None = None,
) -> dict:
    """Run the full ingestion pipeline: Parse → Split → Extract → Draft.

    Args:
        file_path: path to PDF or Markdown source file.
        doc_id: document identifier (must exist in _sources.yaml).
        version: document version string.
        domain: override domain (defaults to rules/_domain.yaml value).
        dry_run: if True, skip YAML writing.
        force: overwrite existing files.
        root: project root directory.

    Returns:
        Summary dict with pipeline results.
    """
    path = Path(file_path)
    if root is None:
        # scripts/ingest.py → scripts/ → project root
        root = Path(__file__).resolve().parent.parent

    # Validate doc_id exists in _sources.yaml
    sources = _load_sources(root)
    if doc_id not in sources:
        raise ValueError(
            f"Unknown doc_id: {doc_id!r} (not found in sources/_sources.yaml). "
            "Use --register-source to register a new source first."
        )

    source_title = sources[doc_id]["title"]

    # Resolve domain
    if domain is None:
        domain = _load_default_domain(root)

    # Phase 1: Parse
    parser = get_parser(path)
    parser_type = type(parser).__name__
    ir = parser.parse(path, doc_id, version)

    # Phase 2: Split
    candidates = split_document(ir)
    deterministic_count = sum(1 for c in candidates if c.split_method == "deterministic")
    llm_count = sum(1 for c in candidates if c.split_method == "llm")

    # Phase 3: Extract
    rules: list[dict] = []
    for candidate in candidates:
        fields = extract_fields(candidate, doc_id, version, domain=domain, root=root)
        fields["doc_id"] = doc_id
        fields["domain"] = domain
        rules.append(fields)

    # Phase 4: Draft
    files_created = 0
    if not dry_run:
        written = write_all_drafts(
            rules, doc_id, root, force=force, default_domain=domain,
        )
        files_created = len(written)

    return {
        "source": f"{source_title} v{version}",
        "parser": parser_type,
        "sections_found": len(ir.sections),
        "rule_candidates": len(candidates),
        "deterministic_count": deterministic_count,
        "llm_count": llm_count,
        "files_created": files_created,
        "status": "all draft",
        "doc_id": doc_id,
    }


def main() -> None:
    """CLI entrypoint with argparse."""
    parser = argparse.ArgumentParser(
        description="Ingest a source document into draft Rule Unit YAML files.",
    )
    parser.add_argument("--file", help="PDF or Markdown file path")
    parser.add_argument("--doc-id", help="Document ID (from _sources.yaml)")
    parser.add_argument("--version", help="Document version")
    parser.add_argument("--domain", default=None, help="Override domain (default: from _domain.yaml)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing YAML files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")

    # --register-source: register a new source document
    parser.add_argument(
        "--register-source", action="store_true",
        help="Register a new source document (requires --title, --authority-level, --publisher)",
    )
    parser.add_argument("--title", help="Document title (for --register-source)")
    parser.add_argument("--authority-level", help="Authority level (for --register-source)")
    parser.add_argument("--publisher", help="Publisher (for --register-source)")
    parser.add_argument("--notes", default="", help="Notes (for --register-source)")

    # --version-update: handle version change (Phase 3)
    parser.add_argument(
        "--version-update", action="store_true",
        help="Handle version change: suspend old rules, cascade relations, show migration guide",
    )
    parser.add_argument("--new-version", help="New version string (for --version-update)")
    parser.add_argument("--supersedes", help="Old version being superseded (for --version-update)")

    # --config: batch processing (Phase 3)
    parser.add_argument("--config", help="Batch config YAML file path (mutually exclusive with --file)")

    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent

    # Mode: --config (batch processing)
    if args.config:
        if args.file:
            parser.error("--config and --file are mutually exclusive")

        try:
            results = run_batch(
                config_path=Path(args.config),
                root=root,
                dry_run=args.dry_run,
                force=args.force,
            )
        except (ValueError, FileNotFoundError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(format_batch_summary(results))
        return

    # Mode: --register-source
    if args.register_source:
        if not args.file or not args.doc_id or not args.version:
            parser.error("--register-source requires --file, --doc-id, --version")

        missing = []
        for field in ("title", "authority_level", "publisher"):
            if not getattr(args, field):
                missing.append(f"--{field.replace('_', '-')}")
        if missing:
            parser.error(f"--register-source requires: {', '.join(missing)}")

        domain = args.domain
        if domain is None:
            domain = _load_default_domain(root)

        try:
            register_new_source(
                doc_id=args.doc_id,
                title=args.title,
                version=args.version,
                authority_level=args.authority_level,
                file_path=args.file,
                publisher=args.publisher,
                notes=args.notes,
                domain=domain,
                root=root,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except UserAbortError as e:
            print(f"Aborted: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"\nSource '{args.doc_id}' registered successfully.")
        return

    # Mode: --version-update
    if args.version_update:
        if not args.doc_id:
            parser.error("--version-update requires --doc-id")
        if not args.new_version:
            parser.error("--version-update requires --new-version")
        if not args.supersedes:
            parser.error("--version-update requires --supersedes")

        file_path = args.file or ""

        try:
            result = version_update(
                doc_id=args.doc_id,
                new_version=args.new_version,
                old_version=args.supersedes,
                file_path=file_path,
                root=root,
            )
        except (ValueError, FileNotFoundError, KeyError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"""Version Update Summary:
  Document: {result['doc_id']}
  Version change: {result['old_version']} → {result['new_version']}
  Rules found: {result['rules_found']}
  Rules suspended: {result['rules_suspended']}
  Relations cascaded: {result['relations_cascaded']}""")

        # Auto-generate migration guide
        guide = generate_relation_migration_guide(
            doc_id=args.doc_id,
            old_version=args.supersedes,
            new_version=args.new_version,
            root=root,
        )
        print()
        print(format_migration_guide(guide))
        return

    # Mode: default (single file ingestion)
    if not args.file:
        parser.error("--file is required (or use --config for batch processing)")
    if not args.doc_id:
        parser.error("--doc-id is required")
    if not args.version:
        parser.error("--version is required")

    try:
        summary = run_pipeline(
            file_path=args.file,
            doc_id=args.doc_id,
            version=args.version,
            domain=args.domain,
            dry_run=args.dry_run,
            force=args.force,
            root=root,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Print summary in RFC Section 9.2 format
    print(f"""Ingestion Summary:
  Source: {summary['source']}
  Parser: {summary['parser']}
  Sections found: {summary['sections_found']}
  Rule candidates: {summary['rule_candidates']}
    - deterministic split: {summary['deterministic_count']}
    - LLM-assisted split: {summary['llm_count']}
  YAML files created: {summary['files_created']} (rules/{summary['doc_id']}/)
  Status: {summary['status']}

Next step: python3 scripts/gate1.py --apply""")


if __name__ == "__main__":
    main()
