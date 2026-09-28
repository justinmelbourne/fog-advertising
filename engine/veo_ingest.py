# engine/veo_ingest.py
import re
from typing import List, Optional, Any
from engine.models import Event

VEO_URL_PATTERN = re.compile(r"app\.veo\.co/matches/([a-zA-Z0-9\-]+)")

def parse_veo_email_body(body_text: str) -> Optional[str]:
    """Extract match UUID from an automated Veo notification email."""
    match = VEO_URL_PATTERN.search(body_text)
    return match.group(1) if match else None

def fetch_veo_match_events(match_id: str, source_id: str, client: Any) -> List[Event]:
    """Ingest AI-tagged events from Veo match data."""
    data = client.get_match_data(match_id)
    highlights = data.get("highlights", [])
    events: List[Event] = []

    for idx, hl in enumerate(highlights):
        hl_type = hl.get("type", "").lower()
        if hl_type in ["half_start", "half_end", "period_start", "period_end"]:
            continue

        event_type = "try" if hl_type in ["goal", "try"] else "highlight"
        start = float(hl.get("start", 0))
        end = float(hl.get("end", start + 20))
        duration = end - start

        events.append(Event(
            event_id=f"veo_evt_{idx+1:03d}",
            source_id=source_id,
            event_type=event_type,
            start_time=start,
            end_time=end,
            duration=duration,
            excitement_score=0.90 if event_type == "try" else 0.75,
            detection_source="veo_ai_tag",
            description=hl.get("label", "Veo AI Match Highlight"),
            suggested_uses=["hype_reel_hook" if event_type == "try" else "general_highlight"]
        ))

    return events
