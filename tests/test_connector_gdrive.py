"""Unit tests for connector.gdrive — Google API mocked, no network required."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
import yaml

from connector.gdrive import (
    DriveFile,
    authenticate,
    download_file,
    list_folder,
    sync_folder,
    _load_manifest,
    _save_manifest,
    _sanitize_filename,
    _check_dependencies,
)


# -- Helpers -----------------------------------------------------------------


def _make_drive_file(
    file_id: str = "file1",
    name: str = "test.pdf",
    mime_type: str = "application/pdf",
    modified_time: str = "2026-03-04T00:00:00.000Z",
) -> DriveFile:
    return DriveFile(
        file_id=file_id,
        name=name,
        mime_type=mime_type,
        modified_time=modified_time,
    )


def _mock_google_modules():
    """Create mock google modules for sys.modules patching."""
    # Build mock module hierarchy
    google = MagicMock()
    google_auth = MagicMock()
    google_oauth2 = MagicMock()
    google_auth_transport = MagicMock()
    google_auth_transport_requests = MagicMock()
    googleapiclient = MagicMock()
    googleapiclient_discovery = MagicMock()
    googleapiclient_http = MagicMock()
    google_auth_oauthlib = MagicMock()
    google_auth_oauthlib_flow = MagicMock()

    return {
        "google": google,
        "google.auth": google_auth,
        "google.auth.transport": google_auth_transport,
        "google.auth.transport.requests": google_auth_transport_requests,
        "google.oauth2": google_oauth2,
        "google.oauth2.credentials": google_oauth2,
        "googleapiclient": googleapiclient,
        "googleapiclient.discovery": googleapiclient_discovery,
        "googleapiclient.http": googleapiclient_http,
        "google_auth_oauthlib": google_auth_oauthlib,
        "google_auth_oauthlib.flow": google_auth_oauthlib_flow,
        "google_auth_httplib2": MagicMock(),
    }


# -- TestDriveFile -----------------------------------------------------------


class TestDriveFile:
    """DriveFile dataclass behavior."""

    def test_pdf_not_google_doc(self):
        df = _make_drive_file(mime_type="application/pdf")
        assert not df.is_google_doc

    def test_gdoc_is_google_doc(self):
        df = _make_drive_file(mime_type="application/vnd.google-apps.document")
        assert df.is_google_doc


# -- TestAuthenticate --------------------------------------------------------


class TestAuthenticate:
    """OAuth2 authentication flow."""

    def test_missing_credentials_raises(self, tmp_path):
        """FileNotFoundError when credentials file doesn't exist."""
        creds = tmp_path / "nonexistent.json"
        token = tmp_path / "token.json"
        with pytest.raises(FileNotFoundError, match="Credentials file not found"):
            authenticate(creds, token)

    def test_cached_valid_token(self, tmp_path):
        """When valid cached token exists, should use it without browser flow."""
        creds_path = tmp_path / "creds.json"
        creds_path.write_text("{}")
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.to_json.return_value = '{"token": "cached"}'

        mock_modules = _mock_google_modules()
        mock_modules["google.oauth2.credentials"].Credentials.from_authorized_user_file.return_value = mock_creds
        mock_build = mock_modules["googleapiclient.discovery"].build

        with patch.dict(sys.modules, mock_modules):
            with patch("connector.gdrive._check_dependencies"):
                service = authenticate(creds_path, token_path)
                mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)

    def test_expired_token_refreshed(self, tmp_path):
        """Expired token with refresh_token should call creds.refresh()."""
        creds_path = tmp_path / "creds.json"
        creds_path.write_text("{}")
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_tok"
        mock_creds.to_json.return_value = '{"token": "refreshed"}'

        mock_modules = _mock_google_modules()
        mock_modules["google.oauth2.credentials"].Credentials.from_authorized_user_file.return_value = mock_creds

        with patch.dict(sys.modules, mock_modules):
            with patch("connector.gdrive._check_dependencies"):
                authenticate(creds_path, token_path)
                mock_creds.refresh.assert_called_once()

    def test_library_not_installed_raises(self):
        """ImportError with install instructions when google libs missing."""
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            with pytest.raises(ImportError, match="agent-db"):
                _check_dependencies()


# -- TestListFolder ----------------------------------------------------------


