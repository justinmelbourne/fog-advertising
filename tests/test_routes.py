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


def test_organize_live_moves_to_needs_review(client):
    drive = _fake_drive()
    with patch.object(main, "DriveClient", return_value=drive):
        client.post("/drive/organize-moments", json={"dry_run": False})
    targets = {call.args[1] for call in drive.move_file.call_args_list}
    assert targets == {"matchfolder/Needs Review"}


def test_highlights_build_requires_match_id(client):
    assert client.post("/highlights/build", json={}).status_code == 400


def test_api_key_gate(monkeypatch):
    monkeypatch.setenv("FOG_API_KEY", "s3cret")
    c = main.app.test_client()
    assert c.get("/health").status_code == 200
    assert c.post("/highlights/build", json={}).status_code == 401
    assert c.get("/drive/debug").status_code == 401
    assert c.post("/highlights/build", json={}, headers={"X-Fog-Api-Key": "s3cret"}).status_code == 400
