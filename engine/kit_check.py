"""
engine/kit_check.py
===================
One-frame, human-confirmed kit calibration per match.

1. Grab a wide 1080p frame where both teams are on screen (scrum/lineout clips work best).
2. Gemini returns a box + team guess for every visible player, plus a plain-English
   description of each team's kit as it actually looks on camera that day.
3. We draw cyan (Fog) / red (opponent) / grey (referee/unknown) boxes on the frame.
4. A human looks once and replies "correct" or "swap". The confirmed kit descriptions
   are stored in the match manifest and drive every clip classification for that match.
"""

import base64
import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from engine.team_analyzer import DEFAULT_FOG_KIT, _gemini_request

logger = logging.getLogger(__name__)

TEAM_COLOURS = {
    "fog": (0, 229, 255),        # cyan: stands out on grass
    "opponent": (255, 65, 54),   # red
    "referee": (170, 170, 170),  # grey
    "unknown": (170, 170, 170),
}
TEAM_LABELS = {"fog": "FOG", "opponent": "OPP", "referee": "REF", "unknown": "?"}


def extract_frame(video_path: str, timestamp: float, out_path: str) -> Optional[str]:
    """Full-resolution JPEG at `timestamp` (no downscale: players are small on Veo)."""
    cmd = [
        "ffmpeg", "-y", "-ss", f"{max(0.0, timestamp):.3f}", "-i", video_path,
        "-frames:v", "1", "-q:v", "2", out_path,
    ]
    res = subprocess.run(cmd, capture_output=True, check=False, timeout=60)
    if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    logger.warning("Kit-check frame extraction failed: %s", res.stderr.decode()[-200:])
    return None


def detect_teams(frame_path: str, fog_kit: str = DEFAULT_FOG_KIT, opponent_name: str = "Opponent") -> Dict[str, Any]:
    """
    Ask Gemini for every player's box and team. Boxes use Gemini's native
    [ymin, xmin, ymax, xmax] format normalised to 0-1000.
    """
    with open(frame_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = f"""This is a frame from a rugby match filmed by a Veo camera.

SF Fog RFC kit: {fog_kit}.
The other team is {opponent_name}.

1. Find every person on the pitch. For each, return a tight box_2d as [ymin, xmin, ymax, xmax] normalised 0-1000,
   and team: "fog", "opponent", "referee" or "unknown".
2. Describe each team's kit exactly as it looks in THIS frame (shirt colour/pattern, shorts, socks).

Return ONLY JSON:
{{
  "fog_kit_observed": "silver shirts with rainbow marking, white shorts",
  "opponent_kit_observed": "...",
  "players": [{{"box_2d": [ymin, xmin, ymax, xmax], "team": "fog"}}]
}}"""

    payload = {
        "contents": [{"role": "user", "parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
        ]}],
        "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
    }
    resp = _gemini_request(payload, api_key=None)
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(text)

    players: List[Dict[str, Any]] = []
    for p in data.get("players", []) or []:
        box = p.get("box_2d")
        team = str(p.get("team", "unknown")).lower()
        if isinstance(box, list) and len(box) == 4:
            players.append({"box_2d": [int(v) for v in box], "team": team if team in TEAM_COLOURS else "unknown"})

    return {
        "fog_kit_observed": data.get("fog_kit_observed", ""),
        "opponent_kit_observed": data.get("opponent_kit_observed", ""),
        "players": players,
    }


def draw_kit_check(frame_path: str, detection: Dict[str, Any], out_path: str) -> str:
    """Draw labelled boxes plus a legend so the frame can be judged at a glance."""
    img = Image.open(frame_path).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=max(18, h // 40))
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()

    counts = {"fog": 0, "opponent": 0}
    for p in detection.get("players", []):
        ymin, xmin, ymax, xmax = p["box_2d"]
        box = (xmin * w / 1000, ymin * h / 1000, xmax * w / 1000, ymax * h / 1000)
        colour = TEAM_COLOURS[p["team"]]
        draw.rectangle(box, outline=colour, width=max(3, w // 480))
        draw.text((box[0], max(0, box[1] - h // 30)), TEAM_LABELS[p["team"]], fill=colour, font=font)
        if p["team"] in counts:
            counts[p["team"]] += 1

    legend = [
        f"CYAN = FOG ({counts['fog']}): {detection.get('fog_kit_observed', '')}",
        f"RED = OPPONENT ({counts['opponent']}): {detection.get('opponent_kit_observed', '')}",
        "Reply 'correct' or 'swap'",
    ]
    # Legend goes in a strip BELOW the frame so it never hides players
    line_h = h // 28
    strip_h = line_h * len(legend) + 10
    canvas = Image.new("RGB", (w, h + strip_h), (0, 0, 0))
    canvas.paste(img, (0, 0))
    legend_draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(legend):
        legend_draw.text((10, h + 5 + i * line_h), line[:140], fill=(255, 255, 255), font=font)

    canvas.save(out_path, "PNG")
    return out_path


def confirmed_kits(manifest_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Return {'fog_kit', 'opponent_kit'} only if a human confirmed the kit check for this match."""
    kc = (manifest_data or {}).get("kit_check") or {}
    if kc.get("confirmed") and kc.get("fog_kit") and kc.get("opponent_kit"):
        return {"fog_kit": kc["fog_kit"], "opponent_kit": kc["opponent_kit"]}
    return None


def apply_confirmation(kit_check: Dict[str, Any], swap: bool = False,
                       fog_kit: Optional[str] = None, opponent_kit: Optional[str] = None) -> Dict[str, Any]:
    """Lock in the human's verdict. 'swap' flips which observed kit is Fog; explicit text overrides both."""
    kc = dict(kit_check)
    if swap:
        kc["fog_kit"], kc["opponent_kit"] = kc.get("opponent_kit", ""), kc.get("fog_kit", "")
    if fog_kit:
        kc["fog_kit"] = fog_kit
    if opponent_kit:
        kc["opponent_kit"] = opponent_kit
    kc["confirmed"] = True
    kc["swapped"] = bool(swap)
    return kc
