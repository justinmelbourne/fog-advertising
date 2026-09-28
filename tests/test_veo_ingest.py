# tests/test_veo_ingest.py
import pytest
from unittest.mock import MagicMock
from engine.veo_ingest import parse_veo_email_body, fetch_veo_match_events

def test_parse_veo_email_body():
    email_text = """
    Hi Fog Rugby,
    Your Veo match SF Fog vs BATS Rugby is ready for viewing!
    Watch here: https://app.veo.co/matches/78a9c2d1-4455-4a11-8c43-98234710abcd/
    Enjoy your highlights!
    """
    match_id = parse_veo_email_body(email_text)
    assert match_id == "78a9c2d1-4455-4a11-8c43-98234710abcd"

def test_fetch_veo_match_events():
    mock_client = MagicMock()
    mock_client.get_match_data.return_value = {
        "title": "SF Fog RFC vs BATS Rugby",
        "highlights": [
            {
                "id": "hl_001",
                "type": "goal",
                "start": 840,
                "end": 865,
                "label": "Try scored by Fog"
            },
            {
                "id": "hl_002",
                "type": "half_start",
                "start": 0,
                "end": 10,
                "label": "First Half"
            }
        ]
    }
    events = fetch_veo_match_events("78a9c2d1-4455-4a11-8c43-98234710abcd", source_id="veo_01", client=mock_client)
    assert len(events) == 1  # half_start filtered out, try retained
    assert events[0].event_type == "try"
    assert events[0].start_time == 840.0
    assert events[0].duration == 25.0
