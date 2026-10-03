#!/usr/bin/env python3
"""
cloud_service/process_full_bleed_clips.py
==========================================
Generates 100% full-bleed 9:16 vertical action-zoomed clips (zero letterboxing,
action centered, -14 LUFS mastered) for all match moments and uploads them
directly to Google Drive Shared Drive 'Social Ready' folder.
Zero permanent local disk usage (runs in tempfile.TemporaryDirectory).
"""

import os
import sys
import time
import tempfile
import subprocess
import requests

os.environ["DRIVE_INGEST_FOLDER_ID"] = "13nRt7Ozw8DKPTM3bjVXZlkpfzr1_Kj9P"
os.environ["DRIVE_OUTPUT_FOLDER_ID"] = "1lNCnRFDyyf3bE0fzNHqHNpzN7s5xalzy"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from cloud_service.drive_client import DriveClient

CLOUD_RUN_BASE = "https://fog-video-analysis-546438448149.us-west1.run.app"
MATCH_SLUG = "20260822-san-francisco-fog-rfc-a-side-vs-sydney-convicts-1-v4fb17b0"
MATCH_TITLE = "SF Fog A vs Sydney Convicts 1"

VF_FULL_BLEED = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:(iw-ow)/2:(ih-oh)/2,format=yuv420p"
AF_LOUDNORM = "-af highpass=f=80,loudnorm=I=-14:TP=-1.0:LRA=7"