class TestListFolder:
    """list_folder() with mocked Drive API."""

    def test_returns_pdf_and_docs(self):
        """Only PDFs and Google Docs returned."""
        service = MagicMock()
        service.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "1", "name": "a.pdf", "mimeType": "application/pdf",
                 "modifiedTime": "2026-01-01T00:00:00Z"},
                {"id": "2", "name": "b", "mimeType": "application/vnd.google-apps.document",
                 "modifiedTime": "2026-01-02T00:00:00Z"},
            ],
            "nextPageToken": None,
        }

        files = list_folder(service, "folder123")
        assert len(files) == 2
        assert not files[0].is_google_doc
        assert files[1].is_google_doc

    def test_empty_folder(self):
        """Empty folder returns empty list."""
        service = MagicMock()
        service.files.return_value.list.return_value.execute.return_value = {
            "files": [],
            "nextPageToken": None,
        }

        files = list_folder(service, "empty_folder")
        assert files == []

    def test_pagination(self):
        """Handles multiple pages of results."""
        service = MagicMock()
        responses = [
            {
                "files": [{"id": "1", "name": "a.pdf", "mimeType": "application/pdf",
                           "modifiedTime": "2026-01-01T00:00:00Z"}],
                "nextPageToken": "page2",
            },
            {
                "files": [{"id": "2", "name": "b.pdf", "mimeType": "application/pdf",
                           "modifiedTime": "2026-01-02T00:00:00Z"}],
                "nextPageToken": None,
            },
        ]
        service.files.return_value.list.return_value.execute.side_effect = responses

        files = list_folder(service, "folder123")
        assert len(files) == 2

    def test_order_by_name(self):
        """orderBy='name' passed to API."""
        service = MagicMock()
        list_mock = service.files.return_value.list
        list_mock.return_value.execute.return_value = {
            "files": [], "nextPageToken": None,
        }

        list_folder(service, "folder123")
        call_kwargs = list_mock.call_args
        assert call_kwargs[1]["orderBy"] == "name"


# -- TestDownloadFile --------------------------------------------------------


class TestDownloadFile:
    """download_file() with mocked API."""

    def test_pdf_direct_download(self, tmp_path):
        """PDF files downloaded directly via get_media."""
        service = MagicMock()
        df = _make_drive_file(name="규약.pdf")

        mock_downloader = MagicMock()
        mock_downloader.next_chunk.return_value = (None, True)

        mock_modules = _mock_google_modules()
        mock_modules["googleapiclient.http"].MediaIoBaseDownload.return_value = mock_downloader

        with patch.dict(sys.modules, mock_modules):
            path = download_file(service, df, tmp_path)
            assert path.exists()
            assert path.suffix == ".pdf"
            service.files.return_value.get_media.assert_called_once()

    def test_gdoc_export_pdf(self, tmp_path):
        """Google Docs exported as PDF by default."""
        service = MagicMock()
        df = _make_drive_file(
            name="세부지침",
            mime_type="application/vnd.google-apps.document",
        )

        mock_downloader = MagicMock()
        mock_downloader.next_chunk.return_value = (None, True)

        mock_modules = _mock_google_modules()
        mock_modules["googleapiclient.http"].MediaIoBaseDownload.return_value = mock_downloader

        with patch.dict(sys.modules, mock_modules):
            path = download_file(service, df, tmp_path, export_format="pdf")
            assert path.suffix == ".pdf"
            service.files.return_value.export_media.assert_called_once()

    def test_gdoc_export_md(self, tmp_path):
        """Google Docs exported as Markdown."""
        service = MagicMock()
        df = _make_drive_file(
            name="지침문서",
            mime_type="application/vnd.google-apps.document",
        )

        mock_downloader = MagicMock()
        mock_downloader.next_chunk.return_value = (None, True)

        mock_modules = _mock_google_modules()
        mock_modules["googleapiclient.http"].MediaIoBaseDownload.return_value = mock_downloader

        with patch.dict(sys.modules, mock_modules):
            path = download_file(service, df, tmp_path, export_format="md")
            assert path.suffix == ".md"

    def test_unsupported_export_format_raises(self, tmp_path):
        """ValueError for unsupported export format."""
        service = MagicMock()
        df = _make_drive_file(mime_type="application/vnd.google-apps.document")

        with pytest.raises(ValueError, match="Unsupported export format"):
            download_file(service, df, tmp_path, export_format="docx")

    def test_unsupported_mime_raises(self, tmp_path):
        """ValueError for unsupported MIME type."""
        service = MagicMock()
        df = _make_drive_file(mime_type="application/zip")

        with pytest.raises(ValueError, match="Unsupported MIME type"):
            download_file(service, df, tmp_path)


