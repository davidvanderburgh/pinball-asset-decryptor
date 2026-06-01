"""Tests for the Replace-Video slot scanning + staging (core/video_slots)
plus the per-manufacturer capability / hook wiring.

The scan + capability tests run anywhere; the staging tests need ffmpeg and
ffprobe (matching a clip's resolution / codec is a re-encode) and skip when
they're unavailable.
"""

import os
import subprocess

import pytest

from pinball_decryptor.core.video_slots import (VideoSlot, scan_video_slots,
                                                stage_replacements)


def _make_testsrc(path, seconds=1.0, width=160, height=120, fps=10,
                  ext="mp4"):
    """Render a tiny test clip with ffmpeg.  Returns True on success."""
    from pinball_decryptor.core.video import find_ffmpeg
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cmd = [ffmpeg, "-y", "-f", "lavfi",
           "-i", f"testsrc=size={width}x{height}:rate={fps}:duration={seconds}"]
    if ext in ("mp4", "mov", "m4v", "mkv"):
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    elif ext == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p"]
    elif ext == "ogv":
        cmd += ["-c:v", "libtheora"]
    cmd.append(path)
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0 and os.path.isfile(path)


# ---- scanning (no ffmpeg needed) -----------------------------------------

def test_scan_finds_loose_video_and_skips_dotdirs(tmp_path):
    # Empty placeholder files are enough for the walk; detect_video_info just
    # returns None on them (no ffprobe payload), which the slot tolerates.
    for rel in ("clips/a.mp4", "intro.webm", ".cache/ignore.mp4",
                "b.mp4.stage.mp4"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00")

    slots = scan_video_slots(str(tmp_path))
    rels = sorted(s.rel_path for s in slots)
    assert rels == ["clips/a.mp4", "intro.webm"]


def test_scan_roots_restricts_walk(tmp_path):
    (tmp_path / "editable").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "editable" / "keep.mp4").write_bytes(b"\x00")
    (tmp_path / "elsewhere" / "drop.mp4").write_bytes(b"\x00")

    slots = scan_video_slots(str(tmp_path), roots=[str(tmp_path / "editable")])
    assert [s.rel_path for s in slots] == ["editable/keep.mp4"]


def test_scan_exts_restricts(tmp_path):
    (tmp_path / "a.ogv").write_bytes(b"\x00")
    (tmp_path / "b.webm").write_bytes(b"\x00")
    ogv_only = scan_video_slots(str(tmp_path), exts=(".ogv",))
    assert [s.rel_path for s in ogv_only] == ["a.ogv"]


def test_probe_false_defers_metadata(tmp_path):
    # Fast scan: no ffprobe per file (so a folder of hundreds of clips lists
    # instantly).  Slots come back with info=None and probed=False.
    (tmp_path / "a.mp4").write_bytes(b"\x00")
    (tmp_path / "b.webm").write_bytes(b"\x00")
    slots = scan_video_slots(str(tmp_path), probe=False)
    assert len(slots) == 2
    assert all(s.info is None and s.probed is False for s in slots)


def test_duration_property_handles_missing_info():
    slot = VideoSlot(rel_path="x.mp4", abs_path="x.mp4", ext=".mp4",
                     info=None, size=0)
    assert slot.duration == 0.0
    assert slot.duration_str() == "—"
    assert slot.resolution_str() == "—"
    assert slot.format_summary() == "MP4"


def test_longest_first_sort_uses_duration():
    from pinball_decryptor.core.video import VideoInfo

    def mk(rel, dur):
        return VideoSlot(rel_path=rel, abs_path=rel, ext=".mp4",
                         info=VideoInfo(rel, width=1920, height=1080,
                                        duration=dur), size=0)

    slots = [mk("a.mp4", 5.0), mk("b.mp4", 120.0), mk("c.mp4", 0.5)]
    slots.sort(key=lambda s: s.duration, reverse=True)
    assert [s.rel_path for s in slots] == ["b.mp4", "a.mp4", "c.mp4"]


# ---- capability + hook wiring --------------------------------------------

def test_replace_video_capability_flags(manufacturers_by_key):
    # Enabled where Write round-trips loose files generically (JJP/Spooky/DP
    # ship video today; AP/PB repack any file the same way audio does, so the
    # tab lights up if a game ships a clip and self-empties otherwise).
    for key in ("jjp", "spooky", "dp", "ap", "pb"):
        assert manufacturers_by_key[key].capabilities.replace_video is True
    # Disabled where it would be a dead-end: BOF has no .ogv->.ctex encoder;
    # CGC renders all video in real time (no loose video files to replace).
    for key in ("bof", "cgc"):
        assert manufacturers_by_key[key].capabilities.replace_video is False


def test_spooky_surfaces_ogv_only_others_default(manufacturers_by_key):
    # Spooky narrows to .ogv (Godot, repackable); JJP uses the default whole
    # VIDEO_EXTS set; DP adds its native .cdmd (covered in test_cdmd_replace).
    assert manufacturers_by_key["spooky"].video_slot_exts("anything") == (".ogv",)
    assert manufacturers_by_key["jjp"].video_slot_exts("anything") is None


def test_dp_video_slot_dirs_excludes_decoded_videos(manufacturers_by_key, tmp_path):
    # A TBL-shaped extract (only _DECODED VIDEOS holds .mp4s) surfaces no
    # editable video; an AAIW-shaped extract (loose video in a real subtree)
    # scans normally.
    dp = manufacturers_by_key["dp"]
    (tmp_path / "_DECODED VIDEOS").mkdir()
    (tmp_path / "_DECODED VIDEOS" / "scene.mp4").write_bytes(b"\x00")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "real.mp4").write_bytes(b"\x00")

    roots = dp.video_slot_dirs(str(tmp_path))
    found = scan_video_slots(str(tmp_path), roots=roots)
    rels = sorted(s.rel_path for s in found)
    assert rels == ["assets/real.mp4"]  # the decoded scene is excluded


# ---- staging (needs ffmpeg) ----------------------------------------------

def test_stage_reencodes_to_slot_format_and_resolution(tmp_path):
    from pinball_decryptor.core.video import (detect_video_info, find_ffmpeg,
                                              find_ffprobe)
    if not (find_ffmpeg() and find_ffprobe()):
        pytest.skip("ffmpeg/ffprobe not available")

    slot = str(tmp_path / "clips" / "intro.mp4")
    if not _make_testsrc(slot, seconds=1.0, width=160, height=120, ext="mp4"):
        pytest.skip("ffmpeg could not render the test clip")
    rep = str(tmp_path / "replacement.webm")
    if not _make_testsrc(rep, seconds=2.0, width=320, height=240, ext="webm"):
        pytest.skip("ffmpeg could not render the replacement clip")

    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path),
                                                     exts=(".mp4",))}
    rel = "clips/intro.mp4"
    staged, failures = stage_replacements({rel: slots[rel]}, {rel: rep})
    assert staged == 1 and failures == []

    after = detect_video_info(slot)
    assert after is not None
    assert after.width == 160 and after.height == 120  # scaled to the slot
    assert after.duration > 1.5                        # full length kept


def test_stage_reports_failure_for_missing_replacement(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"\x00")
    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path))}
    staged, failures = stage_replacements(
        slots, {"a.mp4": str(tmp_path / "nope.mp4")})
    assert staged == 0
    assert failures and failures[0][0] == "a.mp4"
