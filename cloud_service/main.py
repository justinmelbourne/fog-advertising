"""
SF Fog RFC - Rugby Video Analysis Cloud Run API
================================================
Stateless REST API designed to run on Google Cloud Run (Python 3.11 / Flask).
Triggered by the Squarespace portal JS, Veo notification webhooks, and
Drive watch-channel push notifications.

All video assets live in Google Workspace Shared Drive (100 TB nonprofit quota).
Processing is done in-container (FFmpeg + Librosa) and results written back to Drive.

Endpoints:
  POST /analyze            - Trigger analysis of a Drive folder for a match
  GET  /manifest/<match_id> - Retrieve generated manifest.json for a match
  POST /extract            - Kick off on-demand FFmpeg clip extraction
  POST /veo/webhook        - Receive Veo email-style notification (or API callback)
  GET  /health             - Cloud Run health check

Environment Variables (set via Secret Manager):
  GOOGLE_CLOUD_PROJECT     - GCP project ID
  DRIVE_INGEST_FOLDER_ID   - Google Drive folder ID for game day ingest
  DRIVE_OUTPUT_FOLDER_ID   - Google Drive folder ID for social-ready clips
  GCS_BUCKET               - Cloud Storage bucket for proxy previews
  GEMINI_API_KEY           - Gemini API key (from Secret Manager in prod)
  VEO_API_TOKEN            - Veo API bearer token
"""

import os
import uuid
import logging
from typing import Any, Optional

from flask import Flask, jsonify, request, Response

# Local engine imports (bundled in same container image)
from engine.models import Manifest, VideoSource, Event
from engine.veo_ingest import parse_veo_email_body, fetch_veo_match_events
from engine.ai_suggester import generate_clip_pairings
from engine.clipper import build_lossless_cut_command, build_reframe_command
from cloud_service.drive_client import DriveClient
from cloud_service.job_runner import run_analysis_job, run_extract_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Health check — required by Cloud Run
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health() -> Response:
    return jsonify({"status": "ok", "service": "fog-video-analysis-api"})


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
# Body (JSON):
#   email_body str  — raw Veo email text (optional, for email-parse path)
#   match_id   str  — Veo match UUID (optional, for direct API path)
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
        # Fetch events via Veo API and trigger a full analysis job
        from cloud_service.veo_api_client import VeoApiClient
        veo_client = VeoApiClient(token=os.environ.get("VEO_API_TOKEN", ""))
        events = fetch_veo_match_events(match_id, source_id="veo_main", client=veo_client)
        enriched = generate_clip_pairings(events)

        manifest = Manifest(
            match_id=match_id,
            match_title=f"SF Fog RFC — Veo Match {match_id[:8]}",
            match_date="",  # Populated from Veo metadata in production
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
