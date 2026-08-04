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
    # tab lights up if a game ships a clip and self-empties otherwise).  BOF
    # joins them via encode_video_to_ctex — its .ctex video slots are raw Ogg.
    for key in ("jjp", "spooky", "dp", "ap", "pb", "bof"):
        assert manufacturers_by_key[key].capabilities.replace_video is True
    # Disabled where it would be a dead-end: CGC renders all video in real
    # time, so there are no loose video files to replace.
    assert manufacturers_by_key["cgc"].capabilities.replace_video is False


def test_spooky_surfaces_ogv_only_others_default(manufacturers_by_key):
    # Spooky and BOF narrow to .ogv (Godot, repackable); JJP uses the default
    # whole VIDEO_EXTS set; DP adds .cdmd (covered in test_cdmd_replace).
    assert manufacturers_by_key["spooky"].video_slot_exts("anything") == (".ogv",)
    assert manufacturers_by_key["bof"].video_slot_exts("anything") == (".ogv",)
    assert manufacturers_by_key["jjp"].video_slot_exts("anything") is None


def test_bof_surfaces_standalone_videos_not_the_import_cache(
        manufacturers_by_key, tmp_path):
    # BOF's real clips are standalone PCK entries at pck/assets/videos/ —
    # NOT imported binaries — so the scan must reach them at their res://
    # path.  The .godot import cache next door must stay out of the list;
    # it's excluded by scan_video_slots' dot-directory prune rather than by
    # a BOF-specific root, which is why there's no video_slot_dirs override.
    bof = manufacturers_by_key["bof"]
    vids = tmp_path / "pck" / "assets" / "videos" / "arena"
    vids.mkdir(parents=True)
    (vids / "1a_arena_fight_intro.ogv").write_bytes(b"OggS\x00")
    cache = tmp_path / "pck" / ".godot" / "imported"
    cache.mkdir(parents=True)
    (cache / "poster.png-abc123.ctex").write_bytes(b"OggS\x00")
    (cache / "stray.ogv").write_bytes(b"OggS\x00")

    found = scan_video_slots(str(tmp_path),
                             roots=bof.video_slot_dirs(str(tmp_path)),
                             exts=bof.video_slot_exts(str(tmp_path)),
                             probe=False)
    assert [s.rel_path for s in found] == [
        "pck/assets/videos/arena/1a_arena_fight_intro.ogv"]


def test_bof_video_ext_is_substitutable_by_the_packer():
    # The wiring that actually ships a replaced clip: the Replace-Video tab
    # writes over pck/assets/videos/<name>.ogv, the MD5 walk reports it as
    # changed, and _pack_via_directory only swaps extensions on this list.
    # Without .ogv here every video edit is silently dropped at Write.
    from pinball_decryptor.plugins.bof.may_packer import _SUBSTITUTABLE_EXTS
    assert ".ogv" in _SUBSTITUTABLE_EXTS
    # .fontdata must stay off it — extraction decompresses those, so they'd
    # read as edited on every single build.
    assert ".fontdata" not in _SUBSTITUTABLE_EXTS


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


# ---- encode timeout + codec args (no ffmpeg needed) -----------------------

def test_encode_timeout_scales_with_duration():
    # The wall-clock cap exists to catch a hung ffmpeg, not a slow one — it
    # must grow with the clip so a full-song VP9 encode isn't killed (the
    # old flat 900s did exactly that on a 9-minute GNR webm).
    from pinball_decryptor.core.video import _encode_timeout
    assert _encode_timeout(0) == 3600           # unknown length
    assert _encode_timeout(10) == 900           # short clip: floor
    assert _encode_timeout(564) == 564 * 20     # a full song scales up
    assert _encode_timeout(10_000) == 4 * 3600  # bounded


def test_webm_codec_args_use_fast_vp9():
    from pinball_decryptor.core.video import _video_codec_args
    for alpha in (False, True):
        vargs, aargs = _video_codec_args(".webm", alpha)
        assert "libvpx-vp9" in vargs
        assert "-row-mt" in vargs and "-cpu-used" in vargs
        assert aargs == ["-c:a", "libopus"]


# ---------------------------------------------------------------------------
# The re-encode copies the SLOT's codec, not the container's default.
#
# A container says less than it looks like it does: .webm is VP8 or VP9, .mov
# is H.264 or ProRes.  Picking by extension turned a VP8 slot into VP9, which
# an embedded player that only has VP8 demuxes far enough to play the sound
# over a black picture — the same failure the H.264 profile ceiling already
# guards against (PAD-27: two replacement clips black on the machine).
# ---------------------------------------------------------------------------

def test_a_vp8_slot_is_re_encoded_as_vp8():
    from pinball_decryptor.core.video import _video_codec_args
    vargs, aargs = _video_codec_args(".webm", False, "vp8")
    assert "libvpx" in vargs and "libvpx-vp9" not in vargs
    # -row-mt is a VP9-only private option; libvpx would error out on it.
    assert "-row-mt" not in vargs
    assert "-cpu-used" in vargs                  # still not the slow default
    assert aargs == ["-c:a", "libvorbis"]


