# Technical Specification & Design Document: Rugby Match Analysis & Social Clip Hub

**Document ID:** `2026-09-28-rugby-video-analysis-and-social-portal-design`  
**Date:** September 28, 2026  
**Status:** DRAFT (Under Review)  
**Target Platform:** Squarespace Developer Mode Portal (`/portal/media`) + Google Cloud / Google Workspace for Nonprofits Backend + Local/Cloud Video Processing Engine  
**Brand Compliance:** SF Fog RFC Brand System (Pitch Navy `#00243C`, Fog Blue `#006EB6`, Futura PT, Zero-Pill Law, -14 LUFS Audio)

---

## 1. Executive Summary & Goals

San Francisco Fog RFC captures dozens of hours of match and practice footage across every season:
1. **Veo 2/3 Cameras:** Elevated tactical panoramic / follow-cam recordings (40–80 minute continuous halves).
2. **Sideline Phone Cameras:** Mobile, handheld 1080p/4K vertical and landscape video files of individual plays, tries, celebrations, scrums, and bench reactions.

### Core Problem
Match footage sits locked in raw video archives or Veo Clubhouse silos. Finding the 5–10 viral, high-excitement rugby moments (tries, bone-crunching tackles, lineout steals, penalty kicks, end-game celebrations) requires hours of tedious manual scrubbing. Producing high-impact social clips (vertical 9:16 reels, branded overlays, normalized audio) requires significant editing friction.

### Project Objectives
1. **Automate Ingestion & Cataloging:** Scan incoming game-day video folders (Google Drive / Cloud Storage) containing both Veo matches and sideline phone footage.
2. **Automated Highlight & Excitement Detection:** Identify emotional rugby moments using a multi-modal approach:
   - Ingesting Veo AI match tags (halves, tries, fouls).
   - Audio energy, crowd cheering, and referee whistle detection (3.3–4.2 kHz) for sideline phone clips and raw match audio.
   - Multimodal verification (Gemini 2.0 Flash / local VLM) for rugby context classification.
3. **Lossless Extraction:** Extract clip candidates into standalone high-definition files with pre-roll (-5s) and post-roll (+7s) context buffers.
4. **Branded Social Reformatting:** Automate conversion into platform-ready 9:16 Instagram Reels / TikToks using the official SF Fog RFC brand system and EBU R128 (-14.0 LUFS) audio mastering.
5. **Squarespace Club Portal Integration:** Provide a user-friendly management dashboard within the Fog portal (`/portal/media`) where media team members can upload, review detected moments, play previews, approve clips, and trigger social exports.

---

## 2. Research & Platform Comparison: Google Cloud vs. YouTube vs. Google Drive

We evaluated the three candidate platforms across storage capacity, compute, video streaming, API quotas, and Google for Nonprofits cost optimization:

| Dimension | Option A: Google Drive (Workspace Nonprofits) | Option B: YouTube (Unlisted Match Archives) | Option C: Google Cloud Platform (GCS + Cloud Run) |
|---|---|---|---|
| **Storage Capacity** | **100 TB pooled cloud storage** included free in Google Workspace for Nonprofits. | Unlimited free hosting for videos under 12 hours. | Standard GCS: ~$0.02/GB/month. (e.g. 1 TB = ~$20/mo, covered by GCP nonprofit grant if awarded). |
| **Raw Master Retention** | **100% Bit-Exact Original** (No compression, preserves 4K 60fps ProRes/H.264/H.265). | ❌ **Heavily Compressed** (Transcoded to VP9/AV1 at low streaming bitrates; not suitable as editing master). | **100% Bit-Exact Original** with lifecycle tiering (Standard, Nearline, Coldline). |
| **Ingestion Simplicity** | **Highest:** Players and coaches drag-and-drop straight from Google Drive mobile app or desktop folder sync. | Moderate: Requires YouTube upload interface or OAuth API token with 1,600 units/upload. | High: Direct browser-to-bucket resumable PUT via signed URLs. |
| **Web Streaming in Squarespace** | ❌ **Poor:** Google Drive preview player has strict daily playback rate limits, intrusive Google UI, and sluggish buffering. | **Best:** Zero-latency adaptive bitrate streaming (1080p, 720p, 480p), zero bandwidth cost, clean iframe embeds. | **Very High:** Native HTML5 `<video>` tag playback with custom player controls via Cloud Storage Signed URLs or Cloud CDN. |
| **Compute / Automation** | No native video compute. Requires an external worker to read and write files. | Zero compute for custom clipping; must download back via `yt-dlp` (frequently rate-limited/blocked by YouTube). | **Best:** Cloud Run / Cloud Functions can execute containerized FFmpeg, Python audio analysis, and batch clipping serverlessly. |
| **API Quotas & Risks** | Generous Drive API rate limits (20,000 requests/100 seconds). | ⚠️ **Severe Quota Bottleneck:** Default YouTube Data API quota is 10,000 units/day. 1 upload = 1,600 units (max ~6 automated uploads/day without manual quota appeal). Copyright flags on stadium/sideline music. | Enterprise-grade quotas scaling dynamically with project limits. |

