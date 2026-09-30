# Media Hub: Full Veo Catalog, Expiring Backup, Dual Status Badges & Social Ready Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the full 85-match Veo catalog with multi-page pagination, provide urgent 1-click Google Drive backup for the 4 expiring matches, clarify dual Drive storage vs. AI analysis status badges, and activate the Social Ready tab with Google Drive extracted clips gallery and 1-click social copy.

**Architecture:** Python 3.13 backend on Cloud Run with paginated Veo client and Drive metadata scanning; Squarespace Developer Mode frontend with 3-tab pipeline navigation (Veo Clubhouse, Match Review, Social Ready), dual badge rendering, and zero-radius canon styling.

**Tech Stack:** Python 3.13, Flask, Google Drive API, Veo REST API, JavaScript (ES5-safe), LESS 1.3.3.

## Global Constraints
- Strict adherence to SF Fog RFC Brand System Rev 4 (`border-radius: 0`, `--fog-blue: #006EB6`, `--fog-dark-blue: #00243C`, `--fog-light-blue: #24A0F1`, `--fog-gray: #DCDDDE`, `--fog-gray-50: #F4F5F6`, `--fog-green: #157A38`, `--fog-red: #C4321F`).
- No inline styles (`style=""`) in Squarespace templates.
- LESS 1.3.3 compiler clean passing (`tools/lesscheck.js`).
- ES5 JavaScript compliance (`tools/jscheck.js`).

---

### Task 1: Veo API Multi-Page Pagination & Expiration Metadata

**Files:**
- Modify: `cloud_service/veo_api_client.py`
- Test: `tests/test_veo_ingest.py`

- [ ] **Step 1: Write unit test for multi-page pagination and expiration parsing**
- [ ] **Step 2: Update `list_club_recordings` in `veo_api_client.py` to paginate through pages 1–5 and extract `expires_at`, `expiration_status`, and `time_to_expiry`**
- [ ] **Step 3: Run pytest via uv to verify passing tests**
- [ ] **Step 4: Commit changes to git**

---

### Task 2: Backend Routes: Full Catalog Cross-Referencing & Batch Expiring Backup

**Files:**
- Modify: `cloud_service/main.py`
- Test: `tests/test_veo_ingest.py`

- [ ] **Step 1: Update `GET /veo/recordings` in `main.py` to cross-reference all 85 matches with Google Drive and count un-backed-up expiring matches**
- [ ] **Step 2: Add `POST /veo/backup-expiring` in `main.py` to batch-queue download jobs for all expiring matches**
- [ ] **Step 3: Run pytest via uv to verify**
- [ ] **Step 4: Commit changes to git**

---

### Task 3: Backend Route: Social Ready Clips from Drive Output

**Files:**
- Modify: `cloud_service/main.py`
- Modify: `cloud_service/drive_client.py`

- [ ] **Step 1: Add `list_social_clips()` to `DriveClient` to read extracted MP4 clips and manifests from the Drive output folder**
- [ ] **Step 2: Add `GET /drive/social-clips` to `main.py` returning clip metadata, download URLs, and captions**
- [ ] **Step 3: Test via curl on local or unit test**
- [ ] **Step 4: Commit changes to git**

---

### Task 4: Frontend Template: Expiring Backup Alert, Dual Status Filter Pills, and Social Ready Section

**Files:**
- Modify: `fog_website/pages/game-day-media-hub.page`

- [ ] **Step 1: Add `#veo-expiring-alert` warning banner with `#btn-backup-expiring` above media controls**
- [ ] **Step 2: Update status filter pills to include `In Google Drive`, `✓ Analyzed & Ready`, `⚠️ Expiring Soon`, `Expired on Veo`**
- [ ] **Step 3: Add `#social-section` containing format filter pills and `#social-clips-grid`**
- [ ] **Step 4: Run `node tools/speccheck.js` to verify template tags and constraints**
- [ ] **Step 5: Commit changes to git**

---

### Task 5: Frontend Styles: Alert Banner, Dual Badges, and Social Clips Grid

**Files:**
- Modify: `fog_website/styles/brand-system.less`

- [ ] **Step 1: Add `.fog-alert-banner` and `.fog-alert-banner--warning` styles**
- [ ] **Step 2: Add `.fog-social-grid`, `.fog-social-card`, and aspect-ratio media containers**
- [ ] **Step 3: Add dual badge layout styles for `.moment-card` and `.fog-fixture-row`**
- [ ] **Step 4: Run `node tools/lesscheck.js` to verify compilation under LESS 1.3.3**
- [ ] **Step 5: Commit changes to git**

---

### Task 6: Frontend Controller: Navigation, Dual Badges, Expiring Backup Trigger, and Social Hub

**Files:**
- Modify: `fog_website/scripts/fog-media-hub.js`

- [ ] **Step 1: Update `_showTab()` to handle all 3 tabs (`veo`, `moments`, `social`) and wire subnav links**
- [ ] **Step 2: Implement dual badge rendering on cards: display both `[✓ In Google Drive]` and `[✓ Analyzed]`, plus expiring badges**
- [ ] **Step 3: Implement filter pill logic so `In Google Drive` counts all downloaded videos**
- [ ] **Step 4: Wire `#btn-backup-expiring` to call `POST /veo/backup-expiring` with toast notification and progress tracking**
- [ ] **Step 5: Implement `loadSocialClips()` and `_renderSocialClips()` on the Social Ready tab**
- [ ] **Step 6: Run `npm run check` to verify ES5 and LESS safety**
- [ ] **Step 7: Commit changes to git**

---

### Task 7: Automated Tests, Cloud Run Deploy & Squarespace Push

**Files:**
- Deploy: `fog-advertising` (Cloud Run `fog-video-analysis`)
- Push: `fog_website` (Squarespace `master`)

- [ ] **Step 1: Push `fog-advertising` and submit Cloud Build deployment**
- [ ] **Step 2: Push `fog_website` to origin master**
- [ ] **Step 3: Verify Cloud Run revision is live and responding to `/veo/recordings` and `/drive/social-clips`**

---

### Task 8: Live Browser Verification via Chrome DevTools MCP

- [ ] **Step 1: Navigate to `https://fogrugby.com/game-day-media-hub` in desktop viewport**
- [ ] **Step 2: Verify Veo Clubhouse: 85 matches listed, expiring alert banner visible, dual badges on Sydney Convicts 1**
- [ ] **Step 3: Verify Match Review tab: 34 detected AI moments, set-piece pills, seek sync**
- [ ] **Step 4: Verify Social Ready tab: active tab navigation, format pills, clip cards with copy caption**
