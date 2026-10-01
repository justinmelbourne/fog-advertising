"""
cloud_service/replace_non_fog_heroes.py — Replace Non-Fog Photos with Pure SF Fog Heroes
========================================================================================
1. Quarantines flagged non-Fog photos (Flickr albums & Trans match) into 'not fog/'.
2. Removes them from the active 00_Curated_Hero_Shots showcase directory.
3. Scores and selects the top 18 authentic SF Fog RFC photos from Team Photos,
   Reese Photography (Fog C vs Chargers), and Justin Pearson match galleries
   (Fog A vs Chargers Gold, Fog C vs Spartans).
4. Re-indexes the 100 Hero Shots with clean sequential naming HERO_001..HERO_100.
5. Re-generates hero_shots_manifest.json and curated_hero_gallery.html.
"""

import os
import json
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from cloud_service.photo_curator import (
    analyze_photo,
    generate_html_gallery,
    ARCHIVE_BASE,
    HERO_DEST,
    MANIFEST_PATH,
    GALLERY_PATH,
)

NOT_FOG_DIR = HERO_DEST / "not fog"


def main():
    print("=== SF Fog RFC — Curation Refresh: Purging Non-Fog & Adding Pure Fog Heroes ===")
    NOT_FOG_DIR.mkdir(parents=True, exist_ok=True)

    with open(MANIFEST_PATH, "r") as f:
        current_manifest = json.load(f)

    # 1. Identify non-Fog items (all Flickr and Trans Match items)
    non_fog_items = []
    kept_items = []

    for item in current_manifest:
        rp = item.get("relative_path", "")
        fn = item.get("hero_filename", "")
        is_non_fog = (
            "04_IGR_Flickr" in rp
            or "Trans_Match" in rp
            or "TransMatch" in fn
            or "flickr_" in fn
        )
        if is_non_fog:
            non_fog_items.append(item)
        else:
            kept_items.append(item)

    print(f"Identified {len(non_fog_items)} non-Fog items to remove and replace.")
    print(f"Retaining {len(kept_items)} verified SF Fog items.")

    # 2. Move any remaining non-fog files from HERO_DEST into NOT_FOG_DIR
    for item in non_fog_items:
        hero_fn = item.get("hero_filename")
        if not hero_fn:
            continue
        cur_file = HERO_DEST / hero_fn
        dest_quarantine = NOT_FOG_DIR / hero_fn
        if cur_file.exists():
            if not dest_quarantine.exists():
                shutil.move(cur_file, dest_quarantine)
            else:
                cur_file.unlink()
            print(f"  Quarantined: {hero_fn} -> not fog/")

    # 3. Find candidate replacement photos strictly from SF Fog folders
    kept_orig_paths = {item["original_path"] for item in kept_items}
    fog_source_folders = [
        ARCHIVE_BASE / "03_Justin_Pearson_Pixieset/Team_Photos",
        ARCHIVE_BASE / "02_Reese_Photography_Google_Photos",
        ARCHIVE_BASE / "03_Justin_Pearson_Pixieset/Fog_A_vs_Melbourne_Chargers_Gold_(Day_3)",
        ARCHIVE_BASE / "03_Justin_Pearson_Pixieset/Fog_C_vs_Manchester_Spartans_(Day_1)",
        ARCHIVE_BASE / "03_Justin_Pearson_Pixieset/Fog_A_vs_Kings_Cross_Steelers_2nds_(Day_2)",
        ARCHIVE_BASE / "03_Justin_Pearson_Pixieset/Fog_B_vs_Vancouver_Rogues_(Day_1)",
    ]

    candidate_files = []
    for fldr in fog_source_folders:
        if fldr.exists():
            for p in fldr.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    if str(p) not in kept_orig_paths:
                        candidate_files.append(p)

    print(f"\nAnalyzing {len(candidate_files)} pure SF Fog candidates...")
    candidates_scored = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(analyze_photo, p): p for p in candidate_files}
        for fut in futures:
            res = fut.result()
            if res:
                # Give special priority to Team Photos (official club portraits)
                if "Team_Photos" in res.get("relative_path", ""):
                    res["hero_score"] = min(99.0, res["hero_score"] + 15.0)
                    res["category"] = "Team Portrait"
                candidates_scored.append(res)

    candidates_scored.sort(key=lambda x: x["hero_score"], reverse=True)

    needed_count = 100 - len(kept_items)
    selected_replacements = candidates_scored[:needed_count]
    print(f"Selected {len(selected_replacements)} top-scoring pure SF Fog replacement photos.")

    # 4. Clean existing hero files in HERO_DEST before re-indexing
    for item in kept_items:
        old_fn = item.get("hero_filename")
        if old_fn:
            old_p = HERO_DEST / old_fn
            if old_p.exists():
                old_p.unlink()

    # 5. Combine and sort all 100 verified SF Fog items
    all_100 = kept_items + selected_replacements
    all_100.sort(key=lambda x: x["hero_score"], reverse=True)

    # 6. Re-index HERO_001 through HERO_100 and copy with clean names
    print("\nCopying and re-indexing all 100 verified SF Fog Hero Shots...")
    for idx, item in enumerate(all_100, 1):
        src_path = Path(item["original_path"])
        cat_clean = item["category"].replace(" ", "_").replace("&", "and")
        clean_name = f"HERO_{idx:03d}_{cat_clean}_{item['filename']}"
        dest_file = HERO_DEST / clean_name
        shutil.copy2(src_path, dest_file)
        item["hero_filename"] = clean_name
        item["hero_path"] = str(dest_file)

    # 7. Save updated manifest JSON
    with open(MANIFEST_PATH, "w") as f:
        json.dump(all_100, f, indent=2)
    print(f"Saved updated manifest: {MANIFEST_PATH}")

    # 8. Re-generate interactive HTML gallery
    html_content = generate_html_gallery(all_100)
    with open(GALLERY_PATH, "w") as f:
        f.write(html_content)
    print(f"Generated updated showcase gallery: {GALLERY_PATH}")

    print("\n🎉 All 100 Hero Shots are now 100% authentic SF Fog RFC photos!")


if __name__ == "__main__":
    main()