def test_a_vp9_slot_is_still_re_encoded_as_vp9():
    from pinball_decryptor.core.video import _video_codec_args
    vargs, _ = _video_codec_args(".webm", False, "vp9")
    assert "libvpx-vp9" in vargs and "-row-mt" in vargs


def test_a_prores_mov_slot_stays_prores():
    from pinball_decryptor.core.video import _video_codec_args
    vargs, aargs = _video_codec_args(".mov", False, "prores")
    assert "prores_ks" in vargs and "libx264" not in vargs
    assert aargs == ["-c:a", "pcm_s16le"]


def test_an_unprobed_slot_keeps_the_container_default():
    """No ffprobe means no evidence, and a guess is not evidence — fall back
    to what this app has always done rather than inventing a codec."""
    from pinball_decryptor.core.video import _video_codec_args
    assert "libvpx-vp9" in _video_codec_args(".webm", False, "")[0]
    assert "libx264" in _video_codec_args(".mov", False, "")[0]
    assert "libx264" in _video_codec_args(".mp4", False, None)[0]


def test_a_codec_the_container_cannot_hold_is_not_copied():
    """H.264 in a WebM is not a thing ffmpeg will mux, so a slot that somehow
    probes that way must not drag the encoder there."""
    from pinball_decryptor.core.video import _video_codec_args
    assert "libvpx-vp9" in _video_codec_args(".webm", False, "h264")[0]
    assert "libx264" in _video_codec_args(".mp4", False, "vp9")[0]


def test_alpha_is_decided_by_the_container_not_the_slot_codec():
    """Only one encoder per container carries transparency, so an alpha slot
    keeps exactly the behaviour it had."""
    from pinball_decryptor.core.video import _video_codec_args
    vargs, _ = _video_codec_args(".mov", True, "vp8")
    assert "prores_ks" in vargs and "yuva444p10le" in vargs
    vargs, _ = _video_codec_args(".webm", True, "vp8")
    assert "libvpx-vp9" in vargs and "yuva420p" in vargs


def test_unsupported_container_still_reports_nothing_to_encode_with():
    from pinball_decryptor.core.video import _video_codec_args
    assert _video_codec_args(".xyz", False, "h264") == (None, None)


def test_the_log_names_the_codec_only_when_it_saved_the_clip(monkeypatch,
                                                             tmp_path):
    """The one word that distinguishes a clip that plays from one that plays
    black belongs in the build log; the container's default doesn't need
    announcing."""
    from pinball_decryptor.core import video
    from pinball_decryptor.core.video import VideoInfo

    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(video, "probe_duration", lambda p: 5.0)
    monkeypatch.setattr(video, "_run_ffmpeg_watched",
                        lambda cmd, limit, cancel_cb=None: (0, b"", None))
    dst = tmp_path / "out.webm"
    dst.write_bytes(b"x")

    def _detail(codec):
        info = VideoInfo(path="s.webm", vcodec=codec, width=320, height=240,
                         fps=30.0, duration=5.0)
        return video.transcode_video_to(str(tmp_path / "in.mp4"), str(dst),
                                        info)[1]

    assert "VP8" in _detail("vp8")
    assert "VP9" not in _detail("vp9")        # that's the webm default


def test_transcode_abort_reports_friendly_errors(monkeypatch, tmp_path):
    # A killed encode must not surface a raw ffmpeg command dump; each abort
    # reason maps to a human-readable detail ("cancelled" stays terse so the
    # log reads naturally).
    from pinball_decryptor.core import video

    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(video, "probe_duration", lambda p: 5.0)

    for abort, needle in (("timeout", "timed out"),
                          ("stall", "no output"),
                          ("cancelled", "cancelled")):
        monkeypatch.setattr(video, "_run_ffmpeg_watched",
                            lambda cmd, limit, cancel_cb=None, a=abort:
                            (None, b"", a))
        ok, detail = video.transcode_video_to(
            str(tmp_path / "in.mp4"), str(tmp_path / "out.webm"), None)
        assert ok is False
        assert needle in detail
        assert "-c:v" not in detail  # no raw command dump


def test_stage_replacements_stops_on_cancel(tmp_path):
    # A truthy cancel_cb stops before any staging work — nothing staged,
    # nothing reported as a failure (the user asked to stop, they didn't
    # break anything).
    (tmp_path / "a.mp4").write_bytes(b"\x00")
    (tmp_path / "rep.mp4").write_bytes(b"\x00")
    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path),
                                                     probe=False)}
    staged, failures = stage_replacements(
        slots, {"a.mp4": str(tmp_path / "rep.mp4")}, cancel_cb=lambda: True)
    assert staged == 0 and failures == []
    assert (tmp_path / "a.mp4").read_bytes() == b"\x00"  # untouched


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


