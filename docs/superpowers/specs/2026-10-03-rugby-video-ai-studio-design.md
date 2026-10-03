# SF Fog RFC — Game Day Video AI Studio & Highlight Generation Architecture

**Date:** 2026-10-03  
**Status:** Approved for Implementation  
**Target Branch:** `feature/ai-video-studio`  
**Deployment Target:** Google Cloud Run (`sffog-video-analysis`) & Google Drive (`1lNCnRFDyyf3bE0fzNHqHNpzN7s5xalzy`)

---

## 1. Executive Summary & Goals

The objective is to eliminate brittle, hardcoded heuristics and constant debugging by deploying a production-ready, cloud-based rugby video clipping, highlight packaging, and team sentiment classification system for SF Fog RFC.

### Core Goals:
1. **Zero Local Compute Burden:** 100% of video downloading, Gemini Vision inference, and FFmpeg video manipulation runs inside Google Cloud Run.
2. **Unified Standardized Naming:** All match folders, master downloads, and social-ready clips adhere strictly to:
   - Root folder: `YYYYMMDD_UNIQUEID_sf-fog-vs-{opponent}-{side}`
   - Master raw file: `YYYYMMDD_UNIQUEID_sf-fog-rugby_vs_{opponent}_{quality}.mp4`
   - Social clips/reels: `YYYYMMDD_UNIQUEID_fog-rugby_{dimensions}_{moment_type}.mp4`
3. **Automated Team Sentiment Categorization:** 
   - 🟢 **Fog Positive:** Tries, conversions, and dominant set pieces won by SF Fog route into root moment subfolders (`Highlights/`, `Tries/`, `Scrums/`, `Lineouts/`, `Conversions & Kicks/`, `General Play/`).
   - 🔴 **Opposing Team:** Opponent scoring plays and conceded set pieces route into `Opposing Team Videos/{MomentType}/`.
   - 🟡 **Needs Review:** Low confidence plays (<75%) route into `Needs Review/` rather than polluting Fog reels.
4. **High-Resolution Video Extraction:** Support highest-bitrate Veo CDN streams (1080p 60fps and ultra-wide panoramic renders up to 4K).
5. **Lossless Broadcast & Crisp 9:16 Social Mastering:** Stream-copy (`-c copy`) for instant 16:9 cuts; Lanczos4 + unsharp detail boost for vertical 9:16 reels.

---

## 2. Integrated Open-Source Architecture

We synthesize five proven repositories into a cohesive pipeline:

| Repository | Role in Architecture | Key Implementation Component |
| :--- | :--- | :--- |
| **`dennyschwender/sport-video-AI-analysis`** | Chunked frame extraction, Gemini Vision event & team detection, stream-copy concatenation. | `cloud_service/ai_scanner.py` & `engine/highlight_packager.py` |
| **`NaufalRizqullah/opensource-clipping`** | Dynamic deadzones and horizontal-to-vertical crop tracking. | `engine/framing.py` |
| **`justincampbell/veo`** | Veo API client patterns for authenticating, pagination, and direct CDN high-res MP4 extraction. | `cloud_service/veo_api_client.py` |
| **`SharpeShooter02/RugbyViz`** | Club rugby match territory and set-piece clustering from Veo camera angle. | `engine/setpiece_detector.py` |
| **`smartrunners/smartrunners-ball-tracker`** | Kalman filter smoothing and occlusion re-acquisition during rucks and scrums. | `engine/framing.py` |

---

## 3. Google Drive Hierarchy & Naming Standard

### 3.1 Folder Tree
```
📂 [Match Root]: YYYYMMDD_UNIQUEID_sf-fog-vs-{opponent}-{side}/
   ├── 📄 {YYYYMMDD}_{UNIQUEID}_manifest.json
   ├── 📁 Highlights/
   │   ├── {YYYYMMDD}_{UNIQUEID}_fog-rugby_16x9_match-highlights.mp4
   │   └── {YYYYMMDD}_{UNIQUEID}_fog-rugby_9x16_match-highlights.mp4
   ├── 📁 Tries/
   │   ├── {YYYYMMDD}_{UNIQUEID}_fog-rugby_16x9_try-1-breakaway.mp4
   │   └── {YYYYMMDD}_{UNIQUEID}_fog-rugby_9x16_try-1-breakaway.mp4
   ├── 📁 Scrums/
   ├── 📁 Lineouts/
   ├── 📁 Conversions & Kicks/
   ├── 📁 General Play/
   └── 📁 Opposing Team Videos/
       ├── 📁 Tries/
       ├── 📁 Conversions & Kicks/
       └── 📁 Scrums & Lineouts/
```

