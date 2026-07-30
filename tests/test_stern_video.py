"""Tests for the Stern Spike 2 Replace-Video write path (engine.py helpers).

These cover the pure, deterministic pieces — size-neutral ``free``-box padding,
changed-video detection against the ``.checksums.md5`` baseline, and the
inode-resolve + pad path of ``_prepare_video_patches`` driven by a fake ext4
reader.  None of them need ffmpeg or a real card image (the ffmpeg shrink path
for oversized clips is exercised by the manual extract->replace->Write
round-trip).
"""

import os

from pinball_decryptor.core.checksums import generate_checksums, read_checksums
from pinball_decryptor.plugins.stern import engine


# ---- _pad_isobmff: size-neutral padding -----------------------------------

def test_pad_isobmff_exact_fit_is_unchanged():
    data = b"A" * 100
    assert engine._pad_isobmff(data, 100) == data


def test_pad_isobmff_appends_a_valid_free_box():
    data = b"A" * 100
    out = engine._pad_isobmff(data, 200)
    assert len(out) == 200
    assert out[:100] == data
    box = out[100:]
    # 32-bit box: size word == box length, type 'free', zero payload.
    assert int.from_bytes(box[:4], "big") == 100
    assert box[4:8] == b"free"
    assert box[8:] == b"\x00" * 92


def test_pad_isobmff_small_gap_zero_pads():
    # A <8-byte gap can't hold a box header; trailing zeros are tolerated.
    data = b"A" * 100
    out = engine._pad_isobmff(data, 105)
    assert out == data + b"\x00" * 5


def test_pad_isobmff_truncates_when_oversized():
    # Defensive: the caller never pads past the target, but the branch is real.
    assert engine._pad_isobmff(b"A" * 100, 80) == b"A" * 80


# ---- _changed_videos: diff staged clips vs the Extract baseline ------------

def _make_extract(tmp_path):
    vid = tmp_path / "video"
    vid.mkdir()
    (vid / "a.mp4").write_bytes(b"AAAA")
    (vid / "b.mov").write_bytes(b"BBBB")
    (vid / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n"
        "a.mp4\t/spinball_le/scene.assets/1.asset\t4\n"
        "b.mov\t/spinball_le/scene.assets/2.asset\t4\n",
        encoding="utf-8")
    return vid


def test_changed_videos_returns_only_edited(tmp_path):
    vid = _make_extract(tmp_path)
    generate_checksums(str(tmp_path))
    baseline = read_checksums(str(tmp_path))

    # Edit one clip after the baseline was taken.
    (vid / "a.mp4").write_bytes(b"ZZZZZZ")

    changed = engine._changed_videos(str(tmp_path), baseline)
    assert [c[0] for c in changed] == ["a.mp4"]
    fname, card_path, staged = changed[0]
    assert card_path == "/spinball_le/scene.assets/1.asset"
    assert os.path.basename(staged) == "a.mp4"
    assert os.path.isfile(staged)


def test_changed_videos_no_manifest_is_empty(tmp_path):
    assert engine._changed_videos(str(tmp_path), {}) == []


def test_changed_videos_no_baseline_treats_all_as_changed(tmp_path):
    # Without a baseline entry we can't prove a clip is untouched, so it's
    # conservatively included (mirrors the audio "no baseline -> all" path).
    _make_extract(tmp_path)
    changed = engine._changed_videos(str(tmp_path), {})
    assert {c[0] for c in changed} == {"a.mp4", "b.mov"}


# ---- _prepare_video_patches: resolve inode + size-fit (pad path) -----------

class _FakeReader:
    """Duck-typed ext4 reader: yields (path, ino, node) for the given files."""

    def __init__(self, sizes):
        self._sizes = sizes  # {card_path: size}

    def iter_regular_files(self, min_size=1):
        for path, size in self._sizes.items():
            yield path, 0, {"size": size, "mode": 0, "flags": 0, "i_block": b""}


def test_prepare_video_patches_pads_to_slot_size(tmp_path):
    staged = tmp_path / "a.mp4"
    staged.write_bytes(b"A" * 50)
    work = tmp_path / "work"
    work.mkdir()
    reader = _FakeReader({"/g/1.asset": 80})
    edits = [("a.mp4", "/g/1.asset", str(staged))]

    patches, skipped, grow = _prepare(reader, edits, work)
    assert skipped == 0
    assert grow == []                          # nothing oversized here
    assert len(patches) == 1
    node, payload = patches[0]
    assert node["size"] == 80
    assert len(payload) == 80              # exactly the slot size
    assert payload[:50] == b"A" * 50       # original bytes intact, then padded


def test_prepare_video_patches_skips_when_inode_missing(tmp_path):
    staged = tmp_path / "a.mp4"
    staged.write_bytes(b"A" * 50)
    work = tmp_path / "work"
    work.mkdir()
    reader = _FakeReader({})               # card path not found on the card
    edits = [("a.mp4", "/g/1.asset", str(staged))]

    patches, skipped, grow = _prepare(reader, edits, work)
    assert patches == []
    assert grow == []
    assert skipped == 1