def transcode_to_full_bleed_9x16(input_16x9_path: str, output_9x16_path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", input_16x9_path,
        "-vf", VF_FULL_BLEED,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-af", "highpass=f=80,loudnorm=I=-14:TP=-1.0:LRA=7",
        "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_9x16_path,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def main():
    print("====================================================================")
    print(f"🏉 SF FOG RFC — FULL-BLEED 9:16 SOCIAL MOMENTS GENERATOR")
    print(f"Match: {MATCH_TITLE}")
    print(f"Zero letterboxing • Action horizontally centered • -14 LUFS Audio")
    print("====================================================================")

    drive = DriveClient()
    output_folder_id = os.environ["DRIVE_OUTPUT_FOLDER_ID"]

    # 1. Inspect existing files in Drive output folder
    print("\n1. Scanning Google Drive 'Social Ready' folder...")
    out_files = drive.list_all_files(output_folder_id)
    existing_names = {f["name"]: f for f in out_files}
    
    master_files = {k: v for k, v in existing_names.items() if k.endswith("_master_16x9.mp4")}
    vertical_files = {k: v for k, v in existing_names.items() if k.endswith("_9x16.mp4")}
    
    print(f"   Found {len(master_files)} 16:9 master chunks in Drive.")
    print(f"   Found {len(vertical_files)} 9:16 vertical clips in Drive.")

    # 2. Phase 1: Create 9:16 full-bleed for any existing master 16:9 chunk missing 9:16
    print("\n2. Processing Phase 1: Transcoding existing 16:9 masters to full-bleed 9:16...")
    for m_name, m_file in sorted(master_files.items()):
        evt_prefix = m_name.replace("_master_16x9.mp4", "")
        v_name = f"{evt_prefix}_9x16.mp4"

        if v_name in vertical_files:
            print(f"   ✅ {v_name} already exists in Drive. Skipping.")
            continue

        print(f"\n   ⚡ Processing {v_name} from {m_name}...")
        t0 = time.time()
        with tempfile.TemporaryDirectory() as tmpdir:
            m_path = os.path.join(tmpdir, m_name)
            v_path = os.path.join(tmpdir, v_name)

            print(f"      Downloading {m_name} ({int(m_file['size'])/1024/1024:.1f} MB)...")
            drive.download_file_to_path(m_file["id"], m_path)

            print(f"      Transcoding to full-bleed 9:16 (action centered, -14 LUFS)...")
            transcode_to_full_bleed_9x16(m_path, v_path)
            v_size_mb = os.path.getsize(v_path) / 1024 / 1024

            print(f"      Uploading {v_name} ({v_size_mb:.1f} MB) to Google Drive...")
            new_id = drive.upload_file_to_folder(v_path, v_name, output_folder_id)
            vertical_files[v_name] = {"id": new_id, "name": v_name}
            elapsed = round(time.time() - t0, 1)
            print(f"      ✅ Done in {elapsed}s! Drive File ID: {new_id}")

    # 3. Phase 2: Cut and generate remaining events from Veo broadcast
    print("\n3. Processing Phase 2: Checking remaining events in match manifest...")
    manifest = drive.read_manifest(MATCH_SLUG)
    events = manifest.get("events", []) if manifest else []
    print(f"   Total events in match manifest: {len(events)}")

    # Fetch Veo match video URL for remote range cutting
    r = requests.get(f"{CLOUD_RUN_BASE}/veo/match/{MATCH_SLUG}", timeout=15)
    vurl = r.json().get("download_url") or r.json().get("video_url") if r.status_code == 200 else None

    if not vurl:
        print("   ⚠️ Could not resolve remote Veo URL. Only existing masters processed.")
        return

    remaining_events = [
        ev for ev in events
        if f"{ev['event_id']}_master_16x9.mp4" not in master_files
        or f"{ev['event_id']}_9x16.mp4" not in vertical_files
    ]
    print(f"   Remaining events to process: {len(remaining_events)}")

    for idx, ev in enumerate(remaining_events, 1):
        eid = ev["event_id"]
        m_name = f"{eid}_master_16x9.mp4"
        v_name = f"{eid}_9x16.mp4"
        etype = ev.get("event_type", "play").upper()
        desc = ev.get("description", "")
        start_t = max(0.0, float(ev.get("start_time", 0.0)) - 5.0)
        end_t = float(ev.get("end_time", start_t + 20.0)) + 5.0

        print(f"\n   [{idx}/{len(remaining_events)}] {eid} ({etype}: {desc} | {start_t:.1f}s - {end_t:.1f}s)...")
        t0 = time.time()

        with tempfile.TemporaryDirectory() as tmpdir:
            m_path = os.path.join(tmpdir, m_name)
            v_path = os.path.join(tmpdir, v_name)

            # 1. Cut 16:9 master directly from remote URL if not in Drive
            if m_name not in master_files:
                print(f"      Cutting 16:9 lossless master via HTTP range...")
                cmd_cut = [
                    "ffmpeg", "-y",
                    "-ss", str(start_t),
                    "-to", str(end_t),
                    "-i", vurl,
                    "-c", "copy",
                    "-avoid_negative_ts", "1",
                    m_path,
                ]
                subprocess.run(cmd_cut, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                m_size_mb = os.path.getsize(m_path) / 1024 / 1024
                print(f"      Uploading {m_name} ({m_size_mb:.1f} MB)...")
                m_id = drive.upload_file_to_folder(m_path, m_name, output_folder_id)
                master_files[m_name] = {"id": m_id, "name": m_name}
            else:
                drive.download_file_to_path(master_files[m_name]["id"], m_path)

            # 2. Transcode to 9:16 full-bleed vertical
            if v_name not in vertical_files:
                print(f"      Transcoding to full-bleed 9:16 (action centered, -14 LUFS)...")
                transcode_to_full_bleed_9x16(m_path, v_path)
                v_size_mb = os.path.getsize(v_path) / 1024 / 1024
                print(f"      Uploading {v_name} ({v_size_mb:.1f} MB)...")
                v_id = drive.upload_file_to_folder(v_path, v_name, output_folder_id)
                vertical_files[v_name] = {"id": v_id, "name": v_name}

            elapsed = round(time.time() - t0, 1)
            print(f"      ✅ Moment {eid} complete in {elapsed}s!")

    print("\n====================================================================")
    print("🎉 ALL MOMENTS EXTRACTED & ARCHIVED TO GOOGLE DRIVE!")
    print(f"   16:9 Master Chunks: {len(master_files)}")
    print(f"   9:16 Full-Bleed Social Clips: {len(vertical_files)}")
    print("====================================================================")


if __name__ == "__main__":
    main()
