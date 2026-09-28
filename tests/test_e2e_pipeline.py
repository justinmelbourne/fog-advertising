# tests/test_e2e_pipeline.py
import os
import json
import pytest
import numpy as np
from engine.models import VideoSource, Event
from engine.audio_analyzer import detect_whistle_timestamps, compute_rms_energy_peaks
from engine.ai_suggester import generate_clip_pairings
from engine.cli import generate_match_manifest_from_events
from engine.clipper import build_lossless_cut_command, build_reframe_command

def test_full_pipeline_flow():
    # 1. Synthesize audio stream with whistle and cheer
    sr = 22050
    duration = 30.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = 0.05 * np.random.randn(len(t))

    # Whistle at 10.0s for 0.5s
    w_start, w_end = int(10.0 * sr), int(10.5 * sr)
    y[w_start:w_end] += 0.8 * np.sin(2 * np.pi * 3800 * t[w_start:w_end])

    # Cheering at 11.0s to 15.0s
    c_start, c_end = int(11.0 * sr), int(15.0 * sr)
    y[c_start:c_end] *= 6.0

    whistles = detect_whistle_timestamps(y, sr=sr)
    cheers = compute_rms_energy_peaks(y, sr=sr)

    assert len(whistles) >= 1
    assert len(cheers) >= 1

    # 2. Build Event
    event = Event(
        event_id="test_001",
        source_id="match_half1",
        event_type="try",
        start_time=whistles[0],
        end_time=cheers[0][1],
        duration=cheers[0][1] - whistles[0],
        excitement_score=0.92,
        detection_source="audio_whistle+cheer",
        description="Try following whistle"
    )

    source = VideoSource(
        source_id="match_half1",
        filename="match.mp4",
        duration_seconds=duration,
        resolution="1920x1080",
        fps=30.0,
        camera_type="veo"
    )

    manifest = generate_match_manifest_from_events("2026-10-10-e2e", "E2E Test Match", [source], [event])
    assert len(manifest.events) == 1
    assert "hype_reel_hook" in manifest.events[0].suggested_uses

    # 3. Test on-demand clipping commands
    cut_cmd = build_lossless_cut_command("match.mp4", event.start_time, event.end_time, "clip.mp4")
    assert "-c copy" in cut_cmd

    reframe_9x16 = build_reframe_command("clip.mp4", "clip_9x16.mp4", aspect_ratio="9:16")
    assert "scale=1080:1920" in reframe_9x16
    assert "loudnorm=I=-14" in reframe_9x16

    reframe_1x1 = build_reframe_command("clip.mp4", "clip_1x1.mp4", aspect_ratio="1:1")
    assert "scale=1080:1080" in reframe_1x1

    reframe_4x5 = build_reframe_command("clip.mp4", "clip_4x5.mp4", aspect_ratio="4:5")
    assert "scale=1080:1350" in reframe_4x5
