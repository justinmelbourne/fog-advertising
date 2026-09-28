# engine/scanner.py
import os
import re
import json
import subprocess
import numpy as np
from scipy.io import wavfile
from typing import List, Tuple, Optional
from engine.models import VideoSource, Event, Manifest
from engine.audio_analyzer import detect_whistle_timestamps, compute_rms_energy_peaks
from engine.ai_suggester import generate_clip_pairings

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv"}

def classify_camera_type(filename: str, width: int = 1920, height: int = 1080) -> str:
    """Classify video as Veo tactical pitch camera or sideline phone footage."""
    fn_lower = filename.lower()
    if "veo" in fn_lower:
        return "veo"
    if height > width:  # 9:16 vertical orientation
        return "phone"
    if any(k in fn_lower for k in ["img_", "phone", "sideline", "mobile", "clip"]):
        return "phone"
    return "phone"

def process_audio_file_for_events(y: np.ndarray, sr: int = 22050, source_id: str = "video_01") -> List[Event]:
    """Detect excitement and whistle bursts in audio stream and generate Candidate Events."""
    whistles = detect_whistle_timestamps(y, sr=sr)
    cheers = compute_rms_energy_peaks(y, sr=sr)
    events: List[Event] = []
    event_idx = 1

    matched_cheers = set()

    # Correlate whistle with subsequent or overlapping cheering
    for w in whistles:
        # Look for a cheer starting within 4 seconds after whistle
        correlated_cheer = None
        for idx, (c_start, c_end) in enumerate(cheers):
            if idx not in matched_cheers and (w - 1.0 <= c_start <= w + 4.0 or c_start <= w <= c_end):
                correlated_cheer = (c_start, c_end)
                matched_cheers.add(idx)
                break

        if correlated_cheer:
            c_start, c_end = correlated_cheer
            start_time = min(w, c_start)
            end_time = max(w + 3.0, c_end)
            duration = end_time - start_time
            events.append(Event(
                event_id=f"{source_id}_evt_{event_idx:03d}",
                source_id=source_id,
                event_type="try",
                start_time=round(start_time, 2),
                end_time=round(end_time, 2),
                duration=round(duration, 2),
                excitement_score=0.92,
                detection_source="audio_whistle+cheering",
                description="Whistle followed by crowd cheering (Potential Try or Penalty Kick)"
            ))
            event_idx += 1
        else:
            # Standalone whistle
            events.append(Event(
                event_id=f"{source_id}_evt_{event_idx:03d}",
                source_id=source_id,
                event_type="whistle_stoppage",
                start_time=round(max(0.0, w - 3.0), 2),
                end_time=round(w + 5.0, 2),
                duration=8.0,
                excitement_score=0.70,
                detection_source="audio_whistle",
                description="Referee whistle stoppage (Tackle, Penalty, or Lineout)"
            ))
            event_idx += 1

    # Remaining unmatched high-energy cheering segments
    for idx, (c_start, c_end) in enumerate(cheers):
        if idx not in matched_cheers:
            events.append(Event(
                event_id=f"{source_id}_evt_{event_idx:03d}",
                source_id=source_id,
                event_type="celebration",
                start_time=round(c_start, 2),
                end_time=round(c_end, 2),
                duration=round(c_end - c_start, 2),
                excitement_score=0.85,
                detection_source="audio_cheering",
                description="Sideline cheering / reaction surge"
            ))
            event_idx += 1

    return events

def probe_video_file(file_path: str) -> VideoSource:
    """Use ffprobe to inspect video duration, resolution, and framerate."""
    basename = os.path.basename(file_path)
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json", file_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        stream = data.get("streams", [{}])[0]
        fmt = data.get("format", {})

        width = int(stream.get("width", 1920))
        height = int(stream.get("height", 1080))
        duration = float(stream.get("duration") or fmt.get("duration", 0.0))

        fps_str = stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = round(float(num) / float(den), 2) if float(den) > 0 else 30.0
        else:
            fps = float(fps_str)

        camera_type = classify_camera_type(basename, width=width, height=height)
        source_id = os.path.splitext(basename)[0]

        return VideoSource(
            source_id=source_id,
            filename=file_path,
            duration_seconds=round(duration, 2),
            resolution=f"{width}x{height}",
            fps=fps,
            camera_type=camera_type
        )
    except Exception:
        # Fallback if ffprobe is absent or fails on mock
        return VideoSource(
            source_id=os.path.splitext(basename)[0],
            filename=file_path,
            duration_seconds=60.0,
            resolution="1920x1080",
            fps=30.0,
            camera_type=classify_camera_type(basename)
        )

def extract_audio_stem(video_path: str, wav_path: str) -> bool:
    """Extract mono 22050Hz WAV audio stem from video using FFmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1",
        wav_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except Exception:
        return False

def scan_match_directory(dir_path: str, match_title: str = "SF Fog RFC Match") -> Manifest:
    """Scan all videos in a game-day directory, run audio event detection, and produce manifest.json."""
    video_files = [
        os.path.join(dir_path, f) for f in os.listdir(dir_path)
        if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
    ]

    sources: List[VideoSource] = []
    all_events: List[Event] = []

    for vf in sorted(video_files):
        source = probe_video_file(vf)
        sources.append(source)

        temp_wav = os.path.join(dir_path, f"temp_{source.source_id}.wav")
        if extract_audio_stem(vf, temp_wav) and os.path.exists(temp_wav):
            try:
                sr, raw_audio = wavfile.read(temp_wav)
                # Convert int16 to float32 between -1.0 and 1.0
                if raw_audio.dtype == np.int16:
                    y = raw_audio.astype(np.float32) / 32768.0
                else:
                    y = raw_audio.astype(np.float32)

                events = process_audio_file_for_events(y, sr=sr, source_id=source.source_id)
                all_events.extend(events)
            finally:
                # Disk space hygiene: delete temporary audio file immediately
                if os.path.exists(temp_wav):
                    os.remove(temp_wav)

    # Enrich events with AI suggestions and cross-clip pairings
    enriched_events = generate_clip_pairings(all_events)
    folder_basename = os.path.basename(os.path.abspath(dir_path))
    match_id = folder_basename if folder_basename else "match-manifest"

    manifest = Manifest(
        match_id=match_id,
        match_title=match_title,
        match_date=match_id.split("-")[0] if "-" in match_id else "2026-10-10",
        sources=sources,
        events=enriched_events
    )

    manifest_path = os.path.join(dir_path, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest.model_dump_json(indent=2))

    return manifest