def test_stage_reencodes_to_webm_slot(tmp_path):
    # The GNR-shaped path: a non-matching replacement re-encoded into a .webm
    # slot.  Exercises the real libvpx-vp9 invocation (speed + constant-
    # quality flags) — a flag ffmpeg rejects would exit non-zero here.
    from pinball_decryptor.core.video import (detect_video_info, find_ffmpeg,
                                              find_ffprobe)
    if not (find_ffmpeg() and find_ffprobe()):
        pytest.skip("ffmpeg/ffprobe not available")

    slot = str(tmp_path / "clips" / "song.webm")
    if not _make_testsrc(slot, seconds=1.0, width=160, height=120, ext="webm"):
        pytest.skip("ffmpeg could not render the test clip")
    rep = str(tmp_path / "rep.mp4")
    if not _make_testsrc(rep, seconds=1.0, width=320, height=240, ext="mp4"):
        pytest.skip("ffmpeg could not render the replacement clip")

    slots = {s.rel_path: s for s in scan_video_slots(
        str(tmp_path), roots=[str(tmp_path / "clips")], exts=(".webm",))}
    rel = "clips/song.webm"
    staged, failures = stage_replacements({rel: slots[rel]}, {rel: rep})
    assert staged == 1 and failures == []
    after = detect_video_info(slot)
    assert after is not None and after.vcodec == "vp9"
    assert after.width == 160 and after.height == 120


def test_stage_reencodes_a_vp8_slot_back_to_vp8(tmp_path):
    """PAD-27, end to end: the .webm slot holds VP8, so the replacement must
    come out VP8.  It used to come out VP9 because the extension was all that
    was consulted, and a player with only a VP8 decoder shows that as a black
    picture with the sound still playing."""
    from pinball_decryptor.core.video import (detect_video_info, find_ffmpeg,
                                              find_ffprobe)
    ffmpeg = find_ffmpeg()
    if not (ffmpeg and find_ffprobe()):
        pytest.skip("ffmpeg/ffprobe not available")

    slot = str(tmp_path / "clips" / "attract.webm")
    os.makedirs(os.path.dirname(slot), exist_ok=True)
    made = subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi",
         "-i", "testsrc=size=160x120:rate=10:duration=1",
         "-c:v", "libvpx", "-b:v", "300k", "-an", slot],
        capture_output=True)
    if made.returncode != 0 or not os.path.isfile(slot):
        pytest.skip("this ffmpeg build has no libvpx (VP8) encoder")
    assert detect_video_info(slot).vcodec == "vp8"     # the premise

    rep = str(tmp_path / "rep.mp4")
    if not _make_testsrc(rep, seconds=1.0, width=320, height=240, ext="mp4"):
        pytest.skip("ffmpeg could not render the replacement clip")

    slots = {s.rel_path: s for s in scan_video_slots(
        str(tmp_path), roots=[str(tmp_path / "clips")], exts=(".webm",))}
    rel = "clips/attract.webm"
    staged, failures = stage_replacements({rel: slots[rel]}, {rel: rep})
    assert staged == 1 and failures == []
    after = detect_video_info(slot)
    assert after is not None and after.vcodec == "vp8"
    assert after.width == 160 and after.height == 120


def test_stage_copies_through_when_already_matching(tmp_path):
    # A replacement that already matches the slot's container/codec/resolution/
    # fps is copied through verbatim — no re-encode, so the staged bytes equal
    # the source bytes exactly (a re-encode would differ).
    from pinball_decryptor.core.video import find_ffmpeg, find_ffprobe
    if not (find_ffmpeg() and find_ffprobe()):
        pytest.skip("ffmpeg/ffprobe not available")

    slot = str(tmp_path / "clips" / "intro.mp4")
    if not _make_testsrc(slot, seconds=1.0, width=160, height=120, fps=10,
                         ext="mp4"):
        pytest.skip("ffmpeg could not render the test clip")
    rep = str(tmp_path / "src" / "rep.mp4")
    if not _make_testsrc(rep, seconds=1.0, width=160, height=120, fps=10,
                         ext="mp4"):
        pytest.skip("ffmpeg could not render the replacement clip")

    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path),
                                                     roots=[str(tmp_path / "clips")],
                                                     exts=(".mp4",))}
    rel = "clips/intro.mp4"
    with open(rep, "rb") as fh:
        rep_bytes = fh.read()

    staged, failures = stage_replacements({rel: slots[rel]}, {rel: rep})
    assert staged == 1 and failures == []
    with open(slot, "rb") as fh:
        assert fh.read() == rep_bytes  # copied through, not re-encoded


def _ftyp(brand):
    """Minimal ISO-BMFF head carrying *brand* (enough for isobmff_brand)."""
    return b"\x00\x00\x00\x14ftyp" + brand + b"\x00" * 8


def _slot_with(tmp_path, name, brand, **info_kw):
    """A VideoSlot over a stub file with *brand*, described by *info_kw*."""
    from pinball_decryptor.core.video import VideoInfo
    path = tmp_path / name
    path.write_bytes(_ftyp(brand))
    kw = dict(vcodec="h264", width=160, height=120, fps=10.0,
              pix_fmt="yuv420p", profile="Main")
    kw.update(info_kw)
    return VideoSlot(rel_path=name, abs_path=str(path),
                     ext=os.path.splitext(name)[1],
                     info=VideoInfo(str(path), **kw), size=1)


