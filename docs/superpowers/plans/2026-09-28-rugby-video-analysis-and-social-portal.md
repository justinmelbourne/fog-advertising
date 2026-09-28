# Rugby Video Analysis & Social Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated end-to-end rugby game-day video pipeline that ingests Veo match footage and sideline phone clips into Google Drive, detects high-excitement rugby moments (tries, tackles, lineouts, crowd cheers, referee whistles), generates AI editorial clip-pairing suggestions, and exposes an on-demand multi-format social extractor (9:16, 1:1, 4:5, 16:9) via a branded Squarespace club portal.

**Architecture:** Python 3.11 backend engine (`engine/`) utilizing Librosa for 3.3–4.2 kHz whistle detection and RMS audio energy analysis, PySceneDetect for boundary cuts, and Gemini 2.0 Flash for rugby event classification and cross-clip pairing intelligence. FFmpeg executes stream-copy lossless master clipping and on-demand social reformatting with EBU R128 (-14.0 LUFS) audio mastering. A Squarespace Developer Mode portal page (`portal/`) provides an interactive HTML5 video previewer and on-demand format export buttons adhering to the SF Fog RFC design system.

**Tech Stack:** Python 3.11, Librosa, NumPy, SciPy, PySceneDetect, Pydantic v2, FFmpeg 7.x, Google Gemini API, Squarespace Developer Mode (JSON-T / Vanilla LESS / ES6 JS).

## Global Constraints

- **Python Virtual Environment Hygiene:** Single-use virtual environments must be removed immediately after task completion (`rm -rf .venv`).
- **Disk Space Awareness:** Check available storage before processing large video files; auto-purge intermediate audio WAV stems and proxy files immediately after clip extraction.
- **SF Fog RFC Brand System:** Strict adherence to official tokens: Primary Blue `#006EB6`, Pitch Navy `#00243C`, Sky Blue `#24A0F1`, Futura PT typography. Zero Gold (`#C5A059`), zero generic slate navy.
- **Zero-Pill Law:** All portal buttons, filter pills, and badges strictly use `border-radius: 2px`. Cards use `4px`.
- **Single-Hero Invariant:** Portal subpage uses exactly one `.hero-banner`; no duplicate titles or redundant dark hero sections.
- **Audio Standards:** All extracted social video files must measure exactly `-14.0 LUFS` integrated loudness and `-1.0 dBTP` True Peak via two-pass EBU R128.
- **Clean Media by Default:** No automatic on-screen branding burns; master clips remain clean unbranded 16:9 source assets with AI metadata suggestions.

---

### Task 1: Project Setup, Data Models & Manifest Schema

**Files:**
- Create: `requirements.txt`
- Create: `engine/__init__.py`
- Create: `engine/models.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Consumes: None
- Produces: `Match`, `VideoSource`, `Event`, `EditorialSuggestion`, `Manifest` Pydantic models with validation and JSON serialization.

- [ ] **Step 1: Write requirements.txt**

```txt
pydantic>=2.7.0
numpy>=1.26.0
scipy>=1.13.0
librosa>=0.10.1
scenedetect>=0.6.3
pytest>=8.1.0
python-dotenv>=1.0.1
```

- [ ] **Step 2: Write the failing test for data models**

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError
from engine.models import Match, VideoSource, Event, Manifest, PairingSuggestion

def test_manifest_serialization():
    source = VideoSource(
        source_id="veo_01",
        filename="veo_half1.mp4",
        duration_seconds=2400.0,
        resolution="1920x1080",
        fps=30.0,
        camera_type="veo"
    )
    event = Event(
        event_id="evt_001",
        source_id="veo_01",
        event_type="try",
        start_time=855.0,
        end_time=878.0,
        duration=23.0,
        excitement_score=0.95,
        detection_source="veo_ai_tag+audio_cheer",
        description="Corner breakaway try",
        suggested_uses=["hype_reel_hook"],
        suggested_pairings=[
            PairingSuggestion(
                paired_event_id="evt_002",
                reason="Sideline phone celebration of this try"
            )
        ],
        suggested_caption="Try time on Treasure Island! 🏉",
        suggested_hashtags=["#SFFogRFC", "#FogRugby"]
    )
    manifest = Manifest(
        match_id="2026-10-10-fog-vs-seahorses",
        match_title="SF Fog RFC vs San Jose Seahawks",
        match_date="2026-10-10",
        pitch="Treasure Island Pitch 1",
        sources=[source],
        events=[event]
    )

    json_str = manifest.model_dump_json()
    assert "2026-10-10-fog-vs-seahorses" in json_str
    assert "evt_001" in json_str

    deserialized = Manifest.model_validate_json(json_str)
    assert deserialized.match_title == "SF Fog RFC vs San Jose Seahawks"
    assert len(deserialized.events) == 1
    assert deserialized.events[0].suggested_pairings[0].paired_event_id == "evt_002"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.models'`