### Recommendation: The Winning "Nonprofit Hybrid" Architecture
1. **Primary Master Archive:** **Google Drive (Shared Drive via Workspace for Nonprofits)**.
   - Leverages the organization's **100 TB free pooled quota**.
   - Zero storage bill. Zero risk of compression degradation.
   - Seamless desktop integration via *Google Drive for Desktop* (local filesystem paths on macOS).
2. **Compute & Processing Engine:** **Google Cloud Run (or Local Mac Worker)**.
   - Runs lightweight containerized FFmpeg and audio detection tasks on demand.
   - Triggered automatically when new files arrive in the Google Drive folder.
3. **Web Streaming & Review in Squarespace:**
   - For lightweight previewing inside the Squarespace portal, the worker generates low-bitrate 720p MP4 preview proxies stored in Google Cloud Storage or streamed via lightweight signed URLs.
   - For public full-match broadcasts, unlisted YouTube embeds remain ideal, but social highlights stream directly from fast proxy storage.

---

## 3. High-Level System Architecture

```
+-----------------------------------------------------------------------------------+
|                                 INGESTION LAYER                                   |
|                                                                                   |
|  [Veo Clubhouse]                   [Phone Cameras]          [Match Videographers] |
|   AI Tags & Match MP4s             Sideline Clips            Practice Footage     |
|          |                                \                        /              |
|          v                                 v                      v               |
|  +-----------------------------------------------------------------------------+  |
|  |       Google Workspace for Nonprofits Shared Drive (100 TB Pooled)          |  |
|  |       Folder: /SF Fog RFC Media/Game Day Ingest/YYYY-MM-DD-vs-Opponent/     |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        RUGBY HIGHLIGHT ANALYSIS ENGINE                            |
|                                                                                   |
|  1. Veo Event Synchronizer: Ingests Veo AI timestamps (tries, kickoffs, cards)     |
|  2. Audio Excitement Classifier (Librosa + YAMNet): Crowd cheers, whistles (3.5kHz)|
|  3. PySceneDetect: Action boundaries, dead-air / huddle cut points               |
|  4. Multimodal Context (Gemini 2.0 Flash): Rugby classification & player tags     |
|                                                                                   |
|  OUTPUT: manifest.json (Timestamped Event Catalog with confidence & excitement)   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                       SQUARESPACE CLUB PORTAL (/portal/media)                     |
|                                                                                   |
|  - Custom Squarespace Developer Mode Collection & Controller                      |
|  - Displays Match Catalog, Detected Events (Try, Big Tackle, Lineout, Breakaway)  |
|  - In-browser HTML5 Video Player with timestamp scrubber & 9:16 crop preview      |
|  - "Approve & Render" Button -> triggers automated social export pipeline         |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                    DETERMINISTIC CLIPPING & SOCIAL REFORMATTER                    |
|                                                                                   |
|  1. Lossless FFmpeg Segment Cuts (-5s pre-roll, +7s post-roll)                    |
|  2. Aspect Ratio Transformation: 9:16 Vertical (1080x1920) with action tracking   |
|  3. SF Fog RFC Branding Overlays: Futura PT lower-thirds, crest, score bug        |
|  4. Audio Mastering: EBU R128 Two-Pass Normalization (-14.0 LUFS, -1.0 dBTP)       |
|                                                                                   |
|  DESTINATION: Google Drive /SF Fog RFC Media/Social Ready/YYYY-MM-DD/             |
+-----------------------------------------------------------------------------------+
```

