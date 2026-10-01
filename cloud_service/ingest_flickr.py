"""
cloud_service/ingest_flickr.py — Ingest all 9 IGR Bingham Flickr Albums
======================================================================
Consolidates existing 4 downloaded albums from Desktop and fetches the
remaining 5 official albums via gallery-dl into the Bingham 2026 Master Archive.
"""

import os
import shutil
import subprocess
from pathlib import Path

DEST_DIR = Path("/Users/melbourne/Desktop/Bingham_Cup_2026_Archive/04_IGR_Flickr_Match_Albums")
SRC_DIR = Path("/Users/melbourne/Desktop/Bingham_Cup_2026_Photos/gallery-dl/flickr/International Gay Rugby/Albums")

REMAINING_ALBUMS = [
    ("72177720335211011", "Day 1 - Fog C vs Dallas Lost Souls"),
    ("72177720335235751", "Day 1 - Fog C vs Lost Souls, Fog A vs Lorikeets"),
    ("72177720335270622", "Day 2 - Fog C vs Sydney D"),
    ("72177720335274214", "Day 3 - Fog B vs Manchester Spartans"),
    ("72177720335268017", "Day 4 - Legends & Trans match"),
]

def main():
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    print("=== SF Fog RFC — IGR Flickr Match Archive Ingestion ===")
    
    # 1. Copy already downloaded albums to new archive
    if SRC_DIR.exists():
        print(f"\n[1/2] Syncing existing downloaded Flickr albums from:\n  {SRC_DIR}...")
        for item in SRC_DIR.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                target = DEST_DIR / item.name
                if not target.exists():
                    print(f"  Copying {item.name}...")
                    shutil.copytree(item, target)
                else:
                    print(f"  Existing in archive: {item.name}")
    
    # 2. Download remaining 5 albums with gallery-dl
    print("\n[2/2] Fetching remaining 5 Flickr albums via gallery-dl...")
    for album_id, label in REMAINING_ALBUMS:
        url = f"https://www.flickr.com/photos/igrugby/albums/{album_id}"
        print(f"\n  Downloading {label} ({url})...")
        cmd = [
            "/Users/melbourne/.local/bin/gallery-dl",
            "-d", str(DEST_DIR),
            "--write-metadata",
            url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"  ✅ Completed {label}")
        else:
            print(f"  ⚠️ Warning for {label}: {res.stderr[:200]}")

    print(f"\n🎉 All 9 Flickr albums are archived in:\n   {DEST_DIR}")

if __name__ == "__main__":
    main()
