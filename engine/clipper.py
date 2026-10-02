# engine/clipper.py
from typing import Literal

AspectRatio = Literal["16:9", "9:16", "1:1", "4:5"]

ASPECT_RATIO_CONFIGS = {
    "9:16": {"width": 1080, "height": 1920},
    "1:1": {"width": 1080, "height": 1080},
    "4:5": {"width": 1080, "height": 1350},
    "16:9": {"width": 1920, "height": 1080}
}

PITCH_NAVY_HEX = "0x00243C"

def build_lossless_cut_command(input_path: str, start: float, end: float, output_path: str) -> str:
    """Build FFmpeg command for ultra-fast, zero-reencoding stream copy with 5s pre-roll and 7s post-roll buffers."""
    actual_start = max(0.0, start - 5.0)
    actual_end = end + 7.0
    return f'ffmpeg -y -ss {actual_start:.1f} -to {actual_end:.1f} -i "{input_path}" -c copy -avoid_negative_ts 1 "{output_path}"'

def build_reframe_command(input_path: str, output_path: str, aspect_ratio: AspectRatio = "9:16", master_audio: bool = True) -> str:
    """Build FFmpeg command to zoom and center-crop clip to fill target social dimensions (zero letterboxing/padding) with normalized audio."""
    cfg = ASPECT_RATIO_CONFIGS.get(aspect_ratio, ASPECT_RATIO_CONFIGS["9:16"])
    w, h = cfg["width"], cfg["height"]

    # Zoom to fill and center-crop the action (100% full screen, zero blue/black bars)
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:(iw-ow)/2:(ih-oh)/2,format=yuv420p"
    
    if master_audio:
        af = "-af highpass=f=80,loudnorm=I=-14:TP=-1.0:LRA=7"
    else:
        af = "-c:a copy"

    return (
        f'ffmpeg -y -i "{input_path}" '
        f'-vf "{vf}" '
        f'-c:v libx264 -profile:v high -level:v 4.1 -preset fast -crf 20 '
        f'{af} -ar 48000 -c:a aac -b:a 256k '
        f'-movflags +faststart "{output_path}"'
    )

