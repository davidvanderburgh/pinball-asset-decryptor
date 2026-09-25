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


def test_duration_str_keeps_sub_second_clips_off_zero():
    """Short clips are ordinary on a Spike 2 card -- 1007 of Batman's 6331
    slots are under a second, 463 of them under 0.2 s -- and m:ss printed
    every one of them "0:00", which a field report read as zero-length /
    empty slots.  Under a second the milliseconds show, the same m:ss.mmm
    the audio tab's Length column uses."""
    from pinball_decryptor.core.video import VideoInfo

    def mk(dur):
        return VideoSlot(rel_path="a.mp4", abs_path="a.mp4", ext=".mp4",
                         info=VideoInfo("a.mp4", duration=dur), size=0)

    assert mk(0.033333).duration_str() == "0:00.033"   # a one-frame still
    assert mk(0.875875).duration_str() == "0:00.875"
    assert mk(0.9999).duration_str() == "0:00.999"     # floors, never "0:01"
    # A second and up is untouched: floored m:ss, matching the player.
    assert mk(1.0).duration_str() == "0:01"
    assert mk(4.004).duration_str() == "0:04"
    assert mk(25.5).duration_str() == "0:25"
    # Only a clip whose length is genuinely unknown gets the dash.
    assert mk(0.0).duration_str() == "—"


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


def test_bof_surfaces_ogv_only_others_default(manufacturers_by_key):
    # BOF narrows to .ogv — Ogg Theora is the one video form it ships.  JJP
    # and Spooky use the default whole VIDEO_EXTS set (Spooky narrows by
    # FOLDER instead: an extension can't tell a shipped clip from a
    # derivative PAD generated — see test_spooky_video_slots.py); DP adds
    # .cdmd (covered in test_cdmd_replace).
    assert manufacturers_by_key["bof"].video_slot_exts("anything") == (".ogv",)
    assert manufacturers_by_key["jjp"].video_slot_exts("anything") is None
    assert manufacturers_by_key["spooky"].video_slot_exts("anything") is None


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


def test_stream_mismatch_names_the_one_property_that_differs(tmp_path,
                                                             monkeypatch):
    # A re-encode the log can't explain is a re-encode a tester has to guess
    # at ("I am wondering why its re-encoding..."), so the check that forces
    # one now hands back the property that decided it.
    from pinball_decryptor.core import video_slots as vs
    slot = _slot_with(tmp_path, "intro.mov", b"qt  ")
    rep = tmp_path / "rep.mp4"
    rep.write_bytes(_ftyp(b"isom"))

    def _why(**kw):
        _probe_as(monkeypatch, **kw)
        return vs._remux_verdict(slot, str(rep))[1]

    assert _why() is None                              # a drop-in: no reason
    assert _why(width=320, height=240) == \
        "it's 320x240 and this slot's clip is 160x120"
    assert _why(vcodec="hevc") == "it's HEVC and this slot's clip is H264"
    assert _why(fps=25.0) == "it runs at 25 fps and this slot's clip is 10 fps"
    assert _why(pix_fmt="yuv420p10le") == \
        "it's yuv420p10le and this slot's clip is yuv420p"
    assert _why(profile="High") == \
        "it's H.264 High profile and this slot's clip is Main"


def test_stream_mismatch_reports_an_unreadable_slot(tmp_path, monkeypatch):
    # No probe of the slot means no proof of a match — still a re-encode, but
    # say which side couldn't be read rather than nothing at all.
    from pinball_decryptor.core import video_slots as vs
    slot = _slot_with(tmp_path, "intro.mov", b"qt  ")
    slot.info = None
    rep = tmp_path / "rep.mp4"
    rep.write_bytes(_ftyp(b"isom"))
    _probe_as(monkeypatch)
    assert vs._remux_verdict(slot, str(rep))[1] == \
        "the app couldn't read this slot's own video settings"


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


