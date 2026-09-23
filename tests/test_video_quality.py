"""Tests for the on-card video-quality report (PAD-167).

The measurements are pure ISO-BMFF box arithmetic, so everything here runs off
synthetic clips built in-process — no ffmpeg, no card image.  What the clips
are built to prove:

* the bitrate is taken from the PAYLOAD, not the file size, so a clip a Write
  padded back up to its slot's byte length is not flattered by its padding;
* the blocky verdict is the Write-time warning's own rule and constant;
* a card scan finds the clips by their ``ftyp`` magic and names them from the
  scene data, exactly as the extract does.

Ground truth for the parser itself is not here: it was checked against ffprobe
over all 658 clips of a stock Godzilla LE 1.16 card and all 658 of a card built
from it, resolution / frame rate / duration / size, with no mismatches.
"""

import struct

import pytest

from pinball_decryptor.core import video_quality as vq
from pinball_decryptor.plugins.stern import engine
from tests._ext4_fake import FakeExt4Reader


# ---- synthetic ISO-BMFF ----------------------------------------------------

def _box(typ, payload=b""):
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def _full(typ, payload, version=0):
    return _box(typ, bytes([version, 0, 0, 0]) + payload)


def _mvhd(timescale, duration):
    return _full(b"mvhd",
                 struct.pack(">IIII", 0, 0, timescale, duration)
                 + b"\x00" * 80)


def _tkhd(width, height):
    # …everything between the header and the two 16.16 dimensions is ignored
    # by the reader, which takes the LAST eight bytes of the body.
    return _full(b"tkhd", b"\x00" * 76
                 + struct.pack(">II", width << 16, height << 16))


def _mdhd(timescale, duration):
    return _full(b"mdhd",
                 struct.pack(">IIII", 0, 0, timescale, duration) + b"\x00" * 4)


def _hdlr(kind):
    return _full(b"hdlr", b"\x00" * 4 + kind + b"\x00" * 12)


def _stsd(width, height):
    entry = (struct.pack(">I", 86) + b"avc1" + b"\x00" * 6
             + struct.pack(">HHHIII", 1, 0, 0, 0, 0, 0)
             + struct.pack(">HH", width, height) + b"\x00" * 46)
    return _full(b"stsd", struct.pack(">I", 1) + entry)


def _stsz(frames):
    return _full(b"stsz", struct.pack(">II", 0, frames)
                 + b"\x00\x00\x04\x00" * frames)


def _video_trak(width, height, frames, timescale, duration,
                coded=None):
    cw, ch = coded if coded else (width, height)
    stbl = _box(b"stbl", _stsd(cw, ch) + _stsz(frames))
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", _mdhd(timescale, duration) + _hdlr(b"vide") + minf)
    return _box(b"trak", _tkhd(width, height) + mdia)


def make_clip(width=1360, height=768, fps=30, seconds=4.0, payload_bytes=0,
              coded=None):
    """A complete little MP4 padded out with ``mdat`` to *payload_bytes*."""
    timescale = 30000
    duration = int(seconds * timescale)
    frames = int(round(fps * seconds))
    moov = _box(b"moov", _mvhd(timescale, duration)
                + _video_trak(width, height, frames, timescale, duration,
                              coded=coded))
    ftyp = _box(b"ftyp", b"isomiso2avc1mp41")
    head = ftyp + moov
    filler = max(0, payload_bytes - len(head) - 8)
    return head + _box(b"mdat", b"\x00" * filler)


# ---- the measurements ------------------------------------------------------

