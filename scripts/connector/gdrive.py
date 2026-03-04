"""Google Drive connector — authenticate, list, download, sync.

Downloads PDF files and exports Google Docs as PDF (or Markdown)
into a local staging directory for the ingestion pipeline.

Requires: pip install 'agent-db[gdrive]'
  (google-api-python-client, google-auth-oauthlib, google-auth-httplib2)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# MIME types we care about
_PDF_MIME = "application/pdf"
_GDOC_MIME = "application/vnd.google-apps.document"
# Export MIME mapping
_EXPORT_MIMES = {
    "pdf": "application/pdf",
    "md": "text/markdown",
    "markdown": "text/markdown",
}

_MANIFEST_NAME = ".gdrive-manifest.yaml"


def _check_dependencies():
    """Raise ImportError with install instructions if google libs missing."""
    try:
        import googleapiclient.discovery
        import google_auth_oauthlib.flow
        import google.auth.transport.requests
        del googleapiclient, google_auth_oauthlib, google
    except ImportError:
        raise ImportError(
            "Google Drive connector requires google-api-python-client.\n"
            "Install with: pip install 'agent-db[gdrive]'\n"
            "  or: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )


@dataclass
class DriveFile:
    """Metadata for a file in Google Drive."""

    file_id: str
    name: str
    mime_type: str
    modified_time: str  # ISO 8601
    is_google_doc: bool = field(init=False)

    def __post_init__(self):
        self.is_google_doc = self.mime_type == _GDOC_MIME


def authenticate(credentials_path: Path, token_path: Path) -> Any:
    """Authenticate with Google Drive API via OAuth2.

    First run opens browser for consent. Subsequent runs use cached token.

    Args:
        credentials_path: OAuth client credentials JSON from Google Cloud Console.
        token_path: path to cache/load the access token.

    Returns:
        google.discovery.Resource for Drive API v3.

    Raises:
        ImportError: google libs not installed.
        FileNotFoundError: credentials file not found.
    """
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Credentials file not found: {credentials_path}\n"
            "Download from Google Cloud Console → APIs & Services → Credentials."
        )

    _check_dependencies()

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None

    # Load cached token
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # Refresh or run auth flow
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path), SCOPES
        )
        creds = flow.run_local_server(port=0)

    # Save token for next run
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def list_folder(service: Any, folder_id: str) -> list[DriveFile]:
    """List PDF and Google Docs files in a Drive folder.

    Handles pagination automatically. Returns files sorted by name.

    Args:
        service: Drive API Resource from authenticate().
        folder_id: Google Drive folder ID.

    Returns:
        List of DriveFile objects (PDFs + Google Docs only).
    """
    files: list[DriveFile] = []
    page_token = None
    query = (
        f"'{folder_id}' in parents"
        f" and trashed = false"
        f" and (mimeType = '{_PDF_MIME}' or mimeType = '{_GDOC_MIME}')"
    )

    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
            pageToken=page_token,
            orderBy="name",
        ).execute()

        for item in response.get("files", []):
            files.append(DriveFile(
                file_id=item["id"],
                name=item["name"],
                mime_type=item["mimeType"],
                modified_time=item["modifiedTime"],
            ))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def download_file(
    service: Any,
    drive_file: DriveFile,
    dest_dir: Path,
    export_format: str = "pdf",
) -> Path:
    """Download a file from Google Drive.

    PDFs are downloaded directly. Google Docs are exported as PDF (default)
    or Markdown.

    Args:
        service: Drive API Resource.
        drive_file: file metadata from list_folder().
        dest_dir: local directory to save to.
        export_format: "pdf" or "md" for Google Docs export.

    Returns:
        Path to the downloaded local file.

    Raises:
        ValueError: unsupported export format or MIME type.
    """
    import io

    dest_dir.mkdir(parents=True, exist_ok=True)

    if drive_file.is_google_doc:
        # Export Google Docs
        export_mime = _EXPORT_MIMES.get(export_format)
        if not export_mime:
            raise ValueError(
                f"Unsupported export format: {export_format!r}. "
                f"Use one of: {list(_EXPORT_MIMES.keys())}"
            )
        ext = "md" if "markdown" in export_mime else "pdf"
        dest_path = dest_dir / f"{_sanitize_filename(drive_file.name)}.{ext}"

        request = service.files().export_media(
            fileId=drive_file.file_id, mimeType=export_mime
        )
    elif drive_file.mime_type == _PDF_MIME:
        # Direct download for PDF
        dest_path = dest_dir / _sanitize_filename(drive_file.name)
        if not dest_path.suffix:
            dest_path = dest_path.with_suffix(".pdf")

        request = service.files().get_media(fileId=drive_file.file_id)
    else:
        raise ValueError(f"Unsupported MIME type: {drive_file.mime_type}")

    from googleapiclient.http import MediaIoBaseDownload

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    dest_path.write_bytes(buf.getvalue())
    logger.info("Downloaded: %s → %s", drive_file.name, dest_path)
    return dest_path


def _sanitize_filename(name: str) -> str:
    """Remove or replace characters unsafe for filenames."""
    # Keep Korean, alphanumeric, dots, hyphens, underscores
    return "".join(
        c if c.isalnum() or c in ".-_ " or ord(c) > 127 else "_"
        for c in name
    ).strip()


def _load_manifest(dest_dir: Path) -> dict[str, str]:
    """Load sync manifest (file_id → modifiedTime mapping)."""
    manifest_path = dest_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        return {}
    with open(manifest_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _save_manifest(dest_dir: Path, manifest: dict[str, str]) -> None:
    """Save sync manifest."""
    manifest_path = dest_dir / _MANIFEST_NAME
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, default_flow_style=False)


def sync_folder(
    service: Any,
    folder_id: str,
    dest_dir: Path,
    export_format: str = "pdf",
    force: bool = False,
) -> list[tuple[DriveFile, Path]]:
    """Incremental sync: download only changed files from a Drive folder.

    Uses a manifest (.gdrive-manifest.yaml) to track modifiedTime.
    Files unchanged since last sync are skipped.

    Args:
        service: Drive API Resource.
        folder_id: Google Drive folder ID.
        dest_dir: local staging directory.
        export_format: "pdf" or "md" for Google Docs.
        force: if True, re-download everything ignoring manifest.

    Returns:
        List of (DriveFile, local_path) for files that were downloaded.
    """
    drive_files = list_folder(service, folder_id)
    manifest = {} if force else _load_manifest(dest_dir)
    downloaded: list[tuple[DriveFile, Path]] = []

    for df in drive_files:
        cached_time = manifest.get(df.file_id)
        if cached_time == df.modified_time and not force:
            logger.info("Skipping (unchanged): %s", df.name)
            continue

        local_path = download_file(service, df, dest_dir, export_format)
        manifest[df.file_id] = df.modified_time
        downloaded.append((df, local_path))

    _save_manifest(dest_dir, manifest)
    logger.info(
        "Sync complete: %d downloaded, %d skipped",
        len(downloaded), len(drive_files) - len(downloaded),
    )
    return downloaded