def test_stage_logs_why_a_clip_had_to_be_re_encoded(tmp_path):
    # The ✓ line used to name only what the clip was converted TO, so a
    # transfer that re-encoded 228 videos read as the app converting files for
    # no stated reason.  Now the line says which property forced it.
    from pinball_decryptor.core.video import find_ffmpeg, find_ffprobe
    if not (find_ffmpeg() and find_ffprobe()):
        pytest.skip("ffmpeg/ffprobe not available")

    slot = str(tmp_path / "clips" / "intro.mov")
    if not _make_testsrc(slot, seconds=1.0, width=160, height=120, fps=10,
                         ext="mov"):
        pytest.skip("ffmpeg could not render the test clip")
    rep = str(tmp_path / "src" / "rep.mp4")
    if not _make_testsrc(rep, seconds=1.0, width=320, height=240, fps=10,
                         ext="mp4"):
        pytest.skip("ffmpeg could not render the replacement clip")

    slots = {s.rel_path: s for s in scan_video_slots(
        str(tmp_path), roots=[str(tmp_path / "clips")], exts=(".mov",))}
    rel = "clips/intro.mov"
    msgs = []
    staged, failures = stage_replacements(
        {rel: slots[rel]}, {rel: rep},
        log_cb=lambda t, l="info": msgs.append(t))
    assert staged == 1 and failures == []
    done = [m for m in msgs if m.lstrip().startswith("✓")]
    assert done and "re-encoded because" in done[0]
    assert "320x240" in done[0] and "160x120" in done[0]
    assert "→160x120" in done[0]        # and still what it converted TO


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
    # One attempt, which for libvpx is its analysis pass and then the encode.
    assert ok and len(cmds) == 2
    cmd = cmds[-1]
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
    assert "the build will re-encode it to fit" in detail
    rates = [int(c[c.index("-b:v") + 1]) for c in cmds]
    assert rates == sorted(rates, reverse=True), "each retry aims lower"


def test_the_ladder_stops_once_the_encoder_stops_responding(monkeypatch,
                                                            tmp_path):
    """A fake that returns the same size however low the rate goes is a real
    encoder at its quality floor (libvpx pinned at q=63 still emits what the
    picture costs).  Re-asking is a whole wasted encode, so the ladder gives
    up the moment an attempt comes back no smaller than the one before it."""
    ok, detail, cmds = _budget_cmd(monkeypatch, tmp_path, 10,
                                   size=b"x" * 5000)
    assert ok
    # Two attempts x (analysis pass + encode); the third rung is never run
    # because attempt 2 proved the rate is not reaching the encoder.
    assert len(cmds) == 4, "a third attempt could only land in the same place"


def test_a_retry_is_corrected_by_what_the_encoder_actually_produced(
        monkeypatch, tmp_path):
    """THE PAD-192 FIX.  The old ladder re-asked for a smaller slice of the
    budget and trusted the encoder to obey it; libvpx-vp9 overshoots ``-b:v``
    by ~1.6x in single pass, so 0.92 -> 0.80 -> 0.62 could not close a gap
    that needed 60% and all three attempts landed within a couple of per cent
    of each other (cooltoy's 2.17 MB clip "shrunk" to 2.14 MB for a 1.67 MB
    slot, three times running).

    Scaling the next rate by the size actually muxed makes the correction
    proportional to the encoder's real behaviour instead of a guess.
    """
    from pinball_decryptor.core import video as V

    # cooltoy's RTR_RANK_C, measured: a 1,674,054-byte slot, 9.2s, and a first
    # attempt that asked 1,339,243 bps and muxed 2,429,383 bytes.
    budget, dur = 1_674_054, 9.2
    first = int(budget * 8 * 0.92 / dur)
    assert first == 1_339_243

    blind = int(budget * 8 * 0.80 / dur)          # what the old ladder asked
    corrected = V._corrected_bitrate(first, 2_429_383, budget, 0.80)

    assert corrected < blind, "the retry must account for the overshoot"
    # The old rung barely moved (1.34 -> 1.16 Mbps) against an encoder running
    # 1.6x hot; the corrected rate aims where the measurement says 0.80 of the
    # budget actually lies.
    assert 700_000 < corrected < 780_000
    assert blind > 1_100_000


