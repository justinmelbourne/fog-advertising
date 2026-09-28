/**
 * SF Fog RFC — Game Day Media Hub
 * Squarespace Developer Mode Portal Component
 * ============================================
 * File: portal/scripts/fog-media-hub.js
 *
 * This script powers the /portal/media page in the Squarespace Developer Mode
 * template. It communicates with the Cloud Run API to:
 *   1. Load the manifest for the selected match
 *   2. Render detected event moment cards
 *   3. Drive the interactive preview player with aspect-ratio switching
 *   4. Trigger on-demand Cloud Run clip extraction via the export buttons
 *
 * CONFIGURATION:
 *   Set FOG_API_BASE_URL to your Cloud Run service URL in Squarespace
 *   Developer Mode > Settings > Developer API / Script injection, or
 *   directly in the Squarespace Code Block that loads this script.
 *
 * CORS:
 *   The Cloud Run service must have the Squarespace origin whitelisted.
 *   Add your site domain to the CORS_ORIGINS list in cloud_service/main.py.
 *
 * AUTHENTICATION:
 *   The Cloud Run service uses --no-allow-unauthenticated.
 *   For the club portal, use a Cloud Run Invoker service account with an
 *   Identity-Aware Proxy (IAP) or generate short-lived OIDC tokens via a
 *   lightweight token-vending Cloud Function. For simplicity, a shared
 *   API key header (X-Fog-Api-Key) is used for initial development.
 *
 *   Production: Replace X-Fog-Api-Key with IAP / OIDC token flow.
 */

/* global Squarespace, Y */

