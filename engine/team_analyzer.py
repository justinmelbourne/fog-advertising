"""
engine/team_analyzer.py
=======================
Dynamic Multimodal Rugby Match Kit & Action Analysis for Fog Positive vs. Fog Negative (Opponent) Classification.

Sends keyframes to Gemini Vision (pattern from sport-video-AI-analysis) to classify
events from the actual footage. Anything Gemini can't confirm routes to Needs Review;
nothing is ever filed as Fog positive by default.

Official Kit Ground Truth:
--------------------------
1. SF Fog RFC A-Side:
   - Shirt: Deep Pitch Navy (#00243C) or Fog Blue (#006EB6) with vivid Rainbow Band across chest
   - Shorts: White
2. SF Fog RFC B-Side & C-Side:
   - Shirt: Fog Blue (#006EB6) / Deep Pitch Navy (#00243C)
   - Shorts: White or Black
3. Opponents:
   - Whatever kit is passed in per match; otherwise "the team not wearing Fog kit"

Classification Hierarchy:
-------------------------
- Fog Positive (🟢):
    * SF Fog scores a try or conversion
    * SF Fog wins a lineout or dominant scrum
    * SF Fog breakaway, turnover won, or big tackle
    -> Saved into primary moment folders (Tries/, Scrums/, Lineouts/, etc.)
- Fog Negative / Opposing Team (🔴):
    * Opponent scores a try or conversion
    * Opponent wins a lineout or scrum
    * Opponent breakaway
    -> Saved into Opposing Team Videos/{MomentType}/
- Neutral / Needs Review (🟡):
    * Confidence < 0.75 or ambiguous play
    -> Saved into Needs Review/ (never pollutes Fog reels)
"""

import os
import json
import base64
import logging
import subprocess
import tempfile
import requests
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# Model is configurable so a Google model retirement never silently breaks sorting.
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
CONFIDENCE_THRESHOLD = 0.75
VALID_SENTIMENTS = ("fog_positive", "fog_negative", "neutral")


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

DEFAULT_FOG_KIT = "SF Fog RFC: Deep navy or fog-blue jersey with prominent horizontal rainbow band across chest and white shorts (A-side), or solid blue/navy tops with white/black shorts (B/C side)"
DEFAULT_OPPONENT_KIT = "Opposing Team: any kit that does NOT match the SF Fog kit described above"


