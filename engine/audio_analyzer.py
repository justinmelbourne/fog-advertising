# engine/audio_analyzer.py
import numpy as np
from scipy.signal import butter, filtfilt
from typing import List, Tuple

WHISTLE_LOW_HZ = 3300.0
WHISTLE_HIGH_HZ = 4200.0

def butter_bandpass(lowcut: float, highcut: float, fs: int, order: int = 5):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    return b, a

def detect_whistle_timestamps(y: np.ndarray, sr: int = 22050, threshold_factor: float = 5.0) -> List[float]:
    """Isolate referee whistle frequency band (3.3-4.2 kHz) via bandpass STFT and detect sharp energy bursts using robust MAD."""
    b, a = butter_bandpass(WHISTLE_LOW_HZ, WHISTLE_HIGH_HZ, sr, order=4)
    filtered = filtfilt(b, a, y)
    energy = filtered ** 2

    window_size = int(sr * 0.1)  # 100ms
    if len(energy) < window_size:
        return []
    
    smoothed = np.convolve(energy, np.ones(window_size) / window_size, mode='same')
    baseline = np.median(smoothed)
    mad = np.median(np.abs(smoothed - baseline))
    threshold = baseline + threshold_factor * (mad * 1.4826 + 1e-5)

    whistle_indices = np.where(smoothed > threshold)[0]
    if len(whistle_indices) == 0:
        return []

    timestamps: List[float] = []
    min_gap_samples = int(sr * 1.5)  # 1.5s between whistle events
    last_sample = -min_gap_samples

    for idx in whistle_indices:
        if idx - last_sample > min_gap_samples:
            timestamps.append(float(round(idx / sr, 2)))
            last_sample = idx

    return timestamps

def compute_rms_energy_peaks(y: np.ndarray, sr: int = 22050, frame_duration: float = 0.5, threshold_factor: float = 3.0) -> List[Tuple[float, float]]:
    """Compute sliding-window Root-Mean-Square (RMS) loudness and detect high-energy cheering segments using robust MAD."""
    frame_length = int(sr * frame_duration)
    hop_length = frame_length // 2
    
    if len(y) < frame_length:
        return []

    num_frames = (len(y) - frame_length) // hop_length + 1
    rms = np.zeros(num_frames)

    for i in range(num_frames):
        start = i * hop_length
        frame = y[start:start + frame_length]
        rms[i] = np.sqrt(np.mean(frame ** 2))

    baseline = np.median(rms)
    mad = np.median(np.abs(rms - baseline))
    threshold = baseline + threshold_factor * (mad * 1.4826 + 1e-5)

    peak_frames = np.where(rms > threshold)[0]
    if len(peak_frames) == 0:
        return []

    merged_ranges: List[Tuple[float, float]] = []
    current_start = peak_frames[0]
    current_end = peak_frames[0]

    for f in peak_frames[1:]:
        if f <= current_end + 3:  # within ~1.5s gap
            current_end = f
        else:
            merged_ranges.append((
                float(round(current_start * hop_length / sr, 2)),
                float(round((current_end * hop_length + frame_length) / sr, 2))
            ))
            current_start = f
            current_end = f

    merged_ranges.append((
        float(round(current_start * hop_length / sr, 2)),
        float(round((current_end * hop_length + frame_length) / sr, 2))
    ))
    return merged_ranges
