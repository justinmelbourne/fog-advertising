#!/usr/bin/env python3
"""
build_highlight_reels.py
Downloads necessary master clips, renders graphics, assembles both 16:9 Broadcast Highlights
and 9:16 Vertical Action-Zoom Highlights with mastered audio, and uploads to Google Drive.
"""

import os
import sys
import tempfile
import subprocess
import cv2
import numpy as np
from PIL import Image
from typing import Dict, List, Any

os.environ['DRIVE_INGEST_FOLDER_ID'] = '13nRt7Ozw8DKPTM3bjVXZlkpfzr1_Kj9P'
os.environ['DRIVE_OUTPUT_FOLDER_ID'] = '1lNCnRFDyyf3bE0fzNHqHNpzN7s5xalzy'

from cloud_service.drive_client import DriveClient
from engine.highlight_packager import (
    generate_16x9_title_card,
    generate_16x9_outro_card,
    generate_16x9_lower_third,
    generate_9x16_overlay,
    generate_9x16_outro_card,
)

DRIVE_FILE_MAP = {
    'veo_evt_028': '1ChC7gQN1soBJdZUjz8wSM1pJTbx7bOvP', # Try 1
    'veo_evt_004': '1VcoTetY6ZplDqUPG5ZdFstyEFB_hh5VF', # Scrum
    'veo_evt_017': '133FNOU5MNZ-avwRxSJJaoSDQb404FM4Z', # Try 2
    'veo_evt_010': '1-R4EnFl_A_wdxYtza92yM2OFvgh5Ub-1', # Conversion
    'veo_evt_034': '1spy0VESQIk19yPhH_ifNiOqfPcgBC2ks', # Try 3
    'veo_evt_038': '10iuyQhtOncC1oTjtyP12qEiX7-CJQJ76', # Try 4
    'veo_evt_032': '11eCB0gatJ6v7MS_eSml09S7eADdilgy-', # Try 5
    'veo_evt_036': '12GmJbxOP8_7Xdgi0S627RIrh37unp9SL', # Celebration
}

def main():
    print("=== SF FOG RFC HIGHLIGHT REEL PACKAGING ENGINE ===")
    drive = DriveClient()
    
    with tempfile.TemporaryDirectory() as workdir:
        print(f"Working in temporary directory: {workdir}")
        raw_clips_dir = os.path.join(workdir, "raw")
        os.makedirs(raw_clips_dir, exist_ok=True)
        
        # 1. Download source master clips
        print("\n--- Step 1: Downloading 8 Master Event Clips ---")
        clip_paths = {}
        for ev_id, file_id in DRIVE_FILE_MAP.items():
            dest = os.path.join(raw_clips_dir, f"{ev_id}.mp4")
            print(f"Downloading {ev_id} (ID: {file_id})...")
            drive.download_file_to_path(file_id, dest)
            clip_paths[ev_id] = dest
        print("All master clips downloaded successfully.")

        # 2. Build 16:9 Broadcast Highlight Reel
        print("\n--- Step 2: Assembling 16:9 Broadcast Highlight Reel ---")
        reel_16x9_path = os.path.join(workdir, "SF_Fog_vs_Sydney_Convicts_Highlights_16x9.mp4")
        build_16x9_reel(workdir, clip_paths, reel_16x9_path)

        # 3. Build 9:16 Vertical Social Reel (1.25x Action Zoom)
        print("\n--- Step 3: Assembling 9:16 Vertical Social Reel (1.25x Action Zoom) ---")
        reel_9x16_path = os.path.join(workdir, "SF_Fog_vs_Sydney_Convicts_Highlights_9x16.mp4")
        build_9x16_reel(workdir, clip_paths, reel_9x16_path)

        # 4. Upload to Google Drive Social Ready Folder
        print("\n--- Step 4: Uploading Highlight Reels to Google Drive ---")
        target_folder = '1lNCnRFDyyf3bE0fzNHqHNpzN7s5xalzy'
        from googleapiclient.http import MediaFileUpload
        
        # Upload 16:9
        media_16x9 = MediaFileUpload(reel_16x9_path, mimetype='video/mp4', resumable=True)
        meta_16x9 = {
            'name': 'SF_Fog_vs_Sydney_Convicts_Highlights_16x9.mp4',
            'parents': [target_folder]
        }
        res_16x9 = drive._service.files().create(
            body=meta_16x9,
            media_body=media_16x9,
            supportsAllDrives=True
        ).execute()
        print(f"Uploaded 16:9 Broadcast Highlights: ID {res_16x9['id']}")

        # Upload 9:16
        media_9x16 = MediaFileUpload(reel_9x16_path, mimetype='video/mp4', resumable=True)
        meta_9x16 = {
            'name': 'SF_Fog_vs_Sydney_Convicts_Highlights_9x16.mp4',
            'parents': [target_folder]
        }
        res_9x16 = drive._service.files().create(
            body=meta_9x16,
            media_body=media_9x16,
            supportsAllDrives=True
        ).execute()
        print(f"Uploaded 9:16 Vertical Action-Zoom Reel: ID {res_9x16['id']}")

        print("\nHighlight reel packaging completed successfully!")
        print(f"16:9 URL: https://drive.google.com/file/d/{res_16x9['id']}/view?usp=drivesdk")
        print(f"9:16 URL: https://drive.google.com/file/d/{res_9x16['id']}/view?usp=drivesdk")


