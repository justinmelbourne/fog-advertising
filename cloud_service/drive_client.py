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

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.auth import default as google_auth_default

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