def _isobmff(qt=False):
    """Minimal ISO-BMFF head so ``isobmff_brand`` recognises the container."""
    brand = b"qt  " if qt else b"isom"
    return (20).to_bytes(4, "big") + b"ftyp" + brand + b"\x00" * 8


def test_prepare_video_patches_grows_oversized_source(tmp_path, monkeypatch):
    # The user's assigned source is bigger than the on-card slot: instead of
    # crushing it in place, it becomes a GROW job (card_rel, source) — kept
    # intact for the ext4 driver to copy in.  No in-place patch is produced.
    big = tmp_path / "orig.mov"
    big.write_bytes(_isobmff(qt=True) + b"B" * 500)   # > 80 B slot
    staged = tmp_path / "a.mov"
    staged.write_bytes(b"x" * 999)           # transcoded staged copy
    work = tmp_path / "work"; work.mkdir()
    reader = _FakeReader({"/g/1.asset": 80})
    edits = [("a.mov", "/g/1.asset", str(staged))]
    monkeypatch.setattr("pinball_decryptor.core.ext4_grow.available",
                        lambda: (True, "ok"))
    # No ffprobe reading these stubs: the container check is what decides.
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda _p: None)

    patches, skipped, grow = engine._prepare_video_patches(
        reader, edits, str(work), log=lambda *a, **k: None,
        cancel=lambda: False, originals={"video/a.mov": str(big)})
    assert patches == []                     # not patched in place
    assert skipped == 0
    assert grow == [("g/1.asset", str(big))]  # card rel (no leading /), source


def test_prepare_video_patches_replaces_fit_size_original_intact(
        tmp_path, monkeypatch):
    # Even a source that FITS its slot is replaced intact via the ext4 driver
    # rather than re-encoded — any re-encode (even a container remux) is what
    # the game's content validation rejects.
    small = tmp_path / "orig.mov"
    small.write_bytes(_isobmff(qt=True) + b"B" * 20)  # <= 80 B slot (fits)
    staged = tmp_path / "a.mov"
    staged.write_bytes(b"x" * 70)
    work = tmp_path / "work"; work.mkdir()
    reader = _FakeReader({"/g/1.asset": 80})
    edits = [("a.mov", "/g/1.asset", str(staged))]
    monkeypatch.setattr("pinball_decryptor.core.ext4_grow.available",
                        lambda: (True, "ok"))
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda _p: None)

    patches, skipped, grow = engine._prepare_video_patches(
        reader, edits, str(work), log=lambda *a, **k: None,
        cancel=lambda: False, originals={"video/a.mov": str(small)})
    assert patches == []                     # NOT re-encoded / raw-patched
    assert grow == [("g/1.asset", str(small))]   # replaced intact instead


# ---- _intact_copy_source: only a real drop-in goes on the card as-is -------

class _Info:
    def __init__(self, vcodec="h264", width=1280, height=720, fps=30.0,
                 pix_fmt="yuv420p", profile="Main"):
        self.vcodec, self.width, self.height = vcodec, width, height
        self.fps, self.pix_fmt, self.profile = fps, pix_fmt, profile


def _probe_map(monkeypatch, mapping):
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda p: mapping.get(os.path.basename(p)))


def _sources(tmp_path, qt=True):
    src = tmp_path / ("src.mov" if qt else "src.mp4")
    src.write_bytes(_isobmff(qt=qt) + b"S" * 64)
    staged = tmp_path / "a.mov"
    staged.write_bytes(_isobmff(qt=True) + b"T" * 64)
    return src, staged


def _decide(src, staged, fname, msgs=None):
    """Run the gate and return the path it picked, collecting its log line."""
    sink = msgs if msgs is not None else []
    return engine._intact_copy_source(
        str(src), str(staged), fname, 999, lambda m, lvl: sink.append((m, lvl)))


def test_intact_copy_keeps_a_true_drop_in(tmp_path, monkeypatch):
    src, staged = _sources(tmp_path)
    _probe_map(monkeypatch, {"src.mov": _Info(), "a.mov": _Info()})
    msgs = []
    assert _decide(src, staged, "a.mov", msgs) == str(src)
    assert msgs and msgs[0][1] == "info" and "intact" in msgs[0][0]


def test_intact_copy_rejects_a_foreign_container(tmp_path, monkeypatch):
    # An .mkv the user encoded themselves: the machine finds the audio and
    # plays it over a black picture, which is the whole bug being fixed.
    src = tmp_path / "src.mkv"
    src.write_bytes(b"\x1a\x45\xdf\xa3" + b"S" * 64)   # Matroska, no ftyp
    staged = tmp_path / "a.mov"
    staged.write_bytes(_isobmff(qt=True) + b"T" * 64)
    msgs = []
    assert _decide(src, staged, "a.mov", msgs) == str(staged)
    # One line, and not an alarm: the converted copy going on IS the plan when
    # the user left conversion on (a tester read the old warning as a failure).
    assert len(msgs) == 1 and msgs[0][1] == "info"
    assert "format-matched" in msgs[0][0]


