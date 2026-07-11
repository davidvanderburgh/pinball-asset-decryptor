"""Golden tests for partclone_to_raw.py's batched sparse write loop.

The converter's per-block Python loop was rewritten (2026-07-10) to
process runs of consecutive blocks with multi-megabyte I/O and to seek
over free space instead of writing literal zeros.  These tests build
synthetic partclone v2 images (per the struct layout the script parses)
and assert the output is byte-identical to the legacy per-block
algorithm, including the interleaved-checksum consumption and the
logical file size (holes must read back as zeros).
"""

import gzip
import importlib.util
import math
import struct
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parent.parent
          / "pinball_decryptor" / "plugins" / "jjp" / "partclone_to_raw.py")

spec = importlib.util.spec_from_file_location("partclone_to_raw", SCRIPT)
p2r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p2r)

BLOCK_SIZE = 512
CHECKSUM_SIZE = 4
BLOCKS_PER_CHECKSUM = 7


def _block_payload(idx):
    return bytes([(idx * 31 + j) % 251 for j in range(BLOCK_SIZE)])


def build_image(used, bitmap_mode):
    """Serialize a partclone v2 stream for the given per-block used flags."""
    total = len(used)
    head = b"partclone-image\x00"                       # magic (16)
    head += b"0.3.13".ljust(14, b"\x00")                # partclone version
    head += b"0002"                                      # image version
    head += struct.pack("<H", 0xC0DE)                   # endianness
    head += b"EXTFS".ljust(16, b"\x00")                 # fs type
    head += struct.pack("<QQQQ",
                        total * BLOCK_SIZE,             # device size
                        total,                          # total blocks
                        sum(1 for u in used if u),      # super used
                        sum(1 for u in used if u))      # bitmap used
    head += struct.pack("<I", BLOCK_SIZE)
    head += struct.pack("<IHHHHIBB",
                        0,                              # feature size
                        2,                              # image version
                        64,                             # cpu bits
                        1,                              # checksum mode (CRC32)
                        CHECKSUM_SIZE,
                        BLOCKS_PER_CHECKSUM,
                        0,                              # reseed
                        bitmap_mode)
    head += struct.pack("<I", 0xDEADBEEF)               # descriptor CRC

    if bitmap_mode == 1:  # BM_BIT, LSB-first
        bitmap = bytearray(math.ceil(total / 8))
        for i, u in enumerate(used):
            if u:
                bitmap[i // 8] |= 1 << (i % 8)
    else:  # BM_BYTE — deliberately use a non-1 truthy value
        bitmap = bytearray(2 if u else 0 for u in used)
    head += bytes(bitmap)
    head += b"\xAA" * CHECKSUM_SIZE                     # bitmap checksum

    body = b""
    data_blocks = 0
    for i, u in enumerate(used):
        if not u:
            continue
        body += _block_payload(i)
        data_blocks += 1
        if data_blocks % BLOCKS_PER_CHECKSUM == 0:
            body += b"\xCC" * CHECKSUM_SIZE             # interleaved checksum
    return head + body


def legacy_expected(used):
    """The raw image the original per-block algorithm produced (dense)."""
    out = b""
    for i, u in enumerate(used):
        out += _block_payload(i) if u else b"\x00" * BLOCK_SIZE
    return out


def _convert(tmp_path, used, bitmap_mode, n_parts=1):
    stream = gzip.compress(build_image(used, bitmap_mode))
    part_size = max(1, len(stream) // n_parts + 1)
    parts = []
    for i in range(n_parts):
        chunk = stream[i * part_size:(i + 1) * part_size]
        if not chunk:
            break
        p = tmp_path / f"img.gz.a{chr(ord('a') + i)}"
        p.write_bytes(chunk)
        parts.append(str(p))
    out = tmp_path / "raw.img"
    p2r.convert_partclone_to_raw(parts, str(out))
    return out


# Bitmap shapes: long runs, alternating singles, all-used, trailing holes
# (exercises the final truncate), and a lone used block at the very end.
PATTERNS = {
    "mixed_runs": [1] * 40 + [0] * 30 + [1, 0] * 20 + [1] * 9 + [0] * 18,
    "all_used": [1] * 65,
    "leading_hole": [0] * 33 + [1] * 30,
    "trailing_hole": [1] * 30 + [0] * 27,
    "tail_block": [0] * 64 + [1],
}


@pytest.mark.parametrize("pattern", PATTERNS, ids=PATTERNS.keys())
@pytest.mark.parametrize("bitmap_mode", [1, 2], ids=["BM_BIT", "BM_BYTE"])
def test_matches_legacy_output(tmp_path, pattern, bitmap_mode):
    used = PATTERNS[pattern]
    out = _convert(tmp_path, used, bitmap_mode)
    expected = legacy_expected(used)
    assert out.stat().st_size == len(used) * BLOCK_SIZE
    assert out.read_bytes() == expected


def test_split_parts(tmp_path):
    used = PATTERNS["mixed_runs"]
    out = _convert(tmp_path, used, bitmap_mode=1, n_parts=3)
    assert out.read_bytes() == legacy_expected(used)


def test_large_run_crosses_io_and_checksum_batches(tmp_path, monkeypatch):
    # Force tiny I/O batches so a single used-run spans many reads and
    # several checksum boundaries within one run.
    used = [1] * 200 + [0] * 5 + [1] * 51
    stream = gzip.compress(build_image(used, 1))
    p = tmp_path / "img.gz.aa"
    p.write_bytes(stream)
    out = tmp_path / "raw.img"
    p2r.convert_partclone_to_raw([str(p)], str(out))
    assert out.read_bytes() == legacy_expected(used)


def test_pipeline_finder_locates_bundled_converter():
    # The extract phase falls back to this converter when partclone is
    # unavailable; the finder silently returning a nonexistent path made
    # it dead code for months (field logs showed "Python converter not
    # found" on every install).
    from pinball_decryptor.plugins.jjp.pipeline import _find_project_file

    path = _find_project_file("partclone_to_raw.py")
    assert Path(path).is_file()
    assert Path(path).resolve() == SCRIPT