def extract_moment_keyframes(
    video_path: str,
    start_time: float,
    duration: float,
    num_frames: int = 3,
    output_dir: Optional[str] = None,
) -> List[str]:
    """
    Extract keyframes at distributed percentage intervals across the moment duration
    using FFmpeg.
    """
    if not os.path.exists(video_path):
        logger.warning("Video file not found for keyframe extraction: %s", video_path)
        return []

    target_dir = output_dir or tempfile.mkdtemp(prefix="fog_frames_")
    os.makedirs(target_dir, exist_ok=True)
    frame_paths = []

    # Pick timestamps: e.g. 20%, 50%, 80% through the event
    fractions = [0.2, 0.5, 0.8] if num_frames == 3 else [i / (num_frames + 1) for i in range(1, num_frames + 1)]

    for idx, frac in enumerate(fractions):
        timestamp = max(0.0, start_time + (duration * frac))
        out_frame = os.path.join(target_dir, f"frame_{idx:02d}.jpg")
        cmd = [
            "ffmpeg",
            "-ss", f"{timestamp:.3f}",
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease",
            "-y",
            out_frame,
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if res.returncode == 0 and os.path.exists(out_frame) and os.path.getsize(out_frame) > 0:
                frame_paths.append(out_frame)
            else:
                logger.warning("FFmpeg frame extraction failed at %ss: %s", timestamp, res.stderr.decode()[:120])
        except Exception as e:
            logger.warning("Error running ffmpeg keyframe extraction: %s", e)

    return frame_paths


def encode_image_base64(image_path: str) -> str:
    """Encode an image file to a base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def classify_moment_with_gemini(
    keyframe_paths: List[str],
    event_type: str,
    event_description: str = "",
    opponent_name: str = "Opponent",
    fog_kit: str = DEFAULT_FOG_KIT,
    opponent_kit: str = DEFAULT_OPPONENT_KIT,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send extracted keyframes to Gemini 2.0 Flash Vision to determine if the rugby play
    is a Fog Positive moment, an Opposing Team moment, or neutral.
    """
    gemini_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        logger.warning("GEMINI_API_KEY not set. Falling back to heuristic tag evaluation.")
        return fallback_heuristic_classification(event_type, event_description, opponent_name)

    if not keyframe_paths:
        return fallback_heuristic_classification(event_type, event_description, opponent_name)

    # Build multimodal contents parts
    parts: List[Dict[str, Any]] = []

    prompt = f"""You are a professional rugby video analyst reviewing frames of a detected rugby moment: '{event_type}' ({event_description}).

TEAMS & UNIFORMS:
1. SF Fog RFC: {fog_kit}.
2. {opponent_name}: {opponent_kit}.

YOUR TASK:
Inspect the players in the active play area (the ball carrier, try scorer, kicker, or scrum/lineout pack).
1. Identify which team scores, kicks, or wins the contest.
   - If a player in a rainbow-banded or blue jersey grounds the ball or carries forward, it is SF Fog RFC.
   - If a player in the opponent kit grounds the ball or kicks, it is {opponent_name}.
2. Assign 'sentiment':
   - "fog_positive": SF Fog scores a try/conversion, wins a turnover/scrum/lineout, or makes a big play.
   - "fog_negative": {opponent_name} scores, kicks, or wins the contest.
   - "neutral": Inconclusive, whistle blown with no score, or contest contested evenly.
3. Assign 'confidence' between 0.0 and 1.0.
4. Provide a concise 'rationale' describing the jersey colors and play outcome.

Return ONLY a JSON object in this format:
{{
  "sentiment": "fog_positive" | "fog_negative" | "neutral",
  "team": "sf_fog" | "opponent" | "unknown",
  "team_display": "SF Fog RFC" | "{opponent_name}" | "Contested",
  "confidence": 0.95,
  "rationale": "Player in rainbow-banded navy jersey grounds ball over try line."
}}
"""
    parts.append({"text": prompt})

    for frame_path in keyframe_paths:
        if os.path.exists(frame_path):
            try:
                b64_data = encode_image_base64(frame_path)
                parts.append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64_data
                    }
                })
            except Exception as e:
                logger.warning("Could not encode frame %s: %s", frame_path, e)

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    try:
        # Key goes in a header, never the URL, so it can't leak into exception text or logs.
        url = f"{GEMINI_API_BASE}/{gemini_model()}:generateContent"
        resp = requests.post(url, json=payload, headers={"x-goog-api-key": gemini_key}, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if candidates and "content" in candidates[0]:
            content_parts = candidates[0]["content"].get("parts", [])
            if content_parts:
                raw_text = content_parts[0].get("text", "").strip()
                parsed = json.loads(raw_text)
                sentiment = parsed.get("sentiment")
                conf = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))

                # Unknown label or low confidence -> Needs Review, never a Fog folder
                if sentiment not in VALID_SENTIMENTS or conf < CONFIDENCE_THRESHOLD:
                    sentiment = "neutral"

                default_team = {"fog_positive": "sf_fog", "fog_negative": "opponent"}.get(sentiment, "unknown")
                default_display = {"fog_positive": "SF Fog RFC", "fog_negative": opponent_name}.get(sentiment, "Contested")
                return {
                    "sentiment": sentiment,
                    "sentiment_confidence": conf,
                    "sentiment_rationale": parsed.get("rationale", ""),
                    "team": parsed.get("team", default_team) if sentiment != "neutral" else "unknown",
                    "team_display": parsed.get("team_display", default_display) if sentiment != "neutral" else "Contested",
                    "classified_by": f"gemini:{gemini_model()}",
                }

    except requests.HTTPError as exc:
        # Status + Google's error status only; never the request/URL (could carry secrets)
        status_code = exc.response.status_code if exc.response is not None else "?"
        google_status = ""
        try:
            google_status = (exc.response.json().get("error") or {}).get("status", "")
        except Exception:
            pass
        logger.warning(
            "Gemini classification failed: HTTP %s %s (model=%s). Routing to Needs Review.",
            status_code, google_status, gemini_model(),
        )
    except Exception as exc:
        logger.warning("Gemini classification request failed (%s). Routing to Needs Review.", type(exc).__name__)

    return fallback_heuristic_classification(event_type, event_description, opponent_name)


