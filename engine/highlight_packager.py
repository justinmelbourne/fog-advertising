# engine/highlight_packager.py
"""
SF Fog RFC Highlight Packaging Engine
======================================
Assembles high-impact match highlight reels:
1. 16:9 Broadcast Highlights: Comprehensive match story (Title, 5 Tries, Scrum, Conversion, Full Time Celebration, Outro) with 2px-radius brand lower-thirds.
2. 9:16 Vertical Social Reel: 1.25x Action-Zoom full-bleed mobile format for Instagram Reels/TikTok/Shorts with hook, rapid cuts, and social mastering.

Runs both locally and inside Cloud Run (server-to-server).
"""

import os
import subprocess
import tempfile
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Any, Tuple, Optional, Callable

NAVY_BG = (0, 36, 60, 255)       # #00243C
FOG_BLUE = (0, 110, 182, 255)    # #006EB6
SKY_BLUE = (36, 160, 241, 255)   # #24A0F1
FOG_GRAY = (220, 221, 222, 255)  # #DCDDDE
WHITE = (255, 255, 255, 255)

def get_brand_fonts(size: int, weight: str = "bold") -> ImageFont.ImageFont:
    """Load bundled Futura font or fallback to system font."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    font_files = {
        "bold": os.path.join(base_dir, "fonts", "FuturaPTBold.otf"),
        "demi": os.path.join(base_dir, "fonts", "FuturaPTDemi.otf"),
        "book": os.path.join(base_dir, "fonts", "FuturaPTBook.otf")
    }
    target = font_files.get(weight, font_files["bold"])
    if os.path.exists(target):
        return ImageFont.truetype(target, size)
    
    # macOS fallback
    mac_font = "/System/Library/Fonts/Supplemental/Futura.ttc"
    if os.path.exists(mac_font):
        idx = 2 if weight == "bold" else 0
        return ImageFont.truetype(mac_font, size, index=idx)
        
    return ImageFont.load_default()


def generate_16x9_title_card(output_path: str, title: str, subtitle: str, event_tag: str):
    """Generate 1920x1080 Title Card with official Fog Rugby brand tokens."""
    img = Image.new("RGBA", (1920, 1080), NAVY_BG)
    draw = ImageDraw.Draw(img)
    
    draw.rectangle([0, 0, 1920, 14], fill=FOG_BLUE)
    draw.rectangle([0, 1066, 1920, 1080], fill=SKY_BLUE)
    
    f_tag = get_brand_fonts(34, "bold")
    f_main = get_brand_fonts(76, "bold")
    f_vs = get_brand_fonts(40, "book")
    f_sub = get_brand_fonts(54, "demi")
    
    draw.text((960, 320), event_tag.upper(), font=f_tag, fill=SKY_BLUE, anchor="mm")
    draw.text((960, 440), title.upper(), font=f_main, fill=WHITE, anchor="mm")
    draw.text((960, 560), "VS", font=f_vs, fill=FOG_GRAY, anchor="mm")
    draw.text((960, 660), subtitle.upper(), font=f_sub, fill=SKY_BLUE, anchor="mm")
    
    img.save(output_path)


def generate_16x9_outro_card(output_path: str):
    """Generate 1920x1080 Outro Card."""
    img = Image.new("RGBA", (1920, 1080), NAVY_BG)
    draw = ImageDraw.Draw(img)
    
    draw.rectangle([0, 0, 1920, 14], fill=FOG_BLUE)
    draw.rectangle([0, 1066, 1920, 1080], fill=SKY_BLUE)
    
    f_main = get_brand_fonts(86, "bold")
    f_sub = get_brand_fonts(42, "demi")
    
    draw.text((960, 460), "UP THE FOG!", font=f_main, fill=WHITE, anchor="mm")
    draw.text((960, 580), "WWW.FOGRUGBY.COM", font=f_sub, fill=SKY_BLUE, anchor="mm")
    
    img.save(output_path)


def generate_16x9_lower_third(output_path: str, title: str, subtitle: str):
    """Generate 1920x1080 transparent lower-third banner with strict 2px radius."""
    img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    f_title = get_brand_fonts(32, "bold")
    f_sub = get_brand_fonts(22, "book")
    
    box_x, box_y, box_w, box_h = 100, 900, 580, 100
    draw.rounded_rectangle([box_x, box_y, box_x + box_w, box_y + box_h], radius=2, fill=(0, 36, 60, 235), outline=FOG_BLUE, width=2)
    draw.rectangle([box_x, box_y, box_x + 8, box_y + box_h], fill=SKY_BLUE)
    
    draw.text((box_x + 28, box_y + 32), title.upper(), font=f_title, fill=WHITE, anchor="lm")
    draw.text((box_x + 28, box_y + 70), subtitle.upper(), font=f_sub, fill=SKY_BLUE, anchor="lm")
    
    img.save(output_path)


def generate_9x16_overlay(output_path: str, header_text: str, badge_text: str):
    """Generate 1080x1920 transparent overlay for vertical social reel with safe-zone positioning."""
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    f_head = get_brand_fonts(28, "bold")
    f_badge = get_brand_fonts(42, "bold")
    
    top_w, top_h = 860, 80
    top_x, top_y = (1080 - top_w) // 2, 230
    draw.rounded_rectangle([top_x, top_y, top_x + top_w, top_y + top_h], radius=2, fill=(0, 36, 60, 235), outline=FOG_BLUE, width=2)
    draw.rectangle([top_x, top_y, top_x + 10, top_y + top_h], fill=SKY_BLUE)
    draw.text((540, top_y + 40), header_text.upper(), font=f_head, fill=WHITE, anchor="mm")
    
    if badge_text:
        badge_w, badge_h = 760, 96
        badge_x, badge_y = (1080 - badge_w) // 2, 1440
        draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=2, fill=(0, 36, 60, 240), outline=SKY_BLUE, width=2)
        draw.rectangle([badge_x, badge_y, badge_x + 10, badge_y + badge_h], fill=FOG_BLUE)
        draw.text((540, badge_y + 48), badge_text.upper(), font=f_badge, fill=WHITE, anchor="mm")
        
    img.save(output_path)


def generate_9x16_outro_card(output_path: str):
    """Generate 1080x1920 vertical Outro Card."""
    img = Image.new("RGBA", (1080, 1920), NAVY_BG)
    draw = ImageDraw.Draw(img)
    
    draw.rectangle([0, 0, 1080, 16], fill=FOG_BLUE)
    draw.rectangle([0, 1904, 1080, 1920], fill=SKY_BLUE)
    
    f_main = get_brand_fonts(76, "bold")
    f_sub = get_brand_fonts(36, "demi")
    
    draw.text((540, 880), "UP THE FOG!", font=f_main, fill=WHITE, anchor="mm")
    draw.text((540, 1000), "WWW.FOGRUGBY.COM", font=f_sub, fill=SKY_BLUE, anchor="mm")
    
    img.save(output_path)


def build_16x9_reel(workdir: str, clip_paths: Dict[str, str], output_path: str, progress_fn: Optional[Callable[[int, str], None]] = None) -> None:
    """Assemble 16:9 Broadcast Highlight Reel."""
    gfx_dir = os.path.join(workdir, "gfx_16x9")
    os.makedirs(gfx_dir, exist_ok=True)
    
    title_png = os.path.join(gfx_dir, "title.png")
    generate_16x9_title_card(title_png, "SAN FRANCISCO FOG RFC", "SYDNEY CONVICTS 1", "BINGHAM CUP 2026 • MATCH HIGHLIGHTS")
    
    outro_png = os.path.join(gfx_dir, "outro.png")
    generate_16x9_outro_card(outro_png)
    
    title_vid = os.path.join(gfx_dir, "title.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', title_png,
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', '3.0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-shortest', title_vid
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    outro_vid = os.path.join(gfx_dir, "outro.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', outro_png,
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', '3.0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-shortest', outro_vid
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
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
        if progress_fn:
            progress_fn(int(10 + (idx / len(segments)) * 35), f"Rendering 16:9 segment {idx+1}/{len(segments)}: {main_t}")
        lt_png = os.path.join(gfx_dir, f"lt_{idx}.png")
        generate_16x9_lower_third(lt_png, main_t, sub_t)
        
        part_out = os.path.join(gfx_dir, f"seg_{idx}.mp4")
        cmd = [
            'ffmpeg', '-y', '-ss', str(st), '-t', str(dur),
            '-i', clip_paths[ev_id],
            '-loop', '1', '-i', lt_png,
            '-filter_complex',
            f"[1:v]format=rgba,fade=t=in:st=0.5:d=0.3:alpha=1,fade=t=out:st={dur-0.9}:d=0.4:alpha=1[lt];"
            f"[0:v][lt]overlay=0:0:shortest=1:enable='between(t,0.5,{dur-0.5})'[v]",
            '-map', '[v]', '-map', '0:a:0?',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-t', str(dur),
            part_out
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        part_files.append(part_out)
        
    part_files.append(outro_vid)
    
    concat_txt = os.path.join(gfx_dir, "concat.txt")
    with open(concat_txt, "w") as f:
        for p in part_files:
            f.write(f"file '{p}'\n")
            
    concat_raw = os.path.join(workdir, "concat_16x9_raw.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_txt,
        '-c', 'copy', concat_raw
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if progress_fn:
        progress_fn(48, "Mastering 16:9 Broadcast Audio (-14 LUFS)...")
        
    subprocess.run([
        'ffmpeg', '-y', '-i', concat_raw,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-af', 'highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11',
        '-movflags', '+faststart',
        output_path
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_9x16_reel(workdir: str, clip_paths: Dict[str, str], output_path: str, progress_fn: Optional[Callable[[int, str], None]] = None) -> None:
    """Assemble 9:16 Vertical Social Reel with 1.25x Action Zoom, Lanczos4, and Dynamic Overlays."""
    gfx_dir = os.path.join(workdir, "gfx_9x16")
    os.makedirs(gfx_dir, exist_ok=True)
    
    outro_png = os.path.join(gfx_dir, "outro_9x16.png")
    generate_9x16_outro_card(outro_png)
    outro_vid = os.path.join(gfx_dir, "outro_9x16.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', outro_png,
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', '2.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-shortest', outro_vid
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    social_segments = [
        ('veo_evt_034', 27.5, 3.2, 750, 600, "SF FOG RFC vs SYDNEY CONVICTS", "5 TRIES • MATCH HIGHLIGHTS"),
        ('veo_evt_028', 11.5, 5.0, 950, 550, "SF FOG RFC vs SYDNEY CONVICTS", "TRY 1 • THE BREAKAWAY"),
        ('veo_evt_004', 7.5, 4.0, 960, 520, "SF FOG RFC vs SYDNEY CONVICTS", "FORWARD PACK POWER"),
        ('veo_evt_017', 11.5, 5.0, 980, 550, "SF FOG RFC vs SYDNEY CONVICTS", "TRY 2 • BACKLINE SPEED"),
        ('veo_evt_034', 24.0, 5.5, 780, 600, "SF FOG RFC vs SYDNEY CONVICTS", "TRY 3 • CORNER FINISH"),
        ('veo_evt_038', 11.5, 5.0, 1000, 550, "SF FOG RFC vs SYDNEY CONVICTS", "TRY 4 • POWER PLAY"),
        ('veo_evt_032', 11.5, 5.5, 880, 550, "SF FOG RFC vs SYDNEY CONVICTS", "FINAL TRY & VICTORY!"),
        ('veo_evt_036', 5.0, 4.0, 960, 550, "SF FOG RFC vs SYDNEY CONVICTS", "FULL TIME VICTORY"),
    ]
    
    part_files = []
    crop_w = int(608 / 1.25) # 486
    crop_h = int(1080 / 1.25) # 864
    
    for idx, (ev_id, st, dur, cx, cy, head_t, badge_t) in enumerate(social_segments):
        if progress_fn:
            progress_fn(int(50 + (idx / len(social_segments)) * 40), f"Rendering 9:16 Action-Zoom cut {idx+1}/{len(social_segments)}: {badge_t}")
        ol_png = os.path.join(gfx_dir, f"ol_{idx}.png")
        generate_9x16_overlay(ol_png, head_t, badge_t)
        
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
            blur = cv2.GaussianBlur(up, (0, 0), 2.0)
            sharp = cv2.addWeighted(up, 1.35, blur, -0.35, 0)
            pipe.stdin.write(sharp.tobytes())
            
        pipe.stdin.close()
        pipe.wait()
        cap.release()
        
        final_seg = os.path.join(gfx_dir, f"seg_{idx}.mp4")
        comp_cmd = [
            'ffmpeg', '-y', '-i', temp_vid, '-ss', str(st), '-t', str(dur), '-i', clip_paths[ev_id],
            '-loop', '1', '-i', ol_png,
            '-filter_complex',
            f"[2:v]format=rgba,fade=t=in:st=0.3:d=0.3:alpha=1,fade=t=out:st={dur-0.6}:d=0.4:alpha=1[ol];"
            f"[0:v][ol]overlay=0:0:shortest=1[v]",
            '-map', '[v]', '-map', '1:a:0?',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-t', str(dur),
            final_seg
        ]
        subprocess.run(comp_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        part_files.append(final_seg)

    part_files.append(outro_vid)
    
    concat_txt = os.path.join(gfx_dir, "concat.txt")
    with open(concat_txt, "w") as f:
        for p in part_files:
            f.write(f"file '{p}'\n")
            
    concat_raw = os.path.join(workdir, "concat_9x16_raw.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_txt,
        '-c', 'copy', concat_raw
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if progress_fn:
        progress_fn(92, "Mastering 9:16 Social Audio (-14 LUFS)...")
        
    subprocess.run([
        'ffmpeg', '-y', '-i', concat_raw,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-af', 'highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11',
        '-movflags', '+faststart',
        output_path
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
