# engine/veo_ingest.py
import re
from typing import List, Optional, Any
from engine.models import Event

VEO_URL_PATTERN = re.compile(r"(?:app\.veo\.co/matches/)?([a-zA-Z0-9\-]+)")

def parse_veo_email_body(body_text: str) -> Optional[str]:
    """Extract match slug or UUID from an automated Veo notification email or string."""
    match = VEO_URL_PATTERN.search(body_text)
    return match.group(1) if match else None

def parse_veo_highlights(highlights: List[dict], source_id: str = "veo_main") -> List[Event]:
    """
    Convert raw Veo highlights list into standard Event models.
    Supports rugby-specific types: try, conversion, scrum, lineout, tackle, penalty.
    """
    events: List[Event] = []
    
    for idx, hl in enumerate(highlights):
        raw_type = str(hl.get("type", "")).lower().rstrip("_")
        if raw_type in ["half_start", "half_end", "period_start", "period_end"]:
            continue

        tags = hl.get("tags", [])
        tag_names = [t.get("name") for t in tags if isinstance(t, dict) and t.get("name")]
        
        # Determine rugby event type
        if raw_type in ["try", "goal"]:
            event_type = "try"
            score = 0.95
            suggested = ["hype_reel_hook", "story_poll", "feed_vertical"]
        elif raw_type in ["big_hit", "tackle"]:
            event_type = "big_tackle"
            score = 0.88
            suggested = ["hype_reel_hook", "story_poll"]
        elif raw_type in ["lineout", "scrum", "conversion", "penalty"]:
            event_type = raw_type
            score = 0.75
            suggested = ["feed_vertical", "general_highlight"]
        else:
            event_type = "highlight"
            score = 0.70
            suggested = ["general_highlight"]

        start = float(hl.get("start", 0))
        duration = float(hl.get("duration", 20))
        end = start + duration

        label = hl.get("comment") or (", ".join(tag_names) if tag_names else f"Veo AI {event_type.title()}")

        events.append(Event(
            event_id=f"veo_evt_{idx+1:03d}",
            source_id=source_id,
            event_type=event_type,
            start_time=start,
            end_time=end,
            duration=duration,
            excitement_score=score,
            detection_source="veo_ai_tag",
            description=label,
            suggested_uses=suggested
        ))

    return events

def fetch_veo_match_events(match_id: str, source_id: str, client: Any) -> List[Event]:
    """Ingest AI-tagged events from Veo match data."""
    if hasattr(client, "get_match_highlights"):
        highlights = client.get_match_highlights(match_id)
    elif hasattr(client, "get_match_data"):
        data = client.get_match_data(match_id)
        highlights = data.get("highlights", [])
    else:
        highlights = []

    return parse_veo_highlights(highlights, source_id=source_id)
