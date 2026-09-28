// portal/scripts/media-hub.js
let currentEvent = null;

function renderMoments(events) {
  const container = document.getElementById("moment-grid");
  if (!container) return;

  container.innerHTML = events.map(ev => `
    <div class="moment-card" id="card-${ev.event_id}">
      <div>
        <div class="moment-card__header">
          <span class="moment-card__badge">${ev.event_type.replace('_', ' ')}</span>
          <span class="moment-card__score">${Math.round(ev.excitement_score * 100)}% EXCITEMENT</span>
        </div>
        <h4 style="margin: 0 0 0.5rem 0; font-size: 1.05rem;">${ev.description}</h4>
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
          <button class="fog-btn fog-btn--secondary" onclick="exportClip('${ev.event_id}', '4:5')">Feed 4:5</button>
          <button class="fog-btn fog-btn--secondary" onclick="exportClip('${ev.event_id}', '16:9')">Master 16:9</button>
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

  ["16x9", "9x16", "1x1", "4x5"].forEach(r => {
    const btn = document.getElementById(`btn-${r}`);
    if (btn) {
      if (r === ratio) {
        btn.classList.remove("fog-btn--secondary");
      } else {
        btn.classList.add("fog-btn--secondary");
      }
    }
  });
}

function copyCaption() {
  if (!currentEvent) return;
  const fullText = `${currentEvent.suggested_caption} ${(currentEvent.suggested_hashtags || []).join(" ")}`;
  navigator.clipboard.writeText(fullText).then(() => {
    alert("Caption copied to clipboard!");
  }).catch(() => {
    console.log("Clipboard write fallback");
  });
}

function exportClip(eventId, format) {
  alert(`Requested on-demand export for clip ${eventId} in format ${format}. Processing with FFmpeg!`);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { renderMoments, selectClip, setPreviewRatio, copyCaption, exportClip };
}
