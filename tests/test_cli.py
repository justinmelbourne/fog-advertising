# tests/test_cli.py
import json
import pytest
from engine.cli import generate_match_manifest_from_events
from engine.models import VideoSource, Event

def test_generate_match_manifest():
    source = VideoSource(
        source_id="v1", filename="game.mp4", duration_seconds=120.0, resolution="1920x1080", fps=30.0, camera_type="veo"
    )
    event = Event(
        event_id="e1", source_id="v1", event_type="try", start_time=10.0, end_time=30.0, duration=20.0, excitement_score=0.9, detection_source="test", description="Test try"
    )
    manifest = generate_match_manifest_from_events("2026-10-10-test", "SF Fog vs Test RFC", [source], [event])
    assert manifest.match_id == "2026-10-10-test"
    assert len(manifest.events) == 1
    assert "hype_reel_hook" in manifest.events[0].suggested_uses