def test_x264_keeps_its_single_pass_encode(monkeypatch, tmp_path):
    """Only libvpx needs the analysis pass.  x264's single-pass VBR already
    tracks -b:v, so a budgeted H.264 slot must not pay a second encode."""
    from pinball_decryptor.core import video as V

    assert V._two_pass_wanted(["-c:v", "libvpx-vp9"]) is True
    assert V._two_pass_wanted(["-c:v", "libvpx"]) is True
    assert V._two_pass_wanted(["-c:v", "libx264"]) is False


def _budget_seen(monkeypatch, tmp_path, **kw):
    """Stage one assignment; return the byte_budget stage_replacement got."""
    from pinball_decryptor.core import video_slots as VS

    got = {}

    def fake_stage(slot, rep, trim_to_length=False, no_conversion=False,
                   cancel_cb=None, byte_budget=None, match_bitrate=None,
                   best_quality=False):
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


# --------------------------------------------------------------------------
# A conversion is held to the bitrate of the clip it replaces (PAD-171)
#
# With no byte budget the H.264 conversion ran at x264's default constant
# quality, which is a statement about the SOURCE: a user's 3.7 Mbps export
# for Godzilla's 7.6 Mbps magnagrab.mp4 came out at 967 kbps, under the
# blocky bar, and all 533 replaced clips on their card were conversions like it.
# --------------------------------------------------------------------------

def _match_cmd(monkeypatch, tmp_path, match_bitrate, *, max_bytes=None,
               codec="h264", ext=".mp4", has_audio=False, size=b"x" * 7500,
               width=1360, height=768, fps=30.0):
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
    monkeypatch.setattr(V, "probe_duration", lambda p: 5.0)

    slot = VideoInfo(path="slot" + ext, vcodec=codec, width=width,
                     height=height, fps=fps, duration=5.0,
                     has_audio=has_audio, profile="Main", level=32)
    ok, detail = V.transcode_video_to(
        str(tmp_path / "in.mov"), str(tmp_path / ("out" + ext)), slot,
        max_bytes=max_bytes, match_bitrate=match_bitrate)
    return ok, detail, seen


def test_an_h264_conversion_runs_at_the_replaced_clips_bitrate(monkeypatch,
                                                               tmp_path):
    ok, detail, cmds = _match_cmd(monkeypatch, tmp_path, 7_600_000)
    assert ok and len(cmds) == 1
    cmd = cmds[0]
    assert cmd[cmd.index("-b:v") + 1] == "7600000"
    # Capped, not just targeted: a bare -b:v overshot that clip by a quarter,
    # which is enough to miss the slot's bytes on a fit-in-place write.
    assert cmd[cmd.index("-maxrate") + 1] == "7600000"
    assert cmd[cmd.index("-bufsize") + 1] == "15200000"
    assert "-crf" not in cmd
    # The profile ceiling still rides along.
    assert cmd[cmd.index("-profile:v") + 1] == "main"
    # What came out, beside what the slot had: the two numbers they compared.
    assert "encoded at 12 kbps (the clip it replaces is 7.6 Mbps)" in detail


def test_the_audio_reserve_comes_out_of_the_matched_rate(monkeypatch,
                                                         tmp_path):
    _ok, _d, cmds = _match_cmd(monkeypatch, tmp_path, 7_600_000,
                               has_audio=True)
    cmd = cmds[0]
    assert cmd[cmd.index("-b:v") + 1] == str(7_600_000 - 96_000)


