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
        self,
        club_slug: str = DEFAULT_CLUB_SLUG,
        fetch_all: bool = True,
        max_pages: int = 10,
        page: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch match recordings for the club from app.veo.co.
        Supports multi-page pagination (all pages 1..N) and extracts expiration status.
        """
        url = f"{VEO_APP_API_BASE}/clubs/{club_slug}/recordings/"
        fields = [
            "identifier",
            "slug",
            "title",
            "created",
            "start",
            "duration",
            "thumbnail",
            "url",
            "processing_status",
            "expires_at",
            "expiration_status",
            "time_to_expiry",
        ]

        def _fetch_single_page(p: int) -> list[dict[str, Any]]:
            params = {
                "filter": "own",
                "fields": fields,
                "page": p,
            }
            try:
                resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                data = resp.json()
                items = data if isinstance(data, list) else data.get("results", [])
                return items if isinstance(items, list) else []
            except Exception as exc:
                logger.warning("Error fetching Veo recordings page %d for %s: %s", p, club_slug, exc)
                return []

        all_raw: list[dict[str, Any]] = []

        if page is not None or not fetch_all:
            target_page = page if page is not None else 1
            all_raw = _fetch_single_page(target_page)
        else:
            for p in range(1, max_pages + 1):
                page_items = _fetch_single_page(p)
                if not page_items:
                    break
                all_raw.extend(page_items)
                if len(page_items) < 20:
                    break

        seen_ids = set()
        parsed: list[dict[str, Any]] = []

        for it in all_raw:
            ident = it.get("identifier") or it.get("slug")
            if not ident or ident in seen_ids:
                continue
            seen_ids.add(ident)

            # Analyze expiration fields
            exp_status = it.get("expiration_status") or ""
            time_to = it.get("time_to_expiry") or {}
            time_val = time_to.get("value") if isinstance(time_to, dict) else None
            time_unit = time_to.get("unit") if isinstance(time_to, dict) else ""

            is_expired = (exp_status == "expired") or (time_unit == "days" and time_val is not None and time_val <= 0)
            is_expiring_soon = (
                not is_expired
                and (
                    exp_status == "expires-soon"
                    or (time_unit == "days" and time_val is not None and 0 < time_val <= 60)
                )
            )

            it["is_expired"] = is_expired
            it["is_expiring_soon"] = is_expiring_soon
            it["days_until_expiry"] = time_val if time_unit == "days" else None
            parsed.append(it)

        logger.info("Retrieved %d unique recordings from Veo for club %s (expiring_soon=%d, expired=%d)",
                    len(parsed), club_slug,
                    sum(1 for x in parsed if x.get("is_expiring_soon")),
                    sum(1 for x in parsed if x.get("is_expired")))
        return parsed

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

    def restore_match(self, match_id_or_slug: str) -> dict[str, Any]:
        """
        Request AWS Glacier cold-storage unarchiving for an expired match.
        Requires Club Administrator token.
        Returns:
            {"match_id": ident, "status": "restoring", "status_code": 202, ...}
        """
        ident = self.parse_slug_or_id(match_id_or_slug)
        url = f"{VEO_APP_API_BASE}/matches/{ident}/videos/restore/"
        try:
            resp = self._session.post(url, json={}, timeout=DEFAULT_TIMEOUT)
            if resp.status_code in (200, 202):
                return {
                    "match_id": ident,
                    "status": "restoring",
                    "status_code": resp.status_code,
                    "message": "Glacier archive restoration requested (typically takes 3–12 hours).",
                }
            resp.raise_for_status()
            return {"match_id": ident, "status": "unknown", "status_code": resp.status_code}
        except requests.HTTPError as http_err:
            status_code = resp.status_code if "resp" in locals() and resp is not None else 500
            logger.warning("Failed to restore match %s: %s (HTTP %s)", ident, http_err, status_code)
            return {
                "match_id": ident,
                "status": "error",
                "status_code": status_code,
                "error": str(http_err),
            }
        except Exception as exc:
            logger.exception("Unexpected error restoring match %s: %s", ident, exc)
            return {
                "match_id": ident,
                "status": "error",
                "status_code": 500,
                "error": str(exc),
            }

    def check_glacier_status(self, match_id_or_slug: str) -> dict[str, Any]:
        """
        Checks if a Glacier-restoring match has completed unarchiving and is ready to download.
        Calls Veo's POST /matches/{id}/download-video/ endpoint.
        Returns:
            {"status": "ready", "download_url": "...", "status_code": 200} when ready
            {"status": "restoring", "status_code": 403, "message": "..."} when pending
        """
        ident = self.parse_slug_or_id(match_id_or_slug)
        url = f"{VEO_APP_API_BASE}/matches/{ident}/download-video/"
        try:
            resp = self._session.post(url, json={}, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200:
                raw_text = resp.text.strip()
                download_url = ""
                if raw_text.startswith("{") or raw_text.startswith("["):
                    data = resp.json()
                    download_url = data.get("url") if isinstance(data, dict) else str(data)
                else:
                    download_url = raw_text.strip('"')
                return {
                    "match_id": ident,
                    "status": "ready",
                    "status_code": 200,
                    "download_url": download_url,
                    "message": "Video has been restored from AWS Glacier and is ready for download.",
                }
            elif resp.status_code == 403:
                return {
                    "match_id": ident,
                    "status": "restoring",
                    "status_code": 403,
                    "message": "Footage is currently unarchiving in AWS Glacier (typically takes 3–12 hours).",
                }
            else:
                return {
                    "match_id": ident,
                    "status": "pending",
                    "status_code": resp.status_code,
                    "message": f"Veo returned status {resp.status_code}",
                }
        except Exception as exc:
            logger.warning("Error checking Glacier status for %s: %s", ident, exc)
            return {
                "match_id": ident,
                "status": "error",
                "error": str(exc),
            }

