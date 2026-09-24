"""core.source_match: finding the file a replaced clip was made from, by what
it looks like.

Most of these drive the matcher with made-up fingerprints (``fingerprint`` is
swapped for a table), so they run without ffmpeg and say exactly which rule
they pin.  The last few decode real clips ffmpeg makes on the spot.
"""

import os
import shutil
import subprocess

import numpy as np
import pytest

from pinball_decryptor.core import source_match as sm

H, W = sm.THUMB_H, sm.THUMB_W


def _frames(seed, n, color=True):
    """*n* thumbnails of a smooth moving scene, different per *seed*."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (4, 6, 3)).astype(np.float32)
    out = []
    for i in range(n):
        img = np.kron(np.roll(base, i, axis=1), np.ones((H // 4 + 1, W // 6 + 1, 1)))
        img = img[:H, :W]
        if not color:
            y = img @ sm._LUMA
            img = np.repeat(y[..., None], 3, axis=2)
        out.append(img)
    return np.clip(np.array(out), 0, 255).astype(np.uint8)


def _noisy(fp, amount=6, seed=0):
    """*fp* as a lossy re-encode would leave it: noise in brightness, where
    an encoder spends its bits and makes its errors (a thumbnail averages
    away what little colour noise there is)."""
    rng = np.random.default_rng(seed)
    luma = rng.integers(-amount, amount + 1, fp.shape[:-1] + (1,))
    return np.clip(fp.astype(np.int16) + luma, 0, 255).astype(np.uint8)


def _blend(a, b, w):
    return np.clip(a * (1 - w) + b * w, 0, 255).astype(np.uint8)


def _src(path, duration, width=1920, height=1080, size=None):
    return sm.SourceFile(path=path, size=size or int(duration * 1_000_000),
                         mtime_ns=1, duration=duration, width=width,
                         height=height, fps=30.0, codec="h264")


def _run(monkeypatch, clips, sources, table, clip_table):
    """find_sources with fingerprints from *table* (path -> array, or
    (path, fps) -> array for the frame-by-frame pass)."""
    def fake_fp(path, width=0, height=0, max_seconds=None, cancel=None,
                sample_fps=sm.SAMPLE_FPS):
        fp = table.get((path, sample_fps), table.get(path))
        if fp is None:
            return None
        if max_seconds:
            fp = fp[:max(1, int(round(max_seconds * sample_fps)))]
        return fp

    monkeypatch.setattr(sm, "fingerprint", fake_fp)

    def clip_fp(clip, sample_fps):
        return clip_table.get((clip.key, sample_fps), clip_table.get(clip.key))

    return sm.find_sources(clips, sources, clip_fp, cache=sm.FingerprintCache())


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def test_a_reencode_scores_near_one_and_other_footage_does_not():
    a = _frames(1, 20)
    assert sm.compare(a, a)[0] == pytest.approx(1.0)
    assert sm.compare(_noisy(a), a)[0] > 0.95
    assert sm.compare(_noisy(a), _frames(2, 20))[0] < 0.5


def test_brightness_and_contrast_drift_is_not_a_difference():
    """A range conversion (full to limited) rescales every level; the luma
    correlation must not care."""
    a = _frames(3, 20)
    squeezed = (16 + a.astype(np.float32) * 219 / 255).astype(np.uint8)
    assert sm.compare(squeezed, a)[0] > 0.97


def test_colour_and_black_and_white_twins_are_told_apart():
    """Godzilla ships every attract loop twice, in colour and _BW, and their
    luma is all but identical: only the chroma separates them."""
    colour, bw = _frames(4, 20), _frames(4, 20, color=False)
    card_bw = _noisy(bw)
    assert sm.compare(card_bw, bw)[0] > sm.compare(card_bw, colour)[0] + 0.1


def test_coverage_counts_only_the_part_a_short_source_spans():
    a = _frames(5, 20)
    _score, cov = sm.compare(a, a[:10])
    assert cov == pytest.approx(0.5)


def test_letterbox_matches_the_conversion_fit():
    assert sm._letterbox(1360, 768) == (W, H)          # 16:9 within 3%
    assert sm._letterbox(1920, 1080) == (W, H)
    w, h = sm._letterbox(1440, 1080)                    # 4:3 is pillarboxed
    assert h == H and w < W


# --------------------------------------------------------------------------
# choosing between candidates
# --------------------------------------------------------------------------

def test_the_right_file_is_found_among_others_of_the_same_length(monkeypatch):
    clip = sm.Clip("video/a.mov", "", 10.0, 1360, 768, 30.0)
    truth = _frames(10, 20)
    table = {"/s/right.mp4": truth, "/s/wrong1.mp4": _frames(11, 20),
             "/s/wrong2.mp4": _frames(12, 20)}
    srcs = [_src(p, 10.0) for p in table]
    res = _run(monkeypatch, [clip], srcs, table, {clip.key: _noisy(truth)})
    m = res[clip.key]
    assert m.best.path == "/s/right.mp4" and m.sure


def test_a_file_of_a_different_length_is_not_even_decoded(monkeypatch):
    clip = sm.Clip("video/a.mov", "", 10.0, 1360, 768, 30.0)
    truth = _frames(10, 20)
    decoded = []
    table = {"/s/right.mp4": truth, "/s/long.mp4": _frames(10, 120)}

    def clip_fp(c, fps):
        return _noisy(truth)

    def fake_fp(path, *a, **k):
        decoded.append(path)
        return table[path]

    monkeypatch.setattr(sm, "fingerprint", fake_fp)
    res = sm.find_sources([clip], [_src("/s/right.mp4", 10.0),
                                   _src("/s/long.mp4", 60.0)],
                          clip_fp, cache=sm.FingerprintCache())
    assert res[clip.key].best.path == "/s/right.mp4"
    assert decoded == ["/s/right.mp4"]


def test_the_best_copy_of_the_same_content_is_the_answer(monkeypatch):
    """A 4K master, a 1080p export and a 720p proxy of one edit: rebuild
    from the best of them, whichever the card was made from."""
    clip = sm.Clip("video/a.mov", "", 10.0, 1360, 768, 30.0)
    truth = _frames(20, 20)
    table = {"/s/proxy.mp4": _noisy(truth, 2, 1),
             "/s/export.mp4": _noisy(truth, 1, 2),
             "/s/master.mov": truth}
    srcs = [_src("/s/proxy.mp4", 10.0, 1280, 720, 5_000_000),
            _src("/s/export.mp4", 10.0, 1920, 1080, 20_000_000),
            _src("/s/master.mov", 10.0, 3840, 2160, 400_000_000)]
    res = _run(monkeypatch, [clip], srcs, table,
               {clip.key: _noisy(table["/s/export.mp4"], 6, 3)})
    m = res[clip.key]
    assert m.best.path == "/s/master.mov"
    assert sorted(s.path for s in m.same) == ["/s/export.mp4", "/s/proxy.mp4"]


def test_an_upscaled_version_is_not_the_same_content_as_its_original(
        monkeypatch):
    """A real TMNT card: the pre-upscale clip scored 0.955 against 1.000 for
    the upscaled master used.  Being close to the CLIP is not being the same
    file; the two files must agree with each other."""
    clip = sm.Clip("video/a.mov", "", 10.0, 1360, 768, 30.0)
    master = _frames(30, 20)
    other = _noisy(master, 40, 9)                     # same scene, redone
    srcs = [_src("/s/upscaled.mp4", 10.0, 1360, 768, 10_000_000),
            _src("/s/original.mp4", 10.0, 1920, 1080, 90_000_000)]
    table = {"/s/upscaled.mp4": master, "/s/original.mp4": other}
    res = _run(monkeypatch, [clip], srcs, table, {clip.key: _noisy(master)})
    m = res[clip.key]
    assert m.best.path == "/s/upscaled.mp4"       # not the "better" original
    assert m.runner_up.source.path == "/s/original.mp4"


def test_same_content_needs_the_pictures_to_agree_not_just_correlate():
    """Correlation shrugs off a re-grade or an upscale (the same scene lined
    up the same way); the per-pixel difference once brightness is matched
    does not.  A copy under brightness drift is still the same picture."""
    a = _frames(33, 20)
    assert sm.same_content(a, _noisy(a, 2, 1))
    squeezed = (16 + a.astype(np.float32) * 219 / 255).astype(np.uint8)
    assert sm.same_content(a, squeezed)
    regraded = a.astype(np.int16)
    regraded[:, :, :W // 2] += 25
    regraded = np.clip(regraded, 0, 255).astype(np.uint8)
    assert sm.compare(a, regraded)[0] > 0.9
    assert not sm.same_content(a, regraded)


def test_the_file_of_the_clips_own_length_beats_a_frame_shorter_copy(
        monkeypatch):
    """A real TMNT card had one 1.7 s clip under two names, one a frame
    shorter; the slot's is the one of its own length."""
    clip = sm.Clip("video/Weapon_Mike.mov", "", 1.70, 1360, 768, 30.0)
    truth = _frames(40, 4)
    table = {"/s/TeamUp_Nunchucks.mp4": truth, "/s/Weapon_Mike.mp4": truth}
    srcs = [_src("/s/TeamUp_Nunchucks.mp4", 1.667, size=1_200_000),
            _src("/s/Weapon_Mike.mp4", 1.70, size=1_150_000)]
    res = _run(monkeypatch, [clip], srcs, table, {clip.key: _noisy(truth)})
    assert res[clip.key].best.path == "/s/Weapon_Mike.mp4"


