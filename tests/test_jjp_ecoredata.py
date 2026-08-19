"""The shared engine trees (``ecoredata`` / ``JJPECore`` / ``miscfiles``).

These assets are keyed and padded exactly like game assets, so the risk here is
not the cipher — it is the path bookkeeping.  Extract strips a prefix, Write
puts one back, and the two roots use *different* prefixes; get that wrong and a
replacement is written to a path that does not exist, or a game asset is routed
into the engine tree.  Most of these tests pin that mapping in both directions.
"""

import os
import zlib

import pytest

from pinball_decryptor.plugins.jjp import ecoredata as ec
from pinball_decryptor.plugins.jjp.crypto import (PRNG, decrypt_file,
                                                  encrypt_file, xor_keystream)

EDATA_PREFIX = "/jjpe/gen1/Pirates/edata/"

#: (absolute in-image path, extract-relative path, is-shared)
PATH_CASES = [
    ("/jjpe/gen1/Pirates/edata/sound/music/BG_Plunder.ogg",
     "sound/music/BG_Plunder.ogg", False),
    ("/jjpe/gen1/Pirates/edata/graphics/Bonus/Bonus 1_1.webm",
     "graphics/Bonus/Bonus 1_1.webm", False),
    ("/jjpe/gen1/ecoredata/sound/sound_test/music.wav",
     "ecoredata/sound/sound_test/music.wav", True),
    ("/jjpe/gen1/miscfiles/eua/agreement.pdf",
     "miscfiles/eua/agreement.pdf", True),
    ("/jjpe/gen1/JJPECore/graphics/button.png",
     "JJPECore/graphics/button.png", True),
]


@pytest.mark.parametrize("abs_path,rel,shared", PATH_CASES)
def test_is_shared_rel(abs_path, rel, shared):
    assert ec.is_shared_rel(rel) is shared


@pytest.mark.parametrize("abs_path,rel,shared", PATH_CASES)
def test_write_reverse_mapping(abs_path, rel, shared):
    """Write must land every asset back on the exact path Extract took it from."""
    assert ec.image_path_for_rel(rel, EDATA_PREFIX) == abs_path


def test_game_assets_keep_their_original_mapping():
    """A game asset must be composed exactly as before this feature existed."""
    for _abs, rel, shared in PATH_CASES:
        if not shared:
            assert ec.image_path_for_rel(rel, EDATA_PREFIX) == EDATA_PREFIX + rel


def test_windows_separators_still_map():
    """_phase_scan yields OS-native separators on Windows."""
    rel = os.path.join("ecoredata", "sound", "sound_test", "music.wav")
    assert ec.is_shared_rel(rel)
    assert ec.image_path_for_rel(rel, EDATA_PREFIX) == \
        "/jjpe/gen1/ecoredata/sound/sound_test/music.wav"


def test_lookalike_directory_is_not_treated_as_shared():
    """Only the real trees count — a game folder merely starting with the same
    letters (or a nested copy) must not be routed to the engine root."""
    assert not ec.is_shared_rel("ecoredata_backup/x.wav")
    assert not ec.is_shared_rel("graphics/ecoredata/x.png")


# --------------------------------------------------------------------------
# plaintext detection
# --------------------------------------------------------------------------

def test_plaintext_members_are_detected():
    """POTC ships miscfiles as ordinary PDFs/PNGs beside encrypted ecoredata,
    so 'is it encrypted' is a per-file question, not a per-tree one."""
    assert ec.looks_plaintext(b"%PDF-1.4\n...", "/x/a.pdf")
    assert ec.looks_plaintext(b"\x89PNG\r\n\x1a\n", "/x/a.png")
    assert ec.looks_plaintext(b"RIFF....WAVE", "/x/a.wav")


def test_ciphertext_is_not_mistaken_for_plaintext():
    assert not ec.looks_plaintext(bytes(range(64)), "/x/a.wav")


# --------------------------------------------------------------------------
# decrypt -> replace -> encrypt, without fl.dat
# --------------------------------------------------------------------------

def _encrypt_scheme2(content, filler_size, path):
    """Build a scheme-2 asset the way the machine ships one."""
    buf = bytes(bytearray(filler_size)) + content
    prng = PRNG()
    prng.set_seeds_for_crypto(path)
    return xor_keystream(buf, prng)


def test_replacement_round_trips_and_forges_both_crcs():
    """The loader checks a CRC of the ciphertext (n2) and one of the content
    (n3), both normally read from the dongle-encrypted fl.dat.  Recovering them
    from the original asset is what makes engine assets replaceable at all.
    """
    path = "/jjpe/gen1/ecoredata/sound/sound_test/music.wav"
    filler = 264
    original_content = b"RIFF" + b"\x00" * 200 + b"WAVEdata" + bytes(range(256))
    original = _encrypt_scheme2(original_content, filler, path)

    n2 = zlib.crc32(original) & 0xFFFFFFFF
    n3 = zlib.crc32(original_content) & 0xFFFFFFFF

    replacement = b"RIFF" + b"\x11" * 64 + b"WAVEdata" + b"\xab" * 32
    re_enc = encrypt_file(replacement, filler, path, n2, n3)

    # the machine's two checks still pass...
    assert zlib.crc32(re_enc) & 0xFFFFFFFF == n2
    back = decrypt_file(re_enc, filler, path)
    assert zlib.crc32(back) & 0xFFFFFFFF == n3
    # ...and the new audio really is in there (plus 4 forged CRC bytes)
    assert back[:len(replacement)] == replacement
    assert len(back) == len(replacement) + 4


