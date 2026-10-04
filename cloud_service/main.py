"""
SF Fog RFC - Rugby Video Analysis Cloud Run API
================================================
Stateless REST API designed to run on Google Cloud Run (Python 3.11 / Flask).
Triggered by the Squarespace portal JS, Veo direct connector, and
Drive watch-channel push notifications.

All video assets live in Google Workspace Shared Drive (100 TB nonprofit quota).
Processing is done in-container (FFmpeg + Librosa) and results written back to Drive.

Endpoints:
  GET  /health                  - Cloud Run health check
  GET  /veo/recordings          - List all recent club match recordings from Veo
  GET  /veo/match/<slug_or_id>  - Get match video URL and AI rugby highlights from Veo
  POST /veo/ingest              - Stream match MP4 directly from Veo CDN to Google Drive & ingest
  POST /veo/webhook             - Receive Veo notification payload or email body
  POST /analyze                 - Trigger analysis of a Drive folder for a match
  GET  /manifest/<match_id>     - Retrieve generated manifest.json for a match
  POST /extract                 - Kick off on-demand FFmpeg clip extraction

Environment Variables (set via Secret Manager in Cloud Run):
  GOOGLE_CLOUD_PROJECT     - GCP project ID
  DRIVE_INGEST_FOLDER_ID   - Google Drive folder ID for game day ingest
  DRIVE_OUTPUT_FOLDER_ID   - Google Drive folder ID for social-ready clips
  GCS_BUCKET               - Cloud Storage bucket for proxy previews
  GEMINI_BACKEND           - "vertex" (service account, club billing) or "api_key"
  GEMINI_MODEL             - Gemini model id (e.g. gemini-3.8-flash)
  GEMINI_API_KEY           - Only for GEMINI_BACKEND=api_key (local dev)
  FOG_API_KEY              - Optional: require X-Fog-Api-Key on POST routes
  VEO_API_TOKEN            - Optional Veo API bearer token (for private recordings)
"""

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, request, Response

# Persistent and in-memory job registry for real-time progress tracking
JOBS: dict[str, dict[str, Any]] = {}
JOBS_FILE = Path("/tmp/fog_jobs.json")
_jobs_lock = threading.Lock()


def _save_job(job_id: str, data: dict[str, Any]) -> None:
    with _jobs_lock:
        JOBS[job_id] = data
        try:
            all_jobs = {}
            if JOBS_FILE.exists():
                with open(JOBS_FILE, "r") as f:
                    all_jobs = json.load(f)
            all_jobs[job_id] = data
            with open(JOBS_FILE, "w") as f:
                json.dump(all_jobs, f)
        except Exception:
            pass


def _get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _jobs_lock:
        if job_id in JOBS:
            return JOBS[job_id]
        if JOBS_FILE.exists():
            try:
                with open(JOBS_FILE, "r") as f:
                    all_jobs = json.load(f)
                if job_id in all_jobs:
                    JOBS[job_id] = all_jobs[job_id]
                    return all_jobs[job_id]
            except Exception:
                pass
        return None

# Local engine imports (bundled in same container image)
from engine.models import Manifest, VideoSource, Event
from engine.veo_ingest import (
    parse_veo_email_body,
    parse_veo_highlights,
    fetch_veo_match_events,
)
from engine.ai_suggester import generate_clip_pairings
from engine.clipper import build_lossless_cut_command, build_reframe_command
from cloud_service.drive_client import DriveClient
from cloud_service.veo_api_client import VeoApiClient
from cloud_service.job_runner import run_analysis_job, run_extract_job, run_batch_extract_job, run_highlights_job
from engine.naming import (
    get_master_video_filename,
    get_social_clip_filename,
    get_highlight_reel_filename,
    get_match_folder_name,
    get_manifest_filename,
    parse_match_identifiers,
    slugify_moment,
    get_moment_folder_name,
    get_target_subfolder_path,
    FOLDER_HIGHLIGHTS,
    FOLDER_TRIES,
    FOLDER_SCRUMS,
    FOLDER_LINEOUTS,
    FOLDER_KICKS,
    FOLDER_GENERAL,
    FOLDER_OPPOSING_TEAM,
    FOLDER_NEEDS_REVIEW,
)
from engine.team_analyzer import classify_event_sentiment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Global CORS handling — Allows Squarespace and localhost origins
# ---------------------------------------------------------------------------

@app.after_request
def add_cors_headers(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Fog-Api-Key"
    )
    return response


_PROTECTED_GET_PATHS = ("/drive/debug",)


@app.before_request
def require_api_key() -> Optional[Response]:
    """
    When FOG_API_KEY is set (Secret Manager), every mutating request and the Drive
    debug listing must carry a matching X-Fog-Api-Key header. Unset = open (legacy).
    """
    import hmac
    expected = os.environ.get("FOG_API_KEY", "")
    if not expected or request.method == "OPTIONS":
        return None
    if request.method == "GET" and request.path not in _PROTECTED_GET_PATHS:
        return None
    provided = request.headers.get("X-Fog-Api-Key", "")
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.before_request
def handle_preflight() -> Optional[Response]:
    if request.method == "OPTIONS":
        res = Response()
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        res.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-Fog-Api-Key"
        )
        return res
    return None


# ---------------------------------------------------------------------------
# Health check — required by Cloud Run
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health() -> Response:
    return jsonify({"status": "ok", "service": "fog-video-analysis-api"})


# ---------------------------------------------------------------------------
# GET /veo/recordings
# Returns all recent match recordings from the Fog's Veo clubhouse.
# Used by the Squarespace Game Day Media Hub for 1-click ingest.
# ---------------------------------------------------------------------------

