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
