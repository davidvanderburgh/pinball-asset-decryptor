"""Spike 1 DMD decoder: the 4-bit-plane frame format.

The format (4 planes x 512 bytes, MSB-first, row-major) was verified against a
live Game of Thrones LE capture that decoded to legible attract text
("GAME OF THRONES LE", "REPLAY AT 300,000,000"). These tests pin the packing so
a regression can't silently scramble the display.
"""

import importlib.util
import os

_S1DMD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tools", "spike1_emu", "s1dmd.py")
_spec = importlib.util.spec_from_file_location("s1dmd", _S1DMD)
s1dmd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1dmd)


def encode_frame(grid):
    """Inverse of s1dmd.decode_frame: pack a HEIGHT x WIDTH grey grid (0..15)
    into the 4-plane, 512-byte-per-plane, MSB-first layout."""
    frame = bytearray(s1dmd.FRAME_BYTES)
    for y in range(s1dmd.HEIGHT):
        for x in range(s1dmd.WIDTH):
            p = y * s1dmd.WIDTH + x
            byte_i = p >> 3
            bit = 7 - (p & 7)
            v = grid[y][x]
            for plane in range(s1dmd.PLANES):
                if (v >> plane) & 1:
                    frame[plane * s1dmd.PLANE_BYTES + byte_i] |= (1 << bit)
    return bytes(frame)


def test_frame_geometry():
    assert s1dmd.WIDTH == 128
    assert s1dmd.HEIGHT == 32
    assert s1dmd.PLANES == 4
    assert s1dmd.PLANE_BYTES == 512
    assert s1dmd.FRAME_BYTES == 2048


def test_decode_roundtrip():
    # a distinctive pattern using the full grey range and corner pixels
    grid = [[((x * 7 + y * 3) & 0x0f) for x in range(s1dmd.WIDTH)]
            for y in range(s1dmd.HEIGHT)]
    grid[0][0] = 15
    grid[0][s1dmd.WIDTH - 1] = 1
    grid[s1dmd.HEIGHT - 1][0] = 8
    grid[s1dmd.HEIGHT - 1][s1dmd.WIDTH - 1] = 15
    frame = encode_frame(grid)
    assert len(frame) == s1dmd.FRAME_BYTES
    assert s1dmd.decode_frame(frame) == grid


def test_blank_detection():
    assert s1dmd.frame_is_blank(bytes(s1dmd.FRAME_BYTES))
    one = bytearray(s1dmd.FRAME_BYTES)
    one[0] = 0x80
    assert not s1dmd.frame_is_blank(bytes(one))


def test_single_pixel_top_left_msb():
    # pixel (0,0), grey 1 -> plane 0, byte 0, MSB set
    grid = [[0] * s1dmd.WIDTH for _ in range(s1dmd.HEIGHT)]
    grid[0][0] = 1
    frame = encode_frame(grid)
    assert frame[0] == 0x80
    assert s1dmd.decode_frame(frame)[0][0] == 1


def test_iter_frames_counts():
    blob = bytes(s1dmd.FRAME_BYTES * 3)
    assert len(list(s1dmd.iter_frames(blob))) == 3


def test_decode_short_frame_raises():
    import pytest
    with pytest.raises(ValueError):
        s1dmd.decode_frame(bytes(10))


def test_latest_frame_tails_growing_file(tmp_path):
    p = tmp_path / "spi0.cap"
    # no file yet / empty -> None
    assert s1dmd.latest_frame(str(p)) is None
    p.write_bytes(b"")
    assert s1dmd.latest_frame(str(p)) is None
    # two full frames + a trailing partial frame -> returns the 2nd full one
    f0 = bytes([0x11]) + bytes(s1dmd.FRAME_BYTES - 1)
    f1 = bytes([0x22]) + bytes(s1dmd.FRAME_BYTES - 1)
    p.write_bytes(f0 + f1 + b"\x99\x99")     # partial tail must be ignored
    got = s1dmd.latest_frame(str(p))
    assert got == f1
