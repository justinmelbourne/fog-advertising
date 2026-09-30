# SF Fog RFC Media Hub: Multi-View Interface, Resilient Uploads & Veo AI Moments Design

**Date:** 2026-09-29  
**Status:** Approved  
**Author:** Pair Programming Agent & Club President  

---

## 1. Problem Statement

1. **Upload Reliability Defect:** Large match video streaming uploads (1.8 GB – 2.3 GB) from Veo CDN to Google Drive fail when an SSL or socket drop occurs mid-stream (e.g., `SSLEOFError` at 820 MB), because the chunk uploader lacks an exponential-backoff retry loop and resume-offset recovery.
2. **Opaque Error Reporting:** The backend catch-all preserved the raw exception string in `job["error"]` without updating `job["stage_description"]`. The frontend UI displayed only `stage_description`, resulting in an ambiguous red **ERROR** badge with no explanation or retry mechanism.
3. **Crowded Feed Layout:** A 4–5 column grid (`minmax(260px, 1fr)`) leaves cards only ~212px wide inside, squeezing dual action buttons into ~102px and forcing three-line vertical word wrapping (`VIEW \n MATCH \n CLIPS`). Twenty large thumbnails form an undifferentiated wall with a permanent 120px URL input bar at the top.
4. **Underutilized Veo AI Moments Data:** Veo already provides rich camera AI metadata (tries, scrums, lineouts, conversions, timestamps, and excitement scores) for ingested matches, but this data was hidden inside generic JSON manifests rather than showcased interactively.

---

## 2. Core Architecture & Requirements

### 2.1 Resilient Upload Engine (`drive_client.py`)
* **Resumable Session Invariant:** When uploading 10 MB chunks to Google Drive's resumable session URL, wrap each chunk in a 3-attempt exponential-backoff retry loop (`time.sleep(2 ** attempt)`).
* **Socket & SSL Drop Recovery:** Catch `requests.exceptions.RequestException`, `urllib3.exceptions.SSLError`, `ssl.SSLEOFError`, and HTTP 5xx responses.
* **Offset Re-query:** If a chunk upload fails, query the Google Drive resumable session endpoint with `PUT` and `Content-Range: bytes */{total_size}` to retrieve the current `Range: bytes=0-{uploaded}` header, and resume exactly from Google Drive's recorded byte offset.

### 2.2 Structured Error Reporting (`main.py` & `fog-media-hub.js`)
* **Sanitized Error Descriptions:** Map internal network exceptions to actionable messages:
  * `"Upload connection to Google Drive dropped at {mb} MB. Auto-retried 3 times without response."`
* **Synchronized State:** Set both `job["error"]` and `job["stage_description"]` to the human-readable error description so the UI tracker reliably reflects the problem.
* **Actionable Error Card:** When `stage === "error"`, render an alert banner with:
  * Error description callout.
  * **[Retry Ingest]** button (restarts the background job with the same slug/title without re-entering URLs).
  * **[Dismiss]** button.

### 2.3 Multi-View Media Hub (Uncrowding the Feed)
* **Collapsible URL Drawer:** Replace the fixed dark input block with a toggleable `+ Import by Veo URL` button.
* **Status Filter Pills Bar:** Instant client-side filtering:
  * `All Matches ({count})` • `✓ Analyzed & Ready ({count})` • `In Google Drive ({count})` • `Available on Veo ({count})`
* **Real-time Team Search:** Filter matches by opponent, side (`A-Side`, `B-Side`, `C-Side`), or tournament name.
* **3-Way View Switcher:**
  1. **Spacious Grid (Default):** 3 columns maximum on desktop (`minmax(340px, 1fr)`), ensuring action buttons have at least 150px of width each without vertical text wrap.
  2. **Compact List / Fixture Table View:** A scannable tabular view showing *Date*, *Opponent/Match Title*, *Duration*, *Status Badge*, and inline *Action Button*.
  3. **Featured Match Focus View:** Hero feature card for the most recent match with full statistics and direct clips button, with an archive drawer below.

### 2.4 Cool Presentation of Veo AI Moments (Match Clips Tab)
* **Rugby Set Piece Filters:** Instant pills above the clips:
  * `All Moments ({count})` • `Tries ({count})` • `Scrums ({count})` • `Lineouts ({count})` • `Conversions ({count})` • `High Impact (90%+)`
* **Moment Card Design:**
  * Bold event badge (`TRY`, `SCRUM`, `LINEOUT`, `CONVERSION`).
  * Match clock callout (e.g. `12:45 • Minute 13`).
  * Excitement meter with high-contrast styling.
  * Veo AI description text.
  * Social drawer with pre-generated caption and club hashtags (`#SFFogRFC #BinghamCup`) with a 1-click **Copy Caption** button.
* **Video Player Sync:** Clicking any moment card automatically seeks the video player to that timestamp (`start_time - 5s`) for immediate playback.

---

## 3. Brand & Quality Constraints
* **Brand Canon Adherence:** Strict compliance with `fog-rugby-design` Rev 4. Zero radius (`border-radius: 0`) across all buttons, cards, pills, and inputs.
* **Color System:** Grounded exclusively in `--fog-blue` (`#006EB6`), `--fog-dark-blue` (`#00243C`), `--fog-light-blue` (`#24A0F1`), `--fog-gray` (`#DCDDDE`), `--fog-gray-50` (`#F1F2F3`), and semantic `--fog-green` / `--fog-red`.
* **Squarespace Developer Mode Compatibility:** No inline styles, passes `lesscheck` and `speccheck`.
