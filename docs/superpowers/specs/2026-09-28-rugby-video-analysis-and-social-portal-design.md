# Technical Specification & Design Document: Rugby Match Analysis & Social Clip Hub

**Document ID:** `2026-09-28-rugby-video-analysis-and-social-portal-design`  
**Date:** September 28, 2026  
**Status:** DRAFT (Updated with User Review & Architectural Refinements)  
**Target Platform:** Squarespace Developer Mode Portal (`/portal/media`) + Google Cloud / Google Workspace for Nonprofits Backend + Local/Cloud Video Processing Engine  
**Brand Compliance:** SF Fog RFC Brand System (Pitch Navy `#00243C`, Fog Blue `#006EB6`, Futura PT, Zero-Pill Law, -14 LUFS Audio)

---

## 1. Executive Summary & Goals

San Francisco Fog RFC captures dozens of hours of match and practice footage across every season:
1. **Veo 2/3 Cameras:** Elevated tactical panoramic / follow-cam recordings (40–80 minute continuous halves).
2. **Sideline Phone Cameras:** Mobile, handheld 1080p/4K vertical and landscape video files of individual plays, tries, celebrations, scrums, and bench reactions.

### Core Problem
Match footage sits locked in raw video archives or Veo Clubhouse silos. Finding the 5–10 viral, high-excitement rugby moments (tries, bone-crunching tackles, lineout steals, penalty kicks, end-game celebrations) requires hours of tedious manual scrubbing. Producing high-impact social clips requires significant editing friction.

### Project Objectives (Refined with User Feedback)
1. **Automated Veo & Cloud Ingestion:** Automatically ingest Veo match footage and AI tags into Google Cloud / Google Drive the moment Veo finishes processing, alongside incoming phone camera folders.
2. **Automated Highlight & Excitement Detection:** Identify emotional rugby moments using a multi-modal approach:
   - Ingesting Veo AI match tags (halves, tries, fouls).
   - Audio energy, crowd cheering, and referee whistle detection (3.3–4.2 kHz) for sideline phone clips and raw match audio.
   - Multimodal verification (Gemini 2.0 Flash / local VLM) for rugby context classification.
3. **Lossless Master Extraction:** Extract clip candidates into clean, standalone high-definition master files with pre-roll (-5s) and post-roll (+7s) context buffers.
4. **AI/ML Editorial Intelligence & Pairing Suggestions:** Use AI/ML to analyze pulled clips and suggest:
   - **Recommended Uses:** (e.g., "Hype Reel Hook", "Mid-week Player Spotlight", "Defensive Masterclass").
   - **Cross-Clip Pairings & Compilations:** Suggest related clips that belong together (e.g., pairing a Veo try with a sideline phone celebration).
   - **Platform-Tailored Copy:** Ready-to-copy hooks, captions, and hashtags.
5. **On-Demand Multi-Format Social Extraction:** Avoid wasting compute and storage by keeping master clips clean and unbranded by default. Provide one-click on-demand extraction for:
   - 9:16 Vertical Reel / Story (1080x1920)
   - 1:1 Square Feed (1080x1080)
   - 4:5 Portrait Feed (1080x1350)
   - Clean 16:9 Master
6. **Squarespace Club Portal Integration:** Provide a user-friendly management dashboard within the Fog portal (`/portal/media`) where media team members can review detected moments, play previews, approve clips, and trigger social exports.

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
   - Triggered automatically when new files arrive in the Google Drive folder or via Veo notification.
3. **Web Streaming & Review in Squarespace:**
   - For lightweight previewing inside the Squarespace portal, the worker generates low-bitrate 720p MP4 preview proxies stored in Google Cloud Storage or streamed via lightweight signed URLs.
   - For public full-match broadcasts, unlisted YouTube embeds remain ideal, but social highlights stream directly from fast proxy storage.

---

## 3. High-Level System Architecture