def test_a_tie_in_picture_and_quality_goes_to_the_slots_name(monkeypatch):
    """Two files whose pictures are identical and whose sizes differ only by
    their soundtracks: the name decides, not the audio's bytes."""
    clip = sm.Clip("video/Portal_ModeStart.mov", "", 13.7, 1360, 768, 30.0)
    truth = _frames(50, 27)
    table = {"/s/Portal_ModeStart_Slash.mp4": truth,
             "/s/Portal_ModeStart.mp4": truth}
    srcs = [_src("/s/Portal_ModeStart_Slash.mp4", 13.7, size=16_400_000),
            _src("/s/Portal_ModeStart.mp4", 13.7, size=16_200_000)]
    res = _run(monkeypatch, [clip], srcs, table, {clip.key: _noisy(truth)})
    assert res[clip.key].best.path == "/s/Portal_ModeStart.mp4"


def test_a_brief_effect_between_samples_is_found_frame_by_frame(monkeypatch):
    """Two files one edit apart for five frames -- invisible at two samples
    a second, and the reason there is a frame-by-frame pass."""
    clip = sm.Clip("video/a.mov", "", 4.0, 1360, 768, 30.0)
    dense = _frames(60, 120)
    slashed = dense.copy()
    slashed[40:45] = 255 - slashed[40:45]            # the effect
    sparse = dense[::15]                              # 2 per second
    table = {"/s/plain.mp4": sparse, "/s/slash.mp4": sparse,
             ("/s/plain.mp4", 30.0): dense, ("/s/slash.mp4", 30.0): slashed}
    srcs = [_src("/s/plain.mp4", 4.0, size=4_000_000),
            _src("/s/slash.mp4", 4.0, size=4_100_000)]
    clip_table = {clip.key: _noisy(sparse), (clip.key, 30.0): _noisy(slashed)}
    res = _run(monkeypatch, [clip], srcs, table, clip_table)
    m = res[clip.key]
    assert m.best.path == "/s/slash.mp4"
    assert [s.path for s in m.variants] == ["/s/plain.mp4"]