def test_a_lean_original_does_not_drag_the_conversion_under_the_bar(
        monkeypatch, tmp_path):
    """A project extracted from a card an older version built has one of those
    crushed conversions as its "original" -- matching it would repeat it."""
    from pinball_decryptor.core.video import CONVERT_FLOOR_BPP
    from pinball_decryptor.core.video_quality import BLOCKY_BPP

    _ok, detail, cmds = _match_cmd(monkeypatch, tmp_path, 820_000)
    rate = int(cmds[0][cmds[0].index("-b:v") + 1])
    assert rate == pytest.approx(CONVERT_FLOOR_BPP * 1360 * 768 * 30, abs=1)
    assert rate / (1360 * 768 * 30) > BLOCKY_BPP
    assert "(the clip it replaces is 820 kbps)" in detail


def test_a_budget_still_wins_over_the_matched_rate(monkeypatch, tmp_path):
    _ok, _d, cmds = _match_cmd(monkeypatch, tmp_path, 7_600_000,
                               max_bytes=1_000_000, size=b"x" * 10)
    cmd = cmds[0]
    assert cmd[cmd.index("-b:v") + 1] == str(int(1_000_000 * 8 * 0.92 / 5.0))


def test_other_codecs_keep_their_own_rate_control(monkeypatch, tmp_path):
    _ok, detail, cmds = _match_cmd(monkeypatch, tmp_path, 7_600_000,
                                   codec="vp8", ext=".webm")
    cmd = cmds[0]
    assert cmd[cmd.index("-crf") + 1] == "32"
    assert "encoded at" not in detail


def test_no_known_bitrate_keeps_the_old_encode(monkeypatch, tmp_path):
    _ok, detail, cmds = _match_cmd(monkeypatch, tmp_path, None)
    assert "-b:v" not in cmds[0] and "-maxrate" not in cmds[0]
    assert "encoded at" not in detail


def _rate_seen(monkeypatch, tmp_path, measured=7_600_000, **kw):
    """Stage one assignment; return (match_bitrate passed, paths measured)."""
    from pinball_decryptor.core import video_slots as VS

    got, measured_paths = {}, []

    def fake_stage(slot, rep, trim_to_length=False, no_conversion=False,
                   cancel_cb=None, byte_budget=None, match_bitrate=None,
                   best_quality=False):
        got["rate"] = match_bitrate
        return True, ""

    def fake_rate(path):
        measured_paths.append(path)
        return measured

    monkeypatch.setattr(VS, "stage_replacement", fake_stage)
    monkeypatch.setattr(VS, "_clip_bitrate", fake_rate)
    if not (tmp_path / "clip.mp4").exists():
        (tmp_path / "clip.mp4").write_bytes(b"\x00" * 900)
    (tmp_path / "rep.mp4").write_bytes(b"\x00" * 10)
    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path),
                                                     probe=False)}
    VS.stage_replacements(slots, {"clip.mp4": str(tmp_path / "rep.mp4")},
                          assets_dir=str(tmp_path), **kw)
    return got.get("rate"), measured_paths


def test_staging_hands_the_pristine_clips_bitrate_to_the_encoder(
        monkeypatch, tmp_path):
    """Measured off the .orig snapshot, not the slot on disk: re-staging over
    an earlier (crushed) replacement must not match THAT one's bitrate."""
    from pinball_decryptor.core import staged_originals

    (tmp_path / "clip.mp4").write_bytes(b"\x00" * 900)
    staged_originals.snapshot(str(tmp_path), "clip.mp4", None)
    (tmp_path / "clip.mp4").write_bytes(b"\x00" * 120)

    rate, paths = _rate_seen(monkeypatch, tmp_path)
    assert rate == 7_600_000
    assert paths == [staged_originals.snapshot_path(str(tmp_path),
                                                    "clip.mp4")]


def test_a_pinned_slot_keeps_its_old_encode(monkeypatch, tmp_path):
    """JJP holds a clip to its slot's bytes; there the budget (with the length
    matched) or the old encode decides, and the build fits what overshoots."""
    for trim in (True, False):
        rate, paths = _rate_seen(monkeypatch, tmp_path, pin_byte_size=True,
                                 trim_to_length=trim)
        assert rate is None and paths == []


