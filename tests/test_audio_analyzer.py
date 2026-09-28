# tests/test_audio_analyzer.py
import numpy as np
import pytest
from engine.audio_analyzer import detect_whistle_timestamps, compute_rms_energy_peaks

def test_detect_whistle_frequencies():
    sr = 22050
    duration = 5.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # Generate background noise + a 3.8 kHz referee whistle tone at t=2.0s for 0.5s
    signal = 0.05 * np.random.randn(len(t))
    whistle_start = int(2.0 * sr)
    whistle_end = int(2.5 * sr)
    signal[whistle_start:whistle_end] += 0.8 * np.sin(2 * np.pi * 3800 * t[whistle_start:whistle_end])

    whistles = detect_whistle_timestamps(signal, sr=sr)
    assert len(whistles) >= 1
    assert 1.8 <= whistles[0] <= 2.2

def test_compute_rms_energy_peaks():
    sr = 22050
    duration = 10.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    signal = 0.05 * np.random.randn(len(t))
    # Add a cheering surge at t=6.0 to 8.0s
    cheer_start = int(6.0 * sr)
    cheer_end = int(8.0 * sr)
    signal[cheer_start:cheer_end] *= 8.0

    peaks = compute_rms_energy_peaks(signal, sr=sr, threshold_factor=3.0)
    assert len(peaks) >= 1
    start, end = peaks[0]
    assert 5.5 <= start <= 6.5
    assert 7.0 <= end <= 8.5
