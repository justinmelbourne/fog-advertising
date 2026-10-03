"""
job_runner.py — Core job orchestration for Cloud Run workers
=============================================================
run_analysis_job: Downloads video files from Drive, runs audio analysis,
                  ingests Veo AI tags, enriches with AI editorial engine,
                  writes manifest back to Drive.

run_extract_job: Reads an existing manifest, executes FFmpeg clip extraction
                 for a specific event and format, uploads result to Drive.
"""

import logging
import os
import subprocess
import tempfile
from typing import Any, Callable, Optional

from engine.models import Manifest, VideoSource, Event
from engine.naming import (
    get_social_clip_filename,
    get_highlight_reel_filename,
    get_match_folder_name,
    slugify_moment,
    get_target_subfolder_path,
    FOLDER_HIGHLIGHTS,
)
from engine.team_analyzer import classify_event_sentiment
from engine.audio_analyzer import detect_whistle_timestamps, compute_rms_energy_peaks
from engine.ai_suggester import generate_clip_pairings
from engine.cli import generate_match_manifest_from_events
from engine.clipper import build_lossless_cut_command, build_reframe_command
from cloud_service.drive_client import DriveClient

logger = logging.getLogger(__name__)


def run_analysis_job(
    job_id: str,
    match_id: str,
    match_title: str,
    folder_id: str,
) -> Manifest:
    """
    1. List all video files in the provided Drive folder
    2. Download each file to a temp directory
    3. Extract audio and run whistle + excitement detection
    4. Combine events from all sources
    5. Enrich with AI editorial pairing
    6. Write manifest.json back to Drive
    7. Clean up temp files
    """
    drive = DriveClient()
    video_files = drive.list_video_files(folder_id)

    if not video_files:
        raise ValueError(f"No video files found in Drive folder {folder_id}")

    sources: list[VideoSource] = []
    all_events: list[Event] = []

    with tempfile.TemporaryDirectory(prefix=f"fog_job_{job_id}_") as tmpdir:
        for vf in video_files:
            file_id: str = vf["id"]
            filename: str = vf["name"]
            local_path = os.path.join(tmpdir, filename)

            logger.info("[%s] Downloading %s (%s bytes)...", job_id, filename, vf.get("size", "?"))
            drive.download_file_to_path(file_id, local_path)

            # Probe video metadata with FFprobe
            source_id = file_id[:12]
            duration, resolution, fps = _probe_video_metadata(local_path)

            camera_type = "phone" if _is_portrait(resolution) else "veo"
            source = VideoSource(
                source_id=source_id,
                filename=filename,
                duration_seconds=duration,
                resolution=resolution,
                fps=fps,
                camera_type=camera_type,
            )
            sources.append(source)

            # Extract audio and run analysis
            wav_path = os.path.join(tmpdir, f"{source_id}.wav")
            _extract_audio_to_wav(local_path, wav_path)

            try:
                import librosa
                y, sr = librosa.load(wav_path, sr=22050, mono=True)

                whistles = detect_whistle_timestamps(y, sr=sr)
                cheers = compute_rms_energy_peaks(y, sr=sr, threshold_factor=2.0)

                for i, ts in enumerate(whistles):
                    # Pair each whistle with the nearest cheer window
                    cheer_end = _find_cheer_after(ts, cheers)
                    all_events.append(Event(
                        event_id=f"{source_id}_whistle_{i+1:03d}",
                        source_id=source_id,
                        event_type="try",
                        start_time=ts,
                        end_time=cheer_end if cheer_end else ts + 25.0,
                        duration=(cheer_end - ts) if cheer_end else 25.0,
                        excitement_score=0.88,
                        detection_source="audio_whistle+cheer",
                        description=f"Referee whistle + crowd cheer detected ({filename})",
                    ))

            except ImportError:
                logger.warning("librosa not available; skipping audio analysis for %s", filename)
            finally:
                # Purge intermediate audio stem immediately
                if os.path.exists(wav_path):
                    os.remove(wav_path)
                    logger.debug("Purged audio stem: %s", wav_path)

    # Enrich all events with AI editorial pairing
    manifest = generate_match_manifest_from_events(match_id, match_title, sources, all_events)

    # Write manifest to Drive
    drive.write_manifest(manifest)
    logger.info("[%s] Analysis complete: %d events written to manifest", job_id, len(manifest.events))

    return manifest