def test_clip_bitrate_reads_a_real_clip_and_refuses_anything_else(tmp_path):
    from pinball_decryptor.core.video_slots import _clip_bitrate

    clip = str(tmp_path / "c.mp4")
    if not _make_testsrc(clip, seconds=2.0):
        pytest.skip("ffmpeg not available")
    rate = _clip_bitrate(clip)
    assert rate == pytest.approx(os.path.getsize(clip) * 8 / 2.0, rel=0.05)
    (tmp_path / "junk.mp4").write_bytes(b"not a clip at all")
    assert _clip_bitrate(str(tmp_path / "junk.mp4")) is None
    assert _clip_bitrate(str(tmp_path / "missing.mp4")) is None


def test_a_real_conversion_lands_near_the_slots_bitrate(tmp_path):
    """End to end through ffmpeg: a replacement that has to be converted (a
    different size) comes out near the slot clip's bitrate, not at whatever
    the encoder's default quality makes of the source."""
    from pinball_decryptor.core.video import find_ffmpeg
    from pinball_decryptor.core.video_quality import quality_of_file

    rep = str(tmp_path / "rep.mp4")
    if not _make_testsrc(rep, seconds=2.0, width=320, height=240, fps=10):
        pytest.skip("ffmpeg not available")
    # A slot clip encoded rich, the way Stern's are.
    proj = tmp_path / "proj"
    proj.mkdir()
    slot_path = str(proj / "clip.mp4")
    r = subprocess.run([find_ffmpeg(), "-y", "-f", "lavfi", "-i",
                        "testsrc=size=160x120:rate=10:duration=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-b:v", "600k", "-maxrate", "600k",
                        "-bufsize", "1200k", slot_path],
                       capture_output=True)
    assert r.returncode == 0
    slot_rate = quality_of_file(slot_path).bitrate
    slots = {s.rel_path: s for s in scan_video_slots(str(proj))}
    staged, failures = stage_replacements(slots, {"clip.mp4": rep},
                                          assets_dir=str(proj))
    assert staged == 1 and not failures
    out_rate = quality_of_file(slot_path).bitrate
    assert out_rate > 0.6 * slot_rate, (out_rate, slot_rate)


# --------------------------------------------------------------------------
# "Best quality": a conversion at constant quality instead of the replaced
# clip's bitrate, for a card built with room for it.
# --------------------------------------------------------------------------

