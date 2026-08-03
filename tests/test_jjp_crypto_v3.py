"""Tests for the Sonic-era JJPE asset crypto (scheme 3).

The golden vectors below were produced by the reverse-engineered derivation
and cross-checked against real Sonic ciphertext (282/283 staged sample files
decrypt to structurally valid PNG/JPEG/WAV/OGG/TTF/text).  They pin the
algorithm itself — a round-trip test alone would happily pass with the wrong
seeds, so keep these.
"""

import os
import struct
import zlib

import pytest

from pinball_decryptor.plugins.jjp import crypto_v3 as v3
from pinball_decryptor.plugins.jjp.crypto import PRNG, xor_keystream

SAMPLE_PATH = ("/jjpe/gen1/Sonic/edata/graphics/Status Report/"
               "border_vert.png")


def _seeds(path, key):
    p = PRNG()
    v3.set_seeds_for_crypto(p, path, key)
    return (p.s0, p.s1, p.s2, p.s3)


# ---------------------------------------------------------------- seeding


def test_seed_derivation_matches_game():
    assert _seeds(SAMPLE_PATH, b"Sonic") == (
        0xB6B033333E2A7114, 0x1BD709A1481B5EB4,
        0x01890E3BE0881362, 0x4BC003E2EB9137B3)


def test_seed_derivation_core_key():
    assert _seeds(SAMPLE_PATH, b"core") == (
        0xAD2C33337C515C50, 0x36F548A142C69796,
        0x00628367C188C462, 0x96C0C0E2FA6437B3)


def test_keystream_first_16_bytes():
    p = PRNG()
    v3.set_seeds_for_crypto(p, SAMPLE_PATH, b"Sonic")
    assert xor_keystream(b"\x00" * 16, p).hex() == \
        "723c9e12e5260b5e134e4ed85293ef1c"


def test_s2_is_masked_to_58_bits():
    for key in (b"Sonic", b"core", b"X"):
        assert _seeds(SAMPLE_PATH, key)[2] <= v3.S2_MASK


def test_key_rotation_ignores_letter_case():
    """Only bits 0-3 of each key byte are used, so case cannot matter."""
    assert _seeds(SAMPLE_PATH, b"Sonic") == _seeds(SAMPLE_PATH, b"sOnIc")


def test_key_changes_the_seed():
    assert _seeds(SAMPLE_PATH, b"Sonic") != _seeds(SAMPLE_PATH, b"core")


def test_empty_key_rejected():
    with pytest.raises(ValueError):
        _seeds(SAMPLE_PATH, b"")


def test_hash_string_sign_extends():
    """The game uses movsx, so bytes >= 0x80 hash as negative."""
    assert v3.hash_string(b"\x80\x81") == 0xFFFFBE01
    assert v3.hash_string(SAMPLE_PATH) == 0xCED9E7E8


# ------------------------------------------------------- non-ASCII names

CURLY_PATH = "/jjpe/gen1/Sonic/edata/graphics/UI/Eggman’s Lair/bg.png"


def test_non_ascii_path_hashes_raw_filesystem_bytes():
    """Sonic ships assets with a U+2019 apostrophe.

    The game hashes the raw char*, so the key is the UTF-8 on-disk name —
    three bytes for U+2019, each >= 0x80 and therefore sign-extended.
    """
    assert v3.path_bytes(CURLY_PATH) == CURLY_PATH.encode("utf-8")
    assert v3.hash_string(CURLY_PATH) == \
        v3.hash_string(CURLY_PATH.encode("utf-8"))


def test_non_ascii_path_round_trips():
    png = _tiny_png()
    enc = _encrypt_v3(png, CURLY_PATH, "Sonic", lead=64, trail=40)
    scheme, filler = v3.detect_scheme(enc, CURLY_PATH, "Sonic")
    assert (scheme, filler) == (v3.SCHEME_V3, 64)
    assert v3.decrypt_file(enc, filler, CURLY_PATH, "Sonic") == png