---

## 4. Video Analysis & Excitement Detection Pipeline

Rugby video analysis requires handling two distinct footage profiles:

### 4.1 Veo Match Footage Pipeline
*   **Characteristics:** Continuous, elevated 180° tactical or broadcast follow-cam; wide field of view; distant crowd sound; consistent referee whistle.
*   **Strategy:**
    1.  **Veo Tag Sync:** When downloaded via Veo Clubhouse, match clips come pre-tagged (Tries, Half Start/End). The script extracts metadata from the Veo download package or filenames.
    2.  **Whistle & Restart Detection:** Referee whistles have a distinctive acoustic signature concentrated in the **3,300 Hz – 4,200 Hz** band. A Short-Time Fourier Transform (STFT) bandpass filter pinpoints whistle blows marking penalties, tries, and scrums.
    3.  **Ball Movement / Motion Surge:** Optical flow calculation around whistle timestamps isolates the preceding 10 seconds of high-velocity play (the line break or tackle).

### 4.2 Sideline Phone Camera Pipeline
*   **Characteristics:** Handheld, vertical or horizontal; close-up to spectators and bench; intense localized shouting and cheering; variable clip lengths (15s to 3m).
*   **Strategy:**
    1.  **RMS Audio Energy & Loudness Curve:** Computes root-mean-square audio energy in 0.5s windows. Sideline cheering creates a sharp +6dB to +12dB surge over background ambient noise.
    2.  **YAMNet Audio Event Classification:** Open-source lightweight neural net trained on AudioSet. Specifically filters for top-ranked classes: `Cheering`, `Applause`, `Laughter`, `Yell`, `Screaming`.
    3.  **Scene Transition Analysis:** Uses `scenedetect` (content detector threshold 27.0) to locate natural start/stop boundaries so cuts do not slice halfway through a play.

### 4.3 Candidate Event Catalog Schema (`manifest.json`)
Every analyzed match generates a structured manifest:

```json
{
  "match_id": "2026-10-10-fog-vs-seahorses",
  "match_title": "SF Fog RFC vs San Jose Seahawks",
  "match_date": "2026-10-10",
  "pitch": "Treasure Island Pitch 1, San Francisco",
  "sources": [
    {
      "source_id": "veo_cam_half1",
      "filename": "veo_match_half1.mp4",
      "duration_seconds": 2480.5,
      "resolution": "1920x1080",
      "fps": 30.0
    },
    {
      "source_id": "phone_sideline_01",
      "filename": "IMG_4921.MOV",
      "duration_seconds": 45.2,
      "resolution": "1080x1920",
      "fps": 60.0
    }
  ],
  "events": [
    {
      "event_id": "evt_001",
      "source_id": "veo_cam_half1",
      "event_type": "try",
      "start_time": "00:14:15.000",
      "end_time": "00:14:38.000",
      "duration": 23.0,
      "excitement_score": 0.94,
      "detection_source": "veo_ai_tag+audio_cheer",
      "description": "SF Fog breakaway try in right corner",
      "suggested_caption": "Try time on Treasure Island! 🏉 Fog crossing the whitewash!",
      "status": "pending_review"
    },
    {
      "event_id": "evt_002",
      "source_id": "phone_sideline_01",
      "event_type": "big_tackle",
      "start_time": "00:00:08.500",
      "end_time": "00:00:22.000",
      "duration": 13.5,
      "excitement_score": 0.88,
      "detection_source": "audio_energy_spike",
      "description": "Dominant blindside tackle causing turnover",
      "suggested_caption": "Defense setting the standard 😤 Hit of the match!",
      "status": "pending_review"
    }
  ]
}
```