def _best_cmd(monkeypatch, tmp_path, *, max_bytes=None, codec="h264",
              ext=".mp4", width=1360, height=768, fps=30.0,
              size=6_000_000):
    from pinball_decryptor.core import video as V
    from pinball_decryptor.core.video import VideoInfo

    seen = []

    def fake_run(cmd, limit, cancel_cb=None):
        seen.append(list(cmd))
        with open(cmd[-1], "wb") as fh:
            fh.write(b"x" * size)
        return 0, b"", None

    monkeypatch.setattr(V, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(V, "_run_ffmpeg_watched", fake_run)
    monkeypatch.setattr(V, "probe_duration", lambda p: 5.0)
    slot = VideoInfo(path="slot" + ext, vcodec=codec, width=width,
                     height=height, fps=fps, duration=5.0, has_audio=False,
                     profile="Main", level=32)
    ok, detail = V.transcode_video_to(
        str(tmp_path / "in.mov"), str(tmp_path / ("out" + ext)), slot,
        max_bytes=max_bytes, match_bitrate=7_600_000, best_quality=True)
    return ok, detail, seen


def test_best_quality_encodes_at_constant_quality_under_a_peak(monkeypatch,
                                                               tmp_path):
    from pinball_decryptor.core.video import BEST_CRF, BEST_MAX_BPS

    ok, detail, cmds = _best_cmd(monkeypatch, tmp_path)   # 9.6 Mbps out
    assert len(cmds) == 1
    cmd = cmds[0]
    assert ok and cmd[cmd.index("-crf") + 1] == str(BEST_CRF)
    assert "-b:v" not in cmd                  # not held to the stock rate
    assert int(cmd[cmd.index("-maxrate") + 1]) == BEST_MAX_BPS
    assert cmd[cmd.index("-profile:v") + 1] == "main"    # ceiling kept
    assert "flags=lanczos" in cmd[cmd.index("-vf") + 1]
    assert detail.endswith("best quality, 9.6 Mbps")


def test_best_quality_is_never_fewer_bits_than_a_normal_build(monkeypatch,
                                                             tmp_path):
    """A simple picture comes in under the replaced clip's 7.6 Mbps at
    constant quality; it is encoded again at that rate, so best quality is
    the normal rate or more, never less."""
    ok, detail, cmds = _best_cmd(monkeypatch, tmp_path, size=1_000_000)
    assert ok and len(cmds) == 2
    assert "-crf" in cmds[0] and "-crf" not in cmds[1]
    assert cmds[1][cmds[1].index("-b:v") + 1] == "7600000"
    assert "held up to the clip it replaces" in detail


def test_best_quality_peak_scales_with_a_small_slot(monkeypatch, tmp_path):
    from pinball_decryptor.core.video import BEST_MAX_BPP

    _ok, _d, cmds = _best_cmd(monkeypatch, tmp_path, width=520, height=294)
    peak = int(cmds[0][cmds[0].index("-maxrate") + 1])
    assert peak == int(BEST_MAX_BPP * 520 * 294 * 30)


def test_a_pinned_budget_still_wins_over_best_quality(monkeypatch, tmp_path):
    _ok, _d, cmds = _best_cmd(monkeypatch, tmp_path, max_bytes=1_000_000)
    cmd = cmds[0]
    assert "-crf" not in cmd
    assert cmd[cmd.index("-b:v") + 1] == str(int(1_000_000 * 8 * 0.92 / 5.0))


def test_staging_hands_best_quality_down_with_the_stock_rate_as_floor(
        monkeypatch, tmp_path):
    from pinball_decryptor.core import video_slots as VS

    got, measured = {}, []

    def fake_stage(slot, rep, trim_to_length=False, no_conversion=False,
                   cancel_cb=None, byte_budget=None, match_bitrate=None,
                   best_quality=False):
        got.update(best=best_quality, rate=match_bitrate)
        return True, ""

    monkeypatch.setattr(VS, "stage_replacement", fake_stage)
    monkeypatch.setattr(VS, "_clip_bitrate",
                        lambda p: measured.append(p) or 7_600_000)
    (tmp_path / "clip.mp4").write_bytes(b"\x00" * 900)
    (tmp_path / "rep.mp4").write_bytes(b"\x00" * 10)
    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path),
                                                     probe=False)}
    VS.stage_replacements(slots, {"clip.mp4": str(tmp_path / "rep.mp4")},
                          assets_dir=str(tmp_path), best_quality=True)
    # the stock clip's rate still rides along: it is best quality's floor
    assert got == {"best": True, "rate": 7_600_000} and len(measured) == 1


# --------------------------------------------------------------------------
# A Write that changes nothing about a clip doesn't convert it again.
# --------------------------------------------------------------------------

def _count_stagings(monkeypatch):
    from pinball_decryptor.core import video_slots as VS

    calls = []

    def fake_stage(slot, rep, trim_to_length=False, no_conversion=False,
                   cancel_cb=None, byte_budget=None, match_bitrate=None,
                   best_quality=False):
        calls.append((slot.rel_path, best_quality))
        with open(slot.abs_path, "wb") as fh:          # what a conversion does
            fh.write(b"converted" + os.urandom(8))
        return True, ""

    monkeypatch.setattr(VS, "stage_replacement", fake_stage)
    monkeypatch.setattr(VS, "_clip_bitrate", lambda p: 7_600_000)
    return calls