def test_reads_resolution_frame_rate_and_length(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(make_clip(seconds=4.0, fps=30, payload_bytes=400_000))
    c = vq.quality_of_file(str(p))
    assert c.error == ""
    assert (c.width, c.height) == (1360, 768)
    assert c.duration == pytest.approx(4.0, abs=0.01)
    assert c.fps == pytest.approx(30.0, abs=0.01)
    assert c.size == c.payload == p.stat().st_size


def test_coded_size_wins_over_the_display_size(tmp_path):
    # A non-square pixel aspect makes tkhd wider than the frames really are;
    # the bitrate has to buy the CODED pixels (7 of Godzilla's clips are this).
    p = tmp_path / "anamorphic.mp4"
    p.write_bytes(make_clip(width=1365, height=768, coded=(1360, 768),
                            payload_bytes=400_000))
    assert (vq.quality_of_file(str(p)).width,
            vq.quality_of_file(str(p)).height) == (1360, 768)


def test_a_fat_clip_is_ok_and_a_thin_one_is_blocky(tmp_path):
    fat = tmp_path / "fat.mp4"
    fat.write_bytes(make_clip(seconds=4.0, payload_bytes=4_000_000))
    thin = tmp_path / "thin.mp4"
    thin.write_bytes(make_clip(seconds=4.0, payload_bytes=150_000))
    assert vq.quality_of_file(str(fat)).verdict == "ok"
    assert vq.quality_of_file(str(thin)).verdict == "blocky"
    assert vq.quality_of_file(str(thin)).quality_str() == "blocky"


def test_bitrate_matches_the_payload(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(make_clip(seconds=4.0, payload_bytes=400_000))
    c = vq.quality_of_file(str(p))
    assert c.bitrate == pytest.approx(c.payload * 8 / 4.0, rel=0.01)
    assert c.bpp == pytest.approx(c.bitrate / (1360 * 768 * 30), rel=0.01)


# ---- padding: the fingerprint of a fit-in-place Write ----------------------

def test_slot_padding_is_not_counted_as_picture(tmp_path):
    # Exactly what _fit_video_payload leaves on the card: a small clip padded
    # up to the slot's byte length with a trailing free box.  Judged on the
    # file size it would look like a 4 Mbps clip; it is a 300 kbps one.
    clip = make_clip(seconds=4.0, payload_bytes=150_000)
    on_card = engine._pad_isobmff(clip, 2_000_000)
    p = tmp_path / "fitted.mp4"
    p.write_bytes(on_card)

    c = vq.quality_of_file(str(p))
    assert c.size == 2_000_000
    assert c.payload == len(clip)
    assert c.padded is True
    assert c.verdict == "blocky"
    assert c.quality_str() == "blocky (squeezed to fit)"


def test_an_unpadded_clip_is_not_reported_as_squeezed(tmp_path):
    p = tmp_path / "intact.mp4"
    p.write_bytes(make_clip(seconds=4.0, payload_bytes=4_000_000))
    c = vq.quality_of_file(str(p))
    assert c.padded is False
    assert c.quality_str() == "OK"


def test_leading_free_box_is_not_mistaken_for_padding(tmp_path):
    # ffmpeg's faststart reservation sits right after ftyp; subtracting it
    # would under-report the bitrate of most of the clips on a stock card.
    clip = make_clip(seconds=4.0, payload_bytes=1_000_000)
    ftyp_len = struct.unpack(">I", clip[:4])[0]
    spiked = (clip[:ftyp_len] + _box(b"free", b"\x00" * 1000)
              + clip[ftyp_len:])
    p = tmp_path / "faststart.mp4"
    p.write_bytes(spiked)
    c = vq.quality_of_file(str(p))
    assert c.padded is False
    assert c.payload == len(spiked)


# ---- unreadable clips are rows, not crashes -------------------------------

def test_a_non_mp4_is_reported_not_raised(tmp_path):
    p = tmp_path / "notavideo.mp4"
    p.write_bytes(b"RIFF" + b"\x00" * 200)
    c = vq.quality_of_file(str(p))
    assert c.error
    assert c.verdict == "unknown"
    assert c.quality_str() == "couldn't read"


def test_a_clip_with_no_video_track_is_reported(tmp_path):
    moov = _box(b"moov", _mvhd(30000, 120000))
    p = tmp_path / "audioonly.mp4"
    p.write_bytes(_box(b"ftyp", b"isom") + moov + _box(b"mdat", b"\x00" * 99))
    c = vq.quality_of_file(str(p))
    assert c.error == "no video track"


# ---- the report itself -----------------------------------------------------

def _clip(name, bpp_low, padded=False):
    """A ClipQuality with the numbers dialled straight in."""
    payload = 150_000 if bpp_low else 4_000_000
    return vq.ClipQuality(name=name, size=payload, payload=payload,
                          width=1360, height=768, fps=30.0, duration=4.0,
                          padded=padded)


def test_summary_separates_squeezed_from_simply_small():
    squeezed = [_clip("a.mp4", True, padded=True), _clip("b.mp4", False)]
    text = " ".join(vq.summary_lines(squeezed))
    assert "1 of 2" in text
    assert "squeezed into the slot" in text

    own = [_clip("a.mp4", True), _clip("b.mp4", False)]
    text = " ".join(vq.summary_lines(own))
    assert "None of them were squeezed" in text


def test_an_unsqueezed_blocky_clip_is_not_blamed_on_the_users_export():
    """PAD-171: the report said an unpadded clip was the user's own file at
    its own size, that a rebuild would not change it, and to re-export.  On
    the card it said that about, every replaced clip was the app's own
    format-matched conversion; the user re-exported at twice the bitrate and
    the build converted it straight back under the bar.  The card cannot tell
    the two apart, so the line must name the one a rebuild does fix."""
    text = " ".join(vq.summary_lines([_clip("a.mp4", True)]))
    assert "will not change them" not in text
    assert "Re-export" not in text
    assert "converted copy" in text
    assert "build again from your original replacement files" in text
    assert "keeps the bitrate you exported it at" in text


def test_rebuild_advice_says_whole_clips_need_room():
    """PAD-176: following "build again" for hundreds of clips at once (whole,
    or converted at the stock clip's bitrate) is what ran an 8 GB card's
    games partition out of room.  Both pieces of rebuild advice say so and
    point at SD card size; the Check card help says the same."""
    from pinball_decryptor.webui.help_content import HELP_CONTENT
    squeezed = " ".join(vq.summary_lines([_clip("a.mp4", True, padded=True)]))
    small = " ".join(vq.summary_lines([_clip("a.mp4", True)]))
    fine = " ".join(vq.summary_lines([_clip("a.mp4", False)]))
    help_ = dict(HELP_CONTENT["Replace Video"])[
        "Checking a card you already built"]
    for text in (squeezed, small, help_):
        assert "games partition" in text and "SD card size" in text, text
    assert "games partition" not in fine    # nothing to rebuild, no advice


def test_summary_says_so_when_everything_is_fine():
    text = " ".join(vq.summary_lines([_clip("a.mp4", False)]))
    assert "at or above the quality bar" in text


def test_worst_first_puts_the_blocky_clips_on_top():
    clips = [_clip("zzz.mp4", False), _clip("aaa.mp4", False),
             _clip("bad.mp4", True)]
    assert [c.name for c in vq.sort_worst_first(clips)] == [
        "bad.mp4", "aaa.mp4", "zzz.mp4"]


def test_as_text_lists_every_clip():
    clips = [_clip("bad.mp4", True), _clip("good.mp4", False)]
    text = vq.as_text(clips, title="Video quality — card.raw")
    assert "Video quality — card.raw" in text
    assert "bad.mp4" in text and "good.mp4" in text
    assert "blocky" in text


# ---- the Spike 2 card scan -------------------------------------------------

_HASHDIR = "/godzilla_le/assets/lcd/auto_loaded/b372738a"


def _radium(ref, name):
    """A scene.radium record framed the way _parse_radium reads it: a u64
    length-prefixed name, the u32 element id, then the length-prefixed ref."""
    nb = name.encode()
    rb = ref.encode()
    return (struct.pack("<Q", len(nb)) + nb
            + struct.pack("<I", 0x80000001)
            + struct.pack("<Q", len(rb)) + rb)


def _card_spec(clip_bytes, ref="349.asset/0.asset", name="Secret_Combo"):
    hd = _HASHDIR.strip("/").split("/")
    tree = {"scene.radium": _radium(ref, name),
            "scene.assets": {ref.split("/")[0]: {ref.split("/")[1]:
                                                 clip_bytes}}}
    for part in reversed(hd):
        tree = {part: tree}
    return tree


def test_card_scan_finds_names_and_measures_a_clip():
    clip = engine._pad_isobmff(make_clip(seconds=4.0, payload_bytes=150_000),
                               2_000_000)
    reader = FakeExt4Reader(_card_spec(clip))
    lines = []
    clips = engine.scan_video_quality(
        reader, log=lambda m, lvl="info": lines.append((lvl, m)))

    assert len(clips) == 1
    c = clips[0]
    assert c.name == "Secret_Combo.mp4"          # named from the scene data
    assert c.card_path == _HASHDIR + "/scene.assets/349.asset/0.asset"
    assert c.padded is True and c.verdict == "blocky"
    assert any("1 below the quality bar" in m for _lvl, m in lines)


def test_card_scan_skips_files_that_are_not_clips():
    spec = _card_spec(make_clip(payload_bytes=4_000_000))
    spec["godzilla_le"]["readme.txt"] = b"x" * 0x2000
    clips = engine.scan_video_quality(FakeExt4Reader(spec))
    assert [c.name for c in clips] == ["Secret_Combo.mp4"]


def test_card_scan_reports_no_clips_rather_than_failing():
    assert engine.scan_video_quality(FakeExt4Reader({"a.txt": b"x"})) == []


def test_read_range_serves_the_middle_of_a_file():
    reader = FakeExt4Reader({"f.bin": bytes(range(256))})
    node = reader.read_inode(3)
    assert reader.read_range(node, 10, 4) == bytes(range(10, 14))
    # Clamped at the end rather than raising — the box walk reads past it.
    assert reader.read_range(node, 250, 99) == bytes(range(250, 256))
    assert reader.read_range(node, 999, 4) == b""


# ---- plugin wiring ---------------------------------------------------------

def test_stern_spike2_advertises_the_report():
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    mfr = SternManufacturer()
    assert mfr.capabilities.video_quality_report is True


def test_a_rom_zip_is_refused_rather_than_opened(tmp_path):
    # A Whitestar ROM zip has no ext4 games partition; the hook must answer
    # "nothing" instead of dragging the card reader through it.
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    z = tmp_path / "rom.zip"
    z.write_bytes(b"PK\x03\x04")
    assert SternManufacturer().video_quality(str(z)) == []


def test_the_default_plugin_reports_nothing():
    from pinball_decryptor.core.registry import Manufacturer
    assert Manufacturer.video_quality(object(), "/some/card.raw") == []


# ---- which card the window opens on ---------------------------------------

class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v


class _Win:
    """Just enough window for the Video tab's _quality_default_card."""

    def __init__(self, assets="", picked=""):
        self.write_assets_var = _Var(assets)
        self.extract_input_var = _Var(picked)


def _default_card(win):
    from pinball_decryptor.webui.tabs.video import VideoTab
    tab = VideoTab.__new__(VideoTab)
    tab.window = win
    return VideoTab._quality_default_card(tab)


def test_default_card_prefers_the_projects_own_source(tmp_path):
    from pinball_decryptor.core.extract_source import write_extract_source
    built = tmp_path / "built.raw"
    built.write_bytes(b"\x00" * 16)
    other = tmp_path / "stock.raw"
    other.write_bytes(b"\x00" * 16)
    project = tmp_path / "project"
    project.mkdir()
    write_extract_source(str(project), str(built))

    win = _Win(assets=str(project), picked=str(other))
    assert _default_card(win) == str(built)


def test_default_card_falls_back_to_the_extract_tab_pick(tmp_path):
    picked = tmp_path / "stock.raw"
    picked.write_bytes(b"\x00" * 16)
    win = _Win(assets=str(tmp_path / "no-such-project"), picked=str(picked))
    assert _default_card(win) == str(picked)


def test_default_card_is_empty_when_nothing_is_known():
    assert _default_card(_Win()) == ""