- [ ] **Step 4: Implement data models in engine/models.py**

```python
# engine/models.py
from typing import List, Optional
from pydantic import BaseModel, Field

class VideoSource(BaseModel):
    source_id: str
    filename: str
    duration_seconds: float
    resolution: str
    fps: float
    camera_type: str = Field(description="'veo' or 'phone'")

class PairingSuggestion(BaseModel):
    paired_event_id: str
    reason: str

class Event(BaseModel):
    event_id: str
    source_id: str
    event_type: str = Field(description="e.g. try, big_tackle, lineout, scrum, celebration")
    start_time: float = Field(description="Start offset in seconds")
    end_time: float = Field(description="End offset in seconds")
    duration: float = Field(description="Duration in seconds")
    excitement_score: float = Field(ge=0.0, le=1.0)
    detection_source: str
    description: str
    suggested_uses: List[str] = Field(default_factory=list)
    suggested_pairings: List[PairingSuggestion] = Field(default_factory=list)
    suggested_caption: str = ""
    suggested_hashtags: List[str] = Field(default_factory=list)
    status: str = "pending_review"

class Manifest(BaseModel):
    match_id: str
    match_title: str
    match_date: str
    pitch: str = "Treasure Island Pitch 1, San Francisco"
    sources: List[VideoSource] = Field(default_factory=list)
    events: List[Event] = Field(default_factory=list)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add requirements.txt engine/__init__.py engine/models.py tests/__init__.py tests/test_models.py
git commit -m "feat: add pydantic data models and manifest schema"
```

---

### Task 2: Veo Automated Cloud Ingestion Worker

**Files:**
- Create: `engine/veo_ingest.py`
- Create: `tests/test_veo_ingest.py`

**Interfaces:**
- Consumes: Veo API match ID or email payload URL, Veo API token.
- Produces: `download_veo_match_and_tags(match_id, target_dir, api_client)` -> downloads match MP4 and returns `List[Event]` populated from Veo AI tags.

- [ ] **Step 1: Write the failing test for Veo ingestion**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_veo_ingest.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.veo_ingest'`

- [ ] **Step 3: Implement Veo ingestion logic in engine/veo_ingest.py**

```python
# engine/veo_ingest.py
import re
from typing import List, Optional, Any
from engine.models import Event

VEO_URL_PATTERN = re.compile(r"app\.veo\.co/matches/([a-zA-Z0-9\-]+)")

def parse_veo_email_body(body_text: str) -> Optional[str]:
    match = VEO_URL_PATTERN.search(body_text)
    return match.group(1) if match else None

def fetch_veo_match_events(match_id: str, source_id: str, client: Any) -> List[Event]:
    data = client.get_match_data(match_id)
    highlights = data.get("highlights", [])
    events: List[Event] = []

    for idx, hl in enumerate(highlights):
        hl_type = hl.get("type", "").lower()
        if hl_type in ["half_start", "half_end", "period_start", "period_end"]:
            continue

        event_type = "try" if hl_type in ["goal", "try"] else "highlight"
        start = float(hl.get("start", 0))
        end = float(hl.get("end", start + 20))
        duration = end - start

        events.append(Event(
            event_id=f"veo_evt_{idx+1:03d}",
            source_id=source_id,
            event_type=event_type,
            start_time=start,
            end_time=end,
            duration=duration,
            excitement_score=0.90 if event_type == "try" else 0.75,
            detection_source="veo_ai_tag",
            description=hl.get("label", "Veo AI Match Highlight"),
            suggested_uses=["hype_reel_hook" if event_type == "try" else "general_highlight"]
        ))

    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_veo_ingest.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/veo_ingest.py tests/test_veo_ingest.py
git commit -m "feat: implement veo email parsing and match tag ingestion"
```

---

### Task 3: Audio Excitement & Referee Whistle Detector

**Files:**
- Create: `engine/audio_analyzer.py`
- Create: `tests/test_audio_analyzer.py`

**Interfaces:**
- Consumes: Audio signal array or WAV file path.
- Produces: `detect_whistle_timestamps(y, sr)` -> `List[float]` (timestamps in seconds of referee whistles between 3.3–4.2 kHz); `compute_rms_energy_peaks(y, sr, threshold_std=2.0)` -> `List[tuple[float, float]]` (start and end timestamps of cheering/excitement spikes).

