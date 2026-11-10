"""Capcom sounds out of the sound ROMs (PAD-1088).

Synthetic sound ROMs laid out the way Capcom's are (chip headers, banked
pointers, sound tables, playlists, prefixed MPEG frames); the decode
tests make real MPEG-1 Layer II frames with ffmpeg.  The format was
worked out on, and the extract proven against PinMAME's own playback of,
Big Bang Bar, Kingpin and Pinball Magic.
"""

import csv
import os
import struct
import subprocess
import wave
import zipfile

import pytest

from pinball_decryptor.core.audio import find_ffmpeg
from pinball_decryptor.plugins.pinmame_classic import capcom_sound as cs
from pinball_decryptor.plugins.pinmame_classic import capture

FRAME = b"\xff\xfd\x18\xc0" + b"\x11" * 140      # a header + filler


def ptr(chip, off):
    """The board's four-byte pointer to *off* in *chip*."""
    return struct.pack(">I", chip << 24 | (off // 0x8000) << 16
                       | 0x8000 | (off & 0x7FFF))


class Rom:
    def __init__(self, chip, size):
        self.chip = chip
        self.data = bytearray(b"\xff" * size)
        banner = b"Test\0".ljust(0x40, b"\0")
        self.data[:0x40] = banner
        self.data[0x40:0x4a] = bytes([chip, size // 0x8000, chip, 0, 0,
                                      0x5a]) + b"\0" * 4

    def table_here(self, at, chip=None):
        self.data[0x46:0x4a] = ptr(chip or self.chip, at)

    def put(self, at, raw):
        self.data[at:at + len(raw)] = raw
        return at


def frame(rom, at, body=FRAME):
    rom.put(at, cs.FRAME_PREFIX + body)
    return (rom.chip, at)


def playlist(rom, at, frames):
    rom.put(at, struct.pack(">H", len(frames))
            + b"".join(ptr(c, o) for c, o in frames))
    return at


def table(rom, at, entries):
    """entries: (frames, flag, (chip, playlist offset)) or None (unused)"""
    raw = struct.pack(">H", len(entries))
    for e in entries:
        raw += (b"\0" * 8 if e is None else
                struct.pack(">HH", e[0], e[1]) + ptr(*e[2]))
    rom.put(at, raw)
    rom.table_here(at)


def bbb_like(bodies=None):
    """u28 with its own table (sound 0: 2 frames, one across a bank and
    one on u30; 1 unused; sound 2: 1 frame), u30 with its own (1 sound).
    *bodies* replaces the frames' bytes (real MPEG for decoding)."""
    b = list(bodies or [FRAME] * 4)
    u28, u29 = Rom(1, 0x20000), Rom(2, 0x20000)
    u30, u31 = Rom(3, 0x10000), Rom(4, 0x10000)
    u29.data[0x46:0x4a] = b"\0" * 4                 # no table of its own
    u31.data[0x46:0x4a] = b"\0" * 4
    f0 = frame(u28, 0x100, b[0])
    f1 = frame(u28, 0x9234, b[1])                   # bank 1
    f2 = frame(u30, 0x200, b[2])
    f3 = frame(u30, 0x300, b[3])
    p0 = playlist(u28, 0x400, [f0, f1, f2])
    p2 = playlist(u28, 0xA000, [f1])
    table(u28, 0x1F000, [(3, 1, (1, p0)), None, (1, 1, (1, p2))])
    p3 = playlist(u30, 0x500, [f3, f0])
    table(u30, 0xF000, [(2, 70, (3, p3))])
    return {1: bytes(u28.data), 2: bytes(u29.data), 3: bytes(u30.data),
            4: bytes(u31.data)}


def write_zip(path, chips, extra=()):
    names = {1: "u28_b17.bin", 2: "u29_b17.bin", 3: "u30_b17.bin",
             4: "u31_b17.bin"}
    with zipfile.ZipFile(path, "w") as z:
        for c, data in chips.items():
            z.writestr(names[c], data)
        for n in extra:
            z.writestr(n, b"\0" * 64)
    return str(path)


# ------------------------------------------------------------------ format
def test_pointer_is_chip_bank_window():
    assert cs.offset(0x01010A56) == (1, 0x8A56)
    assert cs.offset(0x011F7276) == (1, 0xFF276)
    assert cs.offset(0x0300FFFF) == (3, 0x7FFF)


def test_every_table_every_sound_in_play_order():
    chips = bbb_like()
    assert cs.tables(chips) == [(1, 0x1F000), (3, 0xF000)]
    sounds = cs.read_sounds(chips)
    assert [s.name for s in sounds] == ["u28_000", "u28_002", "u30_000"]
    s0 = sounds[0]
    assert s0.frames == [(1, 0x103), (1, 0x9237), (3, 0x203)]
    assert sounds[2].flag == 70
    assert sounds[2].frames == [(3, 0x303), (1, 0x103)]
    assert cs.mpeg(chips, s0) == FRAME * 3
    assert s0.seconds == pytest.approx(3 * 1152 / 32000)


def test_one_table_for_two_chips():
    """Pinball Magic: u28's header points at u29's table, u29's is zero."""
    chips = bbb_like()
    u28 = bytearray(chips[1])
    u29 = bytearray(chips[2])
    u29[0x1F000:0x1F01A] = u28[0x1F000:0x1F01A]     # move the table to u29
    u28[0x46:0x4a] = ptr(2, 0x1F000)
    chips = chips | {1: bytes(u28), 2: bytes(u29)}
    # u30's own table stays; u28 now names u29's, which u29 doesn't
    assert cs.tables(chips) == [(2, 0x1F000), (3, 0xF000)]
    names = [s.name for s in cs.read_sounds(chips)]
    assert names == ["u29_000", "u29_002", "u30_000"]


def test_read_chips_by_rom_name(tmp_path):
    z = write_zip(tmp_path / "x.zip", bbb_like(), extra=["u24_v11.bin"])
    chips = cs.read_chips(z)
    assert sorted(chips) == [1, 2, 3, 4]
    assert chips == bbb_like()


def test_no_sound_roms():
    with pytest.raises(cs.CapcomSoundError, match="no sound ROMs"):
        cs.read_sounds({})


def test_playlist_not_where_the_table_says():
    chips = bbb_like()
    u28 = bytearray(chips[1])
    u28[0x400:0x402] = b"\0\x09"                     # count disagrees
    with pytest.raises(cs.CapcomSoundError, match="playlist"):
        cs.read_sounds(chips | {1: bytes(u28)})


def test_frame_pointer_to_no_frame():
    chips = bbb_like()
    u30 = bytearray(chips[3])
    u30[0x203:0x207] = b"\0\0\0\0"                   # header gone
    with pytest.raises(cs.CapcomSoundError, match="no MPEG frame"):
        cs.read_sounds(chips | {3: bytes(u30)})


def test_missing_chip_named():
    chips = bbb_like()
    del chips[3]
    with pytest.raises(cs.CapcomSoundError, match="u30"):
        cs.read_sounds(chips)


# ------------------------------------------------------------------ decode
@pytest.fixture(scope="module")
def mpeg_frames(tmp_path_factory):
    """Four real 144-byte MPEG-1 Layer II frames (32 kbit/s, 32 kHz,
    mono), the kind the board's decoders take."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not installed")
    out = str(tmp_path_factory.mktemp("mp2") / "tone.mp2")
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=32000:duration=0.3",
         "-c:a", "mp2", "-b:a", "32k", "-ac", "1", "-ar", "32000", out],
        check=True)
    data = open(out, "rb").read()
    # ffmpeg sets the header's "original" bit; the ROMs' frames don't
    frames = [data[i:i + 3] + bytes([data[i + 3] & ~0x04]) + data[i + 4:i + 144]
              for i in range(0, len(data) - 143, 144)]
    frames = [f for f in frames if f[:4] in cs.FRAME_SYNC]
    if len(frames) < 4:
        pytest.skip("this ffmpeg makes different MPEG frames")
    return frames[:4]


def test_extract_all_writes_every_sound_whole(tmp_path, mpeg_frames):
    z = write_zip(tmp_path / "bbb.zip", bbb_like(mpeg_frames))
    out = tmp_path / "out"
    seen = []
    r = cs.extract_all(z, str(out), find_ffmpeg(),
                       progress=lambda i, n, d: seen.append((i, n)))
    assert r["samples"] == 3
    assert r["seconds"] == pytest.approx(6 * 1152 / 32000)
    assert seen[-1] == (3, 3)
    rows = list(csv.DictReader(open(out / "audio" / "sounds.csv")))
    assert [(x["file"], x["rom"], x["number"], x["frames"], x["flag"])
            for x in rows] == [
        ("u28_000.wav", "u28", "0", "3", "1"),
        ("u28_002.wav", "u28", "2", "1", "1"),
        ("u30_000.wav", "u30", "0", "2", "70")]
    for x in rows:
        with wave.open(str(out / "audio" / x["file"])) as w:
            assert w.getframerate() == 32000 and w.getnchannels() == 1
            # one-frame sounds too: exactly 1152 samples a frame
            assert w.getnframes() == int(x["frames"]) * 1152
    assert not [f for f in os.listdir(out / "audio") if f.endswith(".part")]


def test_extract_all_cancel(tmp_path, mpeg_frames):
    z = write_zip(tmp_path / "bbb.zip", bbb_like(mpeg_frames))
    assert cs.extract_all(z, str(tmp_path / "o"), find_ffmpeg(),
                          cancel=lambda: True) is None


# ---------------------------------------------------------------- pipelines
BBB_ROMS = ["u1l_b19.bin", "u1h_b19.bin", "u24_v11.bin"]


def _run(pipe):
    done = []
    pipe._done = lambda ok, msg: done.append((ok, msg))
    pipe.run()
    return done[-1]


def test_basic_extract_pipeline(tmp_path, manufacturers_by_key,
                                mpeg_frames):
    z = write_zip(tmp_path / "anything.zip", bbb_like(mpeg_frames),
                  extra=BBB_ROMS)
    out = tmp_path / "proj"
    phases = []
    m = manufacturers_by_key["capcom"]
    pipe = m.make_extract_pipeline(
        z, str(out), lambda *a: None, phases.append, lambda *a: None,
        lambda *a: None, extract_categories=None)
    assert isinstance(pipe, capture.CapcomSoundsPipeline)
    ok, msg = _run(pipe)
    assert ok, msg
    assert "3 Capcom sound(s)" in msg
    assert phases == [0, 1, 2]
    assert (out / "audio" / "u30_000.wav").is_file()
    assert (out / ".checksums.md5").is_file()


def test_basic_extract_not_capcom(tmp_path, manufacturers_by_key):
    z = write_zip(tmp_path / "x.zip", bbb_like())
    pipe = manufacturers_by_key["capcom"].make_extract_pipeline(
        z, str(tmp_path / "o"), lambda *a: None, lambda *a: None,
        lambda *a: None, lambda *a: None)
    ok, msg = _run(pipe)
    assert not ok and "Cannot identify a Capcom game" in msg


def test_capture_boxes_pick_the_pipeline(tmp_path, manufacturers_by_key):
    m = manufacturers_by_key["capcom"]
    cbs = [lambda *a: None] * 4
    both = m.make_capture_pipeline("x.zip", str(tmp_path), *cbs,
                                   also_run_static=True)
    assert isinstance(both, capture.CapcomSoundsPlusCapturePipeline)
    assert m.combined_phases == both.PHASES
    alone = m.make_capture_pipeline("x.zip", str(tmp_path), *cbs,
                                    also_run_static=False)
    assert isinstance(alone, capture.CapcomCapturePipeline)
    assert m.extract_phases == capture.CapcomSoundsPipeline.PHASES


def test_basic_plus_capture_sounds_then_capture(tmp_path, monkeypatch,
                                                manufacturers_by_key,
                                                mpeg_frames):
    """The sounds land first, then the capture runs into the same folder
    with its phases after ours, and one done reports both."""
    ran = {}

    def fake_run(self):
        ran["out"] = self.output_dir
        self._set_phase(0)
        self._set_phase(1)                          # Probe libpinmame
        self._done(True, "captured")

    monkeypatch.setattr(capture.CapcomCapturePipeline, "run", fake_run)
    z = write_zip(tmp_path / "bbb109.zip", bbb_like(mpeg_frames),
                  extra=BBB_ROMS)
    out = tmp_path / "proj"
    phases = []
    pipe = manufacturers_by_key["capcom"].make_capture_pipeline(
        z, str(out), lambda *a: None, phases.append, lambda *a: None,
        lambda *a: None, also_run_static=True)
    ok, msg = _run(pipe)
    assert ok and msg.startswith("Sounds: 3 Capcom sound(s)")
    assert msg.endswith("captured")
    assert ran["out"] == str(out)
    assert phases == [0, 1, 2]       # Detect, Decode audio, Probe libpinmame
    assert pipe.PHASES[2] == "Probe libpinmame"
    assert (out / "audio" / "u28_000.wav").is_file()
    assert (out / ".checksums.md5").is_file()
