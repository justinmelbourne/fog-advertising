# engine/models.py
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class VideoSource(BaseModel):
    source_id: str
    filename: str
    duration_seconds: float = 0.0
    resolution: str = "1920x1080"
    fps: float = 30.0
    camera_type: str = Field(default="veo", description="'veo' or 'phone'")
    drive_file_id: Optional[str] = None
    label: Optional[str] = None

class PairingSuggestion(BaseModel):
    paired_event_id: str
    reason: str

class Event(BaseModel):
    event_id: str
    source_id: str
    event_type: str = Field(description="e.g. try, big_tackle, lineout, scrum, celebration")
    start_time: float = Field(description="Start offset in seconds")
    end_time: float = Field(description="End offset in seconds")
    duration: float = Field(description="Duration in seconds")
    excitement_score: float = Field(ge=0.0, le=1.0)
    detection_source: str
    description: str
    suggested_uses: List[str] = Field(default_factory=list)
    suggested_pairings: List[PairingSuggestion] = Field(default_factory=list)
    suggested_caption: str = ""
    suggested_hashtags: List[str] = Field(default_factory=list)
    status: str = "pending_review"
    # Unclassified events are 'neutral' (Needs Review) until Gemini verifies them from footage
    sentiment: Optional[str] = Field(default="neutral", description="'fog_positive', 'fog_negative', or 'neutral'")
    sentiment_confidence: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    sentiment_rationale: Optional[str] = None
    team: Optional[str] = Field(default="unknown", description="'sf_fog', 'opponent', or 'unknown'")
    team_display: Optional[str] = Field(default=None, description="Display name of scoring/winning team")
    classified_by: Optional[str] = Field(default=None, description="e.g. 'gemini:<model>', 'manual', 'unverified'")
    # Gemini's raw call ('fog_positive'/'fog_negative') even when below the filing threshold
    sentiment_lean: Optional[str] = None

class Manifest(BaseModel):
    match_id: str
    match_title: str
    match_date: str
    pitch: str = "Treasure Island Pitch 1, San Francisco"
    sources: List[VideoSource] = Field(default_factory=list)
    events: List[Event] = Field(default_factory=list)
    opponent_name: Optional[str] = None
    # Per-match kit calibration: {fog_kit, opponent_kit, confirmed, image_file_id, ...}
    kit_check: Optional[Dict[str, Any]] = None
