# tests/test_batch_extract.py
import pytest
from unittest.mock import MagicMock, patch
from engine.models import Manifest, VideoSource, Event
from cloud_service.job_runner import run_batch_extract_job
from cloud_service.main import app

@pytest.fixture
def mock_manifest_dict():
    ev1 = Event(
        event_id="veo_main_highlight_001",
        source_id="veo_main",
        event_type="try",
        start_time=100.0,
        end_time=125.0,
        duration=25.0,
        excitement_score=0.95,
        detection_source="veo_ai",
        description="Try scored in corner",
    )
    ev2 = Event(
        event_id="veo_main_highlight_002",
        source_id="veo_main",
        event_type="conversion",
        start_time=130.0,
        end_time=145.0,
        duration=15.0,
        excitement_score=0.85,
        detection_source="veo_ai",
        description="Conversion kick",
    )
    src = VideoSource(
        source_id="veo_main",
        filename="match_1080p.mp4",
        drive_file_id="drive_src_123",
        duration_seconds=3600.0,
        resolution="1920x1080",
        fps=30.0,
        camera_type="veo",
    )
    manifest = Manifest(
        match_id="test-match-slug",
        match_title="SF Fog RFC Test Match",
        match_date="2026-09-30",
        sources=[src],
        events=[ev1, ev2],
    )
    return manifest.model_dump()


def test_run_batch_extract_job_success(mock_manifest_dict, monkeypatch):
    monkeypatch.setenv("DRIVE_OUTPUT_FOLDER_ID", "output_folder_xyz")
    monkeypatch.setenv("DRIVE_INGEST_FOLDER_ID", "ingest_folder_xyz")

    with patch("cloud_service.job_runner.DriveClient") as MockDriveClient, \
         patch("cloud_service.job_runner._run_ffmpeg") as mock_ffmpeg:

        mock_drive = MagicMock()
        mock_drive.read_manifest.return_value = mock_manifest_dict
        mock_drive.upload_file_to_folder.side_effect = lambda path, name, folder: f"uploaded_{name}"
        MockDriveClient.return_value = mock_drive

        progress_calls = []
        def progress_cb(pct, desc, cur, res):
            progress_calls.append((pct, desc, cur, len(res)))

        items = [
            {"event_id": "veo_main_highlight_001", "format": "9:16"},
            {"event_id": "veo_main_highlight_001", "format": "1:1"},
            {"event_id": "veo_main_highlight_002", "format": "4:5"},
        ]

        result = run_batch_extract_job(
            job_id="job123",
            match_id="test-match-slug",
            items=items,
            progress_callback=progress_cb,
        )

        assert result["status"] == "complete"
        assert result["total_items"] == 3
        assert result["success_count"] == 3
        assert len(result["results"]) == 3

        # Check that download_file_to_path was called ONCE for the source video (not 3 times!)
        assert mock_drive.download_file_to_path.call_count == 1

        # Check that 3 files were uploaded to Drive
        assert mock_drive.upload_file_to_folder.call_count == 3

        # Verify progress callback was invoked
        assert len(progress_calls) > 0


def test_batch_extract_api_route():
    client = app.test_client()

    # Empty payload -> 400
    res = client.post("/extract/batch", json={})
    assert res.status_code == 400

    # Valid payload -> 202 accepted with job_id
    with patch("cloud_service.main.run_batch_extract_job") as mock_job:
        mock_job.return_value = {"status": "complete", "results": []}
        res = client.post("/extract/batch", json={
            "match_id": "test-match-slug",
            "items": [{"event_id": "ev1", "format": "9:16"}],
        })
        assert res.status_code == 202
        data = res.get_json()
        assert data["status"] == "processing"
        assert "job_id" in data
