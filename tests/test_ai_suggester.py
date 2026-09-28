# tests/test_ai_suggester.py
import pytest
from engine.models import Event
from engine.ai_suggester import generate_clip_pairings, assign_editorial_uses

def test_assign_editorial_uses():
    event = Event(
        event_id="e1",
        source_id="s1",
        event_type="try",
        start_time=100.0,
        end_time=120.0,
        duration=20.0,
        excitement_score=0.92,
        detection_source="veo",
        description="Try scored by Fog"
    )
    enriched = assign_editorial_uses(event)
    assert "hype_reel_hook" in enriched.suggested_uses
    assert "#SFFogRFC" in enriched.suggested_hashtags
    assert len(enriched.suggested_caption) > 0

def test_generate_clip_pairings():
    veo_try = Event(
        event_id="veo_01",
        source_id="veo",
        event_type="try",
        start_time=800.0,
        end_time=825.0,
        duration=25.0,
        excitement_score=0.95,
        detection_source="veo",
        description="Corner Try"
    )
    phone_celebration = Event(
        event_id="phone_01",
        source_id="phone",
        event_type="celebration",
        start_time=10.0,
        end_time=25.0,
        duration=15.0,
        excitement_score=0.88,
        detection_source="phone",
        description="Sideline bench jumping and cheering"
    )
    pairings = generate_clip_pairings([veo_try, phone_celebration])
    assert len(pairings[0].suggested_pairings) == 1
    assert pairings[0].suggested_pairings[0].paired_event_id == "phone_01"
