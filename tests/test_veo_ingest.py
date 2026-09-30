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


def test_veo_api_client_pagination_and_expiration():
    from cloud_service.veo_api_client import VeoApiClient
    client = VeoApiClient()
    mock_resp_p1 = MagicMock()
    mock_resp_p1.status_code = 200
    mock_resp_p1.json.return_value = [
        {
            "identifier": "id_1",
            "slug": "match-1",
            "title": "Match 1",
            "expiration_status": "expires-soon",
            "time_to_expiry": {"unit": "days", "value": 26},
        },
        {
            "identifier": "id_2",
            "slug": "match-2",
            "title": "Match 2",
            "expiration_status": "expired",
            "time_to_expiry": {"unit": "days", "value": -10},
        },
    ]

    mock_resp_p2 = MagicMock()
    mock_resp_p2.status_code = 404

    client._session.get = MagicMock(side_effect=[mock_resp_p1, mock_resp_p2])
    recs = client.list_club_recordings(fetch_all=True)
    assert len(recs) == 2
    assert recs[0]["is_expiring_soon"] is True
    assert recs[0]["is_expired"] is False
    assert recs[0]["days_until_expiry"] == 26
    assert recs[1]["is_expiring_soon"] is False
    assert recs[1]["is_expired"] is True

