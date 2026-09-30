"""
drive_client.py — Google Drive API wrapper for Cloud Run service
================================================================
Handles reading/writing manifest JSON files and listing video files
from the SF Fog RFC Google Workspace Shared Drive.

Uses Application Default Credentials (ADC) in Cloud Run (service account)
and local Application Default Credentials during development
(`gcloud auth application-default login`).
"""

import io
import json
import logging
import os
from typing import Any, Optional

import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest

from engine.models import Manifest

logger = logging.getLogger(__name__)

MANIFEST_MIME = "application/json"
VIDEO_MIMES = (
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
)


class DriveClient:
    """
    Thin wrapper around Google Drive API v3 for manifest and video file operations.
    Uses Application Default Credentials — no API key needed in Cloud Run.
    """

    def __init__(self) -> None:
        creds, _ = google_auth_default(scopes=["https://www.googleapis.com/auth/drive"])
        self._creds = creds
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._ingest_folder_id: str = os.environ["DRIVE_INGEST_FOLDER_ID"]
        self._output_folder_id: str = os.environ["DRIVE_OUTPUT_FOLDER_ID"]

    # ------------------------------------------------------------------
    # Manifest read / write
    # ------------------------------------------------------------------

    def write_manifest(self, manifest: Manifest) -> str:
        """Upload or update a manifest.json file in the output folder. Returns file ID."""
        filename = f"{manifest.match_id}_manifest.json"
        content = manifest.model_dump_json(indent=2).encode("utf-8")
        fh = io.BytesIO(content)
        media = MediaIoBaseUpload(fh, mimetype=MANIFEST_MIME, resumable=False)

        # Check if it already exists so we update rather than create a duplicate
        existing_id = self._find_file(filename, self._output_folder_id)
        if existing_id:
            file = (
                self._service.files()
                .update(fileId=existing_id, media_body=media)
                .execute()
            )
            logger.info("Updated manifest: %s (%s)", filename, file["id"])
        else:
            metadata = {
                "name": filename,
                "parents": [self._output_folder_id],
                "mimeType": MANIFEST_MIME,
            }
            file = (
                self._service.files()
                .create(body=metadata, media_body=media, fields="id")
                .execute()
            )
            logger.info("Created manifest: %s (%s)", filename, file["id"])

        return file["id"]

    def read_manifest(self, match_id: str) -> Optional[dict[str, Any]]:
        """Download and parse a manifest JSON file by match ID. Returns None if not found."""
        filename = f"{match_id}_manifest.json"
        file_id = self._find_file(filename, self._output_folder_id)
        if not file_id:
            return None

        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(
            fh,
            self._service.files().get_media(fileId=file_id),
        )
        done = False
        while not done:
            _, done = downloader.next_chunk()

        fh.seek(0)
        return json.loads(fh.read().decode("utf-8"))

    def list_ingested_manifests_map(self) -> dict[str, dict[str, Any]]:
        """
        Scan output folder for *_manifest.json files.
        Returns a dict mapping match_id -> { 'file_id': ..., 'match_id': ... }
        """
        query = f"'{self._output_folder_id}' in parents and mimeType='{MANIFEST_MIME}' and trashed=false"
        results: dict[str, dict[str, Any]] = {}
        page_token: Optional[str] = None
        while True:
            resp = (
                self._service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    pageSize=100,
                )
                .execute()
            )
            for f in resp.get("files", []):
                name = f.get("name", "")
                if name.endswith("_manifest.json"):
                    mid = name[:-len("_manifest.json")]
                    results[mid] = {"file_id": f.get("id"), "match_id": mid}
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    def list_downloaded_videos_map(self) -> dict[str, dict[str, Any]]:
        """
        Scan ingest folder for video files.
        Returns a dict mapping match_id -> { 'file_id': ..., 'filename': ..., 'size': ... }
        """
        mime_filter = " or ".join(f"mimeType='{m}'" for m in VIDEO_MIMES)
        query = f"'{self._ingest_folder_id}' in parents and ({mime_filter}) and trashed=false"
        results: dict[str, dict[str, Any]] = {}
        page_token: Optional[str] = None
        while True:
            resp = (
                self._service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, size)",
                    pageToken=page_token,
                    pageSize=100,
                )
                .execute()
            )
            for f in resp.get("files", []):
                name = f.get("name", "")
                mid = name
                for suffix in ["_1080p.mp4", ".mp4", ".mov"]:
                    if mid.endswith(suffix):
                        mid = mid[:-len(suffix)]
                        break
                results[mid] = {"file_id": f.get("id"), "filename": name, "size": f.get("size")}
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    # ------------------------------------------------------------------
    # Video file listing
    # ------------------------------------------------------------------

    def list_video_files(self, folder_id: str) -> list[dict[str, str]]:
        """
        List all video files in a Drive folder. Returns list of dicts with
        keys: id, name, mimeType, size.
        """
        mime_filter = " or ".join(f"mimeType='{m}'" for m in VIDEO_MIMES)
        query = f"'{folder_id}' in parents and ({mime_filter}) and trashed=false"

        results: list[dict[str, str]] = []
        page_token: Optional[str] = None

        while True:
            resp = (
                self._service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    pageToken=page_token,
                    pageSize=50,
                )
                .execute()
            )
            results.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d video files in folder %s", len(results), folder_id)
        return results

    def download_file_to_path(self, file_id: str, dest_path: str) -> None:
        """Download a Drive file to a local path (used by Cloud Run job worker)."""
        with open(dest_path, "wb") as f:
            downloader = MediaIoBaseDownload(
                f,
                self._service.files().get_media(fileId=file_id),
            )
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug("Download %d%%", int(status.progress() * 100))

    def upload_file_to_folder(self, local_path: str, filename: str, folder_id: str) -> str:
        """Upload a local file to the given Drive folder. Returns file ID."""
        mime = "video/mp4"
        metadata = {"name": filename, "parents": [folder_id]}
        with open(local_path, "rb") as f:
            media = MediaIoBaseUpload(f, mimetype=mime, resumable=True, chunksize=5 * 1024 * 1024)
            file = (
                self._service.files()
                .create(body=metadata, media_body=media, fields="id")
                .execute()
            )
        logger.info("Uploaded %s -> Drive %s (%s)", filename, folder_id, file["id"])
        return file["id"]

    def stream_url_to_folder(
        self,
        download_url: str,
        filename: str,
        folder_id: Optional[str] = None,
        progress_callback: Optional[Any] = None,
    ) -> str:
        """
        Streams a video file directly from a remote CDN URL into Google Drive
        using Google Drive Resumable Upload protocol.
        Requires zero local disk storage and minimal (10MB buffer) memory usage.
        Optionally reports uploaded bytes and total bytes via progress_callback(uploaded, total).
        """
        target_folder = folder_id or self._ingest_folder_id

        # 1. Fetch remote content length
        head_resp = requests.head(download_url, timeout=30, allow_redirects=True)
        head_resp.raise_for_status()
        total_size = int(head_resp.headers.get("content-length", 0))

        if progress_callback:
            try:
                progress_callback(0, total_size)
            except Exception as e:
                logger.debug("Progress callback error: %s", e)

        # 2. Get fresh Google OAuth token
        if not self._creds.valid:
            self._creds.refresh(GoogleAuthRequest())
        token = self._creds.token

        # 3. Initiate Drive Resumable Upload session
        init_url = (
            "https://www.googleapis.com/upload/drive/v3/files"
            "?uploadType=resumable&supportsAllDrives=true"
        )
        init_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
        }
        if total_size > 0:
            init_headers["X-Upload-Content-Length"] = str(total_size)

        metadata = {"name": filename, "parents": [target_folder]}
        init_res = requests.post(
            init_url, headers=init_headers, json=metadata, timeout=30
        )
        init_res.raise_for_status()

        upload_session_url = init_res.headers.get("Location")
        if not upload_session_url:
            raise RuntimeError("Drive API did not return a resumable Location header")

        logger.info(
            "Initiated Drive streaming upload for %s (size: %s bytes)",
            filename,
            total_size,
        )

        # 4. Stream chunks from CDN to Drive session
        chunk_size = 10 * 1024 * 1024  # 10 MB chunks
        start_byte = 0
        file_id = ""

        with requests.get(download_url, stream=True, timeout=60) as stream_resp:
            stream_resp.raise_for_status()
            for chunk in stream_resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                end_byte = start_byte + len(chunk) - 1
                chunk_headers = {
                    "Content-Range": f"bytes {start_byte}-{end_byte}/{total_size if total_size > 0 else '*'}",
                    "Content-Length": str(len(chunk)),
                }

                upload_resp = requests.put(
                    upload_session_url, headers=chunk_headers, data=chunk, timeout=120
                )
                if upload_resp.status_code in (200, 201):
                    file_id = upload_resp.json().get("id", "")
                    if progress_callback:
                        try:
                            progress_callback(total_size, total_size)
                        except Exception:
                            pass
                    break
                elif upload_resp.status_code == 308:
                    pass
                else:
                    upload_resp.raise_for_status()

                start_byte = end_byte + 1
                if progress_callback:
                    try:
                        progress_callback(start_byte, total_size)
                    except Exception as e:
                        logger.debug("Progress callback error: %s", e)

        logger.info("Successfully streamed %s directly to Drive: %s", filename, file_id)
        return file_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_file(self, name: str, folder_id: str) -> Optional[str]:
        """Return the Drive file ID for a file with the given name in folder_id, or None."""
        resp = (
            self._service.files()
            .list(
                q=f"name='{name}' and '{folder_id}' in parents and trashed=false",
                spaces="drive",
                fields="files(id)",
                pageSize=1,
            )
            .execute()
        )
        files = resp.get("files", [])
        return files[0]["id"] if files else None