---

## 5. Production Social Formatting Engine (Brand System Compliant)

All social output files strictly follow the **SF Fog RFC Brand System** and **Instagram Video Editor Skill specifications**:

### 5.1 Video Specifications Matrix
*   **Aspect Ratio:** 9:16 Vertical (`1080 × 1920 px`).
*   **Codec:** H.264 (`libx264`), Profile `High`, Level `4.1`, Preset `slow`, CRF `18`.
*   **Pixel Format:** `yuv420p` (mandatory to prevent Instagram black-screen errors).
*   **Container Flags:** `-movflags +faststart` (enables instant buffering).
*   **Letterboxing / Padding:** When reframing horizontal 16:9 Veo footage to 9:16 vertical, padding uses Fog Pitch Navy (`#00243C`), never generic black or random blur.
*   **Safe Zones:**
    *   Top 288 px (0–15%): Header safe zone (free of text/logos).
    *   Bottom 384 px (80–100%): Instagram caption/actions zone (free of critical action/titles).
    *   Action tracking centers the ball/scrum in the vertical 1080px band.

### 5.2 Audio Mastering Engine
*   **Target Loudness:** Exactly **-14.0 LUFS** (integrated), True Peak **-1.0 dBTP** via two-pass EBU R128 (`loudnorm`).
*   **High-Pass Filter:** `highpass=f=80` to remove low-frequency wind buffeting and rumble on phone mics.
*   **Sample Rate:** 48 kHz stereo AAC at 256 kbps.

### 5.3 On-Screen Branding
*   **Typography:** Futura PT (Bold, ALL CAPS, `letter-spacing: 0.05em`) for event titles ("TRY", "BIG HIT", "LINEOUT STEAL").
*   **Club Colors:**
    *   Primary Accent: Fog Blue (`#006EB6`)
    *   Hero Background: Deep Pitch Navy (`#00243C`)
    *   Light Accent: Sky Blue (`#24A0F1`)
*   **Absolute Ban:** No Gold (`#C5A059`), No Gatsby Cyan (`#64FFDA`), No generic slate navy (`#0A192F`).

---

## 6. Squarespace Developer Mode Portal Specification

### 6.1 Portal Architecture & Access
*   **Location:** Resides in the SF Fog RFC Squarespace template under `/portal/media` or `/portal/match-highlights`.
*   **Role Mapping:** Aligns with `fog-portal-roles` (accessible to `Board Member`, `Coach`, and `Media Manager` personas).
*   **Geometry & Design System:**
    *   Zero-Pill Law: All buttons (`.fog-btn`), filter pills (`.fog-filter-pill`), and badges (`.fog-portal-badge`) use strictly `border-radius: var(--fog-radius-btn);` (**2px**).
    *   Single-Hero Invariant: Exactly one `.hero-banner` on the subpage; no duplicate headers.
    *   Secondary Subnavigation: Includes `.fog-subnav` linking `[All Matches | Video Highlights | Raw Ingest | Social Queue]`.

### 6.2 Portal User Interface Components
1.  **Match Selector Bar:** Dropdown / list of matches with status indicator (Processing, Ready for Review, Exported).
2.  **Moment Review Grid:** Cards for each detected event showing:
    *   Event Pill (e.g. `[TRY]` in Fog Blue, `[BIG TACKLE]` in Fog Dark Blue).
    *   Excitement Score Meter (0–100%).
    *   Source Camera Tag (`Veo Cam 1` or `Sideline Phone - Alex`).
    *   Timestamp and duration.
3.  **Interactive Preview Player:**
    *   Instant HTML5 playback of the clip.
    *   Toggle between "Original Raw Framing" and "9:16 Vertical Social Preview".
    *   Trim adjustment handles (`-2s`, `+2s`).
