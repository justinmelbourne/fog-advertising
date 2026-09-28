# engine/ai_suggester.py
from typing import List
from engine.models import Event, PairingSuggestion

FOG_HASHTAGS = ["#SFFogRFC", "#FogRugby", "#InclusiveRugby", "#BinghamCup"]

def assign_editorial_uses(event: Event) -> Event:
    """Categorize event into strategic social media editorial roles and generate ready-to-use copy."""
    ev_type = event.event_type.lower()
    uses: List[str] = []

    if "try" in ev_type:
        uses = ["hype_reel_hook", "player_spotlight", "match_story_recap"]
        caption = "Try time on Treasure Island! 🏉 SF Fog crossing the whitewash!"
    elif "tackle" in ev_type or "hit" in ev_type:
        uses = ["defensive_masterclass", "hard_hits_reel", "shorts_hook"]
        caption = "Defense setting the standard 😤 Dominant hit from the Fog!"
    elif "lineout" in ev_type or "scrum" in ev_type:
        uses = ["forward_pack_pride", "set_piece_clinic"]
        caption = "Forward pack hard at work! Set piece dominance on display 💥"
    elif "celebration" in ev_type:
        uses = ["sideline_culture", "team_spirit_story"]
        caption = "The energy on the sideline is unmatched! 💙🏉 Fog family!"
    else:
        uses = ["general_match_highlight"]
        caption = "Big moment from Saturday's clash! Up the Fog! 🏉"

    event.suggested_uses = uses
    if not event.suggested_caption:
        event.suggested_caption = caption
    if not event.suggested_hashtags:
        event.suggested_hashtags = FOG_HASHTAGS

    return event

def generate_clip_pairings(events: List[Event]) -> List[Event]:
    """Analyze multiple cameras and suggest cross-clip pairings and compilations."""
    enriched = [assign_editorial_uses(e) for e in events]
    tries = [e for e in enriched if "try" in e.event_type.lower()]
    sideline_reactions = [e for e in enriched if e.source_id != "veo" and ("celebration" in e.event_type.lower() or e.excitement_score > 0.85)]

    for t in tries:
        for s in sideline_reactions:
            t.suggested_pairings.append(PairingSuggestion(
                paired_event_id=s.event_id,
                reason="Sideline celebration adds emotional bench reaction to this try"
            ))

    return enriched
