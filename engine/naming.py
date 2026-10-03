"""
engine/naming.py
================
Standardized, scalable file and folder naming conventions for SF Fog RFC Video Analysis.

Format:
  YYYYMMDD_UNIQUEID_file-name.ext

- YYYYMMDD: Match date (8 digits)
- UNIQUEID: Camera unique ID (e.g. v4fb17b0, v38bc810) or cloud generated ID (FOGVEO001)
- Master video: sf-fog-rugby_vs_{opponent}_{quality}.{ext}
- Social ready cuts: fog-rugby_{dimensions}_{moment_type}.{ext}
- Match highlights: fog-rugby_{dimensions}_{reel_type}.{ext}
- Manifests: {match_date}_{unique_id}_manifest.json
"""

import re
import hashlib
from typing import Tuple, Optional, Any


def parse_match_identifiers(match_id: str) -> Tuple[str, str, str]:
    """
    Parses a match identifier or Veo slug into (date, unique_id, opponent).
    Example: '20260822-san-francisco-fog-rfc-a-side-vs-sydney-convicts-1-v4fb17b0'
      -> ('20260822', 'v4fb17b0', 'sydney-convicts-1')
    """
    clean_id = match_id.strip()
    
    # 1. Extract 8-digit date
    date_match = re.match(r'^(\d{8})', clean_id)
    if date_match:
        m_date = date_match.group(1)
        rest = clean_id[8:].lstrip('-_')
    else:
        # Check for YYYY-MM-DD
        dash_date = re.match(r'^(\d{4})-(\d{2})-(\d{2})', clean_id)
        if dash_date:
            m_date = f"{dash_date.group(1)}{dash_date.group(2)}{dash_date.group(3)}"
            rest = clean_id[10:].lstrip('-_')
        else:
            m_date = "20260822"
            rest = clean_id

    # 2. Extract unique ID (e.g. trailing -v4fb17b0 or _v4fb17b0 or FOGVEO001)
    uid_match = re.search(r'[-_](v[0-9a-fA-F]{6,}|[A-Za-z0-9]{7,})$', rest)
    if uid_match:
        unique_id = uid_match.group(1).lstrip('-_')
        rest = rest[:uid_match.start()]
    elif rest.startswith("v") and len(rest) <= 12 and re.match(r'^v[0-9a-fA-F]+$', rest):
        unique_id = rest
        rest = "match"
    else:
        # Generate stable short hash if no Veo ID present
        hash_id = hashlib.sha256(match_id.encode('utf-8')).hexdigest()[:8]
        unique_id = f"FOG{hash_id[:5].upper()}"

    # 3. Clean opponent / team name
    tokens = [
        t.lower() for t in re.split(r'[-_]+', rest)
        if t and t.lower() not in (
            'san', 'francisco', 'fog', 'rfc', 'side', 'a', 'b', 'c',
            'match', 'vs', 'x', 'the', 'rugby'
        )
    ]
    opponent = '-'.join(tokens) or 'opponent'
    
    return m_date, unique_id, opponent


def slugify_moment(event_type: str, description: str = "", event_idx: Optional[Any] = None) -> str:
    """
    Converts event type, description, and event ID/idx into a clean, collision-free moment slug.
    Examples:
      - 'try', 'Try 1 • The Breakaway', 'veo_evt_028' -> 'try-1-breakaway'
      - 'scrum', 'Scrum', 'veo_evt_004' -> 'scrum-004'
      - 'conversion', 'Conversion', 'veo_evt_001' -> 'conversion-001'
    """
    text = (description or event_type or "moment").replace("•", " ").replace("-", " ")
    cleaned_tokens = []
    for word in re.split(r'[^a-zA-Z0-9]+', text):
        w = word.strip().lower()
        if w and w not in ('san', 'francisco', 'fog', 'rfc', 'the', 'a', 'side'):
            cleaned_tokens.append(w)
            
    moment = '-'.join(cleaned_tokens)
    
    num_suffix = ""
    if event_idx is not None:
        idx_str = str(event_idx)
        m = re.search(r'(\d+)$', idx_str)
        if m:
            num_suffix = m.group(1)
        else:
            num_suffix = idx_str
            
    if not moment or moment == (event_type or "").lower():
        if num_suffix:
            moment = f"{event_type.lower()}-{num_suffix}" if event_type else f"moment-{num_suffix}"
    elif num_suffix and not any(char.isdigit() for char in moment):
        moment = f"{moment}-{num_suffix}"
        
    return moment[:40].rstrip('-')


def get_master_video_filename(
    match_id: str,
    quality: str = "1080p",
    ext: str = "mp4"
) -> str:
    """
    Format: YYYYMMDD_UNIQUEID_sf-fog-rugby_vs_{opponent}_{quality}.{ext}
    Example: 20260822_v4fb17b0_sf-fog-rugby_vs_sydney-convicts-1_1080p.mp4
    """
    m_date, unique_id, opponent = parse_match_identifiers(match_id)
    return f"{m_date}_{unique_id}_sf-fog-rugby_vs_{opponent}_{quality}.{ext}"