def _stage_once(tmp_path, **kw):
    slots = {s.rel_path: s for s in scan_video_slots(str(tmp_path),
                                                     probe=False)}
    return stage_replacements(slots, {"clip.mp4": str(tmp_path / "src"
                                                      / "rep.mp4")},
                              assets_dir=str(tmp_path), **kw)


def _project(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"\x00" * 900)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rep.mp4").write_bytes(b"\x01" * 10)


def test_a_second_write_keeps_the_clip_it_already_converted(monkeypatch,
                                                            tmp_path):
    calls = _count_stagings(monkeypatch)
    _project(tmp_path)
    assert _stage_once(tmp_path) == (1, [])
    assert _stage_once(tmp_path) == (1, [])            # counted as staged
    assert len(calls) == 1


def test_a_changed_option_source_or_slot_file_converts_again(monkeypatch,
                                                             tmp_path):
    calls = _count_stagings(monkeypatch)
    _project(tmp_path)
    _stage_once(tmp_path)
    _stage_once(tmp_path, best_quality=True)            # option changed
    assert len(calls) == 2
    (tmp_path / "src" / "rep.mp4").write_bytes(b"\x02" * 12)  # new source
    _stage_once(tmp_path, best_quality=True)
    assert len(calls) == 3
    (tmp_path / "clip.mp4").write_bytes(b"\x00" * 900)  # a revert put stock back
    _stage_once(tmp_path, best_quality=True)
    assert len(calls) == 4
    _stage_once(tmp_path, best_quality=True)
    assert len(calls) == 4


def test_a_failed_conversion_is_not_remembered(monkeypatch, tmp_path):
    from pinball_decryptor.core import video_slots as VS

    _project(tmp_path)
    outcome = [False]

    def fake_stage(slot, rep, **kw):
        return (outcome[0], "" if outcome[0] else "ffmpeg said no")

    monkeypatch.setattr(VS, "stage_replacement", fake_stage)
    monkeypatch.setattr(VS, "_clip_bitrate", lambda p: None)
    assert _stage_once(tmp_path)[0] == 0
    cache = VS.StagedCache(str(tmp_path))
    assert "clip.mp4" not in cache.entries


def test_trim_on_a_later_build_matches_the_stock_length(tmp_path):
    # PAD-215: a 14 s replacement for a 6 s slot, staged once untrimmed, then
    # built with "Trim / pad" ticked, went on at 14 s: the rescan probed the
    # slot's file -- the replacement itself -- so it was trimmed to its own
    # length.  The .orig/ snapshot of the stock clip is the target.
    from pinball_decryptor.core.checksums import generate_checksums
    from pinball_decryptor.core.video import (detect_video_info, find_ffmpeg,
                                              find_ffprobe)
    if not (find_ffmpeg() and find_ffprobe()):
        pytest.skip("ffmpeg/ffprobe not available")

    assets = str(tmp_path / "assets")
    slot = os.path.join(assets, "video", "intro.mov")
    if not _make_testsrc(slot, seconds=1.0, ext="mov"):
        pytest.skip("ffmpeg could not render the test clip")
    generate_checksums(assets)
    rep = str(tmp_path / "replacement.mp4")
    if not _make_testsrc(rep, seconds=3.0, width=320, height=240):
        pytest.skip("ffmpeg could not render the replacement clip")
    rel = "video/intro.mov"

    slots = {s.rel_path: s for s in scan_video_slots(assets)}
    stage_replacements({rel: slots[rel]}, {rel: rep}, assets_dir=assets)
    slots = {s.rel_path: s for s in scan_video_slots(assets)}
    assert slots[rel].duration > 2.5               # the rescan sees the 3 s

    logs = []
    staged, failures = stage_replacements(
        {rel: slots[rel]}, {rel: rep}, trim_to_length=True, assets_dir=assets,
        log_cb=lambda t, l="info": logs.append(t))
    assert staged == 1 and failures == []
    assert any("trim 3.0s→1.0s" in t for t in logs)
    assert detect_video_info(slot).duration < 1.3
