# tests/test_models.py
import pytest
from pydantic import ValidationError
from engine.models import Manifest, VideoSource, Event, PairingSuggestion

def test_manifest_serialization():
    source = VideoSource(
        source_id="veo_01",
        filename="veo_half1.mp4",
        duration_seconds=2400.0,
        resolution="1920x1080",
        fps=30.0,
        camera_type="veo"
    )
    event = Event(
        event_id="evt_001",
        source_id="veo_01",
        event_type="try",
        start_time=855.0,
        end_time=878.0,
        duration=23.0,
        excitement_score=0.95,
        detection_source="veo_ai_tag+audio_cheer",
        description="Corner breakaway try",
        suggested_uses=["hype_reel_hook"],
        suggested_pairings=[
            PairingSuggestion(
                paired_event_id="evt_002",
                reason="Sideline phone celebration of this try"
            )
        ],
        suggested_caption="Try time on Treasure Island! 🏉",
        suggested_hashtags=["#SFFogRFC", "#FogRugby"]
    )
    manifest = Manifest(
        match_id="2026-10-10-fog-vs-seahorses",
        match_title="SF Fog RFC vs San Jose Seahawks",
        match_date="2026-10-10",
        pitch="Treasure Island Pitch 1",
        sources=[source],
        events=[event]
    )

    json_str = manifest.model_dump_json()
    assert "2026-10-10-fog-vs-seahorses" in json_str
    assert "evt_001" in json_str

    deserialized = Manifest.model_validate_json(json_str)
    assert deserialized.match_title == "SF Fog RFC vs San Jose Seahawks"
    assert len(deserialized.events) == 1
    assert deserialized.events[0].suggested_pairings[0].paired_event_id == "evt_002"