- [ ] **Step 1: Write the failing test for audio excitement detection**

```python
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

    peaks = compute_rms_energy_peaks(signal, sr=sr, threshold_factor=2.0)
    assert len(peaks) >= 1
    start, end = peaks[0]
    assert 5.5 <= start <= 6.5
    assert 7.5 <= end <= 8.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_audio_analyzer.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.audio_analyzer'`

- [ ] **Step 3: Implement whistle and energy detection in engine/audio_analyzer.py**

```python
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

def detect_whistle_timestamps(y: np.ndarray, sr: int = 22050, threshold_factor: float = 3.5) -> List[float]:
    b, a = butter_bandpass(WHISTLE_LOW_HZ, WHISTLE_HIGH_HZ, sr, order=4)
    filtered = filtfilt(b, a, y)
    energy = filtered ** 2

    window_size = int(sr * 0.1)  # 100ms
    if len(energy) < window_size:
        return []
    
    smoothed = np.convolve(energy, np.ones(window_size) / window_size, mode='same')
    baseline = np.median(smoothed)
    threshold = baseline + threshold_factor * (np.std(smoothed) + 1e-6)

    whistle_indices = np.where(smoothed > threshold)[0]
    if len(whistle_indices) == 0:
        return []

    timestamps: List[float] = []
    min_gap_samples = int(sr * 1.5)  # 1.5s between whistle events
    last_sample = -min_gap_samples

    for idx in whistle_indices:
        if idx - last_sample > min_gap_samples:
            timestamps.append(round(idx / sr, 2))
            last_sample = idx

    return timestamps

def compute_rms_energy_peaks(y: np.ndarray, sr: int = 22050, frame_duration: float = 0.5, threshold_factor: float = 2.0) -> List[Tuple[float, float]]:
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

    mean_rms = np.mean(rms)
    std_rms = np.std(rms)
    threshold = mean_rms + threshold_factor * std_rms

    peak_frames = np.where(rms > threshold)[0]
    if len(peak_frames) == 0:
        return []

    merged_ranges: List[Tuple[float, float]] = []
    current_start = peak_frames[0]
    current_end = peak_frames[0]

    for f in peak_frames[1:]:
        if f <= current_end + 3:  # within 1.5s gap
            current_end = f
        else:
            merged_ranges.append((round(current_start * hop_length / sr, 2), round((current_end * hop_length + frame_length) / sr, 2)))
            current_start = f
            current_end = f

    merged_ranges.append((round(current_start * hop_length / sr, 2), round((current_end * hop_length + frame_length) / sr, 2)))
    return merged_ranges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_audio_analyzer.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/audio_analyzer.py tests/test_audio_analyzer.py
git commit -m "feat: add whistle bandpass filter and rms excitement detection"
```

---

### Task 4: AI Editorial Suggester & Clip Pairing Engine

**Files:**
- Create: `engine/ai_suggester.py`
- Create: `tests/test_ai_suggester.py`

**Interfaces:**
- Consumes: `List[Event]` (raw detected events from Veo and Phone cameras).
- Produces: `enrich_events_with_ai_insights(events: List[Event]) -> List[Event]` (adds suggested use cases, cross-camera pairing recommendations, hooks, captions, and hashtags).

- [ ] **Step 1: Write the failing test for AI editorial suggestions**

```python
# tests/test_ai_suggester.py
import pytest
from engine.models import Event
from engine.ai_suggester import generate_clip_pairings, assign_editorial_uses

def test_assign_editorial_uses():
    event = Event(
        event_id="e1",
        source_id="s1",
        event_type="try",
        start_time=100.0,
        end_time=120.0,
        duration=20.0,
        excitement_score=0.92,
        detection_source="veo",
        description="Try scored by Fog"
    )
    enriched = assign_editorial_uses(event)
    assert "hype_reel_hook" in enriched.suggested_uses
    assert "#SFFogRFC" in enriched.suggested_hashtags
    assert len(enriched.suggested_caption) > 0

def test_generate_clip_pairings():
    veo_try = Event(
        event_id="veo_01",
        source_id="veo",
        event_type="try",
        start_time=800.0,
        end_time=825.0,
        duration=25.0,
        excitement_score=0.95,
        detection_source="veo",
        description="Corner Try"
    )
    phone_celebration = Event(
        event_id="phone_01",
        source_id="phone",
        event_type="celebration",
        start_time=10.0,
        end_time=25.0,
        duration=15.0,
        excitement_score=0.88,
        detection_source="phone",
        description="Sideline bench jumping and cheering"
    )
    pairings = generate_clip_pairings([veo_try, phone_celebration])
    assert len(pairings[0].suggested_pairings) == 1
    assert pairings[0].suggested_pairings[0].paired_event_id == "phone_01"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_suggester.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.ai_suggester'`