def test_scan_and_extract_round_trip(tmp_path):
    """End-to-end through the module's own scan/extract/encrypt entry points."""
    path = "/jjpe/gen1/ecoredata/sound/sound_test/music.wav"
    content = b"RIFF" + b"\x00" * 128 + b"WAVEdata" + bytes(range(200))
    gen1 = tmp_path / "gen1"
    dest = gen1 / "ecoredata" / "sound" / "sound_test"
    dest.mkdir(parents=True)
    (dest / "music.wav").write_bytes(_encrypt_scheme2(content, 264, path))

    entries = ec.scan_shared_trees(str(gen1), "Pirates")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.encrypted and entry.crypto_path == path
    assert entry.filler_size == 264

    out = tmp_path / "out"
    ec.extract_entry(entry, "Pirates", str(out))
    written = (out / "ecoredata" / "sound" / "sound_test" / "music.wav")
    assert written.read_bytes() == content

    re_enc = ec.encrypt_content(content, entry,
                                (dest / "music.wav").read_bytes(), "Pirates")
    assert zlib.crc32(re_enc) & 0xFFFFFFFF == entry.crc_encrypted


def test_plaintext_entry_passes_through_untouched(tmp_path):
    """An undecryptable or already-plain file must be copied, not mangled."""
    gen1 = tmp_path / "gen1"
    d = gen1 / "miscfiles" / "eua"
    d.mkdir(parents=True)
    pdf = b"%PDF-1.4\n" + bytes(range(256))
    (d / "a.pdf").write_bytes(pdf)

    entry, = ec.scan_shared_trees(str(gen1), "Pirates")
    assert not entry.encrypted
    out = tmp_path / "out"
    ec.extract_entry(entry, "Pirates", str(out))
    assert (out / "miscfiles" / "eua" / "a.pdf").read_bytes() == pdf


# --------------------------------------------------------------------------
# the deployed decrypt script
# --------------------------------------------------------------------------

def _format_script():
    from pinball_decryptor.plugins.jjp.pipeline import _DECRYPT_SCRIPT
    mp = "/mnt/jjp_test"
    return _DECRYPT_SCRIPT.format(
        has_fl_dat="False", mp=mp, out_dir="/mnt/c/out",
        edata_dir=mp + "/jjpe/gen1/Pirates/edata",
        ecore_dirs=repr([mp + "/jjpe/gen1/" + t for t in ec.SHARED_TREES]),
        shared_prefixes=repr([ec.GEN1_PREFIX + t + "/"
                              for t in ec.SHARED_TREES]),
        game_name="Pirates", extract_graphics="True", extract_sounds="True")


def test_decrypt_script_is_valid_python():
    """It is a template string, so a syntax slip here breaks every JJP
    extract and nothing else would catch it until a real run."""
    compile(_format_script(), "<decrypt>", "exec")


def _script_helpers():
    """The script's own ``_out_rel`` / ``_is_shared``, as WSL would run them."""
    script = _format_script()
    start = script.index("def _is_shared")
    ends = [script.index(m, start)
            for m in ("\n_MP_CTX", "\nN_WORKERS", "\ndef _scan_one")
            if m in script[start:]]
    ns = {"os": os,
          "SHARED_PREFIXES": [ec.GEN1_PREFIX + t + "/"
                              for t in ec.SHARED_TREES]}
    exec(compile(script[start:min(ends)], "<helpers>", "exec"), ns)
    ns["PREFIX"] = EDATA_PREFIX      # set last: the slice resets it to ""
    return ns["_out_rel"], ns["_is_shared"]


@pytest.mark.parametrize("abs_path,rel,shared", PATH_CASES)
def test_script_mapping_matches_module(abs_path, rel, shared):
    """The WSL script and the host module implement the same mapping in
    opposite directions; if they ever disagree, Write silently targets the
    wrong path.  This pins them together."""
    out_rel, is_shared = _script_helpers()
    assert out_rel(abs_path) == rel
    assert is_shared(abs_path) is shared
    assert ec.image_path_for_rel(out_rel(abs_path), EDATA_PREFIX) == abs_path


def test_shared_entries_do_not_clobber_the_edata_prefix():
    """Regression guard.

    ``detect_edata_prefix`` looks for a "/edata/" segment in the FIRST entry.
    "/jjpe/gen1/ecoredata/" has no such segment, so deriving the prefix from a
    list that mixes both roots can return "" and send every game asset to the
    wrong output path.  The script must take the prefix from the edata root
    instead, and must not recompute it after the shared trees are appended.
    """
    from pinball_decryptor.plugins.jjp.filelist import detect_edata_prefix
    from pinball_decryptor.plugins.jjp.filelist import FileEntry

    shared_first = [
        FileEntry("/jjpe/gen1/ecoredata/sound/a.wav", 8, 0, 0),
        FileEntry("/jjpe/gen1/Pirates/edata/sound/b.ogg", 8, 0, 0),
    ]
    # This is precisely the wrong answer we must never depend on:
    assert detect_edata_prefix(shared_first) == ""

    script = _format_script()
    body = script[script.index("def main()"):]
    # The prefix comes from the edata root, and is not re-derived afterwards.
    assert "PREFIX = path_prefix" in body
    assert body.count("PREFIX = detect_edata_prefix(entries)") == 1
