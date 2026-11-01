"""Cactus Canyon (CGC `pin` engine, DCS audio) wiring tests.

Fixture-free: these don't need the 14 GB card image or the 6 MB DCS
ROM set.  They verify the plumbing that wires Cactus Canyon into the
shared CGC plugin:

  * the game DB entry + filename detection,
  * the DCS sound-ROM filename selector (s2..s7.rom, not the game ROM),
  * the throwaway-zip naming rule DCSExplorer's loader depends on,
  * that decoded DCS audio is excluded from the Write baseline/diff.

The actual DCS decode (DCSExplorer) is covered by the Williams DCS path;
here we only assert the Cactus-Canyon-specific glue.
"""

import os
import re

from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline
from pinball_decryptor.plugins.cgc.formats import MBR_MAGIC, detect_game
from pinball_decryptor.plugins.cgc.games import GAME_DB


def _fake_img(path):
    """Write a minimal 512-byte file with a valid MBR signature."""
    buf = bytearray(512)
    buf[510:512] = MBR_MAGIC
    path.write_bytes(bytes(buf))
    return str(path)


def test_game_db_entry():
    info = GAME_DB["cactus_canyon"]
    assert info["display"] == "Cactus Canyon"
    # pin engine lives under the debian user (vs Pulp Fiction's ubuntu).
    assert info["asset_subtree"] == "/home/debian/pin"
    assert info["data_dir"] == "ccdata"


def test_detect_from_filename(tmp_path):
    # The card image is named so its basename contains the title.
    assert detect_game(_fake_img(tmp_path / "CactusCanyon_cc113_card.img")) \
        == "cactus_canyon"
    assert detect_game(_fake_img(tmp_path / "cc113_master.img")) \
        == "cactus_canyon"
    # A non-matching name shouldn't be claimed as Cactus Canyon.
    assert detect_game(_fake_img(tmp_path / "PulpFiction102Installer.img")) \
        == "pulp_fiction"


def test_dcs_rom_selector():
    rx = cgc_pipeline._DCS_ROM_RE
    for n in range(2, 8):
        assert rx.match(f"s{n}.rom"), f"s{n}.rom should be a DCS sound ROM"
    assert rx.match("S7.ROM")  # case-insensitive
    # The WPC-95 game CPU ROM is NOT a DCS sound ROM.
    assert not rx.match("cc_g11.1_3")
    assert not rx.match("readme.txt")


def test_dcs_zip_name_matches_loader_rule():
    # DCSExplorer's loader special-cases Cactus Canyon's mislabeled U7
    # ROM only when the zip basename matches ^cc_\d.*  -- guard against a
    # future rename silently dropping s7.rom.
    assert re.match(r"^cc_\d.*", cgc_pipeline._DCS_ZIP_NAME)
    assert cgc_pipeline._DCS_ZIP_NAME.endswith(".zip")


def test_derived_dirs_excluded_from_write_diff(tmp_path):
    # Every decoded output dir (DCS audio, new audio, display art, dmd) must
    # be skipped by the Write diff -- they're derived from eMMC blobs, not
    # loose eMMC files; writing them back would corrupt the image. Repack of
    # each into its source blob is separate, future work.
    assets = tmp_path
    for sub in cgc_pipeline._DERIVED_SUBDIRS:
        d = assets / sub
        d.mkdir()
        (d / "decoded_0001.bin").write_bytes(b"derived")
    # A real eMMC asset that SHOULD be tracked.
    (assets / "fram.bin").write_bytes(b"\x00" * 16)

    changed, missing = cgc_pipeline._diff_assets(str(assets), {})
    assert "fram.bin" in changed
    for sub in cgc_pipeline._DERIVED_SUBDIRS:
        assert not any(rel.startswith(f"{sub}/") for rel in changed), \
            (sub, changed)


def test_usb_audio_decoder_constants():
    from pinball_decryptor.plugins.cgc import cc_usb_audio
    # Stage-2 key is 13 words; export entry points exist.
    assert len(cc_usb_audio.DCSXOR13) == 13
    assert hasattr(cc_usb_audio, "extract_usb_audio")
    assert hasattr(cc_usb_audio, "UsbAudioError")