def test_a_clip_cut_down_from_a_longer_file_is_found_by_its_opening(
        monkeypatch):
    """A "Trim / pad" build cuts a long source to the slot's length."""
    clip = sm.Clip("video/a.mov", "", 5.0, 1360, 768, 30.0)
    long = _frames(70, 40)
    table = {"/s/long.mp4": long, "/s/other.mp4": _frames(71, 40)}
    srcs = [_src("/s/long.mp4", 20.0), _src("/s/other.mp4", 20.0)]
    res = _run(monkeypatch, [clip], srcs, table, {clip.key: _noisy(long[:10])})
    m = res[clip.key]
    assert m.best.path == "/s/long.mp4" and m.trimmed


def test_nothing_alike_is_no_match(monkeypatch):
    clip = sm.Clip("video/a.mov", "", 10.0, 1360, 768, 30.0)
    table = {"/s/x.mp4": _frames(80, 20)}
    res = _run(monkeypatch, [clip], [_src("/s/x.mp4", 10.0)], table,
               {clip.key: _frames(81, 20)})
    assert res[clip.key].best is None


def test_a_close_call_is_marked_worth_a_look(monkeypatch):
    """A different file (not a copy: the two disagree with each other) that
    scores almost as well as the best is a reason for a second look."""
    clip = sm.Clip("video/a.mov", "", 10.0, 1360, 768, 30.0)
    truth = _frames(90, 20)
    near = truth.astype(np.int16)
    near[:, :9, :12] += 20                  # one corner re-graded
    near = np.clip(near, 0, 255).astype(np.uint8)
    assert not sm.same_content(truth, near)
    table = {"/s/a.mp4": truth, "/s/b.mp4": near}
    srcs = [_src("/s/a.mp4", 10.0), _src("/s/b.mp4", 10.0)]
    res = _run(monkeypatch, [clip], srcs, table,
               {clip.key: _noisy(truth, 20, 6)})
    m = res[clip.key]
    assert m.best.path == "/s/a.mp4" and not m.sure
    assert m.runner_up.source.path == "/s/b.mp4"


