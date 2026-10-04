# tests/test_clipper.py
import pytest
from engine.clipper import build_lossless_cut_command, build_reframe_command

def test_build_lossless_cut_command():
    cmd = build_lossless_cut_command("raw.mp4", start=60.0, end=85.0, output_path="clip.mp4")
    assert "-ss 55.0" in cmd  # 60 - 5s buffer
    assert "-to 92.0" in cmd  # 85 + 7s buffer
    assert "-c copy" in cmd
    assert "clip.mp4" in cmd

def test_build_9x16_reframe_command():
    cmd = build_reframe_command("clip.mp4", "social_9x16.mp4", aspect_ratio="9:16", master_audio=True)
    assert "scale=1080:1920" in cmd
    assert "crop=1080:1920" in cmd  # zoom-to-fill, no letterbox padding
    assert "pad=" not in cmd
    assert "yuv420p" in cmd
    assert "+faststart" in cmd
    assert "loudnorm=I=-14" in cmd

def test_build_1x1_reframe_command():
    cmd = build_reframe_command("clip.mp4", "social_1x1.mp4", aspect_ratio="1:1", master_audio=True)
    assert "scale=1080:1080" in cmd
    assert "crop=1080:1080" in cmd

def test_build_4x5_reframe_command():
    cmd = build_reframe_command("clip.mp4", "social_4x5.mp4", aspect_ratio="4:5", master_audio=True)
    assert "scale=1080:1350" in cmd
    assert "crop=1080:1350" in cmd
