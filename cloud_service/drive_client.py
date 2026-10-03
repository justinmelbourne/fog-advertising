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
import time
from typing import Any, Optional

import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest

from engine.models import Manifest
from engine.naming import (
    get_manifest_filename,
    get_match_folder_name,
    get_master_video_filename,
    parse_match_identifiers,
)

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
        self._ingest_folder_id: str = os.environ.get("DRIVE_INGEST_FOLDER_ID", "13nRt7Ozw8DKPTM3bjVXZlkpfzr1_Kj9P")
        self._output_folder_id: str = os.environ.get("DRIVE_OUTPUT_FOLDER_ID", "1lNCnRFDyyf3bE0fzNHqHNpzN7s5xalzy")

    # ------------------------------------------------------------------
    # Manifest read / write
    # ------------------------------------------------------------------

    def write_manifest(self, manifest: Manifest) -> str:
        """Upload or update a manifest.json file in the output folder. Returns file ID."""
        primary_name = get_manifest_filename(manifest.match_id)
        legacy_name = f"{manifest.match_id}_manifest.json"
        content = manifest.model_dump_json(indent=2).encode("utf-8")
        fh = io.BytesIO(content)
        media = MediaIoBaseUpload(fh, mimetype=MANIFEST_MIME, resumable=False)

        # Check if either standardized or legacy exists in root or subfolders
        existing_id = self._find_file(primary_name, self._output_folder_id) or self._find_file(legacy_name, self._output_folder_id)
        if not existing_id:
            query = f"(name='{primary_name}' or name='{legacy_name}') and mimeType='{MANIFEST_MIME}' and trashed=false"
            resp = (
                self._service.files()
                .list(
                    q=query,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                    spaces="drive",
                    fields="files(id, name)",
                    pageSize=1,
                )
                .execute()
            )
            files = resp.get("files", [])
            if files:
                existing_id = files[0]["id"]

        if existing_id:
            file = (
                self._service.files()
                .update(fileId=existing_id, body={"name": primary_name}, media_body=media, supportsAllDrives=True)
                .execute()
            )
            logger.info("Updated manifest: %s (%s)", primary_name, file["id"])
        else:
            match_folder_id = self.get_or_create_match_folder(self._output_folder_id, manifest.match_id)
            metadata = {
                "name": primary_name,
                "parents": [match_folder_id],
                "mimeType": MANIFEST_MIME,
            }
            file = (
                self._service.files()
                .create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
                .execute()
            )
            logger.info("Created manifest: %s (%s) inside match folder %s", primary_name, file["id"], match_folder_id)

        return file["id"]

    def read_manifest(self, match_id: str) -> Optional[dict[str, Any]]:
        """Download and parse a manifest JSON file by match ID. Returns None if not found."""
        primary_name = get_manifest_filename(match_id)
        file_id = self._find_file(primary_name, self._output_folder_id)
        if not file_id:
            legacy_name = f"{match_id}_manifest.json"
            file_id = self._find_file(legacy_name, self._output_folder_id)
        if not file_id:
            # Also search anywhere in Drive (e.g. inside match subfolders)
            query = f"(name='{primary_name}' or name='{match_id}_manifest.json' or name contains '{match_id}') and mimeType='{MANIFEST_MIME}' and trashed=false"
            resp = (
                self._service.files()
                .list(
                    q=query,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                    spaces="drive",
                    fields="files(id, name)",
                    pageSize=10,
                )
                .execute()
            )
            files = resp.get("files", [])
            for f in files:
                if f["name"] in (primary_name, f"{match_id}_manifest.json") or match_id in f["name"]:
                    file_id = f["id"]
                    break
        if not file_id:
            return None

        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(
            fh,
            self._service.files().get_media(fileId=file_id, supportsAllDrives=True),
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
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
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
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
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
                for suffix in ["_1080p.mp4", ".mp4", ".mov", ".m4v"]:
                    if mid.endswith(suffix):
                        mid = mid[:-len(suffix)]
                        break
                results[mid] = {"file_id": f.get("id"), "filename": name, "size": f.get("size")}
                results[name] = {"file_id": f.get("id"), "filename": name, "size": f.get("size")}
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    def list_all_files(self, folder_id: str) -> list[dict[str, Any]]:
        """List all files in any Drive folder (for diagnostics)."""
        query = f"'{folder_id}' in parents and trashed=false"
        results: list[dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            resp = (
                self._service.files()
                .list(
                    q=query,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, size, createdTime)",
                    pageToken=page_token,
                    pageSize=100,
                )
                .execute()
            )
            results.extend(resp.get("files", []))
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
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
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
                self._service.files().get_media(fileId=file_id, supportsAllDrives=True),
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
                .create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
                .execute()
            )
        logger.info("Uploaded %s -> Drive %s (%s)", filename, folder_id, file["id"])
        return file["id"]

    def get_or_create_subfolder(self, parent_folder_id: str, folder_name: str) -> str:
        """
        Ensures a subfolder named folder_name exists in parent_folder_id.
        Returns the subfolder ID.
        """
        query = f"'{parent_folder_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        resp = (
            self._service.files()
            .list(
                q=query,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives",
                spaces="drive",
                fields="files(id, name)",
                pageSize=1,
            )
            .execute()
        )
        files = resp.get("files", [])
        if files:
            return files[0]["id"]

        metadata = {
            "name": folder_name,
            "parents": [parent_folder_id],
            "mimeType": "application/vnd.google-apps.folder",
        }
        res = (
            self._service.files()
            .create(body=metadata, fields="id", supportsAllDrives=True)
            .execute()
        )
        logger.info("Created subfolder: %s (%s) inside %s", folder_name, res["id"], parent_folder_id)
        return res["id"]

    def get_or_create_match_folder(self, parent_folder_id: str, match_id: str) -> str:
        """
        Ensures a subfolder named YYYYMMDD_UNIQUEID_sf-fog-vs-{opponent} exists in parent_folder_id.
        Returns the subfolder ID.
        """
        folder_name = get_match_folder_name(match_id)
        return self.get_or_create_subfolder(parent_folder_id, folder_name)

    def rename_file(self, file_id: str, new_name: str) -> dict[str, Any]:
        """Renames a file in Google Drive without moving or re-uploading content."""
        return (
            self._service.files()
            .update(fileId=file_id, body={"name": new_name}, supportsAllDrives=True)
            .execute()
        )

    def move_file(self, file_id: str, new_parent_id: str) -> dict[str, Any]:
        """Moves a file to a new parent folder in Google Drive."""
        file = self._service.files().get(fileId=file_id, fields="parents, name", supportsAllDrives=True).execute()
        current_parents = file.get("parents", [])
        if new_parent_id in current_parents and len(current_parents) == 1:
            logger.debug("File %s already in target parent %s", file_id, new_parent_id)
            return file

        remove_parents = [p for p in current_parents if p != new_parent_id]
        update_args = {
            "fileId": file_id,
            "supportsAllDrives": True,
            "fields": "id, parents, name",
        }
        if new_parent_id not in current_parents:
            update_args["addParents"] = new_parent_id
        if remove_parents:
            update_args["removeParents"] = ",".join(remove_parents)

        return self._service.files().update(**update_args).execute()

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

                # Upload chunk with 3-attempt exponential-backoff retry on SSL/network drops
                max_retries = 3
                chunk_uploaded = False
                for attempt in range(max_retries):
                    try:
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
                            chunk_uploaded = True
                            break
                        elif upload_resp.status_code == 308:
                            chunk_uploaded = True
                            break
                        elif upload_resp.status_code in (500, 502, 503, 504):
                            logger.warning(
                                "Google Drive returned HTTP %d for chunk %d-%d (attempt %d/%d). Retrying...",
                                upload_resp.status_code, start_byte, end_byte, attempt + 1, max_retries,
                            )
                            time.sleep(2 ** attempt)
                        else:
                            upload_resp.raise_for_status()
                    except Exception as net_err:
                        logger.warning(
                            "Chunk upload dropped at bytes %d-%d (attempt %d/%d): %s. Re-querying session...",
                            start_byte, end_byte, attempt + 1, max_retries, net_err,
                        )
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(2 ** attempt)
                        # Re-query session status to check how many bytes Drive actually received
                        try:
                            check_headers = {
                                "Content-Range": f"bytes */{total_size if total_size > 0 else '*'}",
                                "Content-Length": "0",
                            }
                            status_resp = requests.put(upload_session_url, headers=check_headers, timeout=30)
                            if status_resp.status_code == 308:
                                rng = status_resp.headers.get("Range")
                                if rng and "-" in rng:
                                    confirmed_end = int(rng.split("-")[1])
                                    if confirmed_end >= end_byte:
                                        chunk_uploaded = True
                                        break
                            elif status_resp.status_code in (200, 201):
                                file_id = status_resp.json().get("id", "")
                                chunk_uploaded = True
                                break
                        except Exception as status_err:
                            logger.warning("Could not re-query Drive session status: %s", status_err)

                if file_id:
                    break

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
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives",
                spaces="drive",
                fields="files(id)",
                pageSize=1,
            )
            .execute()
        )
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    # ------------------------------------------------------------------
    # Social ready clip listings
    # ------------------------------------------------------------------

    def list_all_video_files_recursive(self, root_folder_id: str) -> list[dict[str, Any]]:
        """Recursively lists all video files under root_folder_id, traversing all subfolders."""
        all_videos: list[dict[str, Any]] = []
        folders_to_visit = [root_folder_id]
        visited_folders = set()

        while folders_to_visit:
            curr_id = folders_to_visit.pop(0)
            if curr_id in visited_folders:
                continue
            visited_folders.add(curr_id)

            page_token = None
            while True:
                resp = (
                    self._service.files()
                    .list(
                        q=f"'{curr_id}' in parents and trashed=false",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                        corpora="allDrives",
                        spaces="drive",
                        fields="nextPageToken, files(id, name, mimeType, size)",
                        pageToken=page_token,
                        pageSize=100,
                    )
                    .execute()
                )
                for item in resp.get("files", []):
                    mime = item.get("mimeType", "")
                    if mime == "application/vnd.google-apps.folder":
                        folders_to_visit.append(item["id"])
                    elif mime in VIDEO_MIMES or item.get("name", "").endswith((".mp4", ".mov", ".m4v")):
                        all_videos.append(item)
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

        return all_videos

    def list_social_clips(self) -> list[dict[str, Any]]:
        """
        List extracted social video clips (.mp4) in the output folder and all match & moment subfolders.
        Returns list of dicts with clip metadata, format, file id, and direct view URLs.
        """
        if not self._output_folder_id:
            logger.warning("No DRIVE_OUTPUT_FOLDER_ID configured.")
            return []

        files = self.list_all_video_files_recursive(self._output_folder_id)
        clips: list[dict[str, Any]] = []
        seen_ids = set()

        for f in files:
            fid = f.get("id", "")
            if fid in seen_ids:
                continue
            seen_ids.add(fid)

            name = f.get("name", "")

            # Deduce format from filename
            fmt = "16:9"
            if "9x16" in name or "9_16" in name:
                fmt = "9:16"
            elif "1x1" in name or "1_1" in name:
                fmt = "1:1"
            elif "4x5" in name or "4_5" in name:
                fmt = "4:5"

            # Parse standardized naming: YYYYMMDD_UNIQUEID_fog-rugby_DIM_MOMENT.mp4
            display_title = name.replace(".mp4", "").replace("_", " ").title()
            parts = name.replace(".mp4", "").split("_")
            if len(parts) >= 5 and parts[2] == "fog-rugby":
                # Standardized format: parts[0]=date, parts[1]=uid, parts[2]='fog-rugby', parts[3]=dim, parts[4+]=moment
                moment = " ".join(parts[4:]).replace("-", " ").title()
                display_title = f"{moment} ({parts[3]})"

            clips.append({
                "clip_id": fid,
                "file_name": name,
                "title": display_title,
                "format": fmt,
                "size_bytes": f.get("size"),
                "drive_file_id": fid,
                "drive_url": f"https://drive.google.com/file/d/{fid}/view",
                "download_url": f"https://drive.google.com/uc?id={fid}&export=download",
            })

        logger.info("Found %d social-ready clips in Drive output folder and subfolders.", len(clips))
        return clips