def test_a_weak_match_is_marked_worth_a_look(monkeypatch):
    clip = sm.Clip("video/a.mov", "", 10.0, 1360, 768, 30.0)
    truth = _frames(92, 20)
    res = _run(monkeypatch, [clip], [_src("/s/a.mp4", 10.0)],
               {"/s/a.mp4": truth}, {clip.key: _noisy(truth, 40, 6)})
    m = res[clip.key]
    assert sm.MATCH_SCORE <= m.score < sm.SURE_SCORE
    assert m.best is not None and not m.sure


# --------------------------------------------------------------------------
# the cache
# --------------------------------------------------------------------------

def test_the_cache_keeps_fingerprints_by_file_identity(tmp_path):
    cache = sm.FingerprintCache(str(tmp_path))
    fp = _frames(1, 10)
    cache.put("a|1|2", fp, full=True)
    again = sm.FingerprintCache(str(tmp_path)).get("a|1|2", 999)
    assert np.array_equal(again, fp)
    assert cache.get("a|1|3", 1) is None               # a changed file
    assert cache.get("a|1|2", 1, sample_fps=30.0) is None


def test_a_partial_fingerprint_only_serves_what_it_covers(tmp_path):
    cache = sm.FingerprintCache(str(tmp_path))
    cache.put("long", _frames(2, 10), full=False)       # 5 s of a long file
    assert cache.get("long", 5.0) is not None
    assert cache.get("long", 30.0) is None


def test_the_apps_own_folders_are_not_searched_but_hidden_ones_are(tmp_path):
    """A project's .orig/ holds the stock clips; a real TMNT project kept
    every one of its sources in .assets/."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.mp4").write_bytes(b"")
    (tmp_path / ".orig").mkdir()
    (tmp_path / ".orig" / "y.mp4").write_bytes(b"")
    (tmp_path / ".assets").mkdir()
    (tmp_path / ".assets" / "z.mov").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")
    found = sm.list_video_files(str(tmp_path))
    assert sorted(os.path.basename(p) for p in found) == ["x.mp4", "z.mov"]


# --------------------------------------------------------------------------
# real clips
# --------------------------------------------------------------------------

def _ffmpeg():
    from pinball_decryptor.core.audio import find_ffmpeg
    return find_ffmpeg()


def _make(path, src, extra_vf="", seconds=3, size="320x180", rate=30):
    ff = _ffmpeg()
    vf = "format=yuv420p" + ("," + extra_vf if extra_vf else "")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "%s=size=%s:rate=%d:duration=%d" % (src, size, rate,
                                                         seconds),
                    "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
                    path], check=True)


@pytest.mark.skipif(not shutil.which("ffmpeg") and not _ffmpeg(),
                    reason="ffmpeg not available")
def test_real_clips_find_their_sources_colour_and_black_and_white(tmp_path):
    """Two sources and their black-and-white twins, the clips re-encoded
    small and lossy the way a card carries them."""
    ff = _ffmpeg()
    folder = tmp_path / "mine"
    folder.mkdir()
    _make(str(folder / "one.mp4"), "testsrc2")
    _make(str(folder / "one_bw.mp4"), "testsrc2", "hue=s=0")
    _make(str(folder / "two.mp4"), "rgbtestsrc")
    clips = []
    for name, src in (("one", "one.mp4"), ("one_bw", "one_bw.mp4"),
                      ("two", "two.mp4")):
        out = str(tmp_path / ("card_" + name + ".mp4"))
        subprocess.run([ff, "-v", "error", "-y", "-i", str(folder / src),
                        "-vf", "scale=136:76", "-c:v", "libx264",
                        "-b:v", "60k", out], check=True)
        clips.append(sm.Clip(name, out, 3.0, 136, 76, 30.0))
    sources = sm.probe_sources(sm.list_video_files(str(folder)))
    res = sm.find_sources(
        clips, sources,
        lambda c, fps: sm.fingerprint(c.path, c.width, c.height,
                                      sample_fps=fps),
        cache=sm.FingerprintCache(str(tmp_path / "cache")))
    got = {k: os.path.basename(m.best.path) if m.best else None
           for k, m in res.items()}
    assert got == {"one": "one.mp4", "one_bw": "one_bw.mp4",
                   "two": "two.mp4"}
