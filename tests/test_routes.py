# tests/test_routes.py
from unittest.mock import MagicMock, patch

import pytest

import cloud_service.main as main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FOG_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return main.app.test_client()


def _fake_drive():
    drive = MagicMock()
    drive._output_folder_id = "out"
    drive.list_all_files.return_value = [{
        "id": "matchfolder", "name": "20260822_v4fb17b0_sf-fog-vs-sydney-convicts-1",
        "mimeType": "application/vnd.google-apps.folder",
    }]
    drive.read_manifest.return_value = {
        "match_id": "m", "match_title": "t", "match_date": "",
        "events": [{"event_id": "veo_evt_034", "event_type": "try", "start_time": 925, "end_time": 945,
                    "duration": 20, "excitement_score": 0.9, "detection_source": "veo", "description": "Veo AI Try",
                    "source_id": "veo_main"}],
    }
    drive.list_all_video_files_recursive.return_value = [
        {"id": "c1", "name": "20260822_v4fb17b0_fog-rugby_9x16_try-034.mp4"},
        {"id": "c2", "name": "20260822_v4fb17b0_fog-rugby_16x9_try-034.mp4"},
    ]
    drive.get_or_create_subfolder.side_effect = lambda parent, name: f"{parent}/{name}"
    return drive


def test_organize_defaults_to_dry_run_and_never_trusts_unverified(client):
    drive = _fake_drive()
    with patch.object(main, "DriveClient", return_value=drive):
        resp = client.post("/drive/organize-moments", json={})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["dry_run"] is True
    drive.move_file.assert_not_called()
    # No Gemini key -> unverified -> Needs Review, never a Fog folder
    assert {c["sentiment"] for c in body["changes"]} == {"neutral"}
    assert all("/Needs Review" in c["target_folder"] for c in body["changes"])
    # Both formats of the same event share one verdict (one download)
    assert drive.download_file_to_path.call_count == 1


def test_organize_live_blocked_until_kit_check_confirmed(client):
    drive = _fake_drive()
    with patch.object(main, "DriveClient", return_value=drive):
        body = client.post("/drive/organize-moments", json={"dry_run": False}).get_json()
    drive.move_file.assert_not_called()
    assert body["status"] == "blocked"
    assert body["blocked_needs_kit_check"] == ["20260822_v4fb17b0_sf-fog-vs-sydney-convicts-1"]


def test_organize_live_after_confirmation_uses_confirmed_kits(client):
    drive = _fake_drive()
    drive.read_manifest.return_value["kit_check"] = {
        "fog_kit": "silver shirts, white shorts", "opponent_kit": "green hoops", "confirmed": True,
    }
    with patch.object(main, "DriveClient", return_value=drive), \
         patch.object(main, "classify_event_sentiment", wraps=main.classify_event_sentiment) as spy:
        client.post("/drive/organize-moments", json={"dry_run": False})
    targets = {call.args[1] for call in drive.move_file.call_args_list}
    assert targets == {"matchfolder/Needs Review"}  # no Gemini in tests -> unverified
    assert spy.call_args.kwargs["fog_kit"] == "silver shirts, white shorts"
    assert spy.call_args.kwargs["opponent_kit"] == "green hoops"


def test_kit_check_confirm_requires_kit_check(client):
    drive = _fake_drive()
    with patch.object(main, "DriveClient", return_value=drive):
        resp = client.post("/kit-check/confirm", json={"match_id": "sydney-convicts-1"})
    assert resp.status_code == 409


def test_kit_check_confirm_swap(client):
    drive = _fake_drive()
    drive.read_manifest.return_value["kit_check"] = {"fog_kit": "A", "opponent_kit": "B", "confirmed": False}
    with patch.object(main, "DriveClient", return_value=drive):
        body = client.post("/kit-check/confirm", json={"match_id": "sydney-convicts-1", "swap": True}).get_json()
    assert body == {"status": "confirmed", "match_id": "sydney-convicts-1", "fog_kit": "B", "opponent_kit": "A"}
    saved = drive.write_manifest.call_args.args[0]
    assert saved.kit_check["confirmed"] is True


def test_highlights_build_requires_match_id(client):
    assert client.post("/highlights/build", json={}).status_code == 400


def test_api_key_gate(monkeypatch):
    monkeypatch.setenv("FOG_API_KEY", "s3cret")
    c = main.app.test_client()
    assert c.get("/health").status_code == 200
    assert c.post("/highlights/build", json={}).status_code == 401
    assert c.get("/drive/debug").status_code == 401
    assert c.post("/highlights/build", json={}, headers={"X-Fog-Api-Key": "s3cret"}).status_code == 400