```
+-----------------------------------------------------------------------------------+
|                        AUTOMATED INGESTION & SYNC LAYER                           |
|                                                                                   |
|  [Veo Clubhouse API / Notification]         [Sideline Phone Cameras]              |
|   Auto-detects when match is ready           Players/coaches drop into            |
|   Fetches AI tags + Match MP4                shared Game Day Ingest folder        |
|          |                                                |                       |
|          v                                                v                       |
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
|  4. Multimodal AI (Gemini 2.0 Flash): Rugby classification & player tags          |
|  5. AI Editorial Engine: Suggests clip pairings, compilations, and social copy    |
|                                                                                   |
|  OUTPUT: manifest.json (Timestamped Event Catalog + Pairings + AI Suggestions)    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                       SQUARESPACE CLUB PORTAL (/portal/media)                     |
|                                                                                   |
|  - Custom Squarespace Developer Mode Collection & Controller                      |
|  - Displays Match Catalog, Detected Events (Try, Big Tackle, Lineout, Breakaway)  |
|  - Shows AI Suggestions: "Pair with Clip #3 for Hype Reel", captions, hashtags    |
|  - In-browser HTML5 Video Player with timestamp scrubber & framing preview        |
|  - On-Demand Format Selector: [9:16 Reel] [1:1 Square] [4:5 Portrait] [16:9 Raw]  |
+-----------------------------------------------------------------------------------+
                                         | (Triggered On-Demand by User)
                                         v
+-----------------------------------------------------------------------------------+
|                      ON-DEMAND SOCIAL REFORMATTER & EXPORT                        |
|                                                                                   |
|  1. Lossless Master Cut (-5s pre-roll, +7s post-roll)                             |
|  2. Selected Reframe: 9:16 (1080x1920), 1:1 (1080x1080), or 4:5 (1080x1350)       |
|  3. Audio Mastering: EBU R128 Two-Pass Normalization (-14.0 LUFS, -1.0 dBTP)       |
|  4. Optional Branding (Toggleable): Futura PT lower-thirds or clean unbranded     |
|                                                                                   |
|  DESTINATION: Google Drive /SF Fog RFC Media/Social Ready/YYYY-MM-DD/             |
+-----------------------------------------------------------------------------------+
```

---

## 4. Video Analysis & Excitement Detection Pipeline

Rugby video analysis requires handling two distinct footage profiles:

### 4.1 Veo Automated Ingestion & Pipeline
*   **Automated Ingestion Trigger:**
    1.  **Email Notification Hook (Activepieces / Cloud Function):** When Veo finishes AI processing, it sends an email: *"Your match is ready: SF Fog RFC vs [Opponent]"*. An email parser extracts the match URL and triggers the ingest worker.
    2.  **API Polling Fallback:** A lightweight Cloud Run cron checks `api.veo.co.uk` post-game for matches in `COMPLETED` status.
    3.  **Direct Cloud Transfer:** The worker downloads the AI-tagged match events (JSON) and match MP4 directly into the Google Workspace Shared Drive folder, eliminating manual downloading.
*   **Whistle & Restart Detection:** Referee whistles have a distinctive acoustic signature concentrated in the **3,300 Hz – 4,200 Hz** band. A Short-Time Fourier Transform (STFT) bandpass filter pinpoints whistle blows marking penalties, tries, and scrums.
*   **Ball Movement / Motion Surge:** Optical flow calculation around whistle timestamps isolates the preceding 10 seconds of high-velocity play (the line break or tackle).

### 4.2 Sideline Phone Camera Pipeline
*   **Characteristics:** Handheld, vertical or horizontal; close-up to spectators and bench; intense localized shouting and cheering; variable clip lengths (15s to 3m).
*   **Strategy:**
    1.  **RMS Audio Energy & Loudness Curve:** Computes root-mean-square audio energy in 0.5s windows. Sideline cheering creates a sharp +6dB to +12dB surge over background ambient noise.
    2.  **YAMNet Audio Event Classification:** Open-source lightweight neural net trained on AudioSet. Specifically filters for top-ranked classes: `Cheering`, `Applause`, `Laughter`, `Yell`, `Screaming`.
    3.  **Scene Transition Analysis:** Uses `scenedetect` (content detector threshold 27.0) to locate natural start/stop boundaries so cuts do not slice halfway through a play.

### 4.3 AI/ML Editorial Intelligence & Pairing Engine
Rather than burning compute to brand every video blindly, the AI/ML layer acts as a creative assistant:
1.  **Use-Case Categorization:** Tags clips with strategic editorial roles:
    *   `hype_reel_hook`: High-impact tackle or fast breakaway try.
    *   `player_spotlight`: Extended run or individual effort suitable for a player feature.
    *   `forward_pack_pride`: Scrum turnover, maul drive, or lineout steal.
    *   `sideline_culture`: High-energy bench reaction, team chant, or fan celebration.
2.  **Cross-Clip Pairing Suggestions:** Identifies clips that complement one another:
    *   *Example:* Veo tactical angle of a corner try + Sideline phone clip of the post-try team dogpile = *"Pair as a 2-clip Reel transition"*.
3.  **Social Copy & Audio Ideas:** Generates suggested caption, hashtags, and audio vibe (e.g., "fast-tempo hype track").