4.  **One-Click Actions:**
    *   `[Approve & Export to Social]`
    *   `[Download MP4]`
    *   `[Copy Instagram Caption]`

---

## 7. Open Source Tools & MCP Ecosystem Map

The project integrates the following specialized libraries and Model Context Protocol servers:

| Component | Library / MCP Server | Purpose |
|---|---|---|
| **Local Video Editing MCP** | **[Kinocut](https://github.com/KyaniteLabs/kinocut)** / **[dubnium0/ffmpeg-mcp](https://github.com/dubnium0/ffmpeg-mcp)** | Exposes typed FFmpeg operations directly to AI agents for local clipping, cropping, and audio filter execution. |
| **Video Composition** | **Remotion** (`@remotion/cli`, React) | Programmable video generation for rendering vertical 9:16 social templates with dynamic scores, timer tickers, and player name lower-thirds. |
| **Deterministic Trimming** | **FFmpeg 7.x** + `ffmpeg-python` | High-speed stream-copy slicing (`-c copy`) for zero-quality-loss clip extraction. |
| **Audio Excitement Detection** | **Librosa** + **TensorFlow YAMNet** | Spectral analysis of crowd cheering, volume surges, and whistle frequency isolation (3.3–4.2 kHz). |
| **Scene & Cut Detection** | **PySceneDetect** (`scenedetect`) | Content-aware boundary detection to find natural play start and stoppage points. |
| **Cloud Multimodal AI** | **Google Gemini 2.0 Flash API** | Fast, high-context visual understanding to classify complex rugby events and generate social captions. |
| **Cloud Ingestion & Storage** | **Google Drive API v3** + **Google Cloud Storage** | Syncing files from Google Workspace for Nonprofits shared drives with zero local storage footprint. |

---

## 8. Phased Implementation Roadmap

### Phase 1: Core CLI & Video Analysis Engine (Week 1–2)
*   **Goal:** Standalone Python CLI (`fog-highlight-engine`) that runs locally or on a cloud server.
*   **Deliverables:**
    *   Ingest directory scanner for MP4/MOV files.
    *   Audio excitement and whistle detection modules using Librosa and YAMNet.
    *   Veo metadata parser.
    *   Automated generation of `manifest.json`.
    *   FFmpeg lossless clip extraction script.

### Phase 2: Social Reformatting & Brand Styling Engine (Week 3)
*   **Goal:** Turn extracted raw clips into viral 9:16 Instagram Reels.
*   **Deliverables:**
    *   9:16 vertical framing filtergraph with Fog Pitch Navy `#00243C` padding.
    *   Two-pass EBU R128 (-14.0 LUFS) audio mastering pipeline.
    *   Remotion / SVG overlay templates for try animations and player name cards in Futura PT.
    *   Batch export to Google Drive "Social Ready" folder.

### Phase 3: Squarespace Developer Mode Portal Frontend (Week 4)
*   **Goal:** Deploy web-based review and management hub on the club website.
*   **Deliverables:**
    *   Squarespace `/portal/media` page template and styling (JSON-T / CSS adhering to Fog Rugby tokens).
    *   HTML5 video previewer with 9:16 social crop overlay.
    *   Webhook connection to trigger backend render jobs.
    *   Direct download and social caption clipboard integration.

---

## 9. Security, Quotas & Resource Hygiene

1. **Storage Hygiene:** Raw video uploads use the club's **100 TB Google Workspace for Nonprofits** shared drive. Intermediate scratch files (proxies, raw audio WAVs) are automatically purged after clip rendering to prevent Mac/cloud disk saturation (per Disk Space Awareness rule).
2. **Secrets Management:** Google Drive API credentials, Veo tokens, and Gemini API keys are loaded strictly via environment variables (`.env`), never committed to git.
3. **Bandwidth Efficiency:** Clip previews in the web portal use downscaled 720p 1.5 Mbps proxies rather than streaming multi-gigabyte raw 4K match files.
