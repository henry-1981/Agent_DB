"""Source registry management for the ingestion pipeline.

Handles registration of new source documents and version additions.
New doc_ids require explicit --register-source with confirm step (C2 mitigation).
"""

from __future__ import annotations

from pathlib import Path

import yaml


class UserAbortError(Exception):
    """User cancelled the operation."""


def load_sources_registry(root: Path) -> dict:
    """Load sources/_sources.yaml and return the full data dict."""
    path = root / "sources" / "_sources.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def save_sources_registry(data: dict, root: Path) -> None:
    """Save data back to sources/_sources.yaml."""
    path = root / "sources" / "_sources.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_authority_levels(domain: str, root: Path) -> list[str]:
    """Load valid authority levels from domains/{domain}/authority_levels.yaml."""
    path = root / "domains" / domain / "authority_levels.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("levels", []) if data else []


def register_new_source(
    doc_id: str,
    title: str,
    version: str,
    authority_level: str,
    file_path: str,
    publisher: str,
    notes: str,
    domain: str,
    root: Path,
    confirm_fn=None,
) -> None:
    """Register a brand-new source document.

    Validates authority_level against domain config BEFORE registration,
    preventing invalid authority values from entering the registry.

    Args:
        doc_id: unique document identifier.
        title: document title.
        version: version string.
        authority_level: must match domain config.
        file_path: source file path.
        publisher: publishing organization.
        notes: optional notes.
        domain: domain name for authority validation.
        root: project root directory.
        confirm_fn: callable returning bool (for testing). Defaults to input().

    Raises:
        ValueError: invalid authority_level or doc_id already exists.
        UserAbortError: user declined confirmation.
    """
    # Step 1: Validate authority_level against domain config
    valid_levels = load_authority_levels(domain, root)
    if authority_level not in valid_levels:
        raise ValueError(
            f"'{authority_level}' is not valid for domain '{domain}'. "
            f"Valid levels: {valid_levels}"
        )

    # Step 2: Check doc_id doesn't already exist
    data = load_sources_registry(root)
    sources = data.get("sources", {})
    if doc_id in sources:
        raise ValueError(f"doc_id '{doc_id}' already exists in registry")

    # Step 3: Display registration details
    print("=== New Source Registration ===")
    print(f"  doc_id:          {doc_id}")
    print(f"  title:           {title}")
    print(f"  version:         {version}")
    print(f"  authority_level: {authority_level}")
    print(f"  publisher:       {publisher}")
    print(f"  domain:          {domain}")

    # Step 4: Get user confirmation
    if confirm_fn is not None:
        confirmed = confirm_fn()
    else:
        answer = input("Register this source? [y/N] ")
        confirmed = answer.strip().lower() in ("y", "yes")

    if not confirmed:
        raise UserAbortError("Source registration cancelled.")

    # Step 5: Save to registry
    sources[doc_id] = {
        "title": title,
        "versions": [{"version": version, "file": file_path}],
        "publisher": publisher,
        "authority_level": authority_level,
        "notes": notes,
    }
    data["sources"] = sources
    save_sources_registry(data, root)


def add_version_to_existing_source(
    doc_id: str,
    version: str,
    file_path: str,
    root: Path,
    supersedes: str | None = None,
) -> None:
    """Add a new version to an existing source. Auto-allowed (no confirm needed).

    Args:
        doc_id: must already exist in registry.
        version: new version string.
        file_path: source file path.
        root: project root directory.
        supersedes: optional version string this version supersedes.

    Raises:
        KeyError: doc_id not in registry.
        ValueError: version already exists.
    """
    data = load_sources_registry(root)
    sources = data.get("sources", {})

    if doc_id not in sources:
        raise KeyError(
            f"'{doc_id}' not in registry. Use --register-source to register first."
        )

    existing_versions = [v["version"] for v in sources[doc_id]["versions"]]
    if version in existing_versions:
        raise ValueError(
            f"Version '{version}' already exists for doc_id '{doc_id}'"
        )

    entry = {"version": version, "file": file_path}
    if supersedes:
        entry["supersedes"] = supersedes

    sources[doc_id]["versions"].append(entry)
    save_sources_registry(data, root)