def _probe_as(monkeypatch, **info_kw):
    from pinball_decryptor.core.video import VideoInfo
    kw = dict(vcodec="h264", width=160, height=120, fps=10.0,
              pix_fmt="yuv420p", profile="Main")
    kw.update(info_kw)
    monkeypatch.setattr("pinball_decryptor.core.video_slots.detect_video_info",
                        lambda p: VideoInfo(p, **kw))


def test_copy_through_refuses_a_ten_bit_lookalike(tmp_path, monkeypatch):
    # Same container, codec, size and frame rate — but 10-bit, which the
    # machine's decoder can't do.  Copying it through with conversion ON is
    # how an unplayable clip reached the card with nothing in the log to say
    # so; it has to be re-encoded instead.
    from pinball_decryptor.core import video_slots as vs
    slot = _slot_with(tmp_path, "intro.mp4", b"isom")
    rep = tmp_path / "rep.mp4"
    rep.write_bytes(_ftyp(b"isom"))
    _probe_as(monkeypatch, pix_fmt="yuv420p10le")
    assert vs._already_matches(slot, str(rep), ".mp4") is False
    assert vs._remuxable(slot, str(rep)) is False      # a re-encode, not a remux


def test_copy_through_refuses_a_profile_above_the_slots(tmp_path, monkeypatch):
    from pinball_decryptor.core import video_slots as vs
    slot = _slot_with(tmp_path, "intro.mp4", b"isom", profile="Main")
    rep = tmp_path / "rep.mp4"
    rep.write_bytes(_ftyp(b"isom"))
    _probe_as(monkeypatch, profile="High")
    assert vs._already_matches(slot, str(rep), ".mp4") is False
    _probe_as(monkeypatch, profile="Baseline")         # below the ceiling: fine
    assert vs._already_matches(slot, str(rep), ".mp4") is True


def test_matching_extension_is_not_a_matching_container(tmp_path, monkeypatch):
    # A ".mov" some encoder wrote with an MP4 brand is a different wrapper than
    # the QuickTime one the card uses — repackage it, don't copy it through.
    from pinball_decryptor.core import video_slots as vs
    slot = _slot_with(tmp_path, "intro.mov", b"qt  ")
    rep = tmp_path / "rep.mov"
    rep.write_bytes(_ftyp(b"isom"))
    _probe_as(monkeypatch)
    assert vs._already_matches(slot, str(rep), ".mov") is False
    assert vs._remuxable(slot, str(rep)) is True


def test_stage_repackages_a_wrong_container_without_re_encoding(tmp_path):
    # A tester's case: an .mp4 encoded to the slot's codec/resolution/frame rate for
    # a QuickTime slot.  Only the wrapper is wrong, so the staged copy must be
    # a stream copy — the coded frames come out bit-for-bit identical.
    from pinball_decryptor.core.video import find_ffmpeg, find_ffprobe
    if not (find_ffmpeg() and find_ffprobe()):
        pytest.skip("ffmpeg/ffprobe not available")

    slot = str(tmp_path / "clips" / "intro.mov")
    if not _make_testsrc(slot, seconds=1.0, width=160, height=120, fps=10,
                         ext="mov"):
        pytest.skip("ffmpeg could not render the test clip")
    rep = str(tmp_path / "src" / "rep.mp4")
    if not _make_testsrc(rep, seconds=1.0, width=160, height=120, fps=10,
                         ext="mp4"):
        pytest.skip("ffmpeg could not render the replacement clip")

    slots = {s.rel_path: s for s in scan_video_slots(
        str(tmp_path), roots=[str(tmp_path / "clips")], exts=(".mov",))}
    rel = "clips/intro.mov"
    staged, failures = stage_replacements({rel: slots[rel]}, {rel: rep})
    assert staged == 1 and failures == []

    from pinball_decryptor.core.video import isobmff_brand
    assert isobmff_brand(slot) == b"qt  "        # rewrapped for the slot

    def _elementary(path, out):
        subprocess.run([find_ffmpeg(), "-y", "-i", path, "-c", "copy",
                        "-bsf:v", "h264_mp4toannexb", "-f", "h264", out],
                       capture_output=True)
        with open(out, "rb") as fh:
            return fh.read()

    assert _elementary(slot, str(tmp_path / "a.h264")) == \
        _elementary(rep, str(tmp_path / "b.h264"))   # not re-encoded


