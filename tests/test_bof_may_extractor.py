"""Unit tests for the BOF May 2026+ PCK extractor + packer.

These tests synthesize a tiny BOF May-style binary in memory — PCK
header, a couple of RSCC font blobs, a raw texture, a couple of
adjacent sidecars, a sequential GDSC blob with its simple sidecar,
and the standard 12-byte PCK trailer — then exercise extract and
pack against it.  No real BOF fixture is required.
"""

import math
import os
import struct

import pytest

zstandard = pytest.importorskip("zstandard")

from pinball_decryptor.plugins.bof import may_extractor, may_packer
from pinball_decryptor.plugins.bof.rscc_decoder import RSCC_MAGIC


def _build_rscc(payload):
    """Same RSCC v2 layout the extractor / packer understands."""
    blk = 4096
    n = math.ceil(len(payload) / blk) if payload else 0
    cctx = zstandard.ZstdCompressor()
    frames = [cctx.compress(payload[i * blk:(i + 1) * blk]) for i in range(n)]
    sizes = [len(f) for f in frames]
    out = bytearray()
    out += RSCC_MAGIC + struct.pack("<III", 2, blk, len(payload))
    out += struct.pack(f"<{n}I", *sizes)
    for f in frames:
        out += f
    return bytes(out)


def _adjacent_sidecar(path, importer="texture", typ="CompressedTexture2D", uid="abc"):
    """A complex sidecar — the kind the extractor pairs with adjacent
    file data (imported assets)."""
    text = (f'[remap]\n\nimporter="{importer}"\ntype="{typ}"\n'
            f'uid="uid://{uid}"\npath="{path}"\n')
    # Pad to multiple of 8 (BOF convention)
    pad = (8 - len(text) % 8) % 8
    return text.encode("utf-8") + b"\x00" * pad


def _simple_sidecar(path):
    """A simple sidecar — `[remap]\\n\\npath="..."\\n` only.  Used by
    .gdc / .scn / .res files that pair sequentially with blobs by
    magic order."""
    text = f'[remap]\n\npath="{path}"\n'
    pad = (8 - len(text) % 8) % 8
    return text.encode("utf-8") + b"\x00" * pad


def _gdsc_blob(payload_bytes):
    """A minimal GDSC bytecode container with random payload."""
    # GDSC header: magic + version (we use 0x65 like Dune does) + a few
    # placeholder length fields the test doesn't validate.  Real Godot
    # parses these but our extractor only needs to find the magic.
    return b"GDSC" + struct.pack("<II", 0x65, len(payload_bytes)) + payload_bytes


def _build_may_binary(tmp_path, *, font_payloads=None, texture_payload=None,
                     gdsc_payloads=None):
    """Build a synthetic BOF May binary at ``tmp_path / 'fake.x86_64'``.

    Returns the absolute path to the file.
    """
    font_payloads = font_payloads or []
    gdsc_payloads = gdsc_payloads or []

    fake_code = b"\xCC" * 512  # stand-in for ELF/PE code section

    # PCK header (96 bytes): GDPC + ver3 + engine 4.5.2 + flags 0x3 + file_base + reserved
    pck = bytearray()
    pck += b"GDPC"
    pck += struct.pack("<I", 3)                  # pack_version
    pck += struct.pack("<III", 4, 5, 2)          # engine major/minor/patch
    pck += struct.pack("<I", 0x03)               # flags: PACK_DIR_ENCRYPTED + PACK_REL_FILEBASE
    pck += struct.pack("<Q", 0x68)               # file_base_offset
    pck += b"\x00" * 64                          # 16 reserved u32 = 64 bytes
    pck += b"\x00" * 8                           # 8 zero pad

    # Adjacent (fonts via RSCC)
    for i, payload in enumerate(font_payloads):
        pck += _build_rscc(payload)
        pck += b"RSCC\x00\x00\x00\x00"           # 8-byte separator
        pck += _adjacent_sidecar(
            f"res://.godot/imported/font{i}.ttf-{i:032x}.fontdata",
            importer="font_data_dynamic", typ="FontFile", uid=f"fnt{i}")

    # Adjacent (texture, raw GST2-style data)
    if texture_payload is not None:
        pck += texture_payload
        pck += _adjacent_sidecar(
            "res://.godot/imported/tex.png-abc.ctex",
            importer="texture", typ="CompressedTexture2D", uid="tex0")

    # Sequential (GDSC blobs, all data first then all sidecars)
    for payload in gdsc_payloads:
        pck += _gdsc_blob(payload)
    for i in range(len(gdsc_payloads)):
        pck += _simple_sidecar(f"res://scripts/test_{i}.gdc")

    # Trailer: u64 pck_size + GDPC magic
    pck_bytes = bytes(pck)
    trailer = struct.pack("<Q", len(pck_bytes)) + b"GDPC"

    binary = tmp_path / "fake.x86_64"
    binary.write_bytes(fake_code + pck_bytes + trailer)
    return str(binary)