@app.route("/veo/recordings", methods=["GET"])
def list_veo_recordings() -> Response:
    try:
        club_slug = request.args.get("club", "san-francisco-fog-rfc")
        fetch_all = request.args.get("all", "true").lower() in ("true", "1", "yes")
        page_arg = request.args.get("page")
        page = int(page_arg) if page_arg and page_arg.isdigit() else None

        token = os.environ.get("VEO_API_TOKEN", "")
        client = VeoApiClient(token=token)
        recordings = client.list_club_recordings(club_slug=club_slug, fetch_all=fetch_all, page=page)

        # Check Google Drive for existing downloads and analyzed manifests
        ingested_manifests = {}
        downloaded_videos = {}
        try:
            drive = DriveClient()
            ingested_manifests = drive.list_ingested_manifests_map()
            downloaded_videos = drive.list_downloaded_videos_map()
            logger.info("Found %d manifests, %d downloaded videos in Drive", len(ingested_manifests), len(downloaded_videos))
        except Exception as drive_exc:
            logger.warning("Could not check Drive for ingested matches: %s", drive_exc)

        formatted = []
        for r in recordings:
            slug = r.get("slug") or r.get("identifier") or ""
            ident = r.get("identifier") or ""

            # Check if manifest exists (analyzed)
            is_analyzed = (slug in ingested_manifests) or (ident in ingested_manifests)
            if not is_analyzed:
                for mid in ingested_manifests.keys():
                    if (slug and slug in mid) or (ident and ident in mid):
                        is_analyzed = True
                        break

            # Check if video file exists in Google Drive (downloaded)
            is_downloaded = (slug in downloaded_videos) or (ident in downloaded_videos)
            drive_file_id = downloaded_videos.get(slug, {}).get("file_id") or downloaded_videos.get(ident, {}).get("file_id")
            if not is_downloaded:
                for fname, finfo in downloaded_videos.items():
                    if (slug and slug in fname) or (ident and ident in fname):
                        is_downloaded = True
                        drive_file_id = finfo.get("file_id")
                        break

            is_expiring_soon = bool(r.get("is_expiring_soon", False))
            is_expired = bool(r.get("is_expired", False))

            formatted.append({
                "identifier": ident,
                "slug": slug,
                "title": r.get("title", "SF Fog Match"),
                "start": r.get("start") or r.get("created"),
                "duration": r.get("duration"),
                "thumbnail": r.get("thumbnail"),
                "url": f"https://app.veo.co{r.get('url')}" if r.get("url") else None,
                "status": r.get("processing_status"),
                "is_ingested": is_analyzed,
                "is_downloaded": is_downloaded,
                "drive_file_id": drive_file_id,
                "is_expiring_soon": is_expiring_soon,
                "is_expired": is_expired,
                "days_until_expiry": r.get("days_until_expiry"),
                "expires_at": r.get("expires_at"),
            })

        # Calculate high-level summary counts for UI
        expiring_urgent = [x for x in formatted if x["is_expiring_soon"] and not x["is_downloaded"]]
        in_drive_count = sum(1 for x in formatted if x["is_downloaded"])
        analyzed_count = sum(1 for x in formatted if x["is_ingested"])

        return jsonify({
            "club": club_slug,
            "count": len(formatted),
            "expiring_count": len(expiring_urgent),
            "downloaded_count": in_drive_count,
            "analyzed_count": analyzed_count,
            "expired_count": sum(1 for x in formatted if x["is_expired"]),
            "recordings": formatted,
        })
    except Exception as exc:
        logger.exception("Failed to fetch Veo recordings: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# POST /veo/restore
# Requests unarchiving of an expired match video from AWS Glacier.
# ---------------------------------------------------------------------------

@app.route("/veo/restore", methods=["POST"])
def restore_veo_match() -> Response:
    try:
        data = request.get_json(silent=True) or {}
        match_id = data.get("match_id") or data.get("slug") or request.args.get("match_id", "")
        if not match_id:
            return jsonify({"error": "Missing match_id"}), 400

        token = request.headers.get("X-Veo-Token") or data.get("token") or os.environ.get("VEO_API_TOKEN", "")
        client = VeoApiClient(token=token)
        res = client.restore_match(match_id)
        status_code = 202 if res.get("status") == "restoring" else 200 if res.get("status") == "ready" else 400
        return jsonify(res), status_code
    except Exception as exc:
        logger.exception("Failed to restore Veo match: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# GET / POST /veo/restore/check
# Checks whether an AWS Glacier restoration has finished unarchiving.
# ---------------------------------------------------------------------------

@app.route("/veo/restore/check", methods=["GET", "POST"])
def check_veo_glacier_status() -> Response:
    try:
        data = request.get_json(silent=True) or {}
        match_id = request.args.get("match_id") or data.get("match_id") or data.get("slug", "")
        if not match_id:
            return jsonify({"error": "Missing match_id parameter"}), 400

        token = request.headers.get("X-Veo-Token") or data.get("token") or os.environ.get("VEO_API_TOKEN", "")
        client = VeoApiClient(token=token)
        res = client.check_glacier_status(match_id)
        return jsonify(res), 200
    except Exception as exc:
        logger.exception("Failed to check Glacier status: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/veo/backup-expiring", methods=["POST"])
def backup_expiring_matches() -> Response:
    """
    Finds all Veo recordings that are expiring soon and not yet in Google Drive,
    and queues background download jobs for each.
    """
    try:
        token = os.environ.get("VEO_API_TOKEN", "")
        client = VeoApiClient(token=token)
        recordings = client.list_club_recordings(fetch_all=True)

        drive = DriveClient()
        downloaded_videos = drive.list_downloaded_videos_map()

        queued_jobs = []
        for r in recordings:
            if not r.get("is_expiring_soon"):
                continue

            slug = r.get("slug") or r.get("identifier") or ""
            is_already_downloaded = (slug in downloaded_videos)
            if not is_already_downloaded:
                for fname in downloaded_videos.keys():
                    if slug and slug in fname:
                        is_already_downloaded = True
                        break

            if is_already_downloaded:
                continue

            # Queue ingest job
            match_title = r.get("title", f"SF Fog RFC — {slug.replace('-', ' ').title()}")
            job_id = uuid.uuid4().hex[:8]
            initial_job_data = {
                "job_id": job_id,
                "match_id": slug,
                "title": match_title,
                "stage": "starting",
                "stage_description": f"Queued urgent backup: {r.get('days_until_expiry', 0)} days remaining on Veo...",
                "progress_pct": 0,
                "bytes_uploaded": 0,
                "total_bytes": 0,
                "mb_uploaded": 0.0,
                "mb_total": 0.0,
                "speed_mbps": 0.0,
                "eta_seconds": 0,
                "events_count": 0,
                "manifest": None,
                "drive_file_id": None,
                "error": None,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            _save_job(job_id, initial_job_data)

            thread = threading.Thread(
                target=_process_veo_ingest_job,
                args=(job_id, slug, match_title, client, False),
                daemon=True,
            )
            thread.start()

            queued_jobs.append({
                "job_id": job_id,
                "match_id": slug,
                "title": match_title,
                "days_until_expiry": r.get("days_until_expiry"),
            })

        logger.info("Queued %d expiring matches for Drive backup", len(queued_jobs))
        return jsonify({
            "status": "queued",
            "count": len(queued_jobs),
            "jobs": queued_jobs,
            "message": f"Queued {len(queued_jobs)} expiring matches for direct backup to Google Drive."
        })
    except Exception as exc:
        logger.exception("Failed to backup expiring matches: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/drive/social-clips", methods=["GET"])
def list_social_clips() -> Response:
    """
    Returns all social-ready video clips extracted and saved in Google Drive.
    """
    try:
        drive = DriveClient()
        clips = drive.list_social_clips()
        return jsonify({
            "status": "ok",
            "count": len(clips),
            "clips": clips,
        })
    except Exception as exc:
        logger.exception("Failed to list social clips: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/drive/debug", methods=["GET"])
def drive_debug() -> Response:
    try:
        drive = DriveClient()
        inspect_folder = request.args.get("folder_id")
        if inspect_folder:
            files = drive.list_all_files(inspect_folder)
            return jsonify({
                "folder_id": inspect_folder,
                "files_count": len(files),
                "files": [{"id": f["id"], "name": f["name"], "mimeType": f.get("mimeType"), "size": f.get("size")} for f in files],
            })
        ingest_files = drive.list_all_files(drive._ingest_folder_id)
        output_files = drive.list_all_files(drive._output_folder_id)
        return jsonify({
            "ingest_folder_id": drive._ingest_folder_id,
            "output_folder_id": drive._output_folder_id,
            "ingest_files_count": len(ingest_files),
            "ingest_files": [{"id": f["id"], "name": f["name"], "size": f.get("size")} for f in ingest_files],
            "output_files_count": len(output_files),
            "output_files": [{"id": f["id"], "name": f["name"], "mimeType": f.get("mimeType"), "size": f.get("size")} for f in output_files],
        })
    except Exception as exc:
        logger.exception("Drive debug failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# POST /drive/migrate-naming
# Standardizes existing Google Drive files and folder structure according to:
#   YYYYMMDD_UNIQUEID_file-name.ext
# - Moves match clips, highlight reels, and manifests into match subfolders:
#   YYYYMMDD_UNIQUEID_sf-fog-vs-{opponent}
# - Renames clips: YYYYMMDD_UNIQUEID_fog-rugby_{dimensions}_{moment_type}.mp4
# - Renames highlight reels: YYYYMMDD_UNIQUEID_fog-rugby_{dimensions}_{reel_type}.mp4
# - Renames manifests: YYYYMMDD_UNIQUEID_manifest.json
# - Renames ingest match videos: YYYYMMDD_UNIQUEID_sf-fog-rugby_vs_{opponent}_1080p.mp4
# ---------------------------------------------------------------------------

@app.route("/drive/migrate-naming", methods=["POST"])
def migrate_naming() -> Response:
    import re
    data = request.get_json(silent=True) or {}
    dry_run = data.get("dry_run", False)

    try:
        drive = DriveClient()
        changes = []

        # 1. Ingest folder: rename master match videos
        ingest_files = drive.list_all_files(drive._ingest_folder_id)
        for f in ingest_files:
            fname = f["name"]
            fid = f["id"]
            if fname.endswith("_1080p.mp4"):
                if re.match(r'^\d{8}_[A-Za-z0-9]+_sf-fog-rugby_vs_', fname):
                    continue
                slug = fname[:-10]  # remove _1080p.mp4
                new_name = get_master_video_filename(slug, quality="1080p")
                if new_name != fname:
                    if not dry_run:
                        drive.rename_file(fid, new_name)
                    changes.append({
                        "type": "ingest_master_rename",
                        "file_id": fid,
                        "old_name": fname,
                        "new_name": new_name,
                    })

        # 2. Output folder: organize clips, reels, and manifests into match subfolders
        out_files = drive.list_all_files(drive._output_folder_id)
        
        manifest_files = [
            f for f in out_files
            if "manifest" in f["name"].lower() and f["name"].endswith(".json")
        ]
        # Prioritize Sydney Convicts 1st XV match so it claims its legacy clips and highlight reels
        manifest_files.sort(key=lambda x: 0 if "sydney-convicts-1" in x["name"] else 1)

        handled_file_ids = set()

        for mf in manifest_files:
            mf_name = mf["name"]
            manifest_data = drive.read_manifest(mf_name)
            if not manifest_data:
                try:
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".json") as tf:
                        drive.download_file_to_path(mf["id"], tf.name)
                        with open(tf.name, "r") as jf:
                            manifest_data = json.load(jf)
                except Exception as ex:
                    logger.warning("Could not read manifest %s: %s", mf_name, ex)
                    continue

            if not manifest_data or not manifest_data.get("match_id"):
                continue

            match_id = manifest_data["match_id"]
            events_by_id = {e["event_id"]: e for e in manifest_data.get("events", [])}
            _, unique_id, opponent = parse_match_identifiers(match_id)

            match_folder_id = drive.get_or_create_match_folder(drive._output_folder_id, match_id)
            match_folder_name = get_match_folder_name(match_id)

            # Move and rename THIS manifest file
            new_mf_name = get_manifest_filename(match_id)
            if mf["id"] not in handled_file_ids:
                if mf_name != new_mf_name:
                    if not dry_run:
                        drive.rename_file(mf["id"], new_mf_name)
                if not dry_run:
                    drive.move_file(mf["id"], match_folder_id)
                handled_file_ids.add(mf["id"])
                changes.append({
                    "type": "manifest",
                    "file_id": mf["id"],
                    "old_name": mf_name,
                    "new_name": new_mf_name,
                    "folder": match_folder_name,
                })

            match_files = drive.list_all_files(match_folder_id)
            combined_files = {f["id"]: f for f in (out_files + match_files)}

            for fid, f in combined_files.items():
                if fid in handled_file_ids:
                    continue
                fname = f["name"]

                # A. Highlight reels for this match
                if "highlights" in fname.lower() and fname.endswith(".mp4"):
                    if (opponent in fname.lower().replace("_", "-")) or ("sydney" in fname.lower() and "sydney" in opponent):
                        dim = "16x9" if "16x9" in fname else "9x16" if "9x16" in fname else "16x9"
                        new_name = get_highlight_reel_filename(match_id, dim, "match-highlights")
                        if fname != new_name:
                            if not dry_run:
                                drive.rename_file(fid, new_name)
                                drive.move_file(fid, match_folder_id)
                            changes.append({
                                "type": "highlight_reel",
                                "file_id": fid,
                                "old_name": fname,
                                "new_name": new_name,
                                "folder": match_folder_name,
                            })
                            handled_file_ids.add(fid)
                        elif fid in [x["id"] for x in out_files]:
                            if not dry_run:
                                drive.move_file(fid, match_folder_id)
                            changes.append({
                                "type": "move_to_match_folder",
                                "file_id": fid,
                                "name": fname,
                                "folder": match_folder_name,
                            })
                            handled_file_ids.add(fid)

                # B. Social clips matching an event in THIS manifest
                elif fname.endswith(".mp4"):
                    ev_match = re.search(r'(veo_evt_\d+)', fname)
                    if ev_match:
                        ev_id = ev_match.group(1)
                        if ev_id in events_by_id:
                            dim = "16x9" if ("16x9" in fname or "master" in fname) else "9x16" if "9x16" in fname else "16x9"
                            ev_data = events_by_id[ev_id]
                            moment_type = slugify_moment(
                                ev_data.get("event_type", "moment"),
                                ev_data.get("description", ""),
                                ev_id,
                            )
                            new_name = get_social_clip_filename(match_id, dim, moment_type)
                            if fname != new_name:
                                if not dry_run:
                                    drive.rename_file(fid, new_name)
                                    drive.move_file(fid, match_folder_id)
                                changes.append({
                                    "type": "social_clip",
                                    "file_id": fid,
                                    "old_name": fname,
                                    "new_name": new_name,
                                    "folder": match_folder_name,
                                })
                                handled_file_ids.add(fid)
                            elif fid in [x["id"] for x in out_files]:
                                if not dry_run:
                                    drive.move_file(fid, match_folder_id)
                                changes.append({
                                    "type": "move_to_match_folder",
                                    "file_id": fid,
                                    "name": fname,
                                    "folder": match_folder_name,
                                })
                                handled_file_ids.add(fid)

        return jsonify({
            "status": "complete",
            "dry_run": dry_run,
            "changes_count": len(changes),
            "changes": changes,
        })
    except Exception as exc:
        logger.exception("Failed to migrate naming: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# POST /drive/organize-moments
# Organizes match social clips and highlight reels into moment-type subfolders:
#   - Highlights/
#   - Tries/
#   - Scrums/
#   - Lineouts/
#   - Conversions & Kicks/
#   - General Play/
#   - Opposing Team Videos/
#       - Tries/
#       - Scrums/
#       - Lineouts/
#       - Conversions & Kicks/
#       - General Play/
# Analyzes each clip to discern Fog positive vs Fog negative (Opposing team),
# routing opponent scores/wins to Opposing Team Videos/ while Fog positive clips
# stay in the primary moment structure.
# ---------------------------------------------------------------------------

def _event_id_from_clip_name(fname: str) -> Optional[str]:
    """Map 'veo_evt_034' or '..._try-034.mp4' clip names back to a manifest event id."""
    import re
    m = re.search(r"(veo_evt_\d+)", fname)
    if m:
        return m.group(1)
    m = re.search(r"-(\d{3,4})\.mp4$", fname)
    return f"veo_evt_{m.group(1)}" if m else None


def _event_type_from_clip_name(fname: str) -> str:
    lower = fname.lower()
    for candidate in ("try", "scrum", "lineout", "conversion", "kick"):
        if f"_{candidate}" in lower or f"-{candidate}" in lower:
            return candidate
    return ""


def _probe_duration(path: str) -> float:
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out) if out else 20.0
    except Exception:
        return 20.0


@app.route("/drive/organize-moments", methods=["POST"])
def organize_moments() -> Response:
    import re
    data = request.get_json(silent=True) or {}
    match_filter = data.get("match_id")
    # Safe by default: callers must explicitly pass dry_run=false to move files
    dry_run = bool(data.get("dry_run", True))
    opponent_kit: Optional[str] = data.get("opponent_kit")

    try:
        drive = DriveClient()
        changes = []

        out_files = drive.list_all_files(drive._output_folder_id)
        match_folders = [
            f for f in out_files
            if f.get("mimeType") == "application/vnd.google-apps.folder"
        ]

        if not match_folders:
            return jsonify({"status": "no_match_folders_found", "changes": []})

        for mf in match_folders:
            folder_id = mf["id"]
            folder_name = mf["name"]

            if match_filter and match_filter not in folder_name:
                continue

            manifest_data = drive.read_manifest(folder_name)
            if not manifest_data:
                mfiles = drive.list_all_files(folder_id)
                for f in mfiles:
                    if f["name"].endswith(".json"):
                        manifest_data = drive.read_manifest(f["name"])
                        if manifest_data:
                            break

            events_by_id = {}
            if manifest_data and "events" in manifest_data:
                events_by_id = {e["event_id"]: e for e in manifest_data["events"]}

            # 1. Create primary moment subfolders inside match folder
            primary_subfolder_ids = {}
            for f_name in (
                FOLDER_HIGHLIGHTS,
                FOLDER_TRIES,
                FOLDER_SCRUMS,
                FOLDER_LINEOUTS,
                FOLDER_KICKS,
                FOLDER_GENERAL,
                FOLDER_OPPOSING_TEAM,
                FOLDER_NEEDS_REVIEW,
            ):
                if not dry_run:
                    primary_subfolder_ids[f_name] = drive.get_or_create_subfolder(folder_id, f_name)
                else:
                    primary_subfolder_ids[f_name] = f"mock_{f_name}"

            # 2. Create nested subfolders inside Opposing Team Videos/
            opposing_parent_id = primary_subfolder_ids[FOLDER_OPPOSING_TEAM]
            opposing_subfolder_ids = {}
            for f_name in (
                FOLDER_TRIES,
                FOLDER_SCRUMS,
                FOLDER_LINEOUTS,
                FOLDER_KICKS,
                FOLDER_GENERAL,
            ):
                if not dry_run:
                    opposing_subfolder_ids[f_name] = drive.get_or_create_subfolder(opposing_parent_id, f_name)
                else:
                    opposing_subfolder_ids[f_name] = f"mock_opp_{f_name}"

            # 3. List all video files inside this match folder (recursive).
            #    16:9 first: the wider frame gives Gemini the most context, and the
            #    9:16 copy of the same event reuses that verdict.
            match_videos = drive.list_all_video_files_recursive(folder_id)
            match_videos.sort(key=lambda f: 0 if "16x9" in f["name"] else 1)

            _, _, opponent_slug = parse_match_identifiers(folder_name)
            opponent_name = opponent_slug.replace("-", " ").title() if opponent_slug else "Opponent"
            if manifest_data:
                opponent_name = manifest_data.get("opponent_name") or opponent_name

            verdicts: dict[str, dict[str, Any]] = {}

            with tempfile.TemporaryDirectory(prefix="fog_organize_") as tmpdir:
                for f in match_videos:
                    fid = f["id"]
                    fname = f["name"]
                    if not fname.endswith(".mp4"):
                        continue

                    # A. Highlight reels are built from verified Fog clips only
                    if "highlights" in fname.lower():
                        if not dry_run:
                            drive.move_file(fid, primary_subfolder_ids[FOLDER_HIGHLIGHTS])
                        changes.append({
                            "file_id": fid,
                            "file_name": fname,
                            "category": FOLDER_HIGHLIGHTS,
                            "target_folder": f"{folder_name}/{FOLDER_HIGHLIGHTS}",
                        })
                        continue

                    # B. Social clips: classify from the clip's own footage
                    ev_id = _event_id_from_clip_name(fname)
                    ev_data = events_by_id.get(ev_id, {}) if ev_id else {}
                    event_type = ev_data.get("event_type", "") or _event_type_from_clip_name(fname)
                    description = ev_data.get("description", "")

                    cache_key = ev_id or fname
                    sentiment_info = verdicts.get(cache_key)
                    if sentiment_info is None:
                        local_clip = os.path.join(tmpdir, f"{fid}.mp4")
                        try:
                            drive.download_file_to_path(fid, local_clip)
                            clip_duration = _probe_duration(local_clip)
                            sentiment_info = classify_event_sentiment(
                                event_id=cache_key,
                                event_type=event_type,
                                description=description,
                                start_time=0.0,
                                end_time=clip_duration,
                                video_path=local_clip,
                                opponent_name=opponent_name,
                                opponent_kit=opponent_kit,
                            )
                        finally:
                            if os.path.exists(local_clip):
                                os.remove(local_clip)
                        verdicts[cache_key] = sentiment_info

                    primary_folder, nested = get_target_subfolder_path(
                        event_type, sentiment=sentiment_info["sentiment"], filename=fname
                    )
                    if primary_folder == FOLDER_OPPOSING_TEAM:
                        target_folder_id = opposing_subfolder_ids.get(nested, opposing_parent_id)
                    elif primary_folder == FOLDER_NEEDS_REVIEW:
                        target_folder_id = primary_subfolder_ids[FOLDER_NEEDS_REVIEW]
                    else:
                        target_folder_id = primary_subfolder_ids.get(primary_folder, primary_subfolder_ids[FOLDER_GENERAL])
                    target_folder_name = "/".join(p for p in (folder_name, primary_folder, nested) if p)

                    if not dry_run:
                        drive.move_file(fid, target_folder_id)

                    changes.append({
                        "file_id": fid,
                        "file_name": fname,
                        "event_id": ev_id,
                        "category": nested or primary_folder,
                        "sentiment": sentiment_info["sentiment"],
                        "team": sentiment_info["team"],
                        "team_display": sentiment_info["team_display"],
                        "confidence": sentiment_info["confidence"],
                        "rationale": sentiment_info.get("rationale", ""),
                        "classified_by": sentiment_info.get("classified_by", "unverified"),
                        "target_folder": target_folder_name,
                    })

            # 4. Write the footage-based verdicts back onto manifest events (no re-guessing)
            if manifest_data and "events" in manifest_data and not dry_run:
                manifest_updated = False
                for ev in manifest_data["events"]:
                    v = verdicts.get(ev.get("event_id", ""))
                    if not v:
                        continue
                    ev["sentiment"] = v["sentiment"]
                    ev["sentiment_confidence"] = v["confidence"]
                    ev["sentiment_rationale"] = v.get("rationale", "")
                    ev["team"] = v["team"]
                    ev["team_display"] = v["team_display"]
                    ev["classified_by"] = v.get("classified_by")
                    manifest_updated = True

                if manifest_updated:
                    try:
                        updated_manifest_obj = Manifest.model_validate(manifest_data)
                        drive.write_manifest(updated_manifest_obj)
                    except Exception as mf_err:
                        logger.warning("Could not rewrite manifest: %s", mf_err)

        summary: dict[str, int] = {}
        for c in changes:
            key = c.get("sentiment", "highlight_reel")
            summary[key] = summary.get(key, 0) + 1
        return jsonify({
            "status": "complete",
            "dry_run": dry_run,
            "organized_clips_count": len(changes),
            "summary": summary,
            "changes": changes,
        })
    except Exception as exc:
        logger.exception("Failed to organize moments: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# GET /veo/match/<match_id_or_slug>
# Fetch video download details and pre-tagged AI rugby events from Veo.
# ---------------------------------------------------------------------------

@app.route("/veo/match/<match_id_or_slug>", methods=["GET"])
def get_veo_match(match_id_or_slug: str) -> Response:
    try:
        token = os.environ.get("VEO_API_TOKEN", "")
        client = VeoApiClient(token=token)
        details = client.resolve_match_details(match_id_or_slug)
        if not details:
            return jsonify({"error": f"Match not found on Veo: {match_id_or_slug}"}), 404
        return jsonify(details)
    except Exception as exc:
        logger.exception("Failed to resolve Veo match %s: %s", match_id_or_slug, exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# POST /veo/ingest
def _process_veo_ingest_job(job_id: str, slug: str, match_title: str, client: VeoApiClient, force: bool = False) -> None:
    job = _get_job(job_id)
    if not job:
        return
    start_time = time.time()
    try:
        job["stage"] = "resolving"
        job["stage_description"] = "Connecting to Veo API & resolving match video stream..."
        job["progress_pct"] = 5
        job["updated_at"] = time.time()
        _save_job(job_id, job)

        details = client.resolve_match_details(slug)
        if not details or not details.get("video_url"):
            job["stage"] = "error"
            job["error"] = f"Could not resolve video URL for match: {slug}"
            job["updated_at"] = time.time()
            _save_job(job_id, job)
            return

        video_url = details["video_url"]
        filename = get_master_video_filename(slug, quality="1080p")
        legacy_filename = f"{slug}_1080p.mp4"

        # Parse pre-tagged highlights early so the UI sees detected rugby events immediately
        events = parse_veo_highlights(details.get("highlights", []), source_id="veo_main")
        enriched_events = generate_clip_pairings(events)
        job["events_count"] = len(enriched_events)
        job["updated_at"] = time.time()
        _save_job(job_id, job)

        drive = DriveClient()
        drive_file_id = None

        # If not forcing re-download, check if 1080p video already exists in Drive Ingest folder
        if not force:
            downloaded_map = drive.list_downloaded_videos_map()
            existing_info = downloaded_map.get(slug) or downloaded_map.get(filename) or downloaded_map.get(legacy_filename)
            if not existing_info:
                for k, v in downloaded_map.items():
                    if (slug and slug in k) or (filename and filename in k) or (legacy_filename and legacy_filename in k):
                        existing_info = v
                        break
            if existing_info and existing_info.get("file_id"):
                drive_file_id = existing_info["file_id"]
                logger.info("Video %s already exists in Drive (file_id=%s). Skipping download.", filename, drive_file_id)
                job["stage"] = "analyzing"
                job["stage_description"] = f"Video already in Google Drive. Generating {len(enriched_events)} rugby moment pairings..."
                job["progress_pct"] = 90
                job["updated_at"] = time.time()
                _save_job(job_id, job)

        if not drive_file_id:
            job["stage"] = "streaming"
            job["stage_description"] = f"Streaming 1080p video from Veo CDN to Google Drive ({len(enriched_events)} events detected)..."
            job["progress_pct"] = 10
            job["updated_at"] = time.time()
            _save_job(job_id, job)

            last_time = time.time()
            last_bytes = 0

            def on_stream_progress(bytes_uploaded: int, total_bytes: int) -> None:
                nonlocal last_time, last_bytes
                now = time.time()
                elapsed = now - last_time
                if elapsed >= 0.5 or bytes_uploaded == total_bytes:
                    delta_bytes = bytes_uploaded - last_bytes if bytes_uploaded > last_bytes else 0
                    speed_bps = delta_bytes / max(elapsed, 0.001)
                    speed_mbps = round((speed_bps * 8) / (1024 * 1024), 1)

                    pct_stream = (bytes_uploaded / total_bytes) if total_bytes > 0 else 0
                    overall_pct = min(90, int(10 + pct_stream * 80))

                    mb_uploaded = round(bytes_uploaded / (1024 * 1024), 1)
                    mb_total = round(total_bytes / (1024 * 1024), 1)
                    eta_s = int((total_bytes - bytes_uploaded) / max(speed_bps, 1)) if total_bytes > bytes_uploaded else 0

                    job["progress_pct"] = overall_pct
                    job["bytes_uploaded"] = bytes_uploaded
                    job["total_bytes"] = total_bytes
                    job["mb_uploaded"] = mb_uploaded
                    job["mb_total"] = mb_total
                    job["speed_mbps"] = speed_mbps
                    job["eta_seconds"] = eta_s
                    job["stage_description"] = (
                        f"Streaming to Google Drive: {mb_uploaded} MB / {mb_total} MB "
                        f"({int(pct_stream * 100)}%) • {speed_mbps} Mbps"
                    )
                    job["updated_at"] = now
                    last_time = now
                    last_bytes = bytes_uploaded
                    _save_job(job_id, job)

            drive_file_id = drive.stream_url_to_folder(
                download_url=video_url,
                filename=filename,
                progress_callback=on_stream_progress,
            )

        job["stage"] = "analyzing"
        job["progress_pct"] = 92
        job["stage_description"] = "Assembling match manifest and saving to Google Drive..."
        job["updated_at"] = time.time()
        _save_job(job_id, job)

        # Construct and save manifest to Google Drive
        manifest = Manifest(
            match_id=slug,
            match_title=match_title,
            match_date="",
            sources=[
                VideoSource(
                    source_id="veo_main",
                    label="Veo Follow-Cam",
                    filename=filename,
                    drive_file_id=drive_file_id,
                    resolution=f"{details.get('width', 1920)}x{details.get('height', 1080)}",
                    fps=30.0,
                    duration_seconds=float(details.get("duration", 0.0)),
                    camera_type="veo",
                )
            ],
            events=enriched_events,
        )
        drive.write_manifest(manifest)

        job["stage"] = "complete"
        job["progress_pct"] = 100
        job["stage_description"] = f"Complete! {len(enriched_events)} rugby moments ready."
        job["manifest"] = manifest.model_dump()
        job["drive_file_id"] = drive_file_id
        job["updated_at"] = time.time()
        _save_job(job_id, job)
        logger.info("Ingest job %s finished in %.1fs", job_id, time.time() - start_time)

    except Exception as exc:
        logger.exception("Ingest job %s failed: %s", job_id, exc)
        raw_err = str(exc)
        mb_done = job.get("mb_uploaded", 0.0)
        mb_tot = job.get("mb_total", 0.0)

        if any(term in raw_err for term in ("SSLError", "Max retries exceeded", "ConnectionError", "EOF", "timed out")):
            clean_err = f"Google Drive connection dropped at {mb_done} MB / {mb_tot} MB. Click 'Retry Ingest' to resume."
        elif "Could not resolve video URL" in raw_err:
            clean_err = "Could not locate the 1080p video stream on Veo. The match may still be processing on Veo."
        elif "quota" in raw_err.lower() or "403" in raw_err:
            clean_err = "Google Drive API rate limit or quota exceeded. Please check Drive storage."
        else:
            clean_err = f"Ingest error: {raw_err[:160]}"

        job["stage"] = "error"
        job["error"] = clean_err
        job["stage_description"] = clean_err
        job["updated_at"] = time.time()
        _save_job(job_id, job)


# ---------------------------------------------------------------------------
# POST /veo/ingest
# Direct Cloud-to-Cloud ingestion with real-time status tracking:
# Returns job_id immediately (HTTP 202) while streaming proceeds in background.
# ---------------------------------------------------------------------------

@app.route("/veo/ingest", methods=["POST"])
def ingest_veo_match() -> Response:
    data = request.get_json(silent=True) or {}
    match_input = data.get("match") or data.get("match_id") or data.get("url")
    custom_title = data.get("title")

    if not match_input:
        return jsonify({"error": "match (URL, slug, or ID) is required"}), 400

    token = os.environ.get("VEO_API_TOKEN", "")
    client = VeoApiClient(token=token)
    slug = client.parse_slug_or_id(match_input)
    match_title = custom_title or f"SF Fog RFC — {slug.replace('-', ' ').title()}"

    force = bool(data.get("force", False))
    if not force:
        try:
            drive = DriveClient()
            existing_manifest = drive.read_manifest(slug)
            if existing_manifest:
                logger.info("Match %s is already ingested and analyzed; returning existing manifest.", slug)
                return jsonify({
                    "status": "already_ingested",
                    "job_id": None,
                    "match_id": slug,
                    "title": match_title,
                    "manifest": existing_manifest,
                    "message": "Match has already been downloaded and analyzed. Use force=true to re-ingest.",
                }), 200
        except Exception as e:
            logger.warning("Error checking for existing manifest for %s: %s", slug, e)

    job_id = uuid.uuid4().hex[:8]
    logger.info("Starting background Veo ingest job %s for match: %s (force=%s)", job_id, slug, force)

    initial_job_data = {
        "job_id": job_id,
        "match_id": slug,
        "title": match_title,
        "stage": "starting",
        "stage_description": "Initializing direct Veo-to-Drive ingestion...",
        "progress_pct": 0,
        "bytes_uploaded": 0,
        "total_bytes": 0,
        "mb_uploaded": 0.0,
        "mb_total": 0.0,
        "speed_mbps": 0.0,
        "eta_seconds": 0,
        "events_count": 0,
        "manifest": None,
        "drive_file_id": None,
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _save_job(job_id, initial_job_data)

    thread = threading.Thread(
        target=_process_veo_ingest_job,
        args=(job_id, slug, match_title, client, force),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "status": "processing",
        "job_id": job_id,
        "match_id": slug,
        "title": match_title,
        "message": f"Ingest started. Track live progress at /jobs/{job_id}",
    }), 202


# ---------------------------------------------------------------------------
# GET /jobs/<job_id>
# Live status tracker endpoint polled by the Game Day Media Hub UI.
# ---------------------------------------------------------------------------

@app.route("/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id: str) -> Response:
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": f"Job {job_id} not found"}), 404
    return jsonify(job)


# ---------------------------------------------------------------------------
# POST /analyze
# Trigger analysis on a newly uploaded Drive folder.
# Body (JSON):
#   match_id   str  — e.g. "2026-10-12-fog-vs-seahawks"
#   match_title str — e.g. "SF Fog RFC vs San Jose Seahawks"
#   folder_id  str  — Google Drive folder ID containing the raw match videos
# ---------------------------------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze() -> Response:
    data = request.get_json(silent=True) or {}

    match_id: Optional[str] = data.get("match_id")
    match_title: Optional[str] = data.get("match_title", "SF Fog RFC Match")
    folder_id: Optional[str] = data.get("folder_id")

    if not match_id or not folder_id:
        return jsonify({"error": "match_id and folder_id are required"}), 400

    job_id = str(uuid.uuid4())
    logger.info("Dispatching analysis job %s for match %s (folder: %s)", job_id, match_id, folder_id)

    try:
        manifest = run_analysis_job(
            job_id=job_id,
            match_id=match_id,
            match_title=match_title,
            folder_id=folder_id,
        )
        return jsonify({
            "job_id": job_id,
            "status": "complete",
            "match_id": match_id,
            "events_found": len(manifest.events),
            "manifest": manifest.model_dump(),
        })
    except Exception as exc:
        logger.exception("Analysis job %s failed: %s", job_id, exc)
        return jsonify({"job_id": job_id, "status": "error", "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# GET /manifest/<match_id>
# Retrieve the generated manifest for a completed match.
# ---------------------------------------------------------------------------

@app.route("/manifest/<match_id>", methods=["GET"])
def get_manifest(match_id: str) -> Response:
    try:
        drive = DriveClient()
        manifest_json = drive.read_manifest(match_id)
        if not manifest_json:
            return jsonify({"error": f"No manifest found for match_id: {match_id}"}), 404
        return jsonify(manifest_json)
    except Exception as exc:
        logger.exception("Failed to retrieve manifest for %s: %s", match_id, exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# POST /extract
# On-demand clip extraction triggered by Squarespace portal button click.
# Body (JSON):
#   match_id  str  — must have an existing manifest
#   event_id  str  — event ID to extract
#   format    str  — one of "16:9" | "9:16" | "1:1" | "4:5"
# ---------------------------------------------------------------------------

@app.route("/extract", methods=["POST"])
def extract() -> Response:
    data = request.get_json(silent=True) or {}

    match_id: Optional[str] = data.get("match_id")
    event_id: Optional[str] = data.get("event_id")
    fmt: str = data.get("format", "16:9")

    if not match_id or not event_id:
        return jsonify({"error": "match_id and event_id are required"}), 400

    if fmt not in ("16:9", "9:16", "1:1", "4:5"):
        return jsonify({"error": f"Invalid format '{fmt}'. Must be one of: 16:9, 9:16, 1:1, 4:5"}), 400

    try:
        result = run_extract_job(match_id=match_id, event_id=event_id, fmt=fmt)
        return jsonify(result)
    except Exception as exc:
        logger.exception("Extract job failed for event %s: %s", event_id, exc)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# POST /extract/batch
# Batch clip extraction triggered by Squarespace Match Review tab.
# Downloads the match video ONCE from Google Drive, cuts and reframes all
# requested clips, and uploads them to Drive in the background.
# Returns job_id immediately (HTTP 202) for real-time progress tracking.
# Body (JSON):
#   match_id  str                         — match ID / slug
#   items     list[{"event_id", "format"}] — list of clips to generate
# ---------------------------------------------------------------------------

@app.route("/extract/batch", methods=["POST"])
def batch_extract() -> Response:
    data = request.get_json(silent=True) or {}
    match_id: Optional[str] = data.get("match_id")
    items: list[dict[str, str]] = data.get("items") or []

    if not match_id or not items:
        return jsonify({"error": "match_id and a non-empty items list are required"}), 400

    job_id = uuid.uuid4().hex[:8]
    logger.info("Starting batch extraction job %s for match %s (%d items)", job_id, match_id, len(items))

    initial_job_data = {
        "job_id": job_id,
        "match_id": match_id,
        "stage": "starting",
        "stage_description": f"Starting batch extraction for {len(items)} clips...",
        "progress_pct": 0,
        "total_items": len(items),
        "completed_items": 0,
        "current_item": "",
        "results": [],
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _save_job(job_id, initial_job_data)

    def _worker():
        try:
            def on_progress(pct: int, desc: str, current_item: str, results: list):
                job = _get_job(job_id) or initial_job_data
                job["stage"] = "processing"
                job["progress_pct"] = pct
                job["stage_description"] = desc
                job["current_item"] = current_item
                job["results"] = results
                job["completed_items"] = len(results)
                job["updated_at"] = time.time()
                _save_job(job_id, job)

            res = run_batch_extract_job(
                job_id=job_id,
                match_id=match_id,
                items=items,
                progress_callback=on_progress,
            )
            job = _get_job(job_id) or initial_job_data
            job["stage"] = "complete" if res.get("status") != "error" else "error"
            job["progress_pct"] = 100
            job["stage_description"] = res.get("message", "Batch extraction complete.")
            job["results"] = res.get("results", [])
            job["completed_items"] = len(res.get("results", []))
            job["updated_at"] = time.time()
            _save_job(job_id, job)
        except Exception as exc:
            logger.exception("Batch extract job %s failed: %s", job_id, exc)
            job = _get_job(job_id) or initial_job_data
            job["stage"] = "error"
            job["error"] = str(exc)
            job["stage_description"] = f"Batch extraction error: {str(exc)[:160]}"
            job["updated_at"] = time.time()
            _save_job(job_id, job)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    return jsonify({
        "status": "processing",
        "job_id": job_id,
        "match_id": match_id,
        "items_count": len(items),
        "message": f"Batch extraction started. Track progress at /jobs/{job_id}",
    }), 202


# ---------------------------------------------------------------------------
# POST /highlights/build
# Assembles 16:9 Broadcast and 9:16 Action-Zoom highlight reels in Google Drive.
# ---------------------------------------------------------------------------

@app.route("/highlights/build", methods=["POST"])
def build_highlights() -> Response:
    data = request.get_json(silent=True) or {}
    match_id: Optional[str] = data.get("match_id")
    if not match_id:
        return jsonify({"error": "match_id is required"}), 400
    formats: list[str] = [f for f in data.get("formats", ["16:9", "9:16"]) if f in ("16:9", "9:16")]
    if not formats:
        return jsonify({"error": "formats must include '16:9' and/or '9:16'"}), 400
    zoom: float = min(max(float(data.get("zoom", 1.25)), 1.0), 2.0)
    max_moments: int = min(max(int(data.get("max_moments", 8)), 1), 20)
    event_tag: str = str(data.get("event_tag", "MATCH HIGHLIGHTS"))[:60]
    stream: bool = bool(data.get("stream", True))

    job_id = uuid.uuid4().hex[:8]
    logger.info("Starting highlights packaging job %s for match %s (stream=%s)", job_id, match_id, stream)

    initial_job_data = {
        "job_id": job_id,
        "match_id": match_id,
        "stage": "starting",
        "stage_description": "Starting highlight reel packaging in Cloud Run...",
        "progress_pct": 0,
        "reels": {},
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _save_job(job_id, initial_job_data)

    if stream:
        import queue
        q: queue.Queue = queue.Queue()

        def on_progress(p_dict: dict):
            job = _get_job(job_id) or initial_job_data
            job.update(p_dict)
            job["updated_at"] = time.time()
            _save_job(job_id, job)
            logger.info("[%s] %s (%s%%)", job_id, p_dict.get("stage_description"), p_dict.get("progress_pct"))
            q.put({"type": "progress", "job_id": job_id, **p_dict})

        def _stream_worker():
            try:
                res = run_highlights_job(job_id=job_id, match_id=match_id, formats=formats, zoom=zoom, max_moments=max_moments, event_tag=event_tag, progress_callback=on_progress)
                job = _get_job(job_id) or initial_job_data
                job["stage"] = "complete"
                job["progress_pct"] = 100
                job["stage_description"] = "Highlight reels generated and uploaded to Google Drive!"
                job["reels"] = res.get("reels", {})
                job["updated_at"] = time.time()
                _save_job(job_id, job)
                logger.info("[%s] HIGHLIGHTS JOB COMPLETE: %s", job_id, res.get("reels"))
                q.put({"type": "complete", "job_id": job_id, "status": "complete", "reels": res.get("reels", {})})
            except Exception as exc:
                logger.exception("Highlights job %s failed: %s", job_id, exc)
                job = _get_job(job_id) or initial_job_data
                job["stage"] = "error"
                job["error"] = str(exc)
                job["stage_description"] = f"Highlights packaging error: {str(exc)[:160]}"
                job["updated_at"] = time.time()
                _save_job(job_id, job)
                q.put({"type": "error", "job_id": job_id, "error": str(exc)})
            finally:
                q.put(None)

        t = threading.Thread(target=_stream_worker)
        t.start()

        def generate():
            yield f"data: {json.dumps({'type': 'started', 'job_id': job_id, 'match_id': match_id})}\n\n"
            while True:
                item = q.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    def _worker():
        try:
            def on_progress(p_dict: dict):
                job = _get_job(job_id) or initial_job_data
                job.update(p_dict)
                job["updated_at"] = time.time()
                _save_job(job_id, job)

            res = run_highlights_job(job_id=job_id, match_id=match_id, formats=formats, zoom=zoom, max_moments=max_moments, event_tag=event_tag, progress_callback=on_progress)
            job = _get_job(job_id) or initial_job_data
            job["stage"] = "complete"
            job["progress_pct"] = 100
            job["stage_description"] = "Highlight reels generated and uploaded to Google Drive!"
            job["reels"] = res.get("reels", {})
            job["updated_at"] = time.time()
            _save_job(job_id, job)
        except Exception as exc:
            logger.exception("Highlights job %s failed: %s", job_id, exc)
            job = _get_job(job_id) or initial_job_data
            job["stage"] = "error"
            job["error"] = str(exc)
            job["stage_description"] = f"Highlights packaging error: {str(exc)[:160]}"
            job["updated_at"] = time.time()
            _save_job(job_id, job)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    return jsonify({
        "status": "processing",
        "job_id": job_id,
        "match_id": match_id,
        "formats": formats,
        "message": f"Highlight packaging started. Track progress at /jobs/{job_id}",
    }), 202


# ---------------------------------------------------------------------------
# POST /veo/webhook
# Receives Veo match-ready notification (email body forwarded via Activepieces
# or a Veo API callback payload).
# ---------------------------------------------------------------------------

@app.route("/veo/webhook", methods=["POST"])
def veo_webhook() -> Response:
    data = request.get_json(silent=True) or {}

    match_id: Optional[str] = data.get("match_id")
    email_body: Optional[str] = data.get("email_body")

    if not match_id and email_body:
        match_id = parse_veo_email_body(email_body)

    if not match_id:
        return jsonify({"error": "Could not extract match_id from payload"}), 400

    logger.info("Veo webhook received for match: %s", match_id)

    job_id = str(uuid.uuid4())
    try:
        token = os.environ.get("VEO_API_TOKEN", "")
        client = VeoApiClient(token=token)
        events = fetch_veo_match_events(match_id, source_id="veo_main", client=client)
        enriched = generate_clip_pairings(events)

        manifest = Manifest(
            match_id=match_id,
            match_title=f"SF Fog RFC — Veo Match {match_id[:8]}",
            match_date="",
            sources=[],
            events=enriched,
        )
        drive = DriveClient()
        drive.write_manifest(manifest)

        return jsonify({
            "job_id": job_id,
            "status": "ingested",
            "match_id": match_id,
            "events_found": len(enriched),
        })
    except Exception as exc:
        logger.exception("Veo webhook processing failed for match %s: %s", match_id, exc)
        return jsonify({"job_id": job_id, "status": "error", "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Local dev entry point — Cloud Run uses gunicorn via Procfile/CMD
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