def run_extract_job(match_id: str, event_id: str, fmt: str) -> dict:
    """
    1. Read manifest from Drive
    2. Find the requested event
    3. Download source video to temp
    4. Execute FFmpeg lossless cut + reframe
    5. Upload social clip back to Drive output folder
    6. Return download metadata
    """
    drive = DriveClient()
    manifest_data = drive.read_manifest(match_id)
    if not manifest_data:
        raise ValueError(f"Manifest not found for match_id: {match_id}")

    manifest = Manifest.model_validate(manifest_data)

    event = next((e for e in manifest.events if e.event_id == event_id), None)
    if not event:
        raise ValueError(f"Event {event_id} not found in manifest {match_id}")

    source = next((s for s in manifest.sources if s.source_id == event.source_id), None)
    if not source:
        raise ValueError(f"Source {event.source_id} not found in manifest")

    output_folder_id = os.environ["DRIVE_OUTPUT_FOLDER_ID"]

    with tempfile.TemporaryDirectory(prefix=f"fog_extract_{event_id}_") as tmpdir:
        # We need the source file from Drive — find it by name
        all_files = drive.list_video_files(os.environ["DRIVE_INGEST_FOLDER_ID"])
        file_record = next((f for f in all_files if f["name"] == source.filename), None)
        if not file_record:
            raise ValueError(f"Source file '{source.filename}' not found in Drive ingest folder")

        local_src = os.path.join(tmpdir, source.filename)
        drive.download_file_to_path(file_record["id"], local_src)

        # Cut lossless master
        master_path = os.path.join(tmpdir, f"{event_id}_master.mp4")
        cut_cmd = build_lossless_cut_command(local_src, event.start_time, event.end_time, master_path)
        _run_ffmpeg(cut_cmd)

        # Reframe to requested social format
        moment_type = slugify_moment(event.event_type, event.description)
        social_filename = get_social_clip_filename(match_id, fmt, moment_type)
        social_path = os.path.join(tmpdir, social_filename)

        if fmt == "16:9":
            # Already 16:9 master
            social_path = master_path
        else:
            reframe_cmd = build_reframe_command(master_path, social_path, aspect_ratio=fmt)  # type: ignore[arg-type]
            _run_ffmpeg(reframe_cmd)

        # Determine sentiment & subfolder routing
        sentiment_info = classify_event_sentiment(
            event_id=event.event_id,
            event_type=event.event_type,
            description=event.description,
            start_time=event.start_time,
            end_time=event.end_time,
            video_path=master_path,
        )
        primary_folder, nested_subfolder = get_target_subfolder_path(
            event.event_type,
            sentiment=sentiment_info["sentiment"],
            filename=social_filename,
        )

        # Upload to target moment subfolder inside match folder
        match_folder_id = drive.get_or_create_match_folder(output_folder_id, match_id)
        target_folder_id = drive.get_or_create_subfolder(match_folder_id, primary_folder)
        if nested_subfolder:
            target_folder_id = drive.get_or_create_subfolder(target_folder_id, nested_subfolder)

        file_id = drive.upload_file_to_folder(social_path, social_filename, target_folder_id)

        return {
            "status": "complete",
            "event_id": event_id,
            "format": fmt,
            "filename": social_filename,
            "drive_file_id": file_id,
            "sentiment": sentiment_info["sentiment"],
            "team": sentiment_info["team"],
            "message": f"Clip exported as {fmt} ({social_filename}) and saved to Drive. File ID: {file_id}",
        }