# -- TestSyncFolder ----------------------------------------------------------


class TestSyncFolder:
    """sync_folder() incremental sync with manifest."""

    @patch("connector.gdrive.download_file")
    @patch("connector.gdrive.list_folder")
    def test_first_sync_downloads_all(self, mock_list, mock_download, tmp_path):
        """First sync with no manifest downloads everything."""
        files = [
            _make_drive_file(file_id="f1", name="a.pdf"),
            _make_drive_file(file_id="f2", name="b.pdf"),
        ]
        mock_list.return_value = files
        mock_download.side_effect = [
            tmp_path / "a.pdf",
            tmp_path / "b.pdf",
        ]

        result = sync_folder(MagicMock(), "folder1", tmp_path)
        assert len(result) == 2
        assert mock_download.call_count == 2

        # Manifest should be written
        manifest = _load_manifest(tmp_path)
        assert "f1" in manifest
        assert "f2" in manifest

    @patch("connector.gdrive.download_file")
    @patch("connector.gdrive.list_folder")
    def test_incremental_skips_unchanged(self, mock_list, mock_download, tmp_path):
        """Files unchanged since last sync are skipped."""
        files = [
            _make_drive_file(file_id="f1", name="a.pdf",
                             modified_time="2026-01-01T00:00:00Z"),
        ]
        mock_list.return_value = files

        # Pre-populate manifest with same modifiedTime
        _save_manifest(tmp_path, {"f1": "2026-01-01T00:00:00Z"})

        result = sync_folder(MagicMock(), "folder1", tmp_path)
        assert len(result) == 0
        mock_download.assert_not_called()

    @patch("connector.gdrive.download_file")
    @patch("connector.gdrive.list_folder")
    def test_changed_file_redownloaded(self, mock_list, mock_download, tmp_path):
        """File with newer modifiedTime is re-downloaded."""
        files = [
            _make_drive_file(file_id="f1", name="a.pdf",
                             modified_time="2026-03-01T00:00:00Z"),
        ]
        mock_list.return_value = files
        mock_download.return_value = tmp_path / "a.pdf"

        # Old manifest
        _save_manifest(tmp_path, {"f1": "2026-01-01T00:00:00Z"})

        result = sync_folder(MagicMock(), "folder1", tmp_path)
        assert len(result) == 1
        mock_download.assert_called_once()

        # Manifest updated
        manifest = _load_manifest(tmp_path)
        assert manifest["f1"] == "2026-03-01T00:00:00Z"

    @patch("connector.gdrive.download_file")
    @patch("connector.gdrive.list_folder")
    def test_force_redownloads_all(self, mock_list, mock_download, tmp_path):
        """force=True ignores manifest and downloads everything."""
        files = [
            _make_drive_file(file_id="f1", name="a.pdf",
                             modified_time="2026-01-01T00:00:00Z"),
        ]
        mock_list.return_value = files
        mock_download.return_value = tmp_path / "a.pdf"

        # Same time in manifest
        _save_manifest(tmp_path, {"f1": "2026-01-01T00:00:00Z"})

        result = sync_folder(MagicMock(), "folder1", tmp_path, force=True)
        assert len(result) == 1

    @patch("connector.gdrive.download_file")
    @patch("connector.gdrive.list_folder")
    def test_manifest_persists(self, mock_list, mock_download, tmp_path):
        """Manifest file is written to disk after sync."""
        mock_list.return_value = [
            _make_drive_file(file_id="xyz", modified_time="2026-02-01T00:00:00Z"),
        ]
        mock_download.return_value = tmp_path / "test.pdf"

        sync_folder(MagicMock(), "folder1", tmp_path)

        manifest_path = tmp_path / ".gdrive-manifest.yaml"
        assert manifest_path.exists()
        data = yaml.safe_load(manifest_path.read_text())
        assert data["xyz"] == "2026-02-01T00:00:00Z"


# -- TestSanitizeFilename ----------------------------------------------------


class TestSanitizeFilename:
    """Filename sanitization."""

    def test_korean_preserved(self):
        assert "의료기기 규약" in _sanitize_filename("의료기기 규약.pdf")

    def test_special_chars_replaced(self):
        result = _sanitize_filename("file<name>with|bad:chars")
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result
        assert ":" not in result

    def test_dots_and_hyphens_preserved(self):
        result = _sanitize_filename("my-file.v2.pdf")
        assert result == "my-file.v2.pdf"
