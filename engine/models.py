# engine/models.py
from typing import List, Optional
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

class Manifest(BaseModel):
    match_id: str
    match_title: str
    match_date: str
    pitch: str = "Treasure Island Pitch 1, San Francisco"
    sources: List[VideoSource] = Field(default_factory=list)
    events: List[Event] = Field(default_factory=list)