def build_16x9_reel(workdir: str, clip_paths: Dict[str, str], output_path: str):
    """Assemble 16:9 Broadcast Highlight Reel with Title card, Lower-Thirds, and Outro card."""
    gfx_dir = os.path.join(workdir, "gfx_16x9")
    os.makedirs(gfx_dir, exist_ok=True)
    
    # 1. Cards
    title_png = os.path.join(gfx_dir, "title.png")
    generate_16x9_title_card(title_png, "SAN FRANCISCO FOG RFC", "SYDNEY CONVICTS 1", "BINGHAM CUP 2026 • MATCH HIGHLIGHTS")
    
    outro_png = os.path.join(gfx_dir, "outro.png")
    generate_16x9_outro_card(outro_png)
    
    # Render static cards to video clips
    title_vid = os.path.join(gfx_dir, "title.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', title_png,
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', '3.0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', title_vid
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    outro_vid = os.path.join(gfx_dir, "outro.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', outro_png,
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', '3.0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', outro_vid
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Action segments definition (event_id, start_t, duration, title, subtitle)
    segments = [
        ('veo_evt_028', 4.0, 14.0, "TRY 1 • THE BREAKAWAY", "SAN FRANCISCO FOG RFC"),
        ('veo_evt_004', 3.0, 12.0, "FORWARD PACK POWER", "SCRUM DOMINANCE"),
        ('veo_evt_017', 4.0, 14.0, "TRY 2 • BACKLINE SPEED", "SAN FRANCISCO FOG RFC"),
        ('veo_evt_010', 4.0, 10.0, "CONVERSION SUCCESSFUL", "+2 POINTS"),
        ('veo_evt_034', 12.0, 18.0, "TRY 3 • CORNER FINISH", "SAN FRANCISCO FOG RFC"),
        ('veo_evt_038', 4.0, 14.0, "TRY 4 • POWER PLAY", "SAN FRANCISCO FOG RFC"),
        ('veo_evt_032', 4.0, 14.0, "TRY 5 • FINAL CLINCHER", "SAN FRANCISCO FOG RFC"),
        ('veo_evt_036', 3.0, 10.0, "FULL TIME VICTORY", "BINGHAM CUP 2026"),
    ]
    
    part_files = [title_vid]
    
    for idx, (ev_id, st, dur, main_t, sub_t) in enumerate(segments):
        lt_png = os.path.join(gfx_dir, f"lt_{idx}.png")
        generate_16x9_lower_third(lt_png, main_t, sub_t)
        
        part_out = os.path.join(gfx_dir, f"seg_{idx}.mp4")
        # Cut segment and overlay lower third (active from 0.8s to dur-0.5s with subtle fade)
        cmd = [
            'ffmpeg', '-y', '-ss', str(st), '-t', str(dur),
            '-i', clip_paths[ev_id], '-loop', '1', '-i', lt_png,
            '-filter_complex',
            f"[1:v]format=rgba,fade=t=in:st=0.6:d=0.4:alpha=1,fade=t=out:st={dur-1.2}:d=0.5:alpha=1[lt];"
            f"[0:v][lt]overlay=0:0:enable='between(t,0.6,{dur-0.7})'[v]",
            '-map', '[v]', '-map', '0:a:0?',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            part_out
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        part_files.append(part_out)
        
    part_files.append(outro_vid)
    
    # Concat all segments
    concat_txt = os.path.join(gfx_dir, "concat.txt")
    with open(concat_txt, "w") as f:
        for p in part_files:
            f.write(f"file '{p}'\n")
            
    concat_raw = os.path.join(workdir, "concat_16x9_raw.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_txt,
        '-c', 'copy', concat_raw
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Final loudness mastering
    subprocess.run([
        'ffmpeg', '-y', '-i', concat_raw,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-af', 'highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11',
        '-movflags', '+faststart',
        output_path
    ], check=True)
    print("16:9 Broadcast Highlight Reel generated cleanly.")


def build_9x16_reel(workdir: str, clip_paths: Dict[str, str], output_path: str):
    """Assemble 9:16 Vertical Social Reel with 1.25x Action Zoom, Lanczos4, and Dynamic Overlays."""
    gfx_dir = os.path.join(workdir, "gfx_9x16")
    os.makedirs(gfx_dir, exist_ok=True)
    
    # Outro card
    outro_png = os.path.join(gfx_dir, "outro_9x16.png")
    generate_9x16_outro_card(outro_png)
    outro_vid = os.path.join(gfx_dir, "outro_9x16.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', outro_png,
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', '2.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', outro_vid
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Fast-paced vertical social cuts
    # (event_id, start_t, duration, center_x, center_y, header, badge)
    social_segments = [
        # Hook (0-3s): The Try 3 dive
        ('veo_evt_034', 27.5, 3.2, 750, 600, "SF FOG RFC vs SYDNEY CONVICTS", "5 TRIES • MATCH HIGHLIGHTS"),
        # Try 1 breakaway
        ('veo_evt_028', 11.5, 5.0, 950, 550, "SF FOG RFC vs SYDNEY CONVICTS", "TRY 1 • THE BREAKAWAY"),
        # Forward scrum power
        ('veo_evt_004', 7.5, 4.0, 960, 520, "SF FOG RFC vs SYDNEY CONVICTS", "FORWARD PACK POWER"),
        # Try 2
        ('veo_evt_017', 11.5, 5.0, 980, 550, "SF FOG RFC vs SYDNEY CONVICTS", "TRY 2 • BACKLINE SPEED"),
        # Try 3 full dive sequence
        ('veo_evt_034', 24.0, 5.5, 780, 600, "SF FOG RFC vs SYDNEY CONVICTS", "TRY 3 • CORNER FINISH"),
        # Try 4
        ('veo_evt_038', 11.5, 5.0, 1000, 550, "SF FOG RFC vs SYDNEY CONVICTS", "TRY 4 • POWER PLAY"),
        # Try 5 and victory cheer
        ('veo_evt_032', 11.5, 5.5, 880, 550, "SF FOG RFC vs SYDNEY CONVICTS", "FINAL TRY & VICTORY!"),
        ('veo_evt_036', 5.0, 4.0, 960, 550, "SF FOG RFC vs SYDNEY CONVICTS", "FULL TIME VICTORY"),
    ]
    
    part_files = []
    
    crop_w = int(608 / 1.25) # 486
    crop_h = int(1080 / 1.25) # 864
    
    for idx, (ev_id, st, dur, cx, cy, head_t, badge_t) in enumerate(social_segments):
        # 1. Overlay
        ol_png = os.path.join(gfx_dir, f"ol_{idx}.png")
        generate_9x16_overlay(ol_png, head_t, badge_t)
        
        # 2. Render 1.25x action zoom frames
        cap = cv2.VideoCapture(clip_paths[ev_id])
        fps = cap.get(cv2.CAP_PROP_FPS) or 29.97
        total_f = int(dur * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(st * fps))
        
        y1 = max(0, min(1080 - crop_h, cy - crop_h // 2))
        y2 = y1 + crop_h
        x1 = max(0, min(1920 - crop_w, cx - crop_w // 2))
        x2 = x1 + crop_w
        
        temp_vid = os.path.join(gfx_dir, f"temp_raw_{idx}.mp4")
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', '1080x1920', '-pix_fmt', 'bgr24', '-r', str(fps),
            '-i', '-', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-pix_fmt', 'yuv420p', temp_vid
        ]
        pipe = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        
        for _ in range(total_f):
            ret, frame = cap.read()
            if not ret:
                break
            cropped = frame[y1:y2, x1:x2]
            up = cv2.resize(cropped, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)
            # Detail boost
            blur = cv2.GaussianBlur(up, (0, 0), 2.0)
            sharp = cv2.addWeighted(up, 1.35, blur, -0.35, 0)
            pipe.stdin.write(sharp.tobytes())
            
        pipe.stdin.close()
        pipe.wait()
        cap.release()
        
        # Extract audio segment and composite overlay
        final_seg = os.path.join(gfx_dir, f"seg_{idx}.mp4")
        comp_cmd = [
            'ffmpeg', '-y', '-i', temp_vid, '-ss', str(st), '-t', str(dur), '-i', clip_paths[ev_id],
            '-loop', '1', '-i', ol_png,
            '-filter_complex',
            f"[2:v]format=rgba,fade=t=in:st=0.3:d=0.3:alpha=1,fade=t=out:st={dur-0.6}:d=0.4:alpha=1[ol];"
            f"[0:v][ol]overlay=0:0[v]",
            '-map', '[v]', '-map', '1:a:0?',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            final_seg
        ]
        subprocess.run(comp_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        part_files.append(final_seg)

    part_files.append(outro_vid)
    
    # Concat all vertical segments
    concat_txt = os.path.join(gfx_dir, "concat.txt")
    with open(concat_txt, "w") as f:
        for p in part_files:
            f.write(f"file '{p}'\n")
            
    concat_raw = os.path.join(workdir, "concat_9x16_raw.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_txt,
        '-c', 'copy', concat_raw
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Loudness mastering
    subprocess.run([
        'ffmpeg', '-y', '-i', concat_raw,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-af', 'highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11',
        '-movflags', '+faststart',
        output_path
    ], check=True)
    print("9:16 Vertical Action-Zoom Highlight Reel generated cleanly.")


if __name__ == "__main__":
    main()