### 4.4 Candidate Event Catalog Schema (`manifest.json`)
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
      "suggested_uses": ["hype_reel_hook", "story_recap"],
      "suggested_pairings": [
        {
          "paired_event_id": "evt_003",
          "reason": "Sideline phone clip shows close-up celebration of this exact try"
        }
      ],
      "suggested_caption": "Try time on Treasure Island! 🏉 Fog crossing the whitewash!",
      "suggested_hashtags": ["#SFFogRFC", "#FogRugby", "#InclusiveRugby", "#BinghamCup"],
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
      "suggested_uses": ["defensive_reel", "shorts_hook"],
      "suggested_pairings": [],
      "suggested_caption": "Defense setting the standard 😤 Hit of the match!",
      "suggested_hashtags": ["#RugbyHits", "#BigTackle", "#SFFogRFC"],
      "status": "pending_review"
    }
  ]
}
```

---

## 5. On-Demand Multi-Format Social Extraction Engine

To save CPU compute, storage space, and prevent unwanted visual artifacts, clips are **extracted clean and unbranded by default**. Editors can generate specific formats on demand with a single click.

### 5.1 On-Demand Format Recipes

#### 1. 9:16 Vertical Reel / Story (1080 × 1920)
*   **Use Case:** Instagram Reels, TikTok, YouTube Shorts.
*   **Recipe:** Centers action in vertical frame. If letterboxing horizontal 16:9 Veo footage, padding uses Fog Pitch Navy (`#00243C`):
    ```bash
    ffmpeg -y -i input_master.mp4 \
      -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x00243C,format=yuv420p" \
      -c:v libx264 -profile:v high -level:v 4.1 -preset slow -crf 18 \
      -c:a aac -b:a 256k -ar 48000 -movflags +faststart output_9x16.mp4
    ```

#### 2. 1:1 Square Feed (1080 × 1080)
*   **Use Case:** Instagram Grid post, LinkedIn, X/Twitter feed.
*   **Recipe:** Crops or pads into a balanced square presentation:
    ```bash
    ffmpeg -y -i input_master.mp4 \
      -vf "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2:color=0x00243C,format=yuv420p" \
      -c:v libx264 -profile:v high -level:v 4.1 -preset slow -crf 18 \
      -c:a aac -b:a 256k -ar 48000 -movflags +faststart output_1x1.mp4
    ```

#### 3. 4:5 Portrait Feed (1080 × 1350)
*   **Use Case:** Standard Instagram Feed video (takes up maximum screen real estate on mobile feeds without clipping like 9:16):
    ```bash
    ffmpeg -y -i input_master.mp4 \
      -vf "scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=0x00243C,format=yuv420p" \
      -c:v libx264 -profile:v high -level:v 4.1 -preset slow -crf 18 \
      -c:a aac -b:a 256k -ar 48000 -movflags +faststart output_4x5.mp4
    ```

#### 4. Clean 16:9 Master (Original Resolution)
*   **Use Case:** Archival master, match review, full landscape replay. Extracted via lossless stream-copy (`-c copy`) in milliseconds with zero CPU re-encoding.

### 5.2 Audio Mastering Engine
*   **Target Loudness:** Exactly **-14.0 LUFS** (integrated), True Peak **-1.0 dBTP** via two-pass EBU R128 (`loudnorm`).
*   **High-Pass Filter:** `highpass=f=80` to remove low-frequency wind buffeting and rumble on phone mics.
*   **Sample Rate:** 48 kHz stereo AAC at 256 kbps.

### 5.3 Optional On-Screen Branding (Opt-In Toggle)
If an editor explicitly checks *"Add Fog RFC Branding"* before export, the system applies the official SF Fog RFC brand kit:
*   **Typography:** Futura PT (Bold, ALL CAPS, `letter-spacing: 0.05em`) for event titles.
*   **Club Colors:** Fog Blue (`#006EB6`), Deep Pitch Navy (`#00243C`), Sky Blue (`#24A0F1`).
*   **Zero-Pill Law:** Any on-screen badges/tags use strict `2px` corners.

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
1.  **Match Selector Bar:** Dropdown / list of matches with status indicator (Veo Syncing, Analyzed, Clips Ready).
2.  **Moment Review Grid:** Cards for each detected event displaying:
    *   Event Pill (e.g. `[TRY]` in Fog Blue, `[BIG TACKLE]` in Fog Dark Blue).
    *   Excitement Score Meter (0–100%).
    *   Source Camera Tag (`Veo Cam 1` or `Sideline Phone - Alex`).
    *   Timestamp and duration.
    *   **AI Editorial Recommendation:** Badges showing `Hype Reel Hook`, `Suggested with Clip #3`.
