#!/usr/bin/env python3
"""
track_glacier_restore.py — Background Tracking & Cron Monitor for AWS Glacier Restores
====================================================================================
Monitors Veo matches unarchiving from AWS Glacier cold storage.
Once Veo restages the video file (HTTP 200 on /download-video/), it can
optionally notify macOS desktop and dispatch an automated Cloud Run ingest job.

Usage:
  # Check once:
  python3 -m cloud_service.track_glacier_restore --once

  # Run background polling loop (every 15 min):
  python3 -m cloud_service.track_glacier_restore --interval 15 --auto-ingest

  # Custom match:
  python3 -m cloud_service.track_glacier_restore --match-id 22278277-604e-4d7b-a18b-d0973656425b
"""

import os
import sys
import time
import json
import logging
import argparse
import subprocess
from datetime import datetime
from typing import Optional

from cloud_service.veo_api_client import VeoApiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("glacier_tracker")

DEFAULT_MATCH_ID = "22278277-604e-4d7b-a18b-d0973656425b"
DEFAULT_TITLE = "Match 7 Dec 2024 A vs Rebellion"
DEFAULT_API_URL = "https://fog-video-analysis-546438448149.us-west1.run.app"
STATE_FILE = os.path.expanduser("~/.fog_glacier_tracking.json")


def notify_macos(title: str, message: str) -> None:
    """Displays a native macOS banner notification if running on macOS."""
    if sys.platform == "darwin":
        try:
            safe_title = title.replace('"', '\\"')
            safe_msg = message.replace('"', '\\"')
            cmd = f'display notification "{safe_msg}" with title "{safe_title}"'
            subprocess.run(["osascript", "-e", cmd], check=False, capture_output=True)
        except Exception:
            pass


def save_state(match_id: str, data: dict) -> None:
    try:
        current = {}
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                current = json.load(f)
        current[match_id] = data
        with open(STATE_FILE, "w") as f:
            json.dump(current, f, indent=2)
    except Exception as exc:
        logger.debug("Could not save state file: %s", exc)


def check_and_report(
    client: VeoApiClient,
    match_id: str,
    title: str,
    api_url: str,
    auto_ingest: bool = False,
    start_time: Optional[float] = None,
) -> bool:
    """
    Checks the status of the match in AWS Glacier.
    Returns True if the video is ready (restored), False if still unarchiving.
    """
    res = client.check_glacier_status(match_id)
    status = res.get("status")
    status_code = res.get("status_code")
    elapsed_str = ""
    if start_time:
        elapsed_sec = int(time.time() - start_time)
        hours, remainder = divmod(elapsed_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed_str = f" [Elapsed: {hours}h {minutes}m {seconds}s]"

    if status == "ready":
        download_url = res.get("download_url", "")
        logger.info("🎉 MATCH RESTORE COMPLETE! %s", elapsed_str)
        logger.info("Match: %s (%s)", title, match_id)
        logger.info("Download URL: %s", download_url)

        save_state(match_id, {
            "status": "ready",
            "match_id": match_id,
            "title": title,
            "download_url": download_url,
            "completed_at": datetime.now().isoformat(),
        })

        notify_macos(
            "Veo Match Restored! 🏉",
            f"{title} is restored and ready for ingestion."
        )

        if auto_ingest and download_url:
            logger.info("Auto-ingest enabled. Dispatching ingest to %s/ingest ...", api_url)
            import requests
            try:
                ingest_resp = requests.post(
                    f"{api_url}/ingest",
                    json={"match_url": download_url, "match_title": title},
                    timeout=30,
                )
                logger.info("Ingest response: %s %s", ingest_resp.status_code, ingest_resp.text[:200])
            except Exception as e:
                logger.error("Failed to trigger auto-ingest: %s", e)

        return True

    elif status == "restoring" or status_code == 403:
        logger.info("⏳ Still unarchiving in AWS Glacier (HTTP 403)%s...", elapsed_str)
        save_state(match_id, {
            "status": "restoring",
            "match_id": match_id,
            "title": title,
            "last_checked": datetime.now().isoformat(),
        })
        return False

    else:
        logger.warning("Unexpected status from Veo: %s (code %s) %s", status, status_code, res.get("message"))
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor Veo AWS Glacier restoration")
    parser.add_argument("--match-id", default=DEFAULT_MATCH_ID, help="Veo Match UUID or slug")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Match display title")
    parser.add_argument("--token", default=os.environ.get("VEO_API_TOKEN", ""), help="Veo auth token")
    parser.add_argument("--interval", type=int, default=15, help="Polling interval in minutes")
    parser.add_argument("--once", action="store_true", help="Check once and exit immediately")
    parser.add_argument("--auto-ingest", action="store_true", help="Auto-trigger Cloud Run ingest when ready")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Cloud Run backend URL")

    args = parser.parse_args()
    client = VeoApiClient(token=args.token)

    logger.info("Starting Glacier tracking for '%s' (ID: %s)", args.title, args.match_id)

    if args.once:
        is_ready = check_and_report(client, args.match_id, args.title, args.api_url, args.auto_ingest)
        return 0 if is_ready else 1

    start_time = time.time()
    interval_sec = max(60, args.interval * 60)

    try:
        while True:
            is_ready = check_and_report(
                client,
                args.match_id,
                args.title,
                args.api_url,
                args.auto_ingest,
                start_time=start_time,
            )
            if is_ready:
                logger.info("Tracking finished successfully.")
                return 0

            logger.info("Sleeping %d minutes before next ping...", args.interval)
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        logger.info("Glacier tracking interrupted by user. State saved to %s", STATE_FILE)
        return 0


if __name__ == "__main__":
    sys.exit(main())