def fallback_heuristic_classification(
    event_type: str,
    description: str,
    opponent_name: str = "Opponent",
) -> Dict[str, Any]:
    """
    Fallback when keyframes or Gemini are unavailable.
    Only an explicit opponent mention in the text is trusted; everything else is
    'neutral' (Needs Review). Never defaults to Fog positive.
    """
    desc_lower = (description or "").lower()
    opp_lower = opponent_name.lower().strip()
    named_opponent = bool(opp_lower) and opp_lower != "opponent" and opp_lower in desc_lower

    # Explicit opponent keywords only
    if named_opponent or "opponent" in desc_lower or "conceded" in desc_lower:
        return {
            "sentiment": "fog_negative",
            "sentiment_confidence": 0.80,
            "sentiment_rationale": f"Description explicitly tags {opponent_name} as action beneficiary",
            "team": "opponent",
            "team_display": opponent_name,
            "classified_by": "text_heuristic",
        }

    return {
        "sentiment": "neutral",
        "sentiment_confidence": 0.0,
        "sentiment_rationale": "Not verified from footage (no video or Gemini unavailable)",
        "team": "unknown",
        "team_display": "Contested",
        "classified_by": "unverified",
    }


def classify_event(
    event_dict: Dict[str, Any],
    video_path: Optional[str] = None,
    opponent_name: str = "Opponent",
    fog_kit: str = DEFAULT_FOG_KIT,
    opponent_kit: str = DEFAULT_OPPONENT_KIT,
) -> Dict[str, Any]:
    """
    Main entry point for classifying any Event.
    Extracts keyframes if video is present and runs Gemini Vision inference.
    """
    ev_type = str(event_dict.get("event_type", "try")).lower()
    ev_desc = str(event_dict.get("description", ""))
    start_t = float(event_dict.get("start_time", 0.0))
    dur = float(event_dict.get("duration", 20.0))

    if video_path and os.path.exists(video_path):
        with tempfile.TemporaryDirectory(prefix="fog_frames_") as tmpdir:
            frames = extract_moment_keyframes(video_path, start_t, dur, num_frames=3, output_dir=tmpdir)
            if frames:
                res = classify_moment_with_gemini(
                    keyframe_paths=frames,
                    event_type=ev_type,
                    event_description=ev_desc,
                    opponent_name=opponent_name,
                    fog_kit=fog_kit,
                    opponent_kit=opponent_kit,
                )
                return res

    return fallback_heuristic_classification(ev_type, ev_desc, opponent_name)


def classify_event_sentiment(
    event_id: str,
    event_type: str,
    description: str = "",
    start_time: float = 0.0,
    end_time: float = 0.0,
    video_path: Optional[str] = None,
    opponent_name: str = "Opponent",
    opponent_kit: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience wrapper used by Cloud Run endpoints and job runners.
    """
    dur = max(1.0, end_time - start_time) if end_time > start_time else 20.0
    event_dict = {
        "event_id": event_id,
        "event_type": event_type,
        "description": description,
        "start_time": start_time,
        "duration": dur,
    }
    res = classify_event(
        event_dict,
        video_path=video_path,
        opponent_name=opponent_name,
        opponent_kit=opponent_kit or DEFAULT_OPPONENT_KIT,
    )
    return {
        "sentiment": res.get("sentiment", "neutral"),
        "team": res.get("team", "unknown"),
        "team_display": res.get("team_display", "Contested"),
        "confidence": res.get("sentiment_confidence", 0.0),
        "rationale": res.get("sentiment_rationale", ""),
        "classified_by": res.get("classified_by", "unverified"),
    }