3.  **Interactive Preview Player:**
    *   Instant HTML5 playback of the clip.
    *   Framing Preview toggle: `[Raw 16:9 | 9:16 Reel | 1:1 Square | 4:5 Feed]`.
    *   Trim adjustment handles (`-2s`, `+2s`).
4.  **Format Extraction Actions (On-Demand):**
    *   `[Export 9:16 Reel]`
    *   `[Export 1:1 Square]`
    *   `[Export 4:5 Portrait]`
    *   `[Download Raw Master]`
    *   `[Copy AI Caption & Tags]`

---

## 7. Open Source Tools & MCP Ecosystem Map

| Component | Library / MCP Server | Purpose |
|---|---|---|
| **Local Video Editing MCP** | **[Kinocut](https://github.com/KyaniteLabs/kinocut)** / **[dubnium0/ffmpeg-mcp](https://github.com/dubnium0/ffmpeg-mcp)** | Exposes typed FFmpeg operations directly to AI agents for local clipping, cropping, and audio filter execution. |
| **Video Composition** | **Remotion** (`@remotion/cli`, React) | Programmable video generation for rendering vertical 9:16 social templates with dynamic scores, timer tickers, and player name lower-thirds when branding is toggled on. |
| **Deterministic Trimming** | **FFmpeg 7.x** + `ffmpeg-python` | High-speed stream-copy slicing (`-c copy`) for zero-quality-loss clip extraction. |
| **Audio Excitement Detection** | **Librosa** + **TensorFlow YAMNet** | Spectral analysis of crowd cheering, volume surges, and whistle frequency isolation (3.3–4.2 kHz). |
| **Scene & Cut Detection** | **PySceneDetect** (`scenedetect`) | Content-aware boundary detection to find natural play start and stoppage points. |
| **Cloud Multimodal AI** | **Google Gemini 2.0 Flash API** | Fast, high-context visual understanding to classify complex rugby events, suggest cross-clip pairings, and write social captions. |
| **Cloud Ingestion & Storage** | **Google Drive API v3** + **Google Cloud Storage** | Syncing files from Google Workspace for Nonprofits shared drives with zero local storage footprint. |

---

## 8. Phased Implementation Roadmap

### Phase 1: Core CLI & Video Analysis Engine (Week 1–2)
*   **Goal:** Standalone Python CLI (`fog-highlight-engine`) that runs locally or on a cloud server.
*   **Deliverables:**
    *   Ingest directory scanner for MP4/MOV files.
    *   Veo automated download worker (email/webhook trigger + API polling).
    *   Audio excitement and whistle detection modules using Librosa and YAMNet.
    *   AI editorial suggestion generator (pairings, use cases, captions).
    *   Automated generation of `manifest.json`.
    *   Lossless master clip extractor.

### Phase 2: On-Demand Multi-Format Reformatting Engine (Week 3)
*   **Goal:** Format clips into social dimensions on demand without pre-rendering unnecessary files.
*   **Deliverables:**
    *   FFmpeg filtergraphs for 9:16 (Vertical), 1:1 (Square), and 4:5 (Portrait).
    *   Two-pass EBU R128 (-14.0 LUFS) audio mastering pipeline.
    *   Optional opt-in branding template in Futura PT.
    *   Export to Google Drive "Social Ready" folder.

### Phase 3: Squarespace Developer Mode Portal Frontend (Week 4)
*   **Goal:** Deploy web-based review and management hub on the club website.
*   **Deliverables:**
    *   Squarespace `/portal/media` page template and styling (JSON-T / CSS adhering to Fog Rugby tokens).
    *   HTML5 video previewer with multi-format framing toggles.
    *   Action buttons for 9:16, 1:1, 4:5, and Raw master extraction.
    *   Suggested pairings list & social caption clipboard button.

---

## 9. Security, Quotas & Resource Hygiene

1. **Storage Hygiene:** Raw video uploads use the club's **100 TB Google Workspace for Nonprofits** shared drive. Intermediate scratch files (proxies, raw audio WAVs) are automatically purged after clip rendering to prevent Mac/cloud disk saturation (per Disk Space Awareness rule).
2. **On-Demand Resource Conservation:** Avoiding bulk auto-branding and auto-reformatting saves estimated 70% in compute time and storage space.
3. **Secrets Management:** Google Drive API credentials, Veo tokens, and Gemini API keys are loaded strictly via environment variables (`.env`), never committed to git.
4. **Bandwidth Efficiency:** Clip previews in the web portal use downscaled 720p 1.5 Mbps proxies rather than streaming multi-gigabyte raw 4K match files.