# ----------------------------------------------------------------------
# Extractor tests
# ----------------------------------------------------------------------

def test_find_pck_section_uses_trailer(tmp_path):
    binary = _build_may_binary(tmp_path, font_payloads=[b"hello" * 100])
    pck_start, pck_end = may_extractor.find_pck_section(binary)
    size = os.path.getsize(binary)
    assert pck_end == size - 12
    assert pck_start == 512  # the size of our fake_code stub


def test_is_may_format_recognises_pck(tmp_path):
    binary = _build_may_binary(tmp_path, font_payloads=[b"x" * 200])
    pck_start, pck_end = may_extractor.find_pck_section(binary)
    with open(binary, "rb") as f:
        f.seek(pck_start)
        pck = f.read(200)
    assert may_extractor.is_may_format(pck)


def test_extract_round_trips_font_payload(tmp_path):
    payload = b"FAKE_RSRC_FONT_DATA_PAYLOAD_" * 50
    binary = _build_may_binary(tmp_path, font_payloads=[payload])
    out_dir = tmp_path / "out"

    stats = may_extractor.extract_pck(binary, str(out_dir))
    assert stats["adjacent_count"] == 1
    assert stats["rscc_count"] == 1

    # Find the extracted file
    files = list(out_dir.rglob("*.fontdata"))
    assert len(files) == 1
    # Our font payload doesn't contain "FontFile" so the RSRC magic
    # fix-up shouldn't have prepended anything — content should equal
    # the original payload.
    assert files[0].read_bytes() == payload


def test_extract_handles_adjacent_and_sequential(tmp_path):
    binary = _build_may_binary(
        tmp_path,
        font_payloads=[b"FONT_A_DATA" * 30, b"FONT_B_DATA" * 30],
        texture_payload=b"GST2" + b"\x00" * 60 + b"PNG_PIXELS" * 50,
        gdsc_payloads=[b"\xAA" * 200, b"\xBB" * 300],
    )
    out_dir = tmp_path / "out"

    stats = may_extractor.extract_pck(binary, str(out_dir))
    assert stats["adjacent_count"] == 3   # 2 fonts + 1 texture
    assert stats["sequential_count"] == 2 # 2 GDSC scripts
    assert stats["rscc_count"] == 2       # both fonts RSCC-decompressed

    # Verify the texture round-trips
    ctex_files = list(out_dir.rglob("*.ctex"))
    assert len(ctex_files) == 1
    assert ctex_files[0].read_bytes().startswith(b"GST2")

    # Verify both .gdc files round-trip with GDSC magic
    gdc_files = sorted(out_dir.rglob("*.gdc"))
    assert len(gdc_files) == 2
    for gd in gdc_files:
        assert gd.read_bytes().startswith(b"GDSC")


def test_extract_strips_pck_trailer_padding(tmp_path):
    binary = _build_may_binary(tmp_path, font_payloads=[b"x" * 200])
    pck_start, pck_end = may_extractor.find_pck_section(binary)
    # pck_end should NOT include the 12-byte trailer
    assert pck_end == os.path.getsize(binary) - 12


# ----------------------------------------------------------------------
# Packer tests
# ----------------------------------------------------------------------

def test_pack_with_no_modifications_keeps_file_count(tmp_path):
    """Pack with an EMPTY mods directory — file count + paths preserved,
    no substitutions, output is byte-stable-ish (PCK size may differ
    slightly from Zstd re-compression but file boundaries hold)."""
    binary = _build_may_binary(
        tmp_path,
        font_payloads=[b"FONT_DATA_" * 50],
        texture_payload=b"GST2" + b"\x01" * 100,
        gdsc_payloads=[b"\xCD" * 200],
    )
    empty_pck = tmp_path / "empty"
    empty_pck.mkdir()
    out = tmp_path / "repacked.x86_64"

    stats = may_packer.pack_pck(binary, str(empty_pck), str(out))
    assert stats["files_total"] == 3
    assert stats["files_replaced"] == 0
    # Re-extract from packed and verify same file count
    re_dir = tmp_path / "reextract"
    extract_stats = may_extractor.extract_pck(str(out), str(re_dir))
    assert extract_stats["files_written"] == 3


def test_pack_substitutes_modified_texture(tmp_path):
    """When a user modifies a texture with a SMALLER replacement and
    re-packs, the new bytes appear in the output binary's extract (the
    packer zero-pads the entry back to its original size, which the
    extractor trims)."""
    original_texture = b"GST2" + b"\x01" * 200
    binary = _build_may_binary(tmp_path, texture_payload=original_texture)

    # First extract so we have the mods directory shape
    mods_dir = tmp_path / "mods"
    may_extractor.extract_pck(binary, str(mods_dir))

    # Modify the texture — SMALLER so it fits the original footprint.
    ctex = list(mods_dir.rglob("*.ctex"))[0]
    new_texture = b"GST2" + b"\x02" * 50  # smaller + different bytes
    ctex.write_bytes(new_texture)

    # Repack
    out = tmp_path / "modded.x86_64"
    stats = may_packer.pack_pck(binary, str(mods_dir), str(out))
    assert stats["files_replaced"] == 1

    # Re-extract from the modded binary and verify the new bytes are there
    # (trailing zero-pad is trimmed by the extractor's bounds logic).
    verify_dir = tmp_path / "verify"
    may_extractor.extract_pck(str(out), str(verify_dir))
    re_ctex = list(verify_dir.rglob("*.ctex"))[0]
    assert re_ctex.read_bytes() == new_texture


