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
  GEMINI_API_KEY           - Gemini API key
  VEO_API_TOKEN            - Optional Veo API bearer token (for private recordings)
"""

import os
import uuid
import logging
import threading
import time
from typing import Any, Optional

from flask import Flask, jsonify, request, Response

# In-memory job registry for real-time progress tracking
JOBS: dict[str, dict[str, Any]] = {}

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
from cloud_service.job_runner import run_analysis_job, run_extract_job

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
        token = os.environ.get("VEO_API_TOKEN", "")
        client = VeoApiClient(token=token)
        recordings = client.list_club_recordings(club_slug=club_slug)

        formatted = []
        for r in recordings:
            formatted.append({
                "identifier": r.get("identifier"),
                "slug": r.get("slug"),
                "title": r.get("title", "SF Fog Match"),
                "start": r.get("start") or r.get("created"),
                "duration": r.get("duration"),
                "thumbnail": r.get("thumbnail"),
                "url": f"https://app.veo.co{r.get('url')}" if r.get("url") else None,
                "status": r.get("processing_status"),
            })

        return jsonify({
            "club": club_slug,
            "count": len(formatted),
            "recordings": formatted,
        })
    except Exception as exc:
        logger.exception("Failed to fetch Veo recordings: %s", exc)
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
def _process_veo_ingest_job(job_id: str, slug: str, match_title: str, client: VeoApiClient) -> None:
    job = JOBS.get(job_id)
    if not job:
        return
    start_time = time.time()
    try:
        job["stage"] = "resolving"
        job["stage_description"] = "Connecting to Veo API & resolving match video stream..."
        job["progress_pct"] = 5
        job["updated_at"] = time.time()

        details = client.resolve_match_details(slug)
        if not details or not details.get("video_url"):
            job["stage"] = "error"
            job["error"] = f"Could not resolve video URL for match: {slug}"
            job["updated_at"] = time.time()
            return

        video_url = details["video_url"]
        filename = f"{slug}_1080p.mp4"

        # Parse pre-tagged highlights early so the UI sees detected rugby events immediately
        events = parse_veo_highlights(details.get("highlights", []), source_id="veo_main")
        enriched_events = generate_clip_pairings(events)
        job["events_count"] = len(enriched_events)
        job["stage"] = "streaming"
        job["stage_description"] = f"Streaming 1080p video from Veo CDN to Google Drive ({len(enriched_events)} events detected)..."
        job["progress_pct"] = 10
        job["updated_at"] = time.time()

        drive = DriveClient()
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

        drive_file_id = drive.stream_url_to_folder(
            download_url=video_url,
            filename=filename,
            progress_callback=on_stream_progress,
        )

        job["stage"] = "analyzing"
        job["progress_pct"] = 92
        job["stage_description"] = "Assembling match manifest and saving to Google Drive..."
        job["updated_at"] = time.time()

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
                    duration=0.0,
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
        logger.info("Ingest job %s finished in %.1fs", job_id, time.time() - start_time)

    except Exception as exc:
        logger.exception("Ingest job %s failed: %s", job_id, exc)
        job["stage"] = "error"
        job["error"] = str(exc)
        job["updated_at"] = time.time()


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

    job_id = uuid.uuid4().hex[:8]
    logger.info("Starting background Veo ingest job %s for match: %s", job_id, slug)

    JOBS[job_id] = {
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

    thread = threading.Thread(
        target=_process_veo_ingest_job,
        args=(job_id, slug, match_title, client),
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
    job = JOBS.get(job_id)
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