def get_social_clip_filename(
    match_id: str,
    dimensions: str,
    moment_type: str,
    ext: str = "mp4"
) -> str:
    """
    Format: YYYYMMDD_UNIQUEID_fog-rugby_{dimensions}_{moment_type}.{ext}
    Example: 20260822_v4fb17b0_fog-rugby_16x9_try-1-breakaway.mp4
    """
    m_date, unique_id, _ = parse_match_identifiers(match_id)
    dim = dimensions.replace(":", "x")
    return f"{m_date}_{unique_id}_fog-rugby_{dim}_{moment_type}.{ext}"


def get_highlight_reel_filename(
    match_id: str,
    dimensions: str,
    reel_type: str = "match-highlights",
    ext: str = "mp4"
) -> str:
    """
    Format: YYYYMMDD_UNIQUEID_fog-rugby_{dimensions}_{reel_type}.{ext}
    Example: 20260822_v4fb17b0_fog-rugby_16x9_match-highlights.mp4
             20260822_v4fb17b0_fog-rugby_9x16_match-highlights.mp4
    """
    m_date, unique_id, _ = parse_match_identifiers(match_id)
    dim = dimensions.replace(":", "x")
    return f"{m_date}_{unique_id}_fog-rugby_{dim}_{reel_type}.{ext}"


def get_match_folder_name(match_id: str) -> str:
    """
    Format: YYYYMMDD_UNIQUEID_sf-fog-vs-{opponent}
    Example: 20260822_v4fb17b0_sf-fog-vs-sydney-convicts-1
    """
    m_date, unique_id, opponent = parse_match_identifiers(match_id)
    return f"{m_date}_{unique_id}_sf-fog-vs-{opponent}"


def get_manifest_filename(match_id: str, ext: str = "json") -> str:
    """
    Format: YYYYMMDD_UNIQUEID_manifest.json
    Example: 20260822_v4fb17b0_manifest.json
    """
    m_date, unique_id, _ = parse_match_identifiers(match_id)
    return f"{m_date}_{unique_id}_manifest.{ext}"


FOLDER_HIGHLIGHTS = "Highlights"
FOLDER_TRIES = "Tries"
FOLDER_SCRUMS = "Scrums"
FOLDER_LINEOUTS = "Lineouts"
FOLDER_KICKS = "Conversions & Kicks"
FOLDER_GENERAL = "General Play"
FOLDER_OPPOSING_TEAM = "Opposing Team Videos"
FOLDER_NEEDS_REVIEW = "Needs Review"


def get_moment_folder_name(event_type: str, filename: str = "") -> str:
    """
    Returns the clean category subfolder for a given event type or filename.
    Categories:
      - Highlights
      - Tries
      - Scrums
      - Lineouts
      - Conversions & Kicks
      - General Play
    """
    fn = (filename or "").lower()
    et = (event_type or "").lower().strip()

    if "highlights" in fn or et in ("highlights", "highlight_reel"):
        return FOLDER_HIGHLIGHTS
    if et == "try" or "try" in fn:
        return FOLDER_TRIES
    if et == "scrum" or "scrum" in fn:
        return FOLDER_SCRUMS
    if et == "lineout" or "lineout" in fn:
        return FOLDER_LINEOUTS
    if et in ("conversion", "penalty_kick", "kick_for_goal", "kick") or "conversion" in fn or "kick" in fn:
        return FOLDER_KICKS
    return FOLDER_GENERAL


def get_target_subfolder_path(
    event_type: str,
    sentiment: str = "fog_positive",
    filename: str = "",
) -> Tuple[str, Optional[str]]:
    """
    Returns (primary_folder, nested_subfolder).
    For Fog positive clips & highlight reels:
      - ("Tries", None)
      - ("Scrums", None)
      - ("Lineouts", None)
      - ("Conversions & Kicks", None)
      - ("General Play", None)
      - ("Highlights", None)
    For Opposing team (Fog negative) clips:
      - ("Opposing Team Videos", "Tries")
      - ("Opposing Team Videos", "Scrums")
      - ("Opposing Team Videos", "Lineouts")
      - ("Opposing Team Videos", "Conversions & Kicks")
      - ("Opposing Team Videos", "General Play")
    For Neutral / Ambiguous clips:
      - ("Needs Review", "Tries")
    """
    moment_folder = get_moment_folder_name(event_type, filename=filename)
    if sentiment == "fog_negative":
        return FOLDER_OPPOSING_TEAM, moment_folder
    if sentiment == "neutral":
        return FOLDER_NEEDS_REVIEW, moment_folder
    return moment_folder, None