def test_pack_rejects_larger_replacement(tmp_path):
    """A replacement BIGGER than the original entry must be refused — BOF's
    encrypted PCK directory stores absolute offsets we can't shift, so a
    grow would brick the game.  The packer raises a clear PackerError."""
    binary = _build_may_binary(tmp_path, texture_payload=b"GST2" + b"\x01" * 80)
    mods_dir = tmp_path / "mods"
    may_extractor.extract_pck(binary, str(mods_dir))
    ctex = list(mods_dir.rglob("*.ctex"))[0]
    ctex.write_bytes(b"GST2" + b"\x02" * 400)  # bigger than original

    out = tmp_path / "modded.x86_64"
    with pytest.raises(may_packer.PackerError, match="larger than the original"):
        may_packer.pack_pck(binary, str(mods_dir), str(out))


def _entry_offsets(binary):
    """Map res:// path -> (file_start, sidecar_start) for every adjacent
    entry in a binary's PCK (PCK-relative offsets)."""
    ps, pe = may_extractor.find_pck_section(binary)
    with open(binary, "rb") as f:
        f.seek(ps)
        pck = bytearray(f.read(pe - ps))
    adj, _seq = may_packer._read_pck_entries(pck)
    return {p: (fs, ss) for (k, fs, fe, ss, se, p) in adj}


def test_pack_leaves_unchanged_fonts_verbatim(tmp_path):
    """An audio/texture-only edit must NOT re-wrap fonts.  Fonts live
    compressed in the PCK but extract decompressed, so a naive byte
    compare always flags them 'changed' — re-wrapping them needlessly
    perturbs the PCK's byte alignment (the real regression)."""
    binary = _build_may_binary(
        tmp_path,
        font_payloads=[b"FONT_A_" * 80, b"FONT_B_" * 120],
        texture_payload=b"GST2" + b"\x01" * 100,
    )
    mods_dir = tmp_path / "mods"
    may_extractor.extract_pck(binary, str(mods_dir))

    # Edit ONLY the texture (smaller, fits footprint); leave fonts untouched.
    ctex = list(mods_dir.rglob("*.ctex"))[0]
    ctex.write_bytes(b"GST2" + b"\x02" * 50)  # different bytes, smaller

    out = tmp_path / "modded.x86_64"
    stats = may_packer.pack_pck(binary, str(mods_dir), str(out))

    assert stats["files_replaced"] == 1          # only the texture
    assert stats["fonts_verbatim"] == 2          # both fonts left alone

    # And the fonts must be byte-identical in the repacked PCK.
    ps, pe = may_extractor.find_pck_section(binary)
    orig = open(binary, "rb").read()[ps:pe]
    ps2, pe2 = may_extractor.find_pck_section(str(out))
    new = open(str(out), "rb").read()[ps2:pe2]
    assert orig.count(b"RSCC") == new.count(b"RSCC")  # no font separator lost


def test_pack_is_size_neutral(tmp_path):
    """A size-changing (shrinking) adjacent substitution must keep EVERY
    other entry at its EXACT original byte offset — the packer zero-pads
    the replacement back to the original footprint so nothing downstream
    shifts.  This is load-critical: BOF's May PCK is a Godot v3 pack whose
    real file directory (encrypted, at the header dir_offset) stores
    ABSOLUTE offsets the engine uses; any net shift makes it read later
    resources at stale offsets and the game black-screens."""
    binary = _build_may_binary(
        tmp_path,
        font_payloads=[b"FONT_" * 90],
        texture_payload=b"GST2" + b"\x11" * 300,
        gdsc_payloads=[b"\xAB" * 200, b"\xCD" * 200],
    )
    before = _entry_offsets(binary)
    orig_size = os.path.getsize(binary)

    mods_dir = tmp_path / "mods"
    may_extractor.extract_pck(binary, str(mods_dir))
    ctex = list(mods_dir.rglob("*.ctex"))[0]
    ctex.write_bytes(b"GST2" + b"\x22" * 60)  # much smaller -> gets zero-padded

    out = tmp_path / "modded.x86_64"
    may_packer.pack_pck(binary, str(mods_dir), str(out))
    may_extractor.extract_pck(str(out), str(tmp_path / "verify"))  # still extractable
    after = _entry_offsets(str(out))

    # Output binary is the EXACT same size, and every entry — including
    # the edited one — sits at its original (file_start, sidecar_start).
    assert os.path.getsize(str(out)) == orig_size
    assert after == before