(function () {
  "use strict";

  // -------------------------------------------------------------------------
  // Configuration — override via Squarespace Code Block or window object
  // -------------------------------------------------------------------------

  const CONFIG = Object.assign(
    {
      apiBaseUrl: "https://fog-video-analysis-XXXX-uw.a.run.app", // Replace after deploy
      apiKey: "",       // Injected via Squarespace Settings > Advanced > Code Injection
      defaultMatchId: "", // Pre-populate from URL param or Squarespace Collection data
    },
    window.FOG_MEDIA_HUB_CONFIG || {}
  );

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------

  let currentManifest = null;
  let currentEvent = null;
  let currentRatio = "16x9";

  // -------------------------------------------------------------------------
  // Entry point — called once DOM is ready
  // -------------------------------------------------------------------------

  function init() {
    const matchId = _getMatchIdFromUrl() || CONFIG.defaultMatchId;

    if (!matchId) {
      _showError("No match selected. Append ?match=MATCH_ID to the URL or configure a default.");
      return;
    }

    _showLoadingState();
    fetchManifest(matchId);
    _setupRatioPills();
  }

  // -------------------------------------------------------------------------
  // API: Load manifest
  // -------------------------------------------------------------------------

  function fetchManifest(matchId) {
    _apiFetch(`/manifest/${encodeURIComponent(matchId)}`)
      .then(function (data) {
        currentManifest = data;
        _renderMatchHeader(data);
        _renderMomentGrid(data.events || []);
      })
      .catch(function (err) {
        _showError("Could not load match manifest: " + err.message);
        console.error("[FogMediaHub] manifest fetch failed:", err);
      });
  }

  // -------------------------------------------------------------------------
  // API: Trigger on-demand clip extraction
  // -------------------------------------------------------------------------

  function triggerExtract(eventId, format) {
    if (!currentManifest) return;

    const btn = document.getElementById("export-btn-" + eventId + "-" + format.replace(":", "x"));
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Processing…";
    }

    _apiFetch("/extract", {
      method: "POST",
      body: JSON.stringify({
        match_id: currentManifest.match_id,
        event_id: eventId,
        format: format,
      }),
    })
      .then(function (result) {
        _showToast(
          "✅ " + format + " clip ready! Saved to Drive. File ID: " + result.drive_file_id
        );
        if (btn) {
          btn.disabled = false;
          btn.textContent = format + " ✓";
          btn.classList.add("fog-btn--success");
        }
      })
      .catch(function (err) {
        _showToast("❌ Export failed: " + err.message, true);
        if (btn) {
          btn.disabled = false;
          btn.textContent = format + " Retry";
        }
        console.error("[FogMediaHub] extract failed:", err);
      });
  }

  // -------------------------------------------------------------------------
  // API: Trigger full folder analysis
  // -------------------------------------------------------------------------

  function triggerAnalysis(matchId, matchTitle, folderId) {
    const statusEl = document.getElementById("analysis-status");
    if (statusEl) {
      statusEl.textContent = "⏳ Analysis running… this may take a few minutes.";
      statusEl.style.display = "block";
    }

    _apiFetch("/analyze", {
      method: "POST",
      body: JSON.stringify({
        match_id: matchId,
        match_title: matchTitle,
        folder_id: folderId,
      }),
    })
      .then(function (result) {
        if (statusEl) {
          statusEl.textContent =
            "✅ Analysis complete! " + result.events_found + " moments detected.";
        }
        currentManifest = result.manifest;
        _renderMatchHeader(result.manifest);
        _renderMomentGrid(result.manifest.events || []);
      })
      .catch(function (err) {
        if (statusEl) {
          statusEl.textContent = "❌ Analysis failed: " + err.message;
        }
        console.error("[FogMediaHub] analysis failed:", err);
      });
  }

  // -------------------------------------------------------------------------
  // Rendering: Match header
  // -------------------------------------------------------------------------

  function _renderMatchHeader(manifest) {
    var titleEl = document.getElementById("current-match-title");
    var metaEl = document.getElementById("current-match-meta");

    if (titleEl) titleEl.textContent = manifest.match_title || "SF Fog RFC Match";
    if (metaEl) {
      metaEl.textContent =
        (manifest.pitch || "Treasure Island Pitch 1") + " • " + (manifest.match_date || "");
    }
  }

  // -------------------------------------------------------------------------
  // Rendering: Moment card grid
  // -------------------------------------------------------------------------

  function _renderMomentGrid(events) {
    var container = document.getElementById("moment-grid");
    if (!container) return;

    if (!events || events.length === 0) {
      container.innerHTML =
        '<p style="color:#666; padding: 2rem 0; grid-column: 1/-1;">No moments detected yet. ' +
        "Trigger analysis or check back after the video processing completes.</p>";
      return;
    }

    container.innerHTML = events
      .map(function (ev) {
        return _buildMomentCard(ev);
      })
      .join("");
  }

  function _buildMomentCard(ev) {
    var excitement = Math.round((ev.excitement_score || 0) * 100);
    var scoreColor =
      excitement >= 85 ? "#157A38" : excitement >= 65 ? "#006EB6" : "#666";

    var pairingHtml = "";
    if (ev.suggested_pairings && ev.suggested_pairings.length > 0) {
      pairingHtml =
        '<div class="moment-card__pairings">' +
        "<strong>AI Pairing:</strong> " +
        _escapeHtml(ev.suggested_pairings[0].reason) +
        "</div>";
    }

    var usesHtml = "";
    if (ev.suggested_uses && ev.suggested_uses.length > 0) {
      usesHtml =
        '<div class="moment-card__uses">' +
        ev.suggested_uses
          .map(function (u) {
            return '<span class="use-tag">' + _escapeHtml(u.replace(/_/g, " ")) + "</span>";
          })
          .join("") +
        "</div>";
    }

    var exportBtnIds = {
      "9:16": "export-btn-" + ev.event_id + "-9x16",
      "1:1": "export-btn-" + ev.event_id + "-1x1",
      "4:5": "export-btn-" + ev.event_id + "-4x5",
      "16:9": "export-btn-" + ev.event_id + "-16x9",
    };

    return (
      '<div class="moment-card" id="card-' + _escapeHtml(ev.event_id) + '">' +
      "<div>" +
      '<div class="moment-card__header">' +
      '<span class="moment-card__badge">' + _escapeHtml(ev.event_type).toUpperCase() + "</span>" +
      '<span class="moment-card__score" style="color:' + scoreColor + ';">' +
      excitement + "% EXCITEMENT</span>" +
      "</div>" +
      '<h4 style="margin: 0 0 0.35rem 0; font-size: 1rem;">' +
      _escapeHtml(ev.description) + "</h4>" +
      '<p style="font-size: 0.8rem; color: #666; margin: 0 0 0.5rem 0;">' +
      "Source: " + _escapeHtml(ev.source_id) +
      " • " + _formatDuration(ev.duration) +
      " • " + _formatTimecode(ev.start_time) +
      "</p>" +
      pairingHtml +
      usesHtml +
      "</div>" +
      "<div>" +
      '<button class="fog-btn" style="width: 100%; margin-bottom: 0.75rem;" ' +
      'onclick="FogMediaHub.previewEvent(' + JSON.stringify(ev) + ')">' +
      "▶ Preview Clip</button>" +
      '<div class="moment-card__actions">' +
      '<button class="fog-btn fog-btn--secondary" ' +
      'id="' + exportBtnIds["9:16"] + '" ' +
      'onclick="FogMediaHub.triggerExtract(\'' + _escapeHtml(ev.event_id) + "', '9:16')\">Reel 9:16</button>" +
      '<button class="fog-btn fog-btn--secondary" ' +
      'id="' + exportBtnIds["1:1"] + '" ' +
      'onclick="FogMediaHub.triggerExtract(\'' + _escapeHtml(ev.event_id) + "', '1:1')\">Square 1:1</button>" +
      '<button class="fog-btn fog-btn--secondary" ' +
      'id="' + exportBtnIds["4:5"] + '" ' +
      'onclick="FogMediaHub.triggerExtract(\'' + _escapeHtml(ev.event_id) + "', '4:5')\">Feed 4:5</button>" +
      '<button class="fog-btn fog-btn--secondary" ' +
      'id="' + exportBtnIds["16:9"] + '" ' +
      'onclick="FogMediaHub.triggerExtract(\'' + _escapeHtml(ev.event_id) + "', '16:9')\">Master 16:9</button>" +
      "</div>" +
      "</div>" +
      "</div>"
    );
  }

  // -------------------------------------------------------------------------
  // Preview player
  // -------------------------------------------------------------------------

  function previewEvent(ev) {
    currentEvent = ev;

    var captionBox = document.getElementById("caption-box");
    var captionText = document.getElementById("caption-text");
    var previewLabel = document.getElementById("preview-label");

    if (captionBox) captionBox.style.display = "block";
    if (captionText) {
      captionText.textContent =
        (ev.suggested_caption || "") +
        " " +
        ((ev.suggested_hashtags || []).join(" "));
    }
    if (previewLabel) {
      previewLabel.textContent = ev.description + " (" + _formatTimecode(ev.start_time) + ")";
    }

    // Highlight selected card
    document.querySelectorAll(".moment-card").forEach(function (card) {
      card.classList.remove("moment-card--selected");
    });
    var selectedCard = document.getElementById("card-" + ev.event_id);
    if (selectedCard) selectedCard.classList.add("moment-card--selected");
  }

  // -------------------------------------------------------------------------
  // Aspect ratio pill switching
  // -------------------------------------------------------------------------

  function _setupRatioPills() {
    var pills = document.querySelectorAll("[data-ratio-pill]");
    pills.forEach(function (pill) {
      pill.addEventListener("click", function () {
        var ratio = pill.getAttribute("data-ratio-pill");
        setPreviewRatio(ratio);
        pills.forEach(function (p) { p.classList.remove("active"); });
        pill.classList.add("active");
      });
    });
  }

  function setPreviewRatio(ratio) {
    currentRatio = ratio;
    var viewport = document.getElementById("video-viewport");
    if (!viewport) return;
    viewport.className = "video-viewport ratio-" + ratio;
  }

  // -------------------------------------------------------------------------
  // Copy caption to clipboard
  // -------------------------------------------------------------------------

  function copyCaption() {
    if (!currentEvent) return;
    var text =
      (currentEvent.suggested_caption || "") +
      " " +
      ((currentEvent.suggested_hashtags || []).join(" "));
    navigator.clipboard.writeText(text.trim()).then(function () {
      _showToast("📋 Caption copied to clipboard!");
    });
  }

  // -------------------------------------------------------------------------
  // API fetch helper
  // -------------------------------------------------------------------------

  function _apiFetch(path, options) {
    var url = CONFIG.apiBaseUrl.replace(/\/$/, "") + path;
    var opts = Object.assign(
      {
        headers: {
          "Content-Type": "application/json",
          "X-Fog-Api-Key": CONFIG.apiKey,
        },
      },
      options || {}
    );

    return fetch(url, opts).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (body) {
          throw new Error("HTTP " + resp.status + ": " + body.slice(0, 200));
        });
      }
      return resp.json();
    });
  }

  // -------------------------------------------------------------------------
  // UI utilities
  // -------------------------------------------------------------------------

  function _showLoadingState() {
    var grid = document.getElementById("moment-grid");
    if (grid) {
      grid.innerHTML =
        '<p style="color:#006EB6; padding: 2rem 0; grid-column: 1/-1;">' +
        "⏳ Loading match moments…</p>";
    }
  }

  function _showError(msg) {
    var grid = document.getElementById("moment-grid");
    if (grid) {
      grid.innerHTML =
        '<p style="color:#C4321F; padding: 2rem 0; grid-column: 1/-1;">⚠️ ' +
        _escapeHtml(msg) + "</p>";
    }
  }

  function _showToast(msg, isError) {
    var toast = document.getElementById("fog-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "fog-toast";
      toast.style.cssText =
        "position:fixed; bottom:2rem; right:2rem; background:" +
        (isError ? "#C4321F" : "#006EB6") +
        "; color:#fff; padding:0.75rem 1.25rem; border-radius:2px; " +
        "font-family:'Futura PT',Futura,Arial,sans-serif; font-weight:700; " +
        "font-size:0.875rem; z-index:9999; max-width:320px; box-shadow:0 4px 16px rgba(0,0,0,0.2);";
      document.body.appendChild(toast);
    }
    toast.style.background = isError ? "#C4321F" : "#006EB6";
    toast.textContent = msg;
    toast.style.display = "block";
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function () {
      toast.style.display = "none";
    }, 5000);
  }

  function _getMatchIdFromUrl() {
    var params = new URLSearchParams(window.location.search);
    return params.get("match") || params.get("match_id") || "";
  }

  function _formatDuration(secs) {
    if (!secs) return "0s";
    secs = Math.round(secs);
    if (secs < 60) return secs + "s";
    return Math.floor(secs / 60) + "m " + (secs % 60) + "s";
  }

  function _formatTimecode(secs) {
    if (!secs) return "00:00";
    secs = Math.floor(secs);
    var m = Math.floor(secs / 60);
    var s = secs % 60;
    return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  function _escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // -------------------------------------------------------------------------
  // Public API (called from Squarespace template inline handlers)
  // -------------------------------------------------------------------------

  window.FogMediaHub = {
    init: init,
    fetchManifest: fetchManifest,
    previewEvent: previewEvent,
    triggerExtract: triggerExtract,
    triggerAnalysis: triggerAnalysis,
    setPreviewRatio: setPreviewRatio,
    copyCaption: copyCaption,
  };

  // Auto-init when DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