def test_art_decoder_keys_and_magic():
    from pinball_decryptor.plugins.cgc import cc_art
    # The five de-obfuscation keys have the prime lengths the cipher indexes by.
    assert [len(k) for k in (cc_art._K1, cc_art._K2, cc_art._K3,
                             cc_art._K4, cc_art._K5)] == [3, 7, 13, 17, 19]
    # Wrong magic is rejected cleanly.
    import pytest
    with pytest.raises(cc_art.ArtError):
        cc_art.cgc_deobfuscate(b"\x00\x00\x00\x00BADX" + b"\x00" * 64)


# --- repack cipher inverses (fixture-free: no 185 MB/70 MB blobs needed) ---

def test_usb_cipher_is_invertible():
    import pytest
    pytest.importorskip("numpy")
    import os
    from pinball_decryptor.plugins.cgc import cc_usb_audio
    # A pseudo-random buffer (multiple of 4) must survive decrypt -> encrypt.
    buf = bytes((i * 2654435761) & 0xFF for i in range(4096))
    assert cc_usb_audio._dcs_encrypt(cc_usb_audio._dcs_decrypt(buf)) == buf


def test_art_cipher_is_invertible():
    import pytest
    pytest.importorskip("numpy")
    import struct
    from pinball_decryptor.plugins.cgc import cc_art
    payload = bytes((i * 1103515245 + 12345) & 0xFF for i in range(2003))
    raw = struct.pack("<I", 0) + b"CCGC" + b"\x00" * 8 + payload
    # deobfuscate(raw) transforms payload; reobfuscate must recover it exactly.
    assert cc_art.cgc_reobfuscate(cc_art.cgc_deobfuscate(raw)) == payload


def test_rgb565_roundtrip_safe_colors():
    import pytest
    pytest.importorskip("numpy")
    import numpy as np
    from pinball_decryptor.plugins.cgc import cc_art
    # RGB565-exact colours (5/6/5-bit-aligned) survive RGBA<->565 round-trip.
    arr = np.array([[[255, 0, 0, 255], [0, 255, 0, 255]],
                    [[0, 0, 255, 255], [0, 0, 0, 0]]], dtype=np.uint8)
    words = cc_art._rgba_to_rgb565(arr)
    back = cc_art._rgb565_to_rgba(words, 2, 2)
    assert np.array_equal(back, arr)


def test_art_rle_decoder():
    import pytest
    pytest.importorskip("numpy")
    import numpy as np
    from pinball_decryptor.plugins.cgc import cc_art
    # Token stream: transparent-3, literal-2 (pixels 0x1234,0x5678), transparent-1.
    src = np.array([0x8003, 0x0002, 0x1234, 0x5678, 0x8001], dtype=np.uint16)
    out = cc_art._decode_rle_words(src, 6)
    assert list(out) == [0, 0, 0, 0x1234, 0x5678, 0]
    # A no-op token (0x0000) is consumed but emits nothing.
    src2 = np.array([0x0000, 0x0001, 0x0ABC, 0x8002], dtype=np.uint16)
    assert list(cc_art._decode_rle_words(src2, 3)) == [0x0ABC, 0, 0]


def test_cc_repack_prestep_noop_on_non_cc_dir(tmp_path):
    # _repack_modified_cc_assets runs unconditionally in _diff_assets for every
    # CGC title; it must be a harmless no-op when the CC dirs/blobs are absent.
    (tmp_path / "some_other.wav").write_bytes(b"x")
    cgc_pipeline._repack_modified_cc_assets(str(tmp_path))  # must not raise
    assert sorted(p.name for p in tmp_path.iterdir()) == ["some_other.wav"]


# --- usb.so sounds at their own length (PAD-919) ---------------------------

