"""
veo_api_client.py — Production Veo API client for SF Fog RFC
==============================================================
Reverse-engineered from live app.veo.co traffic (ProxyPin HAR capture).

Veo's public match APIs provide:
  1. Club recordings list (all Fog matches, Bingham Cup, friendly fixtures)
  2. Match video renders (direct 1080p MP4 download URLs on c.veocdn.com)
  3. Pre-tagged AI rugby events (tries, lineouts, scrums, conversions with exact timestamps)

All endpoints operate without requiring bearer tokens for public club matches.
Bearer token authentication is supported for private/unlisted clubhouse recordings.
"""

import re
import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

VEO_APP_API_BASE = "https://app.veo.co/api/app"
DEFAULT_CLUB_SLUG = "san-francisco-fog-rfc"
DEFAULT_TIMEOUT = 25

# Pattern to extract slug or UUID from any Veo URL or raw input
VEO_URL_PATTERN = re.compile(
    r"(?:app\.veo\.co/matches/)?([a-zA-Z0-9\-]+)/?"
)


class VeoApiClient:
    """
    Client for app.veo.co REST API endpoints.
    """

    def __init__(self, token: Optional[str] = None) -> None:
        self._token = token or ""
        self._session = requests.Session()
        headers = {
            "Accept": "application/json",
            "User-Agent": "SF-Fog-Media-Hub/1.0",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._session.headers.update(headers)

    @staticmethod
    def parse_slug_or_id(input_str: str) -> str:
        """
        Normalizes a match input (full URL, relative path, slug, or UUID)
        into a clean match identifier/slug.
        """
        cleaned = input_str.strip()
        if "?" in cleaned:
            cleaned = cleaned.split("?")[0]
        cleaned = cleaned.rstrip("/")
        if "matches/" in cleaned:
            cleaned = cleaned.split("matches/")[-1]
        cleaned = cleaned.split("/")[-1]
        return cleaned

    def list_club_recordings(
        self, club_slug: str = DEFAULT_CLUB_SLUG, limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Fetch all recent match recordings for the club from app.veo.co.
        Returns parsed list with title, slug, identifier, start date, duration, thumbnail.
        """
        url = f"{VEO_APP_API_BASE}/clubs/{club_slug}/recordings/"
        params = {
            "filter": "own",
            "fields": [
                "identifier",
                "slug",
                "title",
                "created",
                "start",
                "duration",
                "thumbnail",
                "url",
                "processing_status",
            ],
        }
        try:
            resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("results", [])
            logger.info("Retrieved %d recordings from Veo for club %s", len(items), club_slug)
            return items
        except Exception as exc:
            logger.exception("Failed to list Veo club recordings: %s", exc)
            return []

    def get_match_videos(self, match_slug_or_id: str) -> list[dict[str, Any]]:
        """
        Get all rendered video files (including direct 1080p MP4 URLs on c.veocdn.com).
        """
        identifier = self.parse_slug_or_id(match_slug_or_id)
        url = f"{VEO_APP_API_BASE}/matches/{identifier}/videos/"
        params = {"render_type": "standard", "ordering": "-width"}

        try:
            resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            videos = resp.json()
            return videos if isinstance(videos, list) else []
        except Exception as exc:
            logger.exception("Failed to get match videos for %s: %s", identifier, exc)
            return []

    def get_match_highlights(self, match_slug_or_id: str) -> list[dict[str, Any]]:
        """
        Get all AI-tagged and manual rugby match highlights (tries, conversions, scrums, lineouts).
        """
        identifier = self.parse_slug_or_id(match_slug_or_id)
        url = f"{VEO_APP_API_BASE}/matches/{identifier}/highlights/"
        params = {"include_ai": "true"}

        try:
            resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            highlights = resp.json()
            return highlights if isinstance(highlights, list) else []
        except Exception as exc:
            logger.exception("Failed to get match highlights for %s: %s", identifier, exc)
            return []

    def resolve_match_details(self, match_input: str) -> Optional[dict[str, Any]]:
        """
        Resolves a full package for a match:
        - identifier and slug
        - best video MP4 direct CDN download URL
        - width/height/mime_type
        - thumbnail URL
        - AI highlight tags with rugby events and timestamps
        """
        slug_or_id = self.parse_slug_or_id(match_input)
        videos = self.get_match_videos(slug_or_id)
        if not videos:
            logger.warning("No standard videos found for Veo match: %s", slug_or_id)
            return None

        # Pick best video (highest width, available)
        best_video = videos[0]
        video_url = best_video.get("url")
        if not video_url:
            return None

        highlights = self.get_match_highlights(slug_or_id)

        return {
            "match_id": slug_or_id,
            "video_url": video_url,
            "width": best_video.get("width", 1920),
            "height": best_video.get("height", 1080),
            "mime_type": best_video.get("mime_type", "video/mp4"),
            "thumbnail": best_video.get("thumbnail"),
            "highlights_count": len(highlights),
            "highlights": highlights,
        }
