# engine/cli.py
import argparse
import json
import os
import subprocess
import sys
from typing import List
from engine.models import Manifest, VideoSource, Event
from engine.ai_suggester import generate_clip_pairings
from engine.clipper import build_lossless_cut_command, build_reframe_command
from engine.scanner import scan_match_directory

def generate_match_manifest_from_events(match_id: str, title: str, sources: List[VideoSource], events: List[Event]) -> Manifest:
    """Generate complete game-day manifest enriched with AI editorial suggestions and clip pairings."""
    enriched_events = generate_clip_pairings(events)
    return Manifest(
        match_id=match_id,
        match_title=title,
        match_date=match_id.split("-")[0] if "-" in match_id else "2026-10-10",
        sources=sources,
        events=enriched_events
    )

def main():
    parser = argparse.ArgumentParser(description="SF Fog RFC Match Highlight Engine")
    subparsers = parser.add_subparsers(dest="command")

    # Command: scan
    scan_parser = subparsers.add_parser("scan", help="Scan game-day folder and generate manifest.json")
    scan_parser.add_argument("folder", help="Path to folder containing game day MP4/MOV videos")
    scan_parser.add_argument("--title", default="SF Fog RFC Match", help="Match title (e.g. 'SF Fog RFC vs San Jose Seahawks')")

    # Command: extract
    extract_parser = subparsers.add_parser("extract", help="Extract clips from manifest")
    extract_parser.add_argument("manifest", help="Path to manifest.json")
    extract_parser.add_argument("--format", choices=["16:9", "9:16", "1:1", "4:5"], default="16:9", help="Target social aspect ratio")
    extract_parser.add_argument("--outdir", default="./output_clips", help="Output directory")
    extract_parser.add_argument("--run", action="store_true", help="Execute FFmpeg commands directly")

    args = parser.parse_args()

    if args.command == "scan":
        print(f"Scanning folder: {args.folder}...")
        manifest = scan_match_directory(args.folder, match_title=args.title)
        print(f"Done! Discovered {len(manifest.sources)} video sources and detected {len(manifest.events)} highlight events.")
        print(f"Manifest written to: {os.path.join(args.folder, 'manifest.json')}")

    elif args.command == "extract":
        with open(args.manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
        manifest = Manifest.model_validate(data)
        os.makedirs(args.outdir, exist_ok=True)

        for ev in manifest.events:
            source_file = next((s.filename for s in manifest.sources if s.source_id == ev.source_id), None)
            if not source_file:
                continue

            master_clip = os.path.join(args.outdir, f"{ev.event_id}_master.mp4")
            cut_cmd = build_lossless_cut_command(source_file, ev.start_time, ev.end_time, master_clip)
            print(f"Cutting master: {cut_cmd}")

            if args.run:
                subprocess.run(cut_cmd, shell=True, check=True)

            if args.format != "16:9":
                social_clip = os.path.join(args.outdir, f"{ev.event_id}_{args.format.replace(':', 'x')}.mp4")
                reframe_cmd = build_reframe_command(master_clip, social_clip, aspect_ratio=args.format)
                print(f"Reframing {args.format}: {reframe_cmd}")
                if args.run:
                    subprocess.run(reframe_cmd, shell=True, check=True)

if __name__ == "__main__":
    main()
