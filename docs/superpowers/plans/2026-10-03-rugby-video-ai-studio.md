# SF Fog RFC — Game Day Video AI Studio Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-03-rugby-video-ai-studio-design.md`  
**Branch:** `feature/ai-video-studio`  
**Cloud Service:** Cloud Run (`fog-video-analysis-546438448149.us-west1.run.app`)

---

## Task 1: Veo High-Resolution Stream Extraction & API Client Enhancement
- **Files:** `cloud_service/veo_api_client.py`
- **Actions:**
  - Remove hardcoded `render_type="standard"` constraint from `get_match_videos()`.
  - Add logic to sort and select the highest resolution video render (e.g. 1080p 60fps or Panoramic master).
  - Add timeout resilience and backoff matching patterns from `justincampbell/veo`.
- **Verification:**
  - Run `python3 -m unittest tests/test_veo_client.py` (or targeted test script) confirming high-res stream resolution selection.

---

## Task 2: Gemini 2.0 Flash Vision Multimodal Team Classifier
- **Files:** `engine/team_analyzer.py`, `engine/models.py`
- **Actions:**
  - Replace heuristic color-checking with Google GenAI / Vertex AI `gemini-2.0-flash` multimodal inference.
  - Implement 3–5 keyframe extraction per moment using FFmpeg.
  - Implement structured prompt enforcing the official kit ground truth (SF Fog rainbow band/blue jersey vs. opponent white/pink jersey).
  - Tag moments with `sentiment`: `fog_positive`, `opposing_team`, or `neutral`.
- **Verification:**
  - Run verification on Try 1 (`veo_evt_028`) ➔ asserts `fog_positive`.
  - Run verification on Convicts Try (`veo_evt_034`) ➔ asserts `opposing_team`.

---

## Task 3: Subfolder Organization & Naming Standard Router
- **Files:** `engine/naming.py`, `cloud_service/drive_client.py`, `cloud_service/job_runner.py`
- **Actions:**
  - Ensure all moment types map to their target subfolders:
    - Fog Positive ➔ `Highlights/`, `Tries/`, `Scrums/`, `Lineouts/`, `Conversions & Kicks/`, `General Play/`
    - Opposing Team ➔ `Opposing Team Videos/{MomentType}/`
  - In `drive_client.py`, support recursive video discovery and ensure `read_manifest()` locates manifests in subfolders or root.
  - Update `job_runner.py` to stream-copy 16:9 cuts and render 9:16 vertical cuts into the correct subfolders.
- **Verification:**
  - Run `python3 -c "import engine.naming as n; ..."` verifying correct path resolution for both positive and negative moments.

---

## Task 4: Deploy & Verify Live Pipeline on Bingham Cup Match
- **Files:** `cloud_service/main.py`, `cloudbuild.yaml`
- **Actions:**
  - Wire `/drive/organize-moments` to execute folder creation and file relocation in Google Drive for `20260822_v4fb17b0_sf-fog-vs-sydney-convicts-1`.
  - Prune duplicate reels and verify clean Drive tree structure.
  - Deploy updated container to Cloud Run using `gcloud builds submit` or verify via direct endpoints.
- **Verification:**
  - Verify Google Drive folder `20260822_v4fb17b0_sf-fog-vs-sydney-convicts-1` contains the cleanly separated subfolders and accurately classified clips.