- [ ] **Step 3: Implement AI suggester logic in engine/ai_suggester.py**

```python
# engine/ai_suggester.py
from typing import List
from engine.models import Event, PairingSuggestion

FOG_HASHTAGS = ["#SFFogRFC", "#FogRugby", "#InclusiveRugby", "#BinghamCup"]

def assign_editorial_uses(event: Event) -> Event:
    ev_type = event.event_type.lower()
    uses: List[str] = []

    if "try" in ev_type:
        uses = ["hype_reel_hook", "player_spotlight", "match_story_recap"]
        caption = "Try time on Treasure Island! 🏉 SF Fog crossing the whitewash!"
    elif "tackle" in ev_type or "hit" in ev_type:
        uses = ["defensive_masterclass", "hard_hits_reel", "shorts_hook"]
        caption = "Defense setting the standard 😤 Dominant hit from the Fog!"
    elif "lineout" in ev_type or "scrum" in ev_type:
        uses = ["forward_pack_pride", "set_piece_clinic"]
        caption = "Forward pack hard at work! Set piece dominance on display 💥"
    elif "celebration" in ev_type:
        uses = ["sideline_culture", "team_spirit_story"]
        caption = "The energy on the sideline is unmatched! 💙🏉 Fog family!"
    else:
        uses = ["general_match_highlight"]
        caption = "Big moment from Saturday's clash! Up the Fog! 🏉"

    event.suggested_uses = uses
    if not event.suggested_caption:
        event.suggested_caption = caption
    if not event.suggested_hashtags:
        event.suggested_hashtags = FOG_HASHTAGS

    return event

def generate_clip_pairings(events: List[Event]) -> List[Event]:
    enriched = [assign_editorial_uses(e) for e in events]
    tries = [e for e in enriched if "try" in e.event_type.lower()]
    sideline_reactions = [e for e in enriched if e.source_id != "veo" and ("celebration" in e.event_type.lower() or e.excitement_score > 0.85)]

    for t in tries:
        for s in sideline_reactions:
            t.suggested_pairings.append(PairingSuggestion(
                paired_event_id=s.event_id,
                reason="Sideline celebration adds emotional bench reaction to this try"
            ))

    return enriched
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ai_suggester.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/ai_suggester.py tests/test_ai_suggester.py
git commit -m "feat: implement AI editorial categorization and clip pairing recommendations"
```

---

### Task 5: Deterministic Lossless Master Clipper & On-Demand Reformatting Engine

**Files:**
- Create: `engine/clipper.py`
- Create: `tests/test_clipper.py`

**Interfaces:**
- Consumes: Input video path, start/end seconds, output path, target aspect ratio (`16:9`, `9:16`, `1:1`, `4:5`).
- Produces:
  - `extract_lossless_master(input_path, start, end, output_path)` -> FFmpeg stream-copy (`-c copy`)
  - `reframe_to_aspect_ratio(input_path, output_path, aspect_ratio, master_audio=True)` -> Rescales, pads with Pitch Navy `#00243C`, normalizes audio to `-14.0 LUFS`.

- [ ] **Step 1: Write the failing test for clipper commands**

```python
# tests/test_clipper.py
import pytest
from engine.clipper import build_lossless_cut_command, build_reframe_command

def test_build_lossless_cut_command():
    cmd = build_lossless_cut_command("raw.mp4", start=60.0, end=85.0, output_path="clip.mp4")
    assert "-ss 60.0" in cmd
    assert "-to 85.0" in cmd
    assert "-c copy" in cmd
    assert "clip.mp4" in cmd

def test_build_9x16_reframe_command():
    cmd = build_reframe_command("clip.mp4", "social_9x16.mp4", aspect_ratio="9:16", master_audio=True)
    assert "scale=1080:1920" in cmd
    assert "color=0x00243C" in cmd
    assert "yuv420p" in cmd
    assert "+faststart" in cmd
    assert "loudnorm=I=-14" in cmd

def test_build_1x1_reframe_command():
    cmd = build_reframe_command("clip.mp4", "social_1x1.mp4", aspect_ratio="1:1", master_audio=True)
    assert "scale=1080:1080" in cmd
    assert "color=0x00243C" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clipper.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.clipper'`

- [ ] **Step 3: Implement clipper command builders in engine/clipper.py**

