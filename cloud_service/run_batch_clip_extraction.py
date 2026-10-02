#!/usr/bin/env python3
"""
cloud_service/run_batch_clip_extraction.py
===========================================
Triggers server-to-server batch extraction of all match moments from Google Drive
in both 16:9 Broadcast Landscape and 9:16 Social Vertical.
Zero bytes downloaded to local Mac disk.
"""

import sys
import time
import requests

CLOUD_RUN_BASE = "https://fog-video-analysis-546438448149.us-west1.run.app"
MATCH_SLUG = "20260822-san-francisco-fog-rfc-a-side-vs-sydney-convicts-1-v4fb17b0"
MATCH_TITLE = "SF Fog A vs Sydney Convicts 1"


def main():
    print("====================================================================")
    print(f"🏉 SF FOG RFC — BATCH MOMENT EXTRACTION PIPELINE")
    print(f"Match: {MATCH_TITLE}")
    print(f"Target Formats: 16:9 Landscape & 9:16 Pitch Navy Vertical")
    print("====================================================================")

    # 1. Fetch manifest to get all detected events
    print("1. Fetching match manifest from Cloud Run...")
    r = requests.get(f"{CLOUD_RUN_BASE}/manifest/{MATCH_SLUG}", timeout=15)
    if r.status_code != 200:
        print(f"❌ Failed to fetch manifest: {r.status_code} {r.text}")
        sys.exit(1)

    manifest = r.json()
    events = manifest.get("events", [])
    print(f"   Found {len(events)} events in manifest.")

    # 2. Build items list for both formats
    items = []
    for ev in events:
        eid = ev["event_id"]
        items.append({"event_id": eid, "format": "16:9"})
        items.append({"event_id": eid, "format": "9:16"})

    print(f"2. Prepared {len(items)} clip extraction tasks ({len(events)} events x 2 aspect ratios).")

    # 3. Trigger batch extraction on Cloud Run
    print("3. Dispatching batch extraction to Cloud Run...")
    payload = {"match_id": MATCH_SLUG, "items": items}
    res = requests.post(f"{CLOUD_RUN_BASE}/extract/batch", json=payload, timeout=30)
    if res.status_code not in (200, 202):
        print(f"❌ Failed to dispatch batch job: {res.status_code} {res.text}")
        sys.exit(1)

    data = res.json()
    job_id = data.get("job_id")
    print(f"   Job ID: {job_id}")
    print(f"   Status: {data.get('status')}")
    print(f"   Message: {data.get('message')}")

    # 4. Continuous keep-alive polling loop
    print("\n4. Monitoring progress and keeping Cloud Run active...")
    start_time = time.time()
    last_completed = -1

    while True:
        time.sleep(3.0)
        try:
            r = requests.get(f"{CLOUD_RUN_BASE}/jobs/{job_id}", timeout=15)
            if r.status_code != 200:
                continue
            job = r.json()
        except Exception as e:
            continue

        stage = job.get("stage", "unknown")
        pct = job.get("progress_pct", 0)
        desc = job.get("stage_description", "")
        completed = job.get("completed_items", 0)
        total = job.get("total_items", len(items))

        elapsed = int(time.time() - start_time)
        elapsed_min = round(elapsed / 60.0, 1)

        sys.stdout.write(f"\r⚡ [{pct}%] ({completed}/{total} clips) • {elapsed_min}m elapsed • {desc[:60]}...   ")
        sys.stdout.flush()

        if stage == "complete":
            print(f"\n\n🎉 BATCH EXTRACTION COMPLETE in {elapsed_min} minutes!")
            results = job.get("results", [])
            print(f"   Generated & uploaded {len(results)} clips directly to Google Drive 'Social Ready' folder.")
            break

        if stage == "error":
            print(f"\n\n❌ Batch extraction failed: {job.get('error')}")
            break


if __name__ == "__main__":
    main()
