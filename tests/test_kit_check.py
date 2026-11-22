# tests/test_kit_check.py
import json
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from engine.kit_check import apply_confirmation, confirmed_kits, detect_teams, draw_kit_check, extract_frame


def test_confirmed_kits_only_when_confirmed():
    assert confirmed_kits(None) is None
    assert confirmed_kits({"kit_check": {"fog_kit": "a", "opponent_kit": "b", "confirmed": False}}) is None
    assert confirmed_kits({"kit_check": {"fog_kit": "a", "opponent_kit": "b", "confirmed": True}}) == {
        "fog_kit": "a", "opponent_kit": "b"}


def test_apply_confirmation_swap_and_override():
    kc = apply_confirmation({"fog_kit": "silver", "opponent_kit": "red"}, swap=True)
    assert (kc["fog_kit"], kc["opponent_kit"], kc["confirmed"]) == ("red", "silver", True)
    kc = apply_confirmation({"fog_kit": "x", "opponent_kit": "y"}, opponent_kit="green hoops")
    assert kc["opponent_kit"] == "green hoops" and kc["fog_kit"] == "x"


@patch("engine.kit_check._gemini_request")
def test_detect_teams_parses_boxes_and_drops_bad_rows(mock_req, tmp_path):
    frame = tmp_path / "f.jpg"
    Image.new("RGB", (1920, 1080), (30, 120, 30)).save(frame)
    mock_req.return_value = MagicMock(json=MagicMock(return_value={"candidates": [{"content": {"parts": [{"text": json.dumps({
        "fog_kit_observed": "silver shirts", "opponent_kit_observed": "red shirts",
        "players": [
            {"box_2d": [100, 100, 300, 150], "team": "fog"},
            {"box_2d": [100, 600, 300, 650], "team": "opponent"},
            {"box_2d": [1, 2], "team": "fog"},
            {"box_2d": [100, 800, 300, 850], "team": "coach"},
        ]})}]}}]}))
    det = detect_teams(str(frame))
    assert [p["team"] for p in det["players"]] == ["fog", "opponent", "unknown"]
    out = draw_kit_check(str(frame), det, str(tmp_path / "out.png"))
    img = Image.open(out)
    assert img.size[0] == 1920 and img.size[1] > 1080  # legend strip added below the frame
    # Fog box outline is cyan at its top-left corner (x=192, y=108)
    assert img.getpixel((192, 108))[1] > 150


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_extract_frame_full_resolution(tmp_path):
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=3",
                    "-c:v", "libx264", "-preset", "ultrafast", str(clip)], check=True, capture_output=True)
    frame = extract_frame(str(clip), 1.0, str(tmp_path / "f.jpg"))
    assert Image.open(frame).size == (1920, 1080)