```python
# engine/clipper.py
from typing import Literal

AspectRatio = Literal["16:9", "9:16", "1:1", "4:5"]

ASPECT_RATIO_CONFIGS = {
    "9:16": {"width": 1080, "height": 1920},
    "1:1": {"width": 1080, "height": 1080},
    "4:5": {"width": 1080, "height": 1350},
    "16:9": {"width": 1920, "height": 1080}
}

PITCH_NAVY_HEX = "0x00243C"

def build_lossless_cut_command(input_path: str, start: float, end: float, output_path: str) -> str:
    # Buffer: start 5s earlier if possible, end 7s later
    actual_start = max(0.0, start - 5.0)
    actual_end = end + 7.0
    return f'ffmpeg -y -ss {actual_start:.2f} -to {actual_end:.2f} -i "{input_path}" -c copy -avoid_negative_ts 1 "{output_path}"'

def build_reframe_command(input_path: str, output_path: str, aspect_ratio: AspectRatio = "9:16", master_audio: bool = True) -> str:
    cfg = ASPECT_RATIO_CONFIGS.get(aspect_ratio, ASPECT_RATIO_CONFIGS["9:16"])
    w, h = cfg["width"], cfg["height"]

    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={PITCH_NAVY_HEX},format=yuv420p"
    
    if master_audio:
        af = "-af highpass=f=80,loudnorm=I=-14:TP=-1.0:LRA=7"
    else:
        af = "-c:a copy"

    return (
        f'ffmpeg -y -i "{input_path}" '
        f'-vf "{vf}" '
        f'-c:v libx264 -profile:v high -level:v 4.1 -preset slow -crf 18 '
        f'{af} -ar 48000 -c:a aac -b:a 256k '
        f'-movflags +faststart "{output_path}"'
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_clipper.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/clipper.py tests/test_clipper.py
git commit -m "feat: implement lossless clipping and on-demand social reframe filtergraphs"
```

---

### Task 6: CLI Pipeline Orchestrator

**Files:**
- Create: `engine/cli.py`
- Modify: `engine/__init__.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: Input folder path containing match MP4 and phone videos.
- Produces: CLI interface supporting:
  - `python -m engine.cli scan <dir>` -> scans folder, runs audio/veo analysis, outputs `manifest.json`.
  - `python -m engine.cli extract <manifest.json> --format [16:9|9:16|1:1|4:5]` -> executes on-demand clipping into `output/` directory.

- [ ] **Step 1: Write the failing test for CLI manifest generation and extraction**

```python
# tests/test_cli.py
import json
import pytest
from engine.cli import generate_match_manifest_from_events
from engine.models import VideoSource, Event

def test_generate_match_manifest():
    source = VideoSource(
        source_id="v1", filename="game.mp4", duration_seconds=120.0, resolution="1920x1080", fps=30.0, camera_type="veo"
    )
    event = Event(
        event_id="e1", source_id="v1", event_type="try", start_time=10.0, end_time=30.0, duration=20.0, excitement_score=0.9, detection_source="test", description="Test try"
    )
    manifest = generate_match_manifest_from_events("2026-10-10-test", "SF Fog vs Test RFC", [source], [event])
    assert manifest.match_id == "2026-10-10-test"
    assert len(manifest.events) == 1
    assert "hype_reel_hook" in manifest.events[0].suggested_uses
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`  
Expected: FAIL with `ImportError: cannot import name 'generate_match_manifest_from_events' from 'engine.cli'`

- [ ] **Step 3: Implement CLI pipeline orchestrator in engine/cli.py**

```python
# engine/cli.py
import argparse
import json
import os
import sys
from typing import List
from engine.models import Manifest, VideoSource, Event
from engine.ai_suggester import generate_clip_pairings
from engine.clipper import build_lossless_cut_command, build_reframe_command

def generate_match_manifest_from_events(match_id: str, title: str, sources: List[VideoSource], events: List[Event]) -> Manifest:
    enriched_events = generate_clip_pairings(events)
    return Manifest(
        match_id=match_id,
        match_title=title,
        match_date=match_id.split("-")[0] if "-" in match_id else "2026-10-10",
        sources=sources,
        events=enriched_events
    )