def run_batch_extract_job(
    job_id: str,
    match_id: str,
    items: list[dict[str, str]],
    progress_callback: Optional[Any] = None,
) -> dict:
    """
    Execute batch clip extraction and aspect-ratio reframing for multiple events.
    Downloads the source video ONCE and cuts/reframes all requested clips.

    items: list of dicts, e.g. [{"event_id": "...", "format": "9:16"}, ...]
    Formats supported: "16:9", "9:16", "1:1", "4:5"
    """
    drive = DriveClient()
    manifest_data = drive.read_manifest(match_id)
    if not manifest_data:
        raise ValueError(f"Manifest not found for match_id: {match_id}")

    manifest = Manifest.model_validate(manifest_data)
    output_folder_id = os.environ["DRIVE_OUTPUT_FOLDER_ID"]

    # Validate items against events in manifest
    valid_items = []
    for item in items:
        eid = item.get("event_id")
        fmt = item.get("format", "16:9")
        if fmt not in ("16:9", "9:16", "1:1", "4:5"):
            continue
        ev = next((e for e in manifest.events if e.event_id == eid), None)
        if ev:
            valid_items.append({"event_id": eid, "format": fmt, "event": ev})

    if not valid_items:
        raise ValueError("No matching valid events found in manifest for batch extraction")

    total_items = len(valid_items)
    results = []

    with tempfile.TemporaryDirectory(prefix=f"fog_batch_{job_id}_") as tmpdir:
        # Cache downloaded sources so each video is downloaded only ONCE
        downloaded_sources: dict[str, str] = {}
        # Cache master cuts so multiple aspect ratios for the same event don't re-cut
        cut_masters: dict[str, str] = {}

        if progress_callback:
            progress_callback(5, "Resolving match source video...", "", results)

        for idx, item in enumerate(valid_items):
            event_id = item["event_id"]
            fmt = item["format"]
            event: Event = item["event"]

            source = next((s for s in manifest.sources if s.source_id == event.source_id), None)
            source_filename = source.filename if source else f"{match_id}_1080p.mp4"
            source_id = source.source_id if source else "veo_main"

            # 1. Download source video once if not yet downloaded
            if source_id not in downloaded_sources:
                if progress_callback:
                    progress_callback(
                        10,
                        f"Downloading match master video from Google Drive ({source_filename})...",
                        "",
                        results,
                    )

                # Locate source video file in Drive
                file_id = getattr(source, "drive_file_id", None)
                if not file_id:
                    ingest_folder_id = os.environ.get("DRIVE_INGEST_FOLDER_ID", "")
                    all_files = drive.list_video_files(ingest_folder_id)
                    file_record = next(
                        (f for f in all_files if f["name"] == source_filename or match_id in f["name"]),
                        None,
                    )
                    if file_record:
                        file_id = file_record["id"]
                    else:
                        downloaded_map = drive.list_downloaded_videos_map()
                        existing_info = downloaded_map.get(match_id) or downloaded_map.get(source_filename)
                        if existing_info:
                            file_id = existing_info.get("file_id")

                if not file_id:
                    raise ValueError(f"Could not locate source video file '{source_filename}' in Drive")

                local_src = os.path.join(tmpdir, source_filename)
                logger.info("[%s] Downloading source %s (file_id=%s) to %s", job_id, source_filename, file_id, local_src)
                drive.download_file_to_path(file_id, local_src)
                downloaded_sources[source_id] = local_src

            local_src = downloaded_sources[source_id]

            # Current item progress update
            pct = int(15 + ((idx) / total_items) * 80)
            desc_event = event.description or event.event_type or event_id
            if progress_callback:
                progress_callback(
                    pct,
                    f"Processing clip {idx + 1}/{total_items}: {desc_event} ({fmt})...",
                    event_id,
                    results,
                )

            try:
                # 2. Cut master 16:9 lossless if not already cut for this event
                master_path = cut_masters.get(event_id)
                if not master_path or not os.path.exists(master_path):
                    master_path = os.path.join(tmpdir, f"{event_id}_master.mp4")
                    cut_cmd = build_lossless_cut_command(local_src, event.start_time, event.end_time, master_path)
                    _run_ffmpeg(cut_cmd)
                    cut_masters[event_id] = master_path

                # 3. Reframe to format
                moment_type = slugify_moment(event.event_type, event.description)
                social_filename = get_social_clip_filename(match_id, fmt, moment_type)
                social_path = os.path.join(tmpdir, social_filename)

                if fmt == "16:9":
                    social_path = master_path
                else:
                    reframe_cmd = build_reframe_command(master_path, social_path, aspect_ratio=fmt)
                    _run_ffmpeg(reframe_cmd)

                # 4. Determine sentiment & subfolder routing
                sentiment_info = classify_event_sentiment(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    description=event.description,
                    start_time=event.start_time,
                    end_time=event.end_time,
                    video_path=master_path,
                )
                primary_folder, nested_subfolder = get_target_subfolder_path(
                    event.event_type,
                    sentiment=sentiment_info["sentiment"],
                    filename=social_filename,
                )

                # Upload to target moment subfolder inside match folder
                match_folder_id = drive.get_or_create_match_folder(output_folder_id, match_id)
                target_folder_id = drive.get_or_create_subfolder(match_folder_id, primary_folder)
                if nested_subfolder:
                    target_folder_id = drive.get_or_create_subfolder(target_folder_id, nested_subfolder)

                uploaded_id = drive.upload_file_to_folder(social_path, social_filename, target_folder_id)

                results.append({
                    "event_id": event_id,
                    "format": fmt,
                    "filename": social_filename,
                    "drive_file_id": uploaded_id,
                    "sentiment": sentiment_info["sentiment"],
                    "team": sentiment_info["team"],
                    "status": "success",
                    "description": desc_event,
                })
                logger.info("[%s] Batch extracted %s (%s) [%s] -> Drive file %s (%s)", job_id, event_id, fmt, sentiment_info["sentiment"], uploaded_id, social_filename)

            except Exception as item_err:
                logger.exception("[%s] Failed to extract clip %s (%s): %s", job_id, event_id, fmt, item_err)
                results.append({
                    "event_id": event_id,
                    "format": fmt,
                    "status": "error",
                    "error": str(item_err),
                    "description": desc_event,
                })

            # Update progress after completing item
            pct_after = int(15 + ((idx + 1) / total_items) * 80)
            if progress_callback:
                progress_callback(
                    pct_after,
                    f"Completed {idx + 1}/{total_items}: {desc_event} ({fmt})",
                    event_id,
                    results,
                )

        success_count = sum(1 for r in results if r.get("status") == "success")
        return {
            "status": "complete" if success_count > 0 else "error",
            "match_id": match_id,
            "total_items": total_items,
            "success_count": success_count,
            "results": results,
            "message": f"Extracted and saved {success_count}/{total_items} clips to Google Drive.",
        }


