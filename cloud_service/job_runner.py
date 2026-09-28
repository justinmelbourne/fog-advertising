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
from typing import Optional

from engine.models import Manifest, VideoSource, Event
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
        social_filename = f"{event_id}_{fmt.replace(':', 'x')}.mp4"
        social_path = os.path.join(tmpdir, social_filename)

        if fmt == "16:9":
            # Already 16:9 master — just upload that
            social_path = master_path
            social_filename = f"{event_id}_master_16x9.mp4"
        else:
            reframe_cmd = build_reframe_command(master_path, social_path, aspect_ratio=fmt)  # type: ignore[arg-type]
            _run_ffmpeg(reframe_cmd)

        # Upload to Drive output folder
        file_id = drive.upload_file_to_folder(social_path, social_filename, output_folder_id)

        return {
            "status": "complete",
            "event_id": event_id,
            "format": fmt,
            "filename": social_filename,
            "drive_file_id": file_id,
            "message": f"Clip exported as {fmt} and saved to Drive. File ID: {file_id}",
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