def test_non_ascii_path_does_not_raise_in_scheme_2_probe():
    """The pinned scheme-2 detector raises on such names; we must absorb it."""
    from pinball_decryptor.plugins.jjp.crypto import detect_filler_size
    with pytest.raises(UnicodeEncodeError):
        detect_filler_size(os.urandom(2048), CURLY_PATH)
    assert v3.detect_scheme(os.urandom(2048), CURLY_PATH, "Sonic") == (None, -1)


# ---------------------------------------------------------------- key pick


@pytest.mark.parametrize("path,expected", [
    ("/jjpe/gen1/Sonic/edata/graphics/a.png", b"Sonic"),
    ("/jjpe/gen1/Sonic/vf/adj/a.txt", b"Sonic"),
    ("/jjpe/gen1/ecoredata/graphics/a.png", v3.CORE_KEY),
    ("/jjpe/gen1/miscfiles/a.png", v3.CORE_KEY),
    ("/jjpe/gen1/JJPECore/a.png", v3.CORE_KEY),
])
def test_crypto_key_selection(path, expected):
    assert v3.crypto_key(path, "Sonic") == expected


# ------------------------------------------------------------ round trip


def _tiny_png(pixels=b"\x00\xff\x00\xff"):
    def chunk(typ, body):
        return (struct.pack(">I", len(body)) + typ + body
                + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 0, 0, 0, 0)
    raw = b"\x00" + pixels[:2] + b"\x00" + pixels[2:4]
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _big_png(seed=b"\x11\x22\x33\x44"):
    """One valid PNG comfortably larger than the 128-byte shuffle window.

    Concatenated tiny PNGs would not do: trim_trailing_filler stops at the
    first IEND, so such a fixture has a 71-byte "content" and nothing after
    it is reachable.
    """
    def chunk(typ, body):
        return (struct.pack(">I", len(body)) + typ + body
                + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF))
    w = h = 64
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)   # 8-bit RGB
    raw = b"".join(b"\x00" + (seed * (w * 3 // 4 + 1))[:w * 3]
                   for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _encrypt_v3(content, path, game_name, lead, trail):
    """Mirror of the game's decrypt: shuffle then XOR."""
    assert lead % 8 == 0
    body = bytearray(os.urandom(lead) + content + os.urandom(trail))
    # The decrypt un-shuffles after XOR, so encryption shuffles first.
    v3._unshuffle(body, lead)
    p = PRNG()
    v3.set_seeds_for_crypto(p, path, v3.crypto_key(path, game_name))
    return xor_keystream(bytes(body), p)


def test_round_trip_png():
    png = _tiny_png()
    enc = _encrypt_v3(png, SAMPLE_PATH, "Sonic", lead=216, trail=100)
    scheme, filler = v3.detect_scheme(enc, SAMPLE_PATH, "Sonic")
    assert scheme == v3.SCHEME_V3
    assert filler == 216
    assert v3.decrypt_file(enc, filler, SAMPLE_PATH, "Sonic") == png


def test_round_trip_content_shorter_than_shuffle_window():
    """Content under 128 bytes still round-trips (partial shuffle window)."""
    png = _tiny_png()
    assert len(png) < v3.SHUFFLE_BYTES
    enc = _encrypt_v3(png, SAMPLE_PATH, "Sonic", lead=8, trail=8)
    scheme, filler = v3.detect_scheme(enc, SAMPLE_PATH, "Sonic")
    assert (scheme, filler) == (v3.SCHEME_V3, 8)
    assert v3.decrypt_file(enc, filler, SAMPLE_PATH, "Sonic") == png


def test_wrong_key_does_not_decrypt():
    enc = _encrypt_v3(_tiny_png(), SAMPLE_PATH, "Sonic", lead=216, trail=100)
    assert v3.detect_filler_size(enc, SAMPLE_PATH, "Wonka") < 0


def test_shuffle_window_is_exactly_128_bytes():
    """A wider or narrower window corrupts the content."""
    png = _tiny_png(b"\x11\x22\x33\x44") * 40      # comfortably > 128 bytes
    enc = _encrypt_v3(png, SAMPLE_PATH, "Sonic", lead=216, trail=0)
    assert v3.decrypt_file(enc, 216, SAMPLE_PATH, "Sonic",
                           trim=False) == png
    original = v3.SHUFFLE_BYTES
    try:
        for bad in (64, 120, 136, 256):
            v3.SHUFFLE_BYTES = bad
            assert v3.decrypt_file(enc, 216, SAMPLE_PATH, "Sonic",
                                   trim=False) != png
    finally:
        v3.SHUFFLE_BYTES = original


# ------------------------------------------------------------- dispatch


def test_legacy_assets_still_take_the_legacy_path():
    """Scheme 2 must be tried first so pre-Sonic titles are untouched."""
    from pinball_decryptor.plugins.jjp.crypto import PRNG as P2
    png = _tiny_png()
    path = "/jjpe/gen1/HarryPotter/edata/graphics/a.png"
    body = os.urandom(300) + png
    p = P2()
    p.set_seeds_for_crypto(path)
    enc = xor_keystream(body, p)
    scheme, filler = v3.detect_scheme(enc, path, "HarryPotter")
    assert scheme == v3.SCHEME_LEGACY
    assert filler == 300


def test_detect_scheme_gives_up_cleanly():
    assert v3.detect_scheme(os.urandom(4096), SAMPLE_PATH, "Sonic") == \
        (None, -1)


# ------------------------------------------------------- trailing filler


def test_trim_png():
    png = _tiny_png()
    assert v3.trim_trailing_filler(png + os.urandom(200), SAMPLE_PATH) == png


def test_trim_wav():
    body = b"WAVEfmt " + b"\x00" * 16 + b"data" + b"\x01" * 8
    wav = b"RIFF" + struct.pack("<I", len(body)) + body
    assert v3.trim_trailing_filler(wav + os.urandom(64), "/a/b.wav") == wav


def test_trim_jpeg():
    jpg = b"\xff\xd8\xff\xe0" + b"\x42" * 40 + b"\xff\xd9"
    assert v3.trim_trailing_filler(jpg + b"\x00\x01\x02", "/a/b.jpg") == jpg


def test_trim_text_keeps_all_real_text():
    txt = (b"sprite_list = {\r\n\tsprite_id_a,\r\n\tsprite_id_b,\r\n};\r\n")
    out = v3.trim_trailing_filler(txt + os.urandom(200), "/a/b.txt")
    assert out.startswith(txt)
    assert len(out) < len(txt) + 32


def test_psd_signature_is_supported():
    """Sonic ships a .psd; the pinned scheme-2 magic table has no entry."""
    from pinball_decryptor.plugins.jjp.crypto import _MAGIC_TABLE
    assert ".psd" not in _MAGIC_TABLE          # why _EXTRA_MAGIC exists
    psd = b"8BPS\x00\x01" + b"\x00" * 200
    path = "/jjpe/gen1/Sonic/edata/graphics/Mini LED/x.psd"
    enc = _encrypt_v3(psd, path, "Sonic", lead=464, trail=48)
    scheme, filler = v3.detect_scheme(enc, path, "Sonic")
    assert (scheme, filler) == (v3.SCHEME_V3, 464)
    assert v3.decrypt_file(enc, filler, path, "Sonic").startswith(b"8BPS")


def test_trim_leaves_unknown_formats_alone():
    blob = b"\x1a\x45\xdf\xa3" + os.urandom(500)
    assert v3.trim_trailing_filler(blob, "/a/b.webm") == blob


# --------------------------------------------------- fl_decrypted.dat I/O


def _entries():
    from pinball_decryptor.plugins.jjp.filelist import FileEntry
    return [
        FileEntry(path=CURLY_PATH, filler_size=336,
                  crc_encrypted=0x11111111, crc_decrypted=0x22222222),
        FileEntry(path="/jjpe/gen1/Sonic/edata/graphics/plain.png",
                  filler_size=8, crc_encrypted=3, crc_decrypted=4),
    ]


def test_filelist_round_trips_non_ascii_paths(tmp_path):
    """The pinned writer raises on these names; ours must not, and the
    pinned parser must still read what we wrote."""
    from pinball_decryptor.plugins.jjp.filelist import parse_fl_dat, write_fl_dat
    e = _entries()
    p = tmp_path / "fl_decrypted.dat"

    with pytest.raises(UnicodeEncodeError):
        write_fl_dat(e, str(tmp_path / "pinned.dat"))

    v3.write_filelist(e, str(p))
    back = parse_fl_dat(v3.read_filelist_text(str(p)))
    assert [x.path for x in back] == [x.path for x in e]
    assert [x.filler_size for x in back] == [336, 8]
    assert back[0].crc_encrypted == 0x11111111


def test_filelist_ascii_output_matches_pinned_writer(tmp_path):
    """ASCII-only titles must get byte-identical sidecars."""
    from pinball_decryptor.plugins.jjp.filelist import write_fl_dat
    e = _entries()[1:]
    a, b = tmp_path / "a.dat", tmp_path / "b.dat"
    write_fl_dat(e, str(a))
    v3.write_filelist(e, str(b))
    assert a.read_bytes() == b.read_bytes()


def test_read_filelist_text_falls_back_to_latin1(tmp_path):
    """Sidecars written by older versions are latin-1, not valid UTF-8."""
    p = tmp_path / "old.dat"
    p.write_bytes("/a/caf\xe9.png,8,1,2\n".encode("latin-1"))
    from pinball_decryptor.plugins.jjp.filelist import parse_fl_dat
    back = parse_fl_dat(v3.read_filelist_text(str(p)))
    assert back[0].path == "/a/caf\xe9.png"


def test_read_filelist_text_handles_empty_file(tmp_path):
    """Must not degrade into being treated as a path by parse_fl_dat."""
    from pinball_decryptor.plugins.jjp.filelist import parse_fl_dat
    p = tmp_path / "empty.dat"
    p.write_bytes(b"")
    assert parse_fl_dat(v3.read_filelist_text(str(p))) == []


# ----------------------------------------------------------- re-encrypt


def _scheme3_asset(content, lead=216, trail=212):
    return _encrypt_v3(content, SAMPLE_PATH, "Sonic", lead=lead, trail=trail)


def test_reencrypt_keeps_size_and_crc():
    from pinball_decryptor.plugins.jjp.crypto import crc32_buf
    png = _big_png()
    orig = _scheme3_asset(png)
    edited = bytearray(png)
    edited[40:44] = bytes((0xDE, 0xAD, 0xBE, 0xEF))
    out = v3.reencrypt_asset(orig, bytes(edited), SAMPLE_PATH, "Sonic")
    # The loader checks exactly these two things.
    assert len(out) == len(orig)
    assert crc32_buf(out) == crc32_buf(orig)
    # ...and the game gets our edit back.
    back = v3.decrypt_file(out, 216, SAMPLE_PATH, "Sonic", trim=False)
    assert back[:len(edited)] == bytes(edited)


def test_reencrypt_preserves_both_pads():
    png = _big_png()
    orig = _scheme3_asset(png)
    before = v3.decrypt_file(orig, 216, SAMPLE_PATH, "Sonic", trim=False)
    edited = bytearray(png)
    edited[8:12] = bytes((0, 1, 2, 3))
    out = v3.reencrypt_asset(orig, bytes(edited), SAMPLE_PATH, "Sonic")
    after = v3.decrypt_file(out, 216, SAMPLE_PATH, "Sonic", trim=False)
    # trailing pad byte-identical; lead pad only the 4 forge bytes differ
    assert after[len(edited):] == before[len(edited):]


def test_reencrypt_identity_is_a_noop_for_content():
    png = _big_png()
    orig = _scheme3_asset(png)
    out = v3.reencrypt_asset(orig, png, SAMPLE_PATH, "Sonic")
    from pinball_decryptor.plugins.jjp.crypto import crc32_buf
    assert crc32_buf(out) == crc32_buf(orig) and len(out) == len(orig)
    assert v3.decrypt_file(out, 216, SAMPLE_PATH, "Sonic",
                           trim=False)[:len(png)] == png


def test_forged_bytes_land_in_the_lead_pad_only():
    """Read out of the game's own code (dump of the decrypted .text):

        006a9ce7  xor   edi, edi                  ; seed 0
        006a9ced  mov   rdx, r12                  ; r12 = full file size
        006a9cf0  mov   rsi, r11                  ; r11 = buffer start
        006a9d19  call  0x849700                  ; crc32(0, buf, size)
        006a9d1e  cmp   dword ptr [rbx + 0x18], eax
        006a9d76  mov   edx, dword ptr [rbx + 0x20]   ; f1
        006a9d80  lea   rsi, [r15 + rdx]              ; shuffle starts AT
        006a9d86  ...   pshufb                        ; the content

    So the check covers the whole file, and the 128-byte shuffle begins at
    the content.  The forge therefore has to stay strictly inside the lead
    pad: a byte at or after f1 would be shuffled and would land in the
    content the game keeps.
    """
    lead, trail = 216, 96
    png = _big_png()
    orig = _scheme3_asset(png, lead=lead, trail=trail)
    edited = bytearray(png)
    edited[40:44] = bytes((0xDE, 0xAD, 0xBE, 0xEF))
    out = v3.reencrypt_asset(orig, bytes(edited), SAMPLE_PATH, "Sonic")

    differing = [i for i in range(len(orig)) if orig[i] != out[i]]
    in_lead = [i for i in differing if i < lead]
    in_trail = [i for i in differing if i >= lead + len(png)]
    assert in_lead, "the CRC forge has to rewrite part of the lead pad"
    assert min(in_lead) >= lead - 4 and max(in_lead) < lead, (
        "the forge must use the last 4 bytes of the lead pad and nothing "
        "else: a byte at or after f1 would be shuffled into the content")
    assert not in_trail, "the trailing pad must come through untouched"

    # Same content in, byte-identical file out — no gratuitous rewrite.
    assert v3.reencrypt_asset(orig, png, SAMPLE_PATH, "Sonic") == orig


def test_crc_scope_is_the_whole_file_including_the_trailing_pad():
    """The trailing pad is new in scheme 3, and the loader's crc32 length is
    the full size read off disk (r12), not size-minus-pads — so a rewrite
    has to keep the whole-file CRC, which is what reencrypt_asset targets.
    Guards against someone "fixing" this to hash only the content."""
    from pinball_decryptor.plugins.jjp.crypto import crc32_buf
    trail = 96
    png = _big_png()
    orig = _scheme3_asset(png, trail=trail)
    out = v3.reencrypt_asset(orig, png, SAMPLE_PATH, "Sonic")
    assert crc32_buf(out) == crc32_buf(orig)
    # The trailing pad is inside that scope: its bytes are unchanged, and
    # dropping it changes the hash, so it cannot be excluded by accident.
    assert out[-trail:] == orig[-trail:]
    assert crc32_buf(out[:-trail]) != crc32_buf(out)


def test_reencrypt_rejects_a_different_size():
    png = _big_png()
    orig = _scheme3_asset(png)
    with pytest.raises(v3.SizeMismatch) as ex:
        v3.reencrypt_asset(orig, png + b"extra", SAMPLE_PATH, "Sonic")
    assert "fl.dat" in str(ex.value)


def test_reencrypt_needs_a_scheme3_asset():
    with pytest.raises(ValueError):
        v3.reencrypt_asset(os.urandom(4096), b"x" * 16, SAMPLE_PATH, "Sonic")


# ------------------------------------------------------- scheme detection


def test_detect_write_scheme_picks_v3():
    from pinball_decryptor.plugins.jjp.pipeline import _detect_write_scheme
    from pinball_decryptor.plugins.jjp.filelist import FileEntry
    orig = _scheme3_asset(_tiny_png() * 40)
    entries = [FileEntry(path=SAMPLE_PATH, filler_size=216,
                         crc_encrypted=0, crc_decrypted=0)]
    assert _detect_write_scheme(entries, lambda e: orig, "Sonic") ==         v3.SCHEME_V3


def test_detect_write_scheme_leaves_legacy_alone():
    from pinball_decryptor.plugins.jjp.pipeline import _detect_write_scheme
    from pinball_decryptor.plugins.jjp.filelist import FileEntry
    from pinball_decryptor.plugins.jjp.crypto import PRNG as P2
    path = "/jjpe/gen1/HarryPotter/edata/graphics/a.png"
    p = P2()
    p.set_seeds_for_crypto(path)
    enc = xor_keystream(os.urandom(300) + _tiny_png(), p)
    entries = [FileEntry(path=path, filler_size=300,
                         crc_encrypted=0, crc_decrypted=0)]
    assert _detect_write_scheme(entries, lambda e: enc, "HarryPotter") ==         v3.SCHEME_LEGACY


def test_detect_write_scheme_refuses_to_pick_when_unreadable():
    """An image we can't sample must not silently pick a cipher — either one.

    This used to fall back to legacy, on the reasoning that not switching is
    the conservative move.  It isn't: on a scheme-3 image legacy IS the
    switch, and it's undetectable from inside the app, because the write
    forges the checksums of whatever routine it used.  A Sonic build shipped
    two clips that way and the machine played them black (PAD-28).
    """
    from pinball_decryptor.plugins.jjp.pipeline import (_detect_write_scheme,
                                                        PipelineError)
    from pinball_decryptor.plugins.jjp.filelist import FileEntry

    def boom(entry):
        raise OSError("no such file")

    entries = [FileEntry(path="/x/y.png", filler_size=8,
                         crc_encrypted=0, crc_decrypted=0)]
    with pytest.raises(PipelineError):
        _detect_write_scheme(entries, boom, "Wonka")


def test_encrypt_one_routes_by_scheme():
    from pinball_decryptor.plugins.jjp.pipeline import _encrypt_one
    from pinball_decryptor.plugins.jjp.filelist import FileEntry
    from pinball_decryptor.plugins.jjp.crypto import crc32_buf
    png = _big_png()
    orig = _scheme3_asset(png)
    entry = FileEntry(path=SAMPLE_PATH, filler_size=216,
                      crc_encrypted=0, crc_decrypted=0)
    out, note = _encrypt_one(v3.SCHEME_V3, entry, png, "Sonic",
                             lambda e: orig)
    assert crc32_buf(out) == crc32_buf(orig)
    assert "scheme 3" in note


# -------------------------------------------------------------- packaging


def test_module_is_deployed_and_bundled():
    """crypto_v3 must ship everywhere crypto.py does or Sonic silently fails.

    It is deployed as *source* into WSL/Docker and bundled by PyInstaller on
    macOS; missing either makes the decrypt phase die at import time.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pipeline = os.path.join(root, "pinball_decryptor", "plugins", "jjp",
                            "pipeline.py")
    with open(pipeline, encoding="utf-8") as f:
        src = f.read()
    assert src.count('for module in ("crypto.py", "crypto_v3.py", '
                     '"filelist.py")') == 2

    build = os.path.join(root, "installer", "build_macos.sh")
    with open(build, encoding="utf-8") as f:
        assert "jjp/crypto_v3.py:pinball_decryptor/plugins/jjp" in f.read()


def test_deployed_module_can_import_flat(tmp_path):
    """Deployed as jjp_crypto_v3.py it must fall back off the relative import."""
    import shutil
    import subprocess
    import sys
    src = os.path.dirname(os.path.abspath(v3.__file__))
    for mod in ("crypto.py", "crypto_v3.py"):
        shutil.copy(os.path.join(src, mod), tmp_path / ("jjp_" + mod))
    # Importing is not enough: every code path that runs inside WSL has to
    # work flat.  A call-time `from .crypto import ...` in the CRC forge
    # imported fine and then failed on all 16,440 files at re-encrypt time,
    # so exercise the real work here, not just the module surface.
    png = _big_png()
    enc = _encrypt_v3(png, SAMPLE_PATH, "Sonic", lead=216, trail=212)
    (tmp_path / "asset.bin").write_bytes(enc)
    (tmp_path / "content.bin").write_bytes(png)

    script = (
        "import jjp_crypto_v3 as m\n"
        "from jjp_crypto import crc32_buf\n"
        "orig = open('asset.bin','rb').read()\n"
        "content = open('content.bin','rb').read()\n"
        "s, f = m.detect_scheme(orig, %r, 'Sonic')\n"
        "out = m.reencrypt_asset(orig, content, %r, 'Sonic')\n"
        "print(s, f, len(out) == len(orig), "
        "crc32_buf(out) == crc32_buf(orig))\n" % (SAMPLE_PATH, SAMPLE_PATH))
    r = subprocess.run([sys.executable, "-c", script],
                       cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "3 216 True True"
