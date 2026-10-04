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


def test_studio_page_is_public_and_has_no_data(client, monkeypatch):
    monkeypatch.setenv("FOG_API_KEY", "s3cret")
    c = main.app.test_client()
    resp = c.get("/studio")
    assert resp.status_code == 200 and b"Fog Studio" in resp.data
    assert c.get("/studio/config").get_json() == {"auth_required": True}


def test_data_endpoints_need_key(monkeypatch):
    monkeypatch.setenv("FOG_API_KEY", "s3cret")
    c = main.app.test_client()
    assert c.get("/api/matches").status_code == 401
    assert c.get("/api/match-status?match_id=x").status_code == 401
    assert c.get("/kit-check/image?match_id=x").status_code == 401


def test_api_matches_lists_folders(client):
    drive = _fake_drive()
    with patch.object(main, "DriveClient", return_value=drive):
        body = client.get("/api/matches").get_json()
    assert body == {"matches": [{"id": "matchfolder", "name": "20260822_v4fb17b0_sf-fog-vs-sydney-convicts-1"}]}


def test_organize_background_job_completes(client):
    import time as _t
    drive = _fake_drive()
    with patch.object(main, "DriveClient", return_value=drive):
        start = client.post("/drive/organize-moments", json={"background": True})
        assert start.status_code == 202
        job_id = start.get_json()["job_id"]
        for _ in range(100):
            job = client.get(f"/jobs/{job_id}").get_json()
            if job["stage"] in ("complete", "error"):
                break
            _t.sleep(0.05)
    assert job["stage"] == "complete", job
    assert job["result"]["summary"] == {"neutral": 2}
    drive.move_file.assert_not_called()


def test_manual_verdict_saved_and_reused_by_sort(client):
    drive = _fake_drive()
    with patch.object(main, "DriveClient", return_value=drive):
        body = client.post("/api/verdict", json={"match_id": "sydney-convicts-1",
                           "verdicts": [{"event_id": "veo_evt_034", "sentiment": "fog_positive"}]}).get_json()
        assert body == {"status": "saved", "updated": ["veo_evt_034"], "missing": []}
        drive.read_manifest.return_value = drive.write_manifest.call_args.args[0].model_dump()
        drive.read_manifest.return_value["kit_check"] = {"fog_kit": "a", "opponent_kit": "b", "confirmed": True}
        with patch.object(main, "classify_event_sentiment") as gemini:
            client.post("/drive/organize-moments", json={"dry_run": False})
    gemini.assert_not_called()  # the human verdict wins; no Gemini call
    assert {c.args[1] for c in drive.move_file.call_args_list} == {"matchfolder/Tries"}


def test_verdict_validation(client):
    assert client.post("/api/verdict", json={"match_id": "x", "verdicts": [{"event_id": "e", "sentiment": "great"}]}).status_code == 400


def test_dry_run_saves_verdicts_without_moving(client):
    drive = _fake_drive()
    fake = {"sentiment": "fog_negative", "team": "opponent", "team_display": "Sydney", "confidence": 0.9,
            "rationale": "r", "classified_by": "gemini:vertex:m", "lean": "fog_negative"}
    with patch.object(main, "DriveClient", return_value=drive), \
         patch.object(main, "classify_event_sentiment", return_value=fake):
        client.post("/drive/organize-moments", json={"dry_run": True})
    drive.move_file.assert_not_called()
    saved = drive.write_manifest.call_args.args[0]
    ev = saved.events[0]
    assert (ev.sentiment, ev.classified_by, ev.sentiment_lean) == ("fog_negative", "gemini:vertex:m", "fog_negative")


def test_confirming_kits_clears_ai_verdicts_but_keeps_manual(client):
    drive = _fake_drive()
    m = drive.read_manifest.return_value
    m["kit_check"] = {"fog_kit": "A", "opponent_kit": "B", "confirmed": False}
    m["events"].append(dict(m["events"][0], event_id="veo_evt_001", sentiment="fog_positive", classified_by="manual", sentiment_confidence=1.0))
    m["events"][0].update(sentiment="fog_negative", classified_by="gemini:vertex:m", sentiment_confidence=0.9)
    with patch.object(main, "DriveClient", return_value=drive):
        client.post("/kit-check/confirm", json={"match_id": "sydney-convicts-1"})
    saved = {e.event_id: e for e in drive.write_manifest.call_args.args[0].events}
    assert saved["veo_evt_034"].classified_by is None and saved["veo_evt_034"].sentiment == "neutral"
    assert saved["veo_evt_001"].classified_by == "manual" and saved["veo_evt_001"].sentiment == "fog_positive"
