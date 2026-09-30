# SF Fog RFC Media Hub: Multi-View Interface, Resilient Uploads & Veo AI Moments Implementation Plan

> **Goal:** Eliminate streaming upload network failures with exponential backoff and resume-offset recovery, resolve feed crowdedness via a 3-way view switcher (Grid, List, Featured) and status filter pills, and showcase Veo AI analyzed match moments with interactive set-piece filters and player sync.

---

## Proposed Changes

### Backend Service (`fog-advertising`)

#### [`cloud_service/drive_client.py`](file:///Users/melbourne/Documents/antigravity/fog-advertising/cloud_service/drive_client.py)
* Wrap chunk upload in a 3-attempt exponential-backoff retry loop for network drops (`SSLEOFError`, timeouts, HTTP 5xx).
* Implement resumable offset recovery: query Google Drive's resumable session header with `PUT bytes */{total_size}` to retrieve the exact byte count received and resume cleanly from that byte.

#### [`cloud_service/main.py`](file:///Users/melbourne/Documents/antigravity/fog-advertising/cloud_service/main.py)
* Add error sanitization to `_process_veo_ingest_job`: map network and API exceptions to clean, user-friendly descriptions.
* Synchronize `job["error"]` and `job["stage_description"]` so the UI tracker accurately displays the failure reason.

---

### Squarespace Frontend (`fog_website`)

#### [`pages/game-day-media-hub.page`](file:///Users/melbourne/Documents/antigravity/fog_website/pages/game-day-media-hub.page)
* Replace the bulky permanent URL input bar with a collapsible drawer triggered by a `+ Import by Veo URL` button.
* Add status filter pills bar (`All`, `✓ Analyzed & Ready`, `In Google Drive`, `Available on Veo`) and a search input.
* Add 3-way view switcher buttons: `Grid`, `List`, `Featured`.
* Add set-piece moment filter pills to the `#moments` section (`All`, `Tries`, `Scrums`, `Lineouts`, `Conversions`, `High Impact`).

#### [`styles/brand-system.less`](file:///Users/melbourne/Documents/antigravity/fog_website/styles/brand-system.less)
* Update `.fog-moment-grid` to `minmax(340px, 1fr)` (3 columns max) so action buttons have full width without vertical word wrap.
* Implement `.fog-media-controls`: filter pills, search input, and view switcher styling using strict Fog brand tokens and 0 radius.
* Implement `.fog-fixture-table`: clean, high-density row layout for the compact List view.
* Implement `.fog-featured-match`: hero presentation card for Featured Match view.
* Implement `.fog-tracker-card--error`: actionable error alert styling with retry and dismiss CTAs.
* Implement `.fog-moment-filters`: set-piece filter pill group on the Match Clips tab.

#### [`scripts/fog-media-hub.js`](file:///Users/melbourne/Documents/antigravity/fog_website/scripts/fog-media-hub.js)
* Implement filter pills filtering, search filtering, and view mode switching (`grid`, `list`, `featured`).
* Add error state rendering: display human-readable error callout, **[Retry Ingest]** button, and **[Dismiss]** button in the tracker card.
* Enhance moment cards: display formatted match clock timestamps (e.g. `06:41 • Minute 7`), excitement rating, and 1-click **Copy Caption** button.
* Implement click-to-seek synchronization with the main HTML5 video player.

---

## Verification Plan

### Automated Checks
* Run LESS compiler check: `node tools/lesscheck.js`
* Run Squarespace template spec check: `node tools/speccheck.js`
* Run class and token checks: `node tools/classcheck.js`

### Backend Unit & Integration Tests
* Test chunk retry logic with a simulated socket disconnect.
* Query `https://video-api.fogrugby.com/jobs/<id>` to verify error payloads.

### Manual Live Verification
* Navigate to `https://fogrugby.com/game-day-media-hub#veo`.
* Test view switcher: verify Grid View (buttons no longer wrap), List View (compact table rows), and Featured View.
* Test filter pills: click `Analyzed & Ready` (shows Sydney Convicts 1), `In Google Drive`, `Available on Veo`.
* Test team search: type `"Sydney"` or `"Spartans"`.
* Switch to `#moments` tab: verify set-piece filter pills, timestamp display, 1-click copy caption toast, and player seek synchronization.