def _bank(tmp_path, sounds):
    """An encrypted usb.so holding *sounds* ([(name, pcm)]) laid out the way
    CGC's is: records in order, zero fill after each, hdr[8]^hdr[0xc] = size."""
    import struct
    from pinball_decryptor.plugins.cgc import cc_usb_audio as U
    table = 16 + len(sounds) * 0x58
    dec = bytearray(table)
    struct.pack_into("<4I", dec, 0, len(sounds), 0x180A070A, 0, 0x6C84)
    for i, (name, pcm) in enumerate(sounds):
        o = 16 + i * 0x58
        dec[o + 4:o + 4 + len(name)] = name.encode()
        struct.pack_into("<4I", dec, o + 0x44, len(dec),
                         U.frames_for(len(pcm) // 2), len(pcm), len(pcm) // 2)
        dec += pcm + b"\x00" * 800
    struct.pack_into("<I", dec, 8, len(dec) ^ 0x6C84)
    path = tmp_path / "usb.so"
    path.write_bytes(U._dcs_encrypt(bytes(dec)))
    return str(path)


def _wav(path, pcm):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(pcm)


def _records(path):
    import struct
    from pinball_decryptor.plugins.cgc import cc_usb_audio as U
    dec = U.decode_usb_so(path)        # the loader's size check
    out = []
    for i in range(struct.unpack_from("<I", dec, 0)[0]):
        off, frames, dlen, samples = struct.unpack_from(
            "<4I", dec, 16 + i * 0x58 + 0x44)
        assert dlen == 2 * samples and frames == U.frames_for(samples)
        # the player reads whole frames: they stay inside the bank
        assert off + -(-frames * 1152000 // 3125) * 2 <= len(dec)
        out.append(bytes(dec[off:off + dlen]))
    return out


def _tone(n, k):
    return bytes((i * k) & 0xFF for i in range(2 * n))


def test_usb_frames_match_the_stock_bank():
    # Values read from Cactus Canyon 1.13's usb.so: (sample_count, frames).
    from pinball_decryptor.plugins.cgc import cc_usb_audio as U
    for samples, frames in ((4800, 14), (10030, 28), (369006, 1001),
                            (2192005, 5947), (2123364, 5760), (169501, 460)):
        assert U.frames_for(samples) == frames


def test_usb_repack_keeps_each_sounds_own_length(tmp_path):
    import pytest
    pytest.importorskip("numpy")
    from pinball_decryptor.plugins.cgc import cc_usb_audio as U
    stock = [("a.wav", _tone(4000, 3)), ("music.wav", _tone(9000, 5)),
             ("b.wav", _tone(3000, 7)), ("c.wav", _tone(5000, 11))]
    usb = _bank(tmp_path, stock)
    na = tmp_path / "new_audio"
    na.mkdir()
    for i, (name, pcm) in enumerate(stock):
        _wav(na / f"{i:04d}_{name}", pcm)
    out = str(tmp_path / "out.so")

    # Nothing edited: nothing written.
    s = U.repack_usb(usb, str(na), out)
    assert s["modified_count"] == 0 and not os.path.exists(out)

    # A song three times the slot, and a shorter sound: both kept whole.
    song, short = _tone(27000, 13), _tone(1200, 17)
    _wav(na / "0001_music.wav", song)
    _wav(na / "0002_b.wav", short)
    s = U.repack_usb(usb, str(na), out)
    assert s["modified_count"] == 2
    assert [n for n, *_ in s["longer"]] == ["0001_music.wav"]
    assert s["size"] == os.path.getsize(out) > os.path.getsize(usb)
    assert _records(out) == [stock[0][1], song, short, stock[3][1]]

    # The grown bank is a valid original for the next build: same WAVs, no
    # change; the stock music back, the bank lays it out at its stock length.
    assert U.repack_usb(out, str(na), str(tmp_path / "x.so"))[
        "modified_count"] == 0
    _wav(na / "0001_music.wav", stock[1][1])
    U.repack_usb(out, str(na), str(tmp_path / "back.so"))
    assert _records(str(tmp_path / "back.so"))[1] == stock[1][1]


def test_usb_repack_fit_cuts_to_the_stock_slot(tmp_path):
    import pytest
    pytest.importorskip("numpy")
    from pinball_decryptor.plugins.cgc import cc_usb_audio as U
    stock = [("a.wav", _tone(4000, 3)), ("music.wav", _tone(9000, 5))]
    usb = _bank(tmp_path, stock)
    na = tmp_path / "new_audio"
    na.mkdir()
    _wav(na / "0001_music.wav", _tone(27000, 13))
    out = str(tmp_path / "out.so")
    s = U.repack_usb(usb, str(na), out, fit=True)
    assert os.path.getsize(out) == os.path.getsize(usb)
    assert s["cut"] == [("0001_music.wav", 9000 / 48000, 27000 / 48000)]
    assert _records(out)[1] == _tone(27000, 13)[:18000]


class _Exec:
    """debugfs on a game partition holding *files* ({inner path: host file})
    with *free* bytes free."""

    def __init__(self, files, free):
        self.files, self.free = files, free

    def to_exec_path(self, p):
        return p

    def run(self, cmd, timeout=None):
        import shlex
        import shutil
        req = shlex.split(cmd)[2]
        if req == "stats":
            return (f"Block size:               4096\n"
                    f"Free blocks:              {self.free // 4096}\n")
        op, *args = shlex.split(req)
        if op == "stat":
            return f"  Size: {os.path.getsize(self.files[args[0]])}\n"
        if op == "dump":
            shutil.copyfile(self.files[args[0]], args[1])
            return ""
        raise AssertionError(cmd)


def _fit(tmp_path, free):
    import pytest
    pytest.importorskip("numpy")
    from pinball_decryptor.plugins.cgc import cc_usb_audio as U
    stock = [("a.wav", _tone(4000, 3)), ("music.wav", _tone(9000, 5))]
    card = _bank(tmp_path, stock)
    assets = tmp_path / "assets"
    (assets / "new_audio").mkdir(parents=True)
    _wav(assets / "new_audio" / "0001_music.wav", _tone(27000, 13))
    (assets / "ccdata").mkdir()
    built = str(assets / "ccdata" / "usb.so")
    U.repack_usb(card, str(assets / "new_audio"), built)
    p = cgc_pipeline.WritePipeline.__new__(cgc_pipeline.WritePipeline)
    p.assets_dir = str(assets)
    p.executor = _Exec({"/home/debian/pin/ccdata/usb.so": card}, free)
    logs = []
    p._log = lambda m, level="info": logs.append((level, m))
    p._fit_cc_bank("inner.img", {"ccdata/usb.so": built}, "/home/debian/pin")
    return card, built, logs


def test_cc_write_keeps_a_longer_bank_that_fits(tmp_path):
    card, built, logs = _fit(tmp_path, 40 * 1024 * 1024)
    assert os.path.getsize(built) > os.path.getsize(card)
    assert _records(built)[1] == _tone(27000, 13)
    assert any("grows by" in m for _, m in logs)
    assert not any(level == "warning" for level, _ in logs)


def test_cc_write_cuts_sounds_back_when_the_card_is_full(tmp_path):
    card, built, logs = _fit(tmp_path, cgc_pipeline.CC_BANK_HEADROOM)
    assert os.path.getsize(built) == os.path.getsize(card)
    assert _records(built)[1] == _tone(27000, 13)[:18000]
    warn = "\n".join(m for level, m in logs if level == "warning")
    assert "0001_music.wav: 0.6 s cut to 0.2 s" in warn


def test_cc_repack_failure_is_reported(tmp_path):
    # A usb.so that is not a bank cannot be rebuilt: the build used to ship
    # the stock one silently, so the user's sound edits never reached the card.
    (tmp_path / "ccdata").mkdir()
    (tmp_path / "ccdata" / "usb.so").write_bytes(b"\x00" * 64)
    (tmp_path / "new_audio").mkdir()
    logs = []
    cgc_pipeline._repack_modified_cc_assets(
        str(tmp_path), log=lambda m, level="info": logs.append((level, m)))
    assert any(level == "warning" and "ccdata/usb.so" in m
               for level, m in logs)