def test_intact_copy_rejects_wrong_codec_depth_and_geometry(
        tmp_path, monkeypatch):
    src, staged = _sources(tmp_path)
    slot = _Info()
    for bad in (_Info(vcodec="hevc"),
                _Info(pix_fmt="yuv420p10le"),
                _Info(width=1920, height=1080),
                _Info(fps=60.0),
                _Info(profile="High")):      # slot's clip is Main
        _probe_map(monkeypatch, {"src.mov": bad, "a.mov": slot})
        assert _decide(src, staged, "a.mov") == str(staged)


def test_intact_copy_allows_a_profile_below_the_slots(tmp_path, monkeypatch):
    # The slot's clip is the CEILING, not the target: Baseline decodes on a
    # machine whose clip is Main, so it still goes on intact.
    src, staged = _sources(tmp_path)
    _probe_map(monkeypatch, {"src.mov": _Info(profile="Constrained Baseline"),
                             "a.mov": _Info(profile="Main")})
    assert _decide(src, staged, "a.mov") == str(src)


def test_intact_copy_rejects_a_brand_the_slot_does_not_use(
        tmp_path, monkeypatch):
    # Slot extension ".mp4" means the card's own clip was ISO-branded.
    src, staged = _sources(tmp_path, qt=True)      # user supplied QuickTime
    _probe_map(monkeypatch, {"src.mov": _Info(), "a.mov": _Info()})
    assert _decide(src, staged, "a.mp4") == str(staged)


def test_intact_copy_flags_an_unconverted_file_as_an_error(tmp_path,
                                                           monkeypatch):
    # Nothing converted it (as-is ticked, or no ffmpeg), so the staged bytes
    # ARE the user's bytes: there's no format-matched copy to fall back to and
    # the machine gets an unplayable clip — say so as an error (batch 23).
    src = tmp_path / "src.mp4"
    src.write_bytes(_isobmff(qt=False) + b"S" * 64)
    staged = tmp_path / "a.mov"
    staged.write_bytes(src.read_bytes())           # byte-for-byte copy
    _probe_map(monkeypatch, {"src.mp4": _Info(), "a.mov": _Info()})
    msgs = []
    assert _decide(src, staged, "a.mov", msgs) == str(staged)
    assert len(msgs) == 1 and msgs[0][1] == "error"
    assert "black picture" in msgs[0][0]


def test_prepare_video_patches_oversized_falls_back_to_fit_without_grow(
        tmp_path, monkeypatch):
    # When the ext4 driver isn't reachable, an oversized source falls back to
    # the old size-fit-in-place behaviour (never dropped).  The staged copy is
    # <= slot here so it pads (no ffmpeg needed).
    big = tmp_path / "orig.mp4"
    big.write_bytes(b"B" * 500)
    staged = tmp_path / "a.mov"
    staged.write_bytes(b"y" * 50)            # <= 80 slot -> pads
    work = tmp_path / "work"; work.mkdir()
    reader = _FakeReader({"/g/1.asset": 80})
    edits = [("a.mov", "/g/1.asset", str(staged))]
    monkeypatch.setattr("pinball_decryptor.core.ext4_grow.available",
                        lambda: (False, "no WSL"))

    patches, skipped, grow = engine._prepare_video_patches(
        reader, edits, str(work), log=lambda *a, **k: None,
        cancel=lambda: False, originals={"video/a.mov": str(big)})
    assert grow == []                        # growth unavailable
    assert len(patches) == 1                 # size-fit in place instead


def test_prepare_video_patches_device_dest_never_grows(tmp_path, monkeypatch):
    # Direct-SD writes can't grow slots; an oversized source falls back to fit.
    big = tmp_path / "orig.mp4"; big.write_bytes(b"B" * 500)
    staged = tmp_path / "a.mov"; staged.write_bytes(b"y" * 50)
    work = tmp_path / "work"; work.mkdir()
    reader = _FakeReader({"/g/1.asset": 80})
    edits = [("a.mov", "/g/1.asset", str(staged))]
    # available() would say yes, but dest_is_device must veto growth.
    monkeypatch.setattr("pinball_decryptor.core.ext4_grow.available",
                        lambda: (True, "ok"))
    patches, skipped, grow = engine._prepare_video_patches(
        reader, edits, str(work), log=lambda *a, **k: None,
        cancel=lambda: False, originals={"video/a.mov": str(big)},
        dest_is_device=True)
    assert grow == []
    assert len(patches) == 1


def _prepare(reader, edits, work):
    return engine._prepare_video_patches(
        reader, edits, str(work),
        log=lambda *a, **k: None, cancel=lambda: False)


# ---- capability / note wiring ---------------------------------------------

def test_stern_enables_replace_video_with_a_size_note():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    mfr = SternManufacturer()
    assert mfr.capabilities.replace_video is True
    note = mfr.video_length_note()
    assert note and "fit" in note.lower()