def test_stage_reencodes_when_resolution_differs(tmp_path):
    # The negative of the copy-through case: a same-container clip whose
    # resolution differs is still re-encoded (bytes change, dims match slot).
    from pinball_decryptor.core.video import (detect_video_info, find_ffmpeg,
                                              find_ffprobe)
    if not (find_ffmpeg() and find_ffprobe()):
        pytest.skip("ffmpeg/ffprobe not available")

    slot = str(tmp_path / "clips" / "intro.mp4")
    if not _make_testsrc(slot, seconds=1.0, width=160, height=120, fps=10,
                         ext="mp4"):
        pytest.skip("ffmpeg could not render the test clip")
    rep = str(tmp_path / "src" / "rep.mp4")
    if not _make_testsrc(rep, seconds=1.0, width=320, height=240, fps=10,
                         ext="mp4"):
        pytest.skip("ffmpeg could not render the replacement clip")

    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path),
                                                     roots=[str(tmp_path / "clips")],
                                                     exts=(".mp4",))}
    rel = "clips/intro.mp4"
    with open(rep, "rb") as fh:
        rep_bytes = fh.read()

    staged, failures = stage_replacements({rel: slots[rel]}, {rel: rep})
    assert staged == 1 and failures == []
    with open(slot, "rb") as fh:
        assert fh.read() != rep_bytes  # re-encoded (not copied through)
    after = detect_video_info(slot)
    assert after is not None and after.width == 160 and after.height == 120


def test_no_conversion_copies_through_same_container(tmp_path):
    # "No conversion" copies the file in verbatim (no re-encode) even when the
    # resolution differs from the slot — the user vouches it's game-ready, and
    # it shouldn't even need ffprobe.
    from pinball_decryptor.core.video import find_ffmpeg
    if not find_ffmpeg():
        pytest.skip("ffmpeg not available")
    slot = str(tmp_path / "clips" / "intro.mp4")
    if not _make_testsrc(slot, width=160, height=120, ext="mp4"):
        pytest.skip("ffmpeg could not render the test clip")
    rep = str(tmp_path / "src" / "rep.mp4")
    if not _make_testsrc(rep, width=320, height=240, ext="mp4"):
        pytest.skip("ffmpeg could not render the replacement clip")
    slots = {s.rel_path: s for s in scan_video_slots(
        str(tmp_path), roots=[str(tmp_path / "clips")], exts=(".mp4",),
        probe=False)}
    rel = "clips/intro.mp4"
    with open(rep, "rb") as fh:
        rep_bytes = fh.read()
    staged, failures = stage_replacements({rel: slots[rel]}, {rel: rep},
                                          no_conversion=True)
    assert staged == 1 and failures == []
    with open(slot, "rb") as fh:
        assert fh.read() == rep_bytes  # verbatim, despite the size mismatch


def test_no_conversion_rejects_different_container(tmp_path):
    # A different container can't be copied through as-is — clear failure.
    from pinball_decryptor.core.video_slots import stage_replacement
    (tmp_path / "intro.mp4").write_bytes(b"\x00")
    (tmp_path / "rep.webm").write_bytes(b"\x00")
    slot = VideoSlot(rel_path="intro.mp4", abs_path=str(tmp_path / "intro.mp4"),
                     ext=".mp4", info=None, size=1)
    ok, detail = stage_replacement(slot, str(tmp_path / "rep.webm"),
                                   no_conversion=True)
    assert ok is False
    assert ".mp4" in detail and "no conversion" in detail.lower()


def test_stage_reports_failure_for_missing_replacement(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"\x00")
    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path))}
    staged, failures = stage_replacements(
        slots, {"a.mp4": str(tmp_path / "nope.mp4")})
    assert staged == 0
    assert failures and failures[0][0] == "a.mp4"


# ---- container sniffing + H.264 profile matching --------------------------

def test_isobmff_brand_reads_the_major_brand(tmp_path):
    from pinball_decryptor.core.video import isobmff_brand
    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes((20).to_bytes(4, "big") + b"ftypisom" + b"\x00" * 8)
    mov = tmp_path / "a.mov"
    mov.write_bytes((20).to_bytes(4, "big") + b"ftypqt  " + b"\x00" * 8)
    mkv = tmp_path / "a.mkv"
    mkv.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 16)

    assert isobmff_brand(str(mp4)) == b"isom"
    assert isobmff_brand(str(mov)) == b"qt  "
    assert isobmff_brand(str(mkv)) is None          # not ISO-BMFF at all
    assert isobmff_brand(str(tmp_path / "gone.mp4")) is None


def test_h264_profile_args_match_the_slots_own_stream():
    from pinball_decryptor.core.video import VideoInfo, _h264_profile_args

    def info(profile, level=31, vcodec="h264"):
        return VideoInfo(path="x", vcodec=vcodec, width=1280, height=720,
                         profile=profile, level=level)

    # The stock clip proves what the machine's decoder accepts, so match it.
    assert _h264_profile_args(info("Constrained Baseline"), True) == \
        ["-profile:v", "baseline", "-level", "3.1"]
    assert _h264_profile_args(info("Main"), True) == \
        ["-profile:v", "main", "-level", "3.1"]
    # Level is a statement about resolution, so it's only pinned when the
    # output keeps the slot's dimensions.
    assert _h264_profile_args(info("High"), False) == ["-profile:v", "high"]
    # Nothing sensible to copy -> leave x264 on its own default.
    assert _h264_profile_args(info("High 4:2:2"), True) == []
    assert _h264_profile_args(info("Main", vcodec="vp9"), True) == []
    assert _h264_profile_args(None, True) == []