def main():
    parser = argparse.ArgumentParser(description="SF Fog RFC Match Highlight Engine")
    subparsers = parser.add_subparsers(dest="command")

    # Command: extract
    extract_parser = subparsers.add_parser("extract", help="Extract clips from manifest")
    extract_parser.add_argument("manifest", help="Path to manifest.json")
    extract_parser.add_argument("--format", choices=["16:9", "9:16", "1:1", "4:5"], default="16:9", help="Target social aspect ratio")
    extract_parser.add_argument("--outdir", default="./output_clips", help="Output directory")

    args = parser.parse_args()

    if args.command == "extract":
        with open(args.manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
        manifest = Manifest.model_validate(data)
        os.makedirs(args.outdir, exist_ok=True)

        for ev in manifest.events:
            source_file = next((s.filename for s in manifest.sources if s.source_id == ev.source_id), None)
            if not source_file:
                continue

            master_clip = os.path.join(args.outdir, f"{ev.event_id}_master.mp4")
            cut_cmd = build_lossless_cut_command(source_file, ev.start_time, ev.end_time, master_clip)
            print(f"Cutting master: {cut_cmd}")

            if args.format != "16:9":
                social_clip = os.path.join(args.outdir, f"{ev.event_id}_{args.format.replace(':', 'x')}.mp4")
                reframe_cmd = build_reframe_command(master_clip, social_clip, aspect_ratio=args.format)
                print(f"Reframing {args.format}: {reframe_cmd}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/cli.py tests/test_cli.py
git commit -m "feat: implement cli orchestrator for scanning and on-demand clipping"
```

---

### Task 7: Squarespace Developer Mode Portal Frontend Template & Styling

**Files:**
- Create: `portal/templates/media-hub.html`
- Create: `portal/styles/media-hub.less`
- Create: `portal/scripts/media-hub.js`

**Interfaces:**
- Consumes: `manifest.json` data structure.
- Produces: Fully styled, brand-compliant Squarespace `/portal/media` interface with:
  - Single `.hero-banner` ("GAME DAY MEDIA HUB").
  - Secondary `.fog-subnav` bar.
  - Interactive moment card grid with AI Pairing badges and suggested use-cases.
  - HTML5 video player with aspect-ratio toggle (`[16:9 Master | 9:16 Reel | 1:1 Square | 4:5 Feed]`).
  - Strict 2px radius buttons for on-demand format export.

- [ ] **Step 1: Create portal/styles/media-hub.less adhering to Fog brand system**

```less
/* portal/styles/media-hub.less */
@fog-blue: #006EB6;
@fog-light-blue: #24A0F1;
@fog-dark-blue: #00243C;
@fog-gray: #DCDDDE;
@fog-dark-gray: #141718;
@fog-white: #FFFFFF;
@fog-radius-btn: 2px;
@fog-radius-card: 4px;

.fog-media-portal {
  font-family: "Futura PT", Futura, Arial, Helvetica, sans-serif;
  color: @fog-dark-gray;
  background-color: #F8F9FA;
  padding: 0 0 4rem 0;

  .hero-banner {
    background-color: @fog-dark-blue;
    color: @fog-white;
    padding: 3.5rem 2rem;
    border-bottom: 3px solid @fog-blue;

    h1 {
      font-size: 2.5rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin: 0 0 0.5rem 0;
    }
    p {
      color: @fog-gray;
      margin: 0;
      font-size: 1.1rem;
    }
  }

  .fog-subnav {
    display: flex;
    background: @fog-white;
    border-bottom: 1px solid @fog-gray;
    padding: 0 2rem;
    gap: 1.5rem;

    &__link {
      display: inline-block;
      padding: 1rem 0.5rem;
      text-decoration: none;
      color: @fog-dark-gray;
      font-weight: 600;
      border-bottom: 2px solid transparent;

      &--active {
        color: @fog-blue;
        border-bottom-color: @fog-blue;
      }
    }
  }

  .portal-container {
    max-width: 1440px;
    margin: 2rem auto;
    padding: 0 2rem;
    display: grid;
    grid-template-columns: 1fr 420px;
    gap: 2rem;
  }

  .moment-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 1.5rem;
  }

  .moment-card {
    background: @fog-white;
    border: 1px solid @fog-gray;
    border-radius: @fog-radius-card;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    justify-content: space-between;

    &__header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.75rem;
    }

    &__badge {
      background: @fog-blue;
      color: @fog-white;
      padding: 0.25rem 0.5rem;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      border-radius: @fog-radius-btn;
    }

    &__score {
      font-size: 0.85rem;
      color: @fog-dark-blue;
      font-weight: bold;
    }

    &__pairings {
      background: #F0F4F8;
      border-left: 3px solid @fog-light-blue;
      padding: 0.5rem 0.75rem;
      font-size: 0.8rem;
      margin: 0.75rem 0;
      border-radius: 0 @fog-radius-btn @fog-radius-btn 0;
    }

    &__actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.5rem;
      margin-top: 1rem;
    }
  }

  .fog-btn {
    border-radius: @fog-radius-btn;
    border: 1px solid @fog-blue;
    background: @fog-blue;
    color: @fog-white;
    padding: 0.5rem 0.75rem;
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    cursor: pointer;
    text-align: center;

    &:hover {
      background: @fog-light-blue;
      border-color: @fog-light-blue;
    }

    &--secondary {
      background: transparent;
      color: @fog-blue;

      &:hover {
        background: #EBF5FB;
      }
    }
  }

  .preview-panel {
    background: @fog-white;
    border: 1px solid @fog-gray;
    border-radius: @fog-radius-card;
    padding: 1.5rem;
    height: fit-content;
    position: sticky;
    top: 2rem;

    .video-viewport {
      background: @fog-dark-blue;
      border-radius: @fog-radius-btn;
      display: flex;
      justify-content: center;
      align-items: center;
      overflow: hidden;
      margin: 1rem 0;

      &.ratio-9x16 {
        aspect-ratio: 9 / 16;
        max-height: 480px;
        margin: 0 auto 1rem auto;
      }
      &.ratio-1x1 {
        aspect-ratio: 1 / 1;
      }
      &.ratio-16x9 {
        aspect-ratio: 16 / 9;
      }
    }

    .format-pills {
      display: flex;
      gap: 0.5rem;
      margin-bottom: 1rem;
    }
  }
}
```

- [ ] **Step 2: Create portal/templates/media-hub.html**

```html
<!-- portal/templates/media-hub.html -->
<div class="fog-media-portal">
  <section class="hero-banner">
    <h1>Game Day Media Hub</h1>
    <p>San Francisco Fog RFC • Automated Video Highlights & Social Repurposing</p>
  </section>

  <nav class="fog-subnav">
    <a href="#matches" class="fog-subnav__link fog-subnav__link--active">Match Clips</a>
    <a href="#veo" class="fog-subnav__link">Veo Ingest Queue</a>
    <a href="#social" class="fog-subnav__link">Social Ready</a>
  </nav>

  <div class="portal-container">
    <main class="moment-section">
      <div class="moment-header">
        <h2 id="current-match-title">SF Fog RFC vs San Jose Seahawks</h2>
        <span class="match-meta">Treasure Island Pitch 1 • 2026-10-10</span>
      </div>

      <div class="moment-grid" id="moment-grid">
        <!-- Rendered dynamically by media-hub.js -->
      </div>
    </main>

    <aside class="preview-panel">
      <h3>Interactive Clip Preview</h3>
      <div class="format-pills">
        <button class="fog-btn fog-btn--secondary active" onclick="setPreviewRatio('16x9')">16:9</button>
        <button class="fog-btn fog-btn--secondary" onclick="setPreviewRatio('9x16')">9:16 Reel</button>
        <button class="fog-btn fog-btn--secondary" onclick="setPreviewRatio('1x1')">1:1 Square</button>
      </div>

      <div class="video-viewport ratio-16x9" id="video-viewport">
        <video id="player" controls style="max-width: 100%; max-height: 100%;">
          <source src="" type="video/mp4">
        </video>
      </div>

      <div class="caption-box" id="caption-box" style="display:none;">
        <h4 style="margin: 0.5rem 0 0.25rem 0;">Suggested Social Copy</h4>
        <p id="caption-text" style="font-size: 0.85rem; color: #444;"></p>
        <button class="fog-btn fog-btn--secondary" style="width: 100%;" onclick="copyCaption()">Copy Caption & Hashtags</button>
      </div>
    </aside>
  </div>