### 3.2 Naming Enforcement (`engine/naming.py`)
- Standardized parser ensures clean extraction of date, camera ID, opponent slug, dimensions, and moment slugs.
- Auto-generates path routers for Cloud Run upload jobs.

---

## 4. Kit Ground Truth & Gemini 2.0 Flash Vision Classification

### 4.1 Official SF Fog Kit Truth Set
- **SF Fog A-Side:** Jersey with vivid rainbow band across chest, white shorts.
- **SF Fog B-Side & C-Side:** Blue tops (`--fog-blue` `#006EB6` or navy `#00243C`) with white or black shorts.
- **Opponent (Sydney Convicts):** White jerseys with pink/red collars, stripes, and numbers.

### 4.2 Gemini Vision Structured Inference
Using `gemini-2.0-flash` on Vertex AI:
1. Extract 3 to 5 key frames per candidate moment (start, mid/contact, finish/grounding).
2. Prompt Gemini with kit definitions, field position, and referee signals.
3. Response schema returns:
   - `action`: `try` | `conversion` | `scrum` | `lineout` | `breakaway` | `tackle`
   - `scoring_team`: `SF Fog RFC` | `Opponent` | `Unknown`
   - `sentiment`: `fog_positive` | `opposing_team` | `neutral`
   - `confidence`: float `0.0` - `1.0`
   - `rationale`: string explanation of jersey detection and play outcome.

---

## 5. High-Resolution Veo Stream & Video Mastering

1. **High-Res Extraction:**
   - Update `VeoApiClient.get_match_videos()` to query all available render types without restricting to standard follow-cam.
   - Select the highest available resolution stream (1080p 60fps or Panoramic master).
2. **Mastering Standards (Per SF Fog Sports Video Guardrail):**
   - **Full-Bleed 9:16:** $608\times1080$ crop window with zero pillarbox or letterbox bars.
   - **Upscaling:** 8-tap Lanczos interpolation (`flags=lanczos` / `cv2.INTER_LANCZOS4`).
   - **Detail Boost:** FFmpeg unsharp filter (`unsharp=5:5:0.7:3:3:0.3`).
   - **Audio Mastering:** EBU R128 `-14 LUFS` integrated loudness, `-1.5 dBFS` true peak, 80Hz highpass rumble filter.
   - **Encoding:** `-crf 18`, `-preset slow`, `yuv420p`, `-movflags +faststart`.

---

## 6. Implementation Components

1. `cloud_service/veo_api_client.py`: High-res stream discovery and enhanced error recovery.
2. `engine/team_analyzer.py`: Vertex AI / Gemini 2.0 Flash multimodal classifier replacing naive HSV color checks.
3. `cloud_service/ai_scanner.py`: Full-match chunked background scanner for discovering untagged plays.
4. `engine/naming.py` & `cloud_service/drive_client.py`: Strict subfolder creation, manifest routing, and duplicate reel pruning.
5. `cloud_service/job_runner.py`: Stream-copy 16:9 cuts and Lanczos4 9:16 vertical video processing.
6. `cloud_service/main.py`: Interactive Studio endpoints (`/analyze`, `/analyze/rescan`, `/drive/organize-moments`, `/reel/compile`).

---

## 7. Verification & Success Criteria

1. **Verification on Bingham Cup Match:**
   - Run on `20260822_v4fb17b0_sf-fog-vs-sydney-convicts-1`.
   - Verify Try 1 (06:41) classified as **Fog Positive** ➔ `Tries/`.
   - Verify Convicts Try (15:25) classified as **Opposing Team** ➔ `Opposing Team Videos/Tries/`.
   - Verify Scrums and Lineouts partitioned into their respective subfolders.
2. **No Hardware Impact:** Cloud Run logs confirm all rendering and Drive uploads happen server-side.
3. **No Duplicate Files:** Google Drive contains exactly one copy of each cut per subfolder.