def run_highlights_job(
    job_id: str,
    match_id: str,
    formats: list[str] = ["16:9", "9:16"],
    zoom: float = 1.25,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """
    Server-side Cloud Run worker that compiles 16:9 Broadcast Highlights
    and 9:16 Vertical Action-Zoom Highlights directly in Google Drive.
    """
    from engine.highlight_packager import build_16x9_reel, build_9x16_reel
    from googleapiclient.http import MediaFileUpload

    drive = DriveClient()
    output_folder_id = os.environ["DRIVE_OUTPUT_FOLDER_ID"]
    match_folder_id = drive.get_or_create_match_folder(output_folder_id, match_id)

    if progress_callback:
        progress_callback({"stage": "scanning", "progress_pct": 5, "stage_description": "Locating match clips in Google Drive..."})

    # Search in both the match folder and the root output folder
    out_files = drive.list_all_files(match_folder_id) + drive.list_all_files(output_folder_id)

    events_needed = [
        'veo_evt_028', 'veo_evt_004', 'veo_evt_017', 'veo_evt_010',
        'veo_evt_034', 'veo_evt_038', 'veo_evt_032', 'veo_evt_036'
    ]

    with tempfile.TemporaryDirectory(prefix=f"highlights_{job_id}_") as tmpdir:
        raw_dir = os.path.join(tmpdir, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        clip_paths = {}

        for idx, ev_id in enumerate(events_needed):
            # Locate file matching event id and 16x9 or master
            fid = None
            for f in out_files:
                fname = f["name"]
                if (fname == f"{ev_id}_master_16x9.mp4") or (ev_id in fname and ("16x9" in fname or "master" in fname)):
                    fid = f["id"]
                    break

            if not fid:
                raise ValueError(f"Required master clip for {ev_id} not found in Drive output folder or match subfolder.")

            local_path = os.path.join(raw_dir, f"{ev_id}.mp4")
            if progress_callback:
                progress_callback({
                    "stage": "downloading",
                    "progress_pct": int(5 + (idx / len(events_needed)) * 15),
                    "stage_description": f"Streaming {ev_id} ({idx+1}/{len(events_needed)}) to Cloud Run worker..."
                })
            drive.download_file_to_path(fid, local_path)
            clip_paths[ev_id] = local_path

        uploaded_reels = {}

        # Create or retrieve Highlights subfolder inside match folder
        highlights_folder_id = drive.get_or_create_subfolder(match_folder_id, FOLDER_HIGHLIGHTS)

        # 16:9 Broadcast Reel
        if "16:9" in formats:
            def p_16x9(pct: int, desc: str):
                if progress_callback:
                    progress_callback({"stage": "rendering_16x9", "progress_pct": int(20 + pct * 0.35), "stage_description": desc})

            reel_16x9_name = get_highlight_reel_filename(match_id, "16x9", "match-highlights")
            reel_16x9 = os.path.join(tmpdir, reel_16x9_name)
            build_16x9_reel(tmpdir, clip_paths, reel_16x9, progress_fn=p_16x9)

            if progress_callback:
                progress_callback({"stage": "uploading", "progress_pct": 55, "stage_description": "Uploading 16:9 Broadcast Highlights to Drive..."})

            media = MediaFileUpload(reel_16x9, mimetype="video/mp4", resumable=True)
            res = drive._service.files().create(
                body={"name": reel_16x9_name, "parents": [highlights_folder_id]},
                media_body=media,
                supportsAllDrives=True
            ).execute()
            uploaded_reels["16:9"] = {
                "file_id": res["id"],
                "name": reel_16x9_name,
                "url": f"https://drive.google.com/file/d/{res['id']}/view?usp=drivesdk"
            }

        # 9:16 Vertical Action-Zoom Reel
        if "9:16" in formats:
            def p_9x16(pct: int, desc: str):
                if progress_callback:
                    progress_callback({"stage": "rendering_9x16", "progress_pct": int(55 + pct * 0.40), "stage_description": desc})

            reel_9x16_name = get_highlight_reel_filename(match_id, "9x16", "match-highlights")
            reel_9x16 = os.path.join(tmpdir, reel_9x16_name)
            build_9x16_reel(tmpdir, clip_paths, reel_9x16, progress_fn=p_9x16)

            if progress_callback:
                progress_callback({"stage": "uploading", "progress_pct": 95, "stage_description": "Uploading 9:16 Action-Zoom Reel to Drive..."})

            media = MediaFileUpload(reel_9x16, mimetype="video/mp4", resumable=True)
            res = drive._service.files().create(
                body={"name": reel_9x16_name, "parents": [highlights_folder_id]},
                media_body=media,
                supportsAllDrives=True
            ).execute()
            uploaded_reels["9:16"] = {
                "file_id": res["id"],
                "name": reel_9x16_name,
                "url": f"https://drive.google.com/file/d/{res['id']}/view?usp=drivesdk"
            }

        if progress_callback:
            progress_callback({"stage": "complete", "progress_pct": 100, "stage_description": "Highlights generated and saved to Drive!"})

        return {
            "status": "complete",
            "match_id": match_id,
            "reels": uploaded_reels
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _probe_video_metadata(path: str) -> tuple[float, str, float]:
    """Return (duration_seconds, resolution_string, fps) using ffprobe."""
    import json
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "v:0", path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        width = stream.get("width", 1920)
        height = stream.get("height", 1080)
        duration = float(stream.get("duration", 0) or stream.get("tags", {}).get("DURATION", "0").split(".")[0])
        fps_raw = stream.get("r_frame_rate", "30/1")
        num, den = fps_raw.split("/")
        fps = round(int(num) / int(den), 2)
        return duration, f"{width}x{height}", fps
    except Exception as exc:
        logger.warning("ffprobe failed for %s: %s — using defaults", path, exc)
        return 0.0, "1920x1080", 30.0


def _is_portrait(resolution: str) -> bool:
    parts = resolution.split("x")
    if len(parts) == 2:
        return int(parts[1]) > int(parts[0])
    return False


def _extract_audio_to_wav(video_path: str, wav_path: str) -> None:
    """Extract mono 22050Hz WAV from video using FFmpeg."""
    cmd = f'ffmpeg -y -i "{video_path}" -vn -ac 1 -ar 22050 -f wav "{wav_path}"'
    _run_ffmpeg(cmd)


def _run_ffmpeg(cmd: str) -> None:
    """Execute an FFmpeg shell command string, raising on non-zero exit."""
    logger.debug("FFmpeg: %s", cmd)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed (exit {result.returncode}):\n{result.stderr[-2000:]}")


def _find_cheer_after(whistle_ts: float, cheer_windows: list[tuple[float, float]]) -> Optional[float]:
    """Find the end of the first cheer window that starts after whistle_ts (within 30s)."""
    for start, end in cheer_windows:
        if whistle_ts <= start <= whistle_ts + 30.0:
            return end
    return None