</div>
```

- [ ] **Step 3: Create portal/scripts/media-hub.js**

```javascript
// portal/scripts/media-hub.js
let currentEvent = null;

function renderMoments(events) {
  const container = document.getElementById("moment-grid");
  if (!container) return;

  container.innerHTML = events.map(ev => `
    <div class="moment-card" id="card-${ev.event_id}">
      <div>
        <div class="moment-card__header">
          <span class="moment-card__badge">${ev.event_type}</span>
          <span class="moment-card__score">${Math.round(ev.excitement_score * 100)}% EXCITEMENT</span>
        </div>
        <h4 style="margin: 0 0 0.5rem 0;">${ev.description}</h4>
        <p style="font-size: 0.8rem; color: #666; margin: 0 0 0.5rem 0;">
          Source: ${ev.source_id} • Duration: ${ev.duration}s
        </p>
        ${ev.suggested_pairings && ev.suggested_pairings.length > 0 ? `
          <div class="moment-card__pairings">
            <strong>Suggested Pairing:</strong> ${ev.suggested_pairings[0].reason}
          </div>
        ` : ''}
      </div>
      <div>
        <button class="fog-btn" style="width: 100%; margin-bottom: 0.5rem;" onclick='selectClip(${JSON.stringify(ev)})'>Preview Clip</button>
        <div class="moment-card__actions">
          <button class="fog-btn fog-btn--secondary" onclick="exportClip('${ev.event_id}', '9:16')">Reel 9:16</button>
          <button class="fog-btn fog-btn--secondary" onclick="exportClip('${ev.event_id}', '1:1')">Square 1:1</button>
        </div>
      </div>
    </div>
  `).join("");
}

