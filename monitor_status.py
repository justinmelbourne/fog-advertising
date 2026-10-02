#!/usr/bin/env python3
"""
Live Video Ingest & Google Drive Status Monitor
Run anytime in terminal: python3 monitor_status.py
"""
import sys
import time
import requests

CLOUD_RUN_BASE = "https://fog-video-analysis-546438448149.us-west1.run.app"

def get_status():
    try:
        # Check drive debug
        r_drive = requests.get(f"{CLOUD_RUN_BASE}/drive/debug", timeout=15)
        drive_data = r_drive.json() if r_drive.status_code == 200 else {}
        ingest_files = drive_data.get("ingest_files", [])

        print("\033[2J\033[H", end="")  # Clear screen
        print("====================================================================")
        print("🏉 SF FOG RFC — BINGHAM CUP 2026 VIDEO INGEST MONITOR")
        print("====================================================================")
        print(f"📦 Completed Matches in Google Drive ({len(ingest_files)} files):")
        total_bytes = 0
        for f in ingest_files:
            size_gb = int(f.get("size", 0)) / (1024**3)
            total_bytes += int(f.get("size", 0))
            print(f"  ✅ {f.get('name')} ({size_gb:.2f} GB)")
        print(f"  Total Archived: {total_bytes / (1024**3):.2f} GB")
        print("--------------------------------------------------------------------")

        # Check latest job
        job_id = "861dde05"
        if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
            job_id = sys.argv[1]
        elif "--job" in sys.argv:
            idx = sys.argv.index("--job")
            if idx + 1 < len(sys.argv):
                job_id = sys.argv[idx + 1]
        r_job = requests.get(f"{CLOUD_RUN_BASE}/jobs/{job_id}", timeout=15)
        if r_job.status_code == 200:
            job = r_job.json()
            stage = job.get("stage", "unknown")
            pct = job.get("progress_pct", 0)
            mb_up = job.get("mb_uploaded", 0.0)
            mb_tot = job.get("mb_total", 0.0)
            speed = job.get("speed_mbps", 0.0)
            eta_s = job.get("eta_seconds", 0)
            title = job.get("title", "Active Stream")
            
            print(f"⚡ Current Stream: {title}")
            print(f"   Stage: {stage.upper()}")
            print(f"   Progress: [{pct}%] {mb_up:.1f} MB / {mb_tot:.1f} MB")
            print(f"   Speed: {speed} Mbps • ETA: ~{round(eta_s / 60.0, 1)} min")
            print(f"   Status: {job.get('stage_description')}")
        else:
            print(f"ℹ️ Job {job_id} not currently active.")
            
        print("====================================================================")
        print("Press Ctrl+C to exit monitor.")
    except Exception as e:
        print(f"Error checking status: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        get_status()
    else:
        while True:
            get_status()
            time.sleep(3)