def test_banner_parse_picks_up_the_profile():
    from pinball_decryptor.core.video import parse_video_banner
    banner = (
        "  Duration: 00:00:04.00, start: 0.000000, bitrate: 500 kb/s\n"
        "  Stream #0:0[0x1](und): Video: h264 (Constrained Baseline) "
        "(avc1 / 0x31637661), yuv420p(tv, bt709), 1280x720 [SAR 1:1 DAR 16:9],"
        " 480 kb/s, 30 fps, 30 tbr, 15360 tbn\n")
    info = parse_video_banner(banner, "x.mp4")
    assert info.vcodec == "h264"
    assert info.profile == "Constrained Baseline"
    assert (info.width, info.height) == (1280, 720)


def test_transcode_strips_audio_for_a_silent_slot(monkeypatch, tmp_path):
    """Spike 2 clips are nearly all silent and the game plays its own sound,
    so a converted replacement must not smuggle its source's soundtrack onto
    the card (feedback batch 23)."""
    from pinball_decryptor.core import video as _video
    seen = {}

    def _fake_run(cmd, limit, cancel_cb=None):
        seen["cmd"] = list(cmd)
        return 0, "", None
    monkeypatch.setattr(_video, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(_video, "_run_ffmpeg_watched", _fake_run)
    monkeypatch.setattr(_video, "probe_duration", lambda _p: 5.0)
    dst = tmp_path / "out.mov"
    dst.write_bytes(b"x")                    # the success check stats the file
    info = _video.VideoInfo(path="slot.mov", vcodec="h264", width=1360,
                            height=768, fps=30.0, duration=5.0,
                            has_audio=False, pix_fmt="yuv420p")
    _video.transcode_video_to(str(tmp_path / "src.mov"), str(dst), info)
    assert "-an" in seen["cmd"]
    assert "-c:a" not in seen["cmd"]


def test_transcode_keeps_audio_when_the_slot_has_it(monkeypatch, tmp_path):
    """Deadpool 1.14 LE really does carry audio on 7 of its 99 clips, so this
    is matched per slot rather than stripped as a blanket rule."""
    from pinball_decryptor.core import video as _video
    seen = {}

    def _fake_run(cmd, limit, cancel_cb=None):
        seen["cmd"] = list(cmd)
        return 0, "", None
    monkeypatch.setattr(_video, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(_video, "_run_ffmpeg_watched", _fake_run)
    monkeypatch.setattr(_video, "probe_duration", lambda _p: 5.0)
    dst = tmp_path / "out.mov"
    dst.write_bytes(b"x")
    info = _video.VideoInfo(path="slot.mov", vcodec="h264", width=1360,
                            height=768, fps=30.0, duration=5.0,
                            has_audio=True, pix_fmt="yuv420p")
    _video.transcode_video_to(str(tmp_path / "src.mov"), str(dst), info)
    assert "-an" not in seen["cmd"]
    assert "-c:a" in seen["cmd"]


# ---- exact-size padding (core/video) -------------------------------------
#
# Cards that hold every asset at a fixed byte length (Stern's in-place SD
# patch; JJP scheme 3, whose lengths live in a dongle-encrypted fl.dat) need a
# replacement to land on the slot's size to the byte.  That costs nothing,
# because both containers carry an element that exists to be ignored: an EBML
# Void for Matroska/WebM, a `free` box for MP4/QuickTime.
# -------------------------------------------------------------------------

def test_void_element_is_exactly_the_size_asked_for():
    from pinball_decryptor.core.video import _ebml_void
    for total in [2, 3, 8, 127, 128, 129, 130, 16383, 16384, 1097296]:
        void = _ebml_void(total)
        assert void is not None and len(void) == total, total
        assert void[0] == 0xEC                      # the Void element ID
    # 0 needs no element and 1 has no legal encoding (ID + size won't fit).
    assert _ebml_void(1) is None


def test_padding_a_webm_hits_the_target_and_keeps_every_frame(tmp_path):
    """The whole point: a clip fitted to a fixed slot must decode to the
    identical picture, or 'it fits' has bought a black screen."""
    from pinball_decryptor.core.video import find_ffmpeg, pad_video_to_size
    ffmpeg = find_ffmpeg()
    src = str(tmp_path / "a.webm")
    if not (ffmpeg and _make_testsrc(src, seconds=1.0, ext="webm")):
        pytest.skip("ffmpeg/libvpx not available")
    with open(src, "rb") as fh:
        clip = fh.read()

    def raw(data):
        p = tmp_path / "probe.webm"
        p.write_bytes(data)
        r = subprocess.run([ffmpeg, "-v", "error", "-i", str(p), "-f",
                            "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True)
        return r.stdout if r.returncode == 0 else None

    before = raw(clip)
    assert before, "the fixture itself must decode"
    for pad in (0, 2, 3, 8, 129, 5000, 1097296):
        out = pad_video_to_size(clip, len(clip) + pad)
        assert out is not None and len(out) == len(clip) + pad, pad
        assert raw(out) == before, f"padding by {pad} changed the picture"


def test_padding_an_mp4_hits_the_target_and_keeps_every_frame(tmp_path):
    from pinball_decryptor.core.video import find_ffmpeg, pad_video_to_size
    ffmpeg = find_ffmpeg()
    src = str(tmp_path / "a.mp4")
    if not (ffmpeg and _make_testsrc(src, seconds=1.0, ext="mp4")):
        pytest.skip("ffmpeg not available")
    with open(src, "rb") as fh:
        clip = fh.read()

    def raw(data):
        p = tmp_path / "probe.mp4"
        p.write_bytes(data)
        r = subprocess.run([ffmpeg, "-v", "error", "-i", str(p), "-f",
                            "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True)
        return r.stdout if r.returncode == 0 else None

    before = raw(clip)
    assert before
    for pad in (0, 1, 7, 8, 4096):
        out = pad_video_to_size(clip, len(clip) + pad)
        assert out is not None and len(out) == len(clip) + pad, pad
        assert raw(out) == before, f"padding by {pad} changed the picture"


def test_padding_refuses_what_it_cannot_pad():
    from pinball_decryptor.core.video import pad_video_to_size
    assert pad_video_to_size(b"\x1a\x45\xdf\xa3" + b"\x00" * 40, 500) is None
    assert pad_video_to_size(b"not a video at all", 500) is None
    # already bigger than the slot is the caller's problem, not a silent crop
    assert pad_video_to_size(b"\x00" * 100, 50) is None


def test_the_shrink_budget_follows_the_clip_being_encoded(monkeypatch,
                                                          tmp_path):
    """original_info is a FORMAT template: a caller may pass the SLOT's own
    clip to pin resolution / frame rate / codec.  Reading the duration off it
    budgets the bitrate by the wrong clip's length, so a replacement longer
    than the slot's original is encoded several times over its byte budget and
    overshoots on every retry (PAD-28: a 9s clip budgeted as a 3s one)."""
    from pinball_decryptor.core import video as V
    from pinball_decryptor.core.video import VideoInfo

    seen = []

    def fake_run(cmd, limit, cancel_cb=None):
        seen.append(cmd)
        with open(cmd[-1], "wb") as fh:
            fh.write(b"x")
        return 0, b"", None

    monkeypatch.setattr(V, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(V, "_run_ffmpeg_watched", fake_run)
    monkeypatch.setattr(V, "probe_duration", lambda p: 9.0)   # the SOURCE

    src = tmp_path / "replacement.webm"
    src.write_bytes(b"x" * 10)
    slot = VideoInfo(path="slot.webm", vcodec="vp8", width=320, height=240,
                     fps=30.0, duration=3.0)                  # the TEMPLATE

    ok, _ = V.shrink_video_to_size(str(src), str(tmp_path / "out.webm"),
                                   90_000, original_info=slot)
    assert ok
    rate = int(seen[0][seen[0].index("-b:v") + 1])
    # 90000 bytes over 9 seconds, with the module's 0.92 first-pass headroom.
    assert rate == int(90_000 * 8 * 0.92 / 9), (
        "bitrate was budgeted from the template's 3s, not the clip's 9s")


# --------------------------------------------------------------------------
# A pinned slot's byte budget belongs to the STAGING encode (PAD-29)
#
# Staging re-encoded a clip to the slot's shape with no idea of its byte
# budget, and the build then re-encoded whatever overshot down to the slot —
# two generations of loss for one replacement.  cooltoy's JJP Logo RIP came
# out of staging at 5,189,537 bytes for a 2,620,331-byte slot and was encoded
# a second time to get there.
# --------------------------------------------------------------------------

def _budget_cmd(monkeypatch, tmp_path, max_bytes, *, src_dur=10.0,
                slot_dur=20.0, size=b"x", has_audio=False):
    """Run transcode_video_to under a fake ffmpeg; return (ok, detail, cmds)."""
    from pinball_decryptor.core import video as V
    from pinball_decryptor.core.video import VideoInfo

    seen = []

    def fake_run(cmd, limit, cancel_cb=None):
        seen.append(list(cmd))
        with open(cmd[-1], "wb") as fh:
            fh.write(size)
        return 0, b"", None

    monkeypatch.setattr(V, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(V, "_run_ffmpeg_watched", fake_run)
    monkeypatch.setattr(V, "probe_duration", lambda p: src_dur)

    slot = VideoInfo(path="slot.webm", vcodec="vp8", width=320, height=240,
                     fps=30.0, duration=slot_dur, has_audio=has_audio)
    ok, detail = V.transcode_video_to(
        str(tmp_path / "in.mov"), str(tmp_path / "out.webm"), slot,
        match_length=True, max_bytes=max_bytes)
    return ok, detail, seen


def test_a_byte_budget_sets_the_rate_from_the_length_being_produced(
        monkeypatch, tmp_path):
    """The budget buys bitrate x the seconds actually encoded.

    With trim/pad on, that is the SLOT's length, not the source's — budgeting
    a 10s source that gets padded to a 20s slot as if it were 10s puts twice
    the bitrate in and overshoots exactly the way the un-budgeted encode did.
    """
    ok, detail, cmds = _budget_cmd(monkeypatch, tmp_path, 1_000_000,
                                   src_dur=10.0, slot_dur=20.0)
    assert ok and len(cmds) == 1
    cmd = cmds[0]
    rate = int(cmd[cmd.index("-b:v") + 1])
    assert rate == int(1_000_000 * 8 * 0.92 / 20.0)
    # capped, not just targeted — libvpx will drift over a bare -b:v
    assert cmd[cmd.index("-maxrate") + 1] == str(rate)
    assert "-crf" not in cmd, "a budget replaces the constant-quality guess"
    assert "fitted to the slot's 1000000 bytes" in detail


def test_without_a_budget_the_vpx_encode_is_unchanged(monkeypatch, tmp_path):
    """The no-budget path is every other manufacturer's staging encode and
    must keep the pinned constant-quality flags."""
    ok, detail, cmds = _budget_cmd(monkeypatch, tmp_path, None)
    assert ok and len(cmds) == 1
    cmd = cmds[0]
    assert cmd[cmd.index("-crf") + 1] == "32"
    assert cmd[cmd.index("-b:v") + 1] == "0"
    assert "-maxrate" not in cmd
    assert "fitted" not in detail


def test_a_clip_that_will_not_reach_the_budget_is_still_staged(monkeypatch,
                                                               tmp_path):
    """The budget is a quality optimisation, not a gate.

    libvpx overshoots a low -b:v on some material, and the build's own fit has
    always handled that.  Failing here instead would drop the user's clip for
    a reason that was never a correctness problem.
    """
    ok, detail, cmds = _budget_cmd(monkeypatch, tmp_path, 10,
                                   size=b"x" * 5000)
    assert ok, "an unreachable budget must not lose the replacement"
    assert len(cmds) == 3, "it should try the whole headroom ladder first"
    assert "the build will re-encode it to fit" in detail
    rates = [int(c[c.index("-b:v") + 1]) for c in cmds]
    assert rates == sorted(rates, reverse=True), "each retry aims lower"


def _budget_seen(monkeypatch, tmp_path, **kw):
    """Stage one assignment; return the byte_budget stage_replacement got."""
    from pinball_decryptor.core import video_slots as VS

    got = {}

    def fake_stage(slot, rep, trim_to_length=False, no_conversion=False,
                   cancel_cb=None, byte_budget=None):
        got["budget"] = byte_budget
        return True, ""

    monkeypatch.setattr(VS, "stage_replacement", fake_stage)
    (tmp_path / "clip.mp4").write_bytes(b"\x00" * 900)
    (tmp_path / "rep.mp4").write_bytes(b"\x00" * 10)
    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path),
                                                     probe=False)}
    VS.stage_replacements(slots, {"clip.mp4": str(tmp_path / "rep.mp4")},
                          assets_dir=str(tmp_path), **kw)
    return got.get("budget")


def test_the_budget_needs_the_length_to_be_matched_too(monkeypatch, tmp_path):
    """A clip free to run to its own length must NOT be squeezed into the
    slot's bytes: a 30-second replacement for a 3-second slot would be
    crushed.  The budget only means the slot's own bitrate when the duration
    is the slot's too."""
    assert _budget_seen(monkeypatch, tmp_path,
                        pin_byte_size=True, trim_to_length=True) == 900
    assert _budget_seen(monkeypatch, tmp_path,
                        pin_byte_size=True, trim_to_length=False) is None
    assert _budget_seen(monkeypatch, tmp_path,
                        pin_byte_size=False, trim_to_length=True) is None


def test_the_budget_is_the_pristine_original_not_the_last_replacement(
        monkeypatch, tmp_path):
    """Re-staging over an earlier replacement must budget against the slot the
    game actually has, or every pass ratchets the quality down against the
    previous pass's smaller file."""
    from pinball_decryptor.core import staged_originals

    (tmp_path / "clip.mp4").write_bytes(b"\x00" * 900)
    staged_originals.snapshot(str(tmp_path), "clip.mp4", None)
    # ...now the slot on disk is an earlier, much smaller replacement
    (tmp_path / "clip.mp4").write_bytes(b"\x00" * 120)

    assert _budget_seen(monkeypatch, tmp_path,
                        pin_byte_size=True, trim_to_length=True) == 900


def test_only_the_plugins_that_pin_a_slot_ask_for_a_budget():
    from pinball_decryptor.core.registry import Manufacturer
    from pinball_decryptor.plugins.jjp.manufacturer import JJPManufacturer

    assert Manufacturer.video_pins_byte_size(object()) is False
    assert JJPManufacturer().video_pins_byte_size(None) is True
