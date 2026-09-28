# tests/test_scanner.py
import os
import json
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from engine.scanner import classify_camera_type, process_audio_file_for_events
from engine.models import VideoSource, Event

def test_classify_camera_type():
    assert classify_camera_type("veo_match_half1.mp4", width=1920, height=1080) == "veo"
    assert classify_camera_type("veo_cam_02.MOV", width=3840, height=2160) == "veo"
    assert classify_camera_type("IMG_4920.mov", width=1080, height=1920) == "phone"
    assert classify_camera_type("sideline_alex.mp4", width=1920, height=1080) == "phone"

def test_process_audio_file_for_events():
    sr = 22050
    duration = 20.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = 0.05 * np.random.randn(len(t))

    # Whistle at 5.0s
    w_start, w_end = int(5.0 * sr), int(5.5 * sr)
    y[w_start:w_end] += 0.8 * np.sin(2 * np.pi * 3800 * t[w_start:w_end])

    # Cheering at 6.0s to 10.0s
    c_start, c_end = int(6.0 * sr), int(10.0 * sr)
    y[c_start:c_end] *= 6.0

    events = process_audio_file_for_events(y, sr=sr, source_id="phone_01")
    assert len(events) >= 1
    ev = events[0]
    assert ev.source_id == "phone_01"
    assert ev.start_time <= 6.0
    assert ev.end_time >= 9.0
    assert ev.excitement_score >= 0.80
