"""
veo_api_client.py — Minimal Veo API client for Cloud Run
=========================================================
Wraps the public Veo Clubhouse API (api.veo.co.uk) to fetch match data
and AI tag events. Used by the /veo/webhook endpoint and the polling cron.

The VEO_API_TOKEN is loaded from environment (injected from Secret Manager
in Cloud Run production; .env file for local development).
"""

import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

VEO_API_BASE = "https://api.veo.co.uk/api/v2"
DEFAULT_TIMEOUT = 30


class VeoApiClient:
    """
    Minimal Veo REST API client using bearer token auth.
    """

    def __init__(self, token: str) -> None:
        if not token:
            logger.warning("VEO_API_TOKEN is empty — Veo API calls will fail in production")
        self._token = token
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def get_match_data(self, match_id: str) -> dict[str, Any]:
        """
        Fetch match metadata and AI highlight tags for a given Veo match UUID.
        Returns the raw Veo API response as a dict.
        """
        url = f"{VEO_API_BASE}/recordings/{match_id}"
        resp = self._session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def list_recent_matches(self, team_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Poll for recent matches for a given team ID.
        Used for the fallback cron-based Veo check when webhooks are unavailable.
        """
        url = f"{VEO_API_BASE}/recordings"
        params = {"team_id": team_id, "status": "COMPLETED", "limit": limit}
        resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("data", [])

    def get_download_url(self, match_id: str) -> Optional[str]:
        """
        Get a temporary pre-signed download URL for the match MP4.
        Used when we want to download the Veo recording directly to Drive.
        """
        url = f"{VEO_API_BASE}/recordings/{match_id}/download"
        resp = self._session.get(url, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            return resp.json().get("url")
        logger.warning("Failed to get download URL for match %s: %s", match_id, resp.status_code)
        return None
