"""
cloud_service/run_cloud_ingest_pipeline.py — Server-to-Server Bingham Media Ingest
==================================================================================
Automates streaming of all active Bingham Cup 2026 matches directly from Veo CDN
into the SF Fog RFC Google Shared Drive via Cloud Run.

Zero bytes touch the local Mac SSD or Wi-Fi.
Continuously keeps Cloud Run active and reports live progress.
"""

import sys
import time
import requests

CLOUD_RUN_BASE = "https://fog-video-analysis-546438448149.us-west1.run.app"

# Active Bingham Cup 2026 Matches to Archive in Google Drive
MATCH_SLUGS = [
    ("20260822-san-francisco-fog-rfc-a-side-vs-sydney-convicts-1-v4fb17b0", "SF Fog A vs Sydney Convicts 1"),
    ("20260822-san-francisco-fog-rfc-b-side-vs-manchester-village-spartans-v71435fc", "SF Fog B vs Manchester Spartans"),
    ("20260822-san-francisco-fog-rfc-a-side-vs-melbourne-chargers-gold-v59dc515", "SF Fog A vs Melbourne Chargers Gold"),
    ("20260821-san-francisco-fog-rfc-b-side-vs-brisbane-hustlers-2-v663df38", "SF Fog B vs Brisbane Hustlers 2nds"),
    ("20260820-san-francisco-fog-rfc-a-side-vs-kings-cross-steelers-2nd-xv-v58359a0", "SF Fog A vs Kings Cross Steelers 2nd XV"),
    ("20260821-match-san-francisco-fog-rfc-x-baltimore-flamingos-v25fb8a2", "SF Fog vs Baltimore Flamingos"),
    ("20260821-san-francisco-fog-rfc-c-side-vs-sydney-convicts-4-vadfd62c", "SF Fog C vs Sydney Convicts 4"),
    ("20260823-international-gay-rugby-trans-match-v38bc810", "International Gay Rugby Trans Match"),
]


def check_existing_drive_files() -> set[str]:
    """Check which matches are already ingested into Google Drive."""
    try:
        r = requests.get(f"{CLOUD_RUN_BASE}/drive/debug", timeout=15)
        if r.status_code == 200:
            data = r.json()
            ingest_files = data.get("ingest_files", [])
            existing = set()
            for f in ingest_files:
                name = f.get("name", "")
                for slug, _ in MATCH_SLUGS:
                    if slug in name:
                        existing.add(slug)
            return existing
    except Exception as e:
        print(f"⚠️ Could not check existing files: {e}")
    return set()


def stream_match(slug: str, title: str, force: bool = False, existing_job_id: str | None = None) -> bool:
    """Trigger and monitor a single match stream on Cloud Run until completion."""
    print(f"\n=======================================================")
    print(f"▶ Initiating Direct Cloud Stream: {title}")
    print(f"  Match Slug: {slug}")
    print(f"=======================================================")

    if existing_job_id:
        job_id = existing_job_id
        print(f"  Attaching to existing active Job ID: {job_id}")
    else:
        payload = {"match_id": slug, "force": force}
        try:
            res = requests.post(f"{CLOUD_RUN_BASE}/veo/ingest", json=payload, timeout=30)
            res_data = res.json()
        except Exception as e:
            print(f"❌ Failed to trigger ingest on Cloud Run: {e}")
            return False

        if res_data.get("status") == "already_ingested":
            print(f"✅ Match already archived in Google Drive. Skipping download.")
            return True

        job_id = res_data.get("job_id")
        if not job_id:
            print(f"❌ No job_id returned: {res_data}")
            return False

    print(f"  Job ID: {job_id}")
    print(f"  Streaming directly to Google Drive (Zero local storage)...")

    # Poll loop to monitor progress and keep Cloud Run active
    last_uploaded = -1.0
    stagnant_count = 0

    while True:
        time.sleep(3.0)
        try:
            r = requests.get(f"{CLOUD_RUN_BASE}/jobs/{job_id}", timeout=15)
            if r.status_code != 200:
                print(f"  [Status {r.status_code}] Retrying poll...")
                continue
            job = r.json()
        except Exception:
            continue

        stage = job.get("stage", "unknown")
        error = job.get("error")

        if stage == "complete":
            mb_tot = job.get("mb_total", 0.0)
            events = job.get("events_count", 0)
            drive_id = job.get("drive_file_id", "Drive ID stored")
            print(f"\n🎉 {title} INGEST COMPLETE!")
            print(f"   Size: {mb_tot} MB archived to Google Drive")
            print(f"   Events: {events} rugby moments detected and paired")
            print(f"   Drive File: {drive_id}")
            return True

        if stage == "error" or error:
            print(f"\n❌ Stream failed for {title}: {error}")
            return False

        mb_up = job.get("mb_uploaded", 0.0)
        mb_tot = job.get("mb_total", 0.0)
        pct = job.get("progress_pct", 0)
        speed = job.get("speed_mbps", 0.0)
        eta_s = job.get("eta_seconds", 0)
        eta_min = round(eta_s / 60.0, 1)

        sys.stdout.write(
            f"\r  ⚡ [{pct}%] {mb_up}/{mb_tot} MB • {speed} Mbps • ETA ~{eta_min} min  "
        )
        sys.stdout.flush()

        if mb_up == last_uploaded and stage == "streaming":
            stagnant_count += 1
            if stagnant_count > 60:  # 3 minutes with 0 progress
                print(f"\n⚠️ Transfer stalled. Retrying stream session...")
                return stream_match(slug, title, force=True)
        else:
            stagnant_count = 0
            last_uploaded = mb_up


def main():
    print("====================================================================")
    print("  SF Fog RFC — Direct Server-to-Server Match Ingestion Pipeline")
    print("  Streaming Veo Broadcast Matches Directly to Google Shared Drive")
    print("  (Zero bytes downloaded to local Mac disk)")
    print("====================================================================")

    existing = check_existing_drive_files()
    print(f"Found {len(existing)} matches already in Google Drive.")

    total = len(MATCH_SLUGS)
    success_count = 0

    for idx, (slug, title) in enumerate(MATCH_SLUGS, 1):
        print(f"\n[{idx}/{total}] Processing: {title}")
        if slug in existing:
            print(f"  ✅ Already archived in Google Drive. Skipping.")
            success_count += 1
            continue

        existing_id = "396f9c04" if slug == "20260821-san-francisco-fog-rfc-b-side-vs-brisbane-hustlers-2-v663df38" else None
        ok = stream_match(slug, title, existing_job_id=existing_id)
        if ok:
            success_count += 1
        else:
            print(f"  ⚠️ Match {slug} encountered an issue. Will allow retry.")

    print(f"\n=======================================================")
    print(f"🎉 Pipeline Run Complete: {success_count}/{total} matches archived in Google Drive.")
    print(f"=======================================================")


if __name__ == "__main__":
    main()
