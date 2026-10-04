# engine/highlight_packager.py
"""
SF Fog RFC Highlight Packaging Engine
======================================
Assembles match highlight reels from VERIFIED Fog-positive manifest events only:
1. 16:9 Broadcast Highlights: title card, moments in match order with brand lower-thirds, outro.
2. 9:16 Vertical Social Reel: 1.25x action-zoom, Lanczos upscale + unsharp, branded overlays.

Nothing is hardcoded per match: select_reel_moments() picks the clips and
plan_segments() turns them into cut lists, so any manifest works.

Runs both locally and inside Cloud Run (server-to-server).
"""

import os
import subprocess
import tempfile
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Any, Optional, Callable

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


CONFIDENCE_THRESHOLD = 0.75

MOMENT_LABELS = {
    "try": "TRY",
    "big_tackle": "BIG HIT",
    "tackle": "BIG HIT",
    "scrum": "SCRUM WON",
    "lineout": "LINEOUT WON",
    "conversion": "CONVERSION",
    "penalty": "PENALTY KICK",
}


def select_reel_moments(events: List[Dict[str, Any]], max_moments: int = 8) -> List[Dict[str, Any]]:
    """
    Pick the best verified Fog-positive moments, then return them in match order.
    Unclassified, low-confidence, neutral and opponent moments are never selected.
    """
    verified = [
        e for e in events
        if e.get("sentiment") == "fog_positive"
        and float(e.get("sentiment_confidence") or 0.0) >= CONFIDENCE_THRESHOLD
        and e.get("status") != "rejected"
    ]
    # Tries first, then by excitement, then cap; finally restore chronology for the story
    ranked = sorted(
        verified,
        key=lambda e: (e.get("event_type") == "try", float(e.get("excitement_score") or 0.0)),
        reverse=True,
    )[:max_moments]
    return sorted(ranked, key=lambda e: float(e.get("start_time") or 0.0))


def label_moments(moments: List[Dict[str, Any]]) -> List[str]:
    """'TRY 1', 'TRY 2', 'SCRUM WON', ... numbered in match order for repeated tries."""
    labels, try_count = [], 0
    for m in moments:
        et = str(m.get("event_type", "")).lower()
        if et == "try":
            try_count += 1
            labels.append(f"TRY {try_count}")
        else:
            labels.append(MOMENT_LABELS.get(et, et.replace("_", " ").upper() or "FOG MOMENT"))
    return labels


def plan_segments(
    moments: List[Dict[str, Any]],
    source_paths: Dict[str, str],
    vertical: bool = False,
) -> List[Dict[str, Any]]:
    """
    Turn manifest moments into absolute cut windows on the source match video.
    Vertical cuts are tighter (social pacing); 16:9 keeps a little build-up.
    """
    lead_in, pad, min_d, max_d = (1.0, 2.0, 4.0, 7.0) if vertical else (2.0, 4.0, 6.0, 16.0)
    segments = []
    for moment, label in zip(moments, label_moments(moments)):
        src = source_paths.get(moment.get("source_id", ""))
        if not src:
            continue
        start = max(0.0, float(moment.get("start_time") or 0.0) - lead_in)
        dur = float(moment.get("duration") or 0.0) + pad
        segments.append({
            "source_path": src,
            "start": round(start, 2),
            "duration": round(min(max(dur, min_d), max_d), 2),
            "label": label,
            "event_id": moment.get("event_id"),
        })
    return segments


