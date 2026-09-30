# SF Fog RFC Media Hub: Full Veo Catalog, Expiring Backup, Dual Status Badges & Social Ready Hub Design

> **Goal:** Surface the full 85-match Veo clubhouse catalog (pages 1–5), provide urgent 1-click Google Drive backup for the 4 expiring matches, clarify dual Drive storage vs. AI analysis status badges, and activate the Social Ready tab with Google Drive extracted clips gallery and 1-click social copy.

---

## 1. Problem Statement & Root Cause Analysis

1. **Missing Recordings (Pages 1–6 & Expiring Soon):**
   The Veo REST API at `https://app.veo.co/api/app/clubs/san-francisco-fog-rfc/recordings/` paginates in blocks of 20. The club has 85 total recordings across 5 pages:
   - 34 current recordings (`does-not-expire-soon`).
   - 4 expiring-soon recordings (1 with 26 days left, 3 with ~47–53 days left) which still have full 1080p video renders available for download on Veo CDN.
   - 47 older expired recordings where Veo deleted standard renders.
   The backend was previously fetching only `page=1` (20 items).
2. **Confusing Drive vs. Analyzed Status:**
   The Sydney Convicts 1 match was downloaded to Google Drive (2.3 GB) and analyzed. However, the frontend filter logic treated `Analyzed` and `In Drive` as mutually exclusive, hiding the `In Drive` badge and displaying `0` for the `In Google Drive` filter pill count.
3. **Inactive Social Ready Tab:**
   `#subnav-social` was present in the template subnav but lacked an HTML section and JS controller. Finished vertical reels (9:16) and square highlights (1:1) saved in Google Drive had no hub for coaches/players to view and post.

---

## 2. Architecture & System Design

```
+----------------------------------------------------------------------------------------------------+
|                                    SF FOG RFC GAME DAY MEDIA HUB                                   |
|                                                                                                    |
|  [Tab 1: Veo Clubhouse]           [Tab 2: Match Review]              [Tab 3: Social Ready]         |
|  - Full 85-match catalog          - 34 detected AI moments           - Extracted 9:16/1:1 clips    |
|  - 4-Match Expiring Alert         - Set-piece filter pills           - Google Drive downloads      |
|  - Dual Badges (Drive + Analyzed) - Video player seek sync           - 1-click caption & hashtags  |
|  - Grid / List / Featured views   - On-demand clip extraction        - Post-ready social preview   |
+----------------------------------------------------------------------------------------------------+
                                      |                                  ^
                                      v                                  |
               +---------------------------------------------------------------+
               |                 CLOUD RUN SERVICE (Python 3.13)               |
               |                                                               |
               |  GET  /veo/recordings?all=true (multi-page paginator)         |
               |  POST /veo/backup-expiring (batch download 4 urgent matches)  |
               |  GET  /drive/social-clips (reads Drive output folder)         |
               |  POST /extract (ffmpeg extracts 9:16, 1:1, 4:5 to Drive)     |
               +---------------------------------------------------------------+
```

---

## 3. Detailed Component Specifications

### 3.1 Backend Service (`fog-advertising`)

#### `cloud_service/veo_api_client.py`
- Update `list_club_recordings(club_slug, page=None, fetch_all=True)`:
  - If `fetch_all=True`, loop through `page=1, 2, 3...` until a 404 or empty list is returned.
  - Extract native expiration fields: `expires_at`, `expiration_status`, and `time_to_expiry`.
  - Mark records:
    - `is_expiring_soon`: True if `expiration_status == "expires-soon"` or `0 < time_to_expiry.value <= 60`.
    - `is_expired`: True if `expiration_status == "expired"`.
    - `time_to_expiry_days`: Integer days remaining.

#### `cloud_service/main.py`
- Update `/veo/recordings`:
  - Cross-reference all 85 recordings against `DriveClient.list_downloaded_videos_map()` and existing manifests.
  - Return `expiring_count` (number of expiring matches not yet in Google Drive).
- Add `POST /veo/backup-expiring`:
  - Finds all un-downloaded matches with `is_expiring_soon=True`.
  - Queues ingest jobs for each.
- Add `GET /drive/social-clips`:
  - Queries Google Drive output folder for extracted video files (`.mp4`) and corresponding metadata.
  - Returns list with `clip_id`, `match_title`, `format` (`9:16`, `1:1`, `4:5`), `drive_file_id`, `download_url`, `created_time`, and `suggested_caption`.

---

### 3.2 Squarespace Template & Styles (`fog_website`)

#### `pages/game-day-media-hub.page`
1. **Veo Clubhouse Tab (`#veo-section`):**
   - Add `#veo-expiring-alert`: Urgent warning banner shown if `expiring_count > 0`, with button `#btn-backup-expiring`.
   - Update filter pills:
     - `All Matches`
     - `In Google Drive` (all matches stored in Drive, regardless of analysis state)
     - `✓ Analyzed & Ready` (matches with manifests)
     - `⚠️ Expiring Soon` (matches with `< 60 days` left on Veo)
     - `Expired on Veo` (legacy records)
2. **Social Ready Tab (`#social-section`):**
   - Container `#social-section` with header "Social Ready Clips".
   - Format filter pills: `All Formats`, `Reels (9:16)`, `Square (1:1)`, `Feed (4:5)`.
   - Clip grid `#social-clips-grid` with `.fog-social-card`:
     - Aspect ratio video container with HTML5 video player.
     - Badge for format (`9:16 REEL`, `1:1 SQUARE`).
     - Match title and moment event type.
     - Copy Caption & Hashtags button.
     - Direct Download / Open in Drive button.

#### `styles/brand-system.less`
- Implement `.fog-alert-banner`: 0-radius alert container with `--fog-red` / `--fog-yellow` accent.
- Implement `.fog-social-grid` and `.fog-social-card`: 0-radius cards styled to Fog brand tokens.
- Implement dual badge rendering for `.moment-card` and `.fog-fixture-row`.

#### `scripts/fog-media-hub.js`
- Connect subnav: `#subnav-clips`, `#subnav-veo`, `#subnav-social`.
- Implement `_showTab("social")` and `loadSocialClips()`.
- Implement `_renderDualBadges()`: displays both `[✓ In Google Drive]` and `[✓ Analyzed]` without collision.
- Wire `#btn-backup-expiring` to call `POST /veo/backup-expiring`.

---

## 4. Verification Plan

1. **Automated Checks:**
   - Run `npm run check` in `fog_website` (LESS 1.3.3 compiler check, ES5 check, speccheck token check).
   - Run pytest tests via `uv` in `fog-advertising`.
2. **Backend API Validation:**
   - `GET /veo/recordings`: Verify 85 recordings returned with accurate `is_downloaded`, `is_ingested`, and `is_expiring_soon` flags.
   - `GET /drive/social-clips`: Verify returns social-ready video files.
3. **Live UI Verification via Chrome DevTools MCP:**
   - Veo Clubhouse: Verify 85 matches appear, with `In Google Drive (1)` and `Analyzed & Ready (1)`.
   - Expiring alert: Verify surfaces the 4 expiring matches with days countdown.
   - Social Ready: Click `#subnav-social`, verify active tab state and social clip gallery.