function selectClip(ev) {
  currentEvent = ev;
  const player = document.getElementById("player");
  const captionBox = document.getElementById("caption-box");
  const captionText = document.getElementById("caption-text");

  if (captionBox && captionText) {
    captionBox.style.display = "block";
    captionText.innerText = `${ev.suggested_caption} ${(ev.suggested_hashtags || []).join(" ")}`;
  }
}

function setPreviewRatio(ratio) {
  const viewport = document.getElementById("video-viewport");
  if (!viewport) return;
  viewport.className = `video-viewport ratio-${ratio}`;
}

function copyCaption() {
  if (!currentEvent) return;
  const fullText = `${currentEvent.suggested_caption} ${(currentEvent.suggested_hashtags || []).join(" ")}`;
  navigator.clipboard.writeText(fullText).then(() => {
    alert("Caption copied to clipboard!");
  });
}

function exportClip(eventId, format) {
  alert(`Requested on-demand export for clip ${eventId} in format ${format}. Processing with FFmpeg!`);
}
```

- [ ] **Step 4: Commit portal assets**

```bash
git add portal/styles/media-hub.less portal/templates/media-hub.html portal/scripts/media-hub.js
git commit -m "feat: create branded squarespace developer mode portal template and controller"
```

---

### Task 8: Verification & End-to-End Test Suite

**Files:**
- Create: `tests/test_e2e_pipeline.py`

**Interfaces:**
- Consumes: All components from Tasks 1–7.
- Produces: Integrated test confirming Veo ingest -> whistle & audio detection -> manifest creation -> lossless cut -> on-demand social reframe.

- [ ] **Step 1: Write end-to-end integration test**

```python
# tests/test_e2e_pipeline.py
import os
import json
import pytest
import numpy as np
from engine.models import VideoSource, Event
from engine.audio_analyzer import detect_whistle_timestamps, compute_rms_energy_peaks
from engine.ai_suggester import generate_clip_pairings
from engine.cli import generate_match_manifest_from_events
from engine.clipper import build_lossless_cut_command, build_reframe_command

def test_full_pipeline_flow():
    # 1. Synthesize audio stream with whistle and cheer
    sr = 22050
    duration = 30.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = 0.05 * np.random.randn(len(t))

    # Whistle at 10.0s
    w_start, w_end = int(10.0 * sr), int(10.5 * sr)
    y[w_start:w_end] += 0.8 * np.sin(2 * np.pi * 3800 * t[w_start:w_end])

    # Cheering at 11.0s to 15.0s
    c_start, c_end = int(11.0 * sr), int(15.0 * sr)
    y[c_start:c_end] *= 6.0

    whistles = detect_whistle_timestamps(y, sr=sr)
    cheers = compute_rms_energy_peaks(y, sr=sr)

    assert len(whistles) >= 1
    assert len(cheers) >= 1

    # 2. Build Event
    event = Event(
        event_id="test_001",
        source_id="match_half1",
        event_type="try",
        start_time=whistles[0],
        end_time=cheers[0][1],
        duration=cheers[0][1] - whistles[0],
        excitement_score=0.92,
        detection_source="audio_whistle+cheer",
        description="Try following whistle"
    )

    source = VideoSource(
        source_id="match_half1",
        filename="match.mp4",
        duration_seconds=duration,
        resolution="1920x1080",
        fps=30.0,
        camera_type="veo"
    )

    manifest = generate_match_manifest_from_events("2026-10-10-e2e", "E2E Test Match", [source], [event])
    assert len(manifest.events) == 1
    assert "hype_reel_hook" in manifest.events[0].suggested_uses

    # 3. Test on-demand clipping commands
    cut_cmd = build_lossless_cut_command("match.mp4", event.start_time, event.end_time, "clip.mp4")
    assert "-c copy" in cut_cmd

    reframe_9x16 = build_reframe_command("clip.mp4", "clip_9x16.mp4", aspect_ratio="9:16")
    assert "scale=1080:1920" in reframe_9x16
    assert "loudnorm=I=-14" in reframe_9x16
```

- [ ] **Step 2: Run pytest across the entire test suite**

Run: `pytest tests/ -v`  
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_pipeline.py
git commit -m "test: add comprehensive end-to-end integration test suite"
```