def _render_card(png_path: str, out_path: str, seconds: float) -> None:
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', png_path,
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', str(seconds), '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', out_path
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _concat_and_master(part_files: List[str], workdir: str, tag: str, output_path: str) -> None:
    """Concat uniform segments, then master audio to -14 LUFS for social/broadcast."""
    concat_txt = os.path.join(workdir, f"concat_{tag}.txt")
    with open(concat_txt, "w") as f:
        for p in part_files:
            f.write(f"file '{p}'\n")
    concat_raw = os.path.join(workdir, f"concat_{tag}_raw.mp4")
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_txt, '-c', 'copy', concat_raw
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([
        'ffmpeg', '-y', '-i', concat_raw,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        '-af', 'highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11',
        '-movflags', '+faststart', output_path
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_AUDIO_CACHE: Dict[str, bool] = {}


def _has_audio(path: str) -> bool:
    if path not in _AUDIO_CACHE:
        try:
            out = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', path],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
            _AUDIO_CACHE[path] = bool(out)
        except Exception:
            _AUDIO_CACHE[path] = False
    return _AUDIO_CACHE[path]


def _segment_audio_inputs(source_path: str) -> List[str]:
    """Extra silent input (index 2) when the source has no audio, so every part has a track."""
    return [] if _has_audio(source_path) else ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']


def _segment_audio_args(source_path: str) -> List[str]:
    # Uniform 48k stereo AAC on every part so concat -c copy is safe
    src = '0:a:0' if _has_audio(source_path) else '2:a:0'
    return ['-map', src, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']


def build_16x9_reel(
    workdir: str,
    segments: List[Dict[str, Any]],
    output_path: str,
    opponent_display: str,
    event_tag: str = "MATCH HIGHLIGHTS",
    progress_fn: Optional[Callable[[int, str], None]] = None,
) -> None:
    """Assemble the 16:9 broadcast reel: title card, verified moments with lower-thirds, outro."""
    if not segments:
        raise ValueError("No verified Fog-positive segments to build a 16:9 reel from")
    gfx_dir = os.path.join(workdir, "gfx_16x9")
    os.makedirs(gfx_dir, exist_ok=True)

    title_png = os.path.join(gfx_dir, "title.png")
    generate_16x9_title_card(title_png, "SAN FRANCISCO FOG RFC", opponent_display, event_tag)
    outro_png = os.path.join(gfx_dir, "outro.png")
    generate_16x9_outro_card(outro_png)
    title_vid = os.path.join(gfx_dir, "title.mp4")
    outro_vid = os.path.join(gfx_dir, "outro.mp4")
    _render_card(title_png, title_vid, 3.0)
    _render_card(outro_png, outro_vid, 3.0)

    part_files = [title_vid]
    for idx, seg in enumerate(segments):
        dur = seg["duration"]
        if progress_fn:
            progress_fn(int(10 + (idx / len(segments)) * 80), f"Rendering 16:9 segment {idx+1}/{len(segments)}: {seg['label']}")
        lt_png = os.path.join(gfx_dir, f"lt_{idx}.png")
        generate_16x9_lower_third(lt_png, seg["label"], "SAN FRANCISCO FOG RFC")

        part_out = os.path.join(gfx_dir, f"seg_{idx}.mp4")
        # Input seek + re-encode = frame-accurate cut straight from the match master
        cmd = [
            'ffmpeg', '-y', '-ss', str(seg["start"]), '-t', str(dur), '-i', seg["source_path"],
            '-loop', '1', '-i', lt_png,
            *_segment_audio_inputs(seg["source_path"]),
            '-filter_complex',
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[base];"
            f"[1:v]format=rgba,fade=t=in:st=0.5:d=0.3:alpha=1,fade=t=out:st={max(dur-0.9, 0.6)}:d=0.4:alpha=1[lt];"
            f"[base][lt]overlay=0:0:shortest=1:enable='between(t,0.5,{max(dur-0.5, 0.6)})'[v]",
            '-map', '[v]', *_segment_audio_args(seg["source_path"]),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p',
            '-t', str(dur), part_out
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        part_files.append(part_out)

    part_files.append(outro_vid)
    if progress_fn:
        progress_fn(92, "Mastering 16:9 audio (-14 LUFS)...")
    _concat_and_master(part_files, gfx_dir, "16x9", output_path)


def build_9x16_reel(
    workdir: str,
    segments: List[Dict[str, Any]],
    output_path: str,
    header_text: str,
    zoom: float = 1.25,
    progress_fn: Optional[Callable[[int, str], None]] = None,
) -> None:
    """
    Assemble the 9:16 social reel. Single ffmpeg pass per segment:
    centre action-zoom crop -> Lanczos upscale -> unsharp -> branded overlay.
    """
    if not segments:
        raise ValueError("No verified Fog-positive segments to build a 9:16 reel from")
    gfx_dir = os.path.join(workdir, "gfx_9x16")
    os.makedirs(gfx_dir, exist_ok=True)

    outro_png = os.path.join(gfx_dir, "outro_9x16.png")
    generate_9x16_outro_card(outro_png)
    outro_vid = os.path.join(gfx_dir, "outro_9x16.mp4")
    _render_card(outro_png, outro_vid, 2.5)

    # 9:16 window inside a 1080-tall frame, tightened by the zoom factor
    crop_expr = f"crop=trunc(ih*9/16/{zoom}/2)*2:trunc(ih/{zoom}/2)*2:(iw-ow)/2:(ih-oh)/2"
    try_total = sum(1 for s in segments if s["label"].startswith("TRY"))

    part_files = []
    for idx, seg in enumerate(segments):
        dur = seg["duration"]
        badge = seg["label"]
        if idx == 0 and try_total > 1:
            badge = f"{try_total} TRIES • MATCH HIGHLIGHTS"
        if progress_fn:
            progress_fn(int(10 + (idx / len(segments)) * 80), f"Rendering 9:16 cut {idx+1}/{len(segments)}: {badge}")
        ol_png = os.path.join(gfx_dir, f"ol_{idx}.png")
        generate_9x16_overlay(ol_png, header_text, badge)

        final_seg = os.path.join(gfx_dir, f"seg_{idx}.mp4")
        cmd = [
            'ffmpeg', '-y', '-ss', str(seg["start"]), '-t', str(dur), '-i', seg["source_path"],
            '-loop', '1', '-i', ol_png,
            *_segment_audio_inputs(seg["source_path"]),
            '-filter_complex',
            f"[0:v]{crop_expr},scale=1080:1920:flags=lanczos,unsharp=5:5:0.7:5:5:0.0,fps=30,setsar=1[base];"
            f"[1:v]format=rgba,fade=t=in:st=0.3:d=0.3:alpha=1,fade=t=out:st={max(dur-0.6, 0.6)}:d=0.4:alpha=1[ol];"
            f"[base][ol]overlay=0:0:shortest=1[v]",
            '-map', '[v]', *_segment_audio_args(seg["source_path"]),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-t', str(dur), final_seg
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        part_files.append(final_seg)

    part_files.append(outro_vid)
    if progress_fn:
        progress_fn(92, "Mastering 9:16 audio (-14 LUFS)...")
    _concat_and_master(part_files, gfx_dir, "9x16", output_path)
