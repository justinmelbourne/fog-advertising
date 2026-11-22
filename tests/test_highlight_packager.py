# tests/test_highlight_packager.py
import os
import shutil
import subprocess

import pytest

from engine.highlight_packager import (
    select_reel_moments,
    label_moments,
    plan_segments,
    build_16x9_reel,
    build_9x16_reel,
    hook_first,
)


def _ev(eid, etype, start, sentiment="fog_positive", conf=0.9, score=0.8, source="veo_main"):
    return {
        "event_id": eid, "event_type": etype, "start_time": start, "duration": 10.0,
        "sentiment": sentiment, "sentiment_confidence": conf, "excitement_score": score,
        "source_id": source,
    }


def test_select_only_verified_fog_positive_in_match_order():
    events = [
        _ev("e3", "try", 900),
        _ev("e1", "try", 100),
        _ev("opp", "try", 500, sentiment="fog_negative", conf=0.99),
        _ev("unsure", "try", 600, conf=0.6),
        _ev("review", "scrum", 700, sentiment="neutral"),
        {"event_id": "legacy", "event_type": "try", "start_time": 50},  # never classified
    ]
    picked = select_reel_moments(events)
    assert [m["event_id"] for m in picked] == ["e1", "e3"]


def test_select_caps_and_prefers_tries():
    events = [_ev(f"s{i}", "scrum", i * 10, score=0.99) for i in range(5)] + [_ev("t", "try", 999, score=0.1)]
    picked = select_reel_moments(events, max_moments=2)
    assert "t" in [m["event_id"] for m in picked]


def test_labels_number_tries():
    moments = [_ev("a", "try", 1), _ev("b", "scrum", 2), _ev("c", "try", 3)]
    assert label_moments(moments) == ["TRY 1", "SCRUM WON", "TRY 2"]


def test_plan_segments_windows_and_missing_source():
    moments = [_ev("a", "try", 100), _ev("b", "try", 1.0), _ev("x", "try", 5, source="phone")]
    segs = plan_segments(moments, {"veo_main": "/m.mp4"})
    assert len(segs) == 2  # phone source not downloaded -> skipped
    assert segs[0]["start"] == 98.0 and segs[0]["duration"] == 14.0
    assert segs[1]["start"] == 0.0  # clamped at match start
    vert = plan_segments(moments[:1], {"veo_main": "/m.mp4"}, vertical=True)
    assert vert[0]["duration"] == 7.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_reels_render_end_to_end(tmp_path):
    """Real ffmpeg render on a synthetic 1080p match (one source silent) — catches filter-graph bugs."""
    with_audio = tmp_path / "match.mp4"
    silent = tmp_path / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=12",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest", str(with_audio)], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=8",
        "-c:v", "libx264", "-preset", "ultrafast", str(silent)], check=True, capture_output=True)

    moments = [
        {**_ev("a", "try", 3.0), "duration": 1.0},
        {**_ev("b", "scrum", 4.0, source="cam2"), "duration": 1.0},
    ]
    sources = {"veo_main": str(with_audio), "cam2": str(silent)}

    out16 = tmp_path / "reel16.mp4"
    build_16x9_reel(str(tmp_path), plan_segments(moments, sources), str(out16), opponent_display="TEST XV")
    out9 = tmp_path / "reel9.mp4"
    build_9x16_reel(str(tmp_path), plan_segments(moments, sources, vertical=True), str(out9), header_text="SF FOG RFC vs TEST XV")
    out9c = tmp_path / "reel9_crop.mp4"
    build_9x16_reel(str(tmp_path), plan_segments(moments, sources, vertical=True), str(out9c),
                    header_text="SF FOG RFC vs TEST XV", framing="crop")

    def probe(path):
        return subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True).stdout

    p16, p9 = probe(out16), probe(out9)
    assert "video,1080,1920" in probe(out9c)
    assert "video,1920,1080" in p16 and "audio" in p16
    assert "video,1080,1920" in p9 and "audio" in p9
    assert os.path.getsize(out16) > 0 and os.path.getsize(out9) > 0


def test_hook_first_opens_with_best_try_then_match_order():
    moments = [
        _ev("scrum", "scrum", 100, score=0.95),
        _ev("try_small", "try", 200, score=0.5),
        _ev("try_big", "try", 300, score=0.9),
        _ev("tackle", "big_tackle", 400, score=0.7),
    ]
    segs = plan_segments(moments, {"veo_main": "/m.mp4"}, vertical=True)
    ordered = [s["event_id"] for s in hook_first(segs, moments)]
    assert ordered == ["try_big", "scrum", "try_small", "tackle"]
    assert hook_first(segs[:1], moments) == segs[:1]
