"""Unit tests for BOF's PCK magic patcher.

BOF's newer Godot builds (May 2026+) renamed the embedded PCK magic from
the stock "GDPC" to "GBOF" to defeat off-the-shelf tools like GDRE.  Both
DecryptPipeline (so the user can browse the PCK) and ModifyPipeline (so
GDRE can read and re-patch the binary) rely on the same swap helper —
this verifies its byte-level behaviour against synthetic mini-binaries
without needing gpg, WSL, GDRE, or a real .fun file.
"""

import os
import struct
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.bof.pipeline import (
    _BOF_PCK_MAGIC, _GODOT_PCK_MAGIC, _PATCH_MAGIC_SCRIPT,
)


def _build_fake_binary(path, magic, pck_payload=b"FAKEPCKBODY"):
    """Write a minimal Godot-style embedded-PCK binary.

    Layout:  [prefix junk][magic + pck_payload][u64 LE pck_size][magic]
    pck_size covers the magic + payload (i.e. everything from PCK start
    up to but not including the trailer's size field).
    """
    prefix = b"\x00" * 32
    pck_bytes = magic + pck_payload
    pck_size = len(pck_bytes)
    trailer = struct.pack("<Q", pck_size) + magic
    with open(path, "wb") as f:
        f.write(prefix)
        f.write(pck_bytes)
        f.write(trailer)


def _run_patch_script(path, from_magic, to_magic):
    """Invoke the in-tree patch script via python3 the same way the
    executor does at runtime, and return its trimmed stdout."""
    result = subprocess.run(
        [sys.executable, "-c", _PATCH_MAGIC_SCRIPT,
         str(path), from_magic.decode(), to_magic.decode()],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_patch_swaps_both_occurrences(tmp_path):
    binary = tmp_path / "fake.x86_64"
    _build_fake_binary(binary, _BOF_PCK_MAGIC)

    status = _run_patch_script(binary, _BOF_PCK_MAGIC, _GODOT_PCK_MAGIC)
    assert status.startswith("patched"), status

    data = binary.read_bytes()
    # Trailer magic
    assert data[-4:] == _GODOT_PCK_MAGIC
    # Header magic — recompute the same offset the script does
    pck_size = struct.unpack("<Q", data[-12:-4])[0]
    header_off = len(data) - 12 - pck_size
    assert data[header_off:header_off + 4] == _GODOT_PCK_MAGIC
    # No stray "GBOF" left
    assert _BOF_PCK_MAGIC not in data


def test_patch_noop_when_already_target(tmp_path):
    binary = tmp_path / "stock.x86_64"
    _build_fake_binary(binary, _GODOT_PCK_MAGIC)
    before = binary.read_bytes()

    status = _run_patch_script(binary, _BOF_PCK_MAGIC, _GODOT_PCK_MAGIC)
    assert status.startswith("skip:already_GDPC"), status
    assert binary.read_bytes() == before


def test_patch_noop_when_no_embedded_pck(tmp_path):
    binary = tmp_path / "no_pck.x86_64"
    binary.write_bytes(b"\x00" * 64 + b"some_other_trailing_bytes_here")
    before = binary.read_bytes()

    status = _run_patch_script(binary, _BOF_PCK_MAGIC, _GODOT_PCK_MAGIC)
    assert status.startswith("skip:trailer="), status
    assert binary.read_bytes() == before


def test_patch_round_trip(tmp_path):
    """Modify pipeline path: GBOF -> GDPC -> GBOF must yield original bytes."""
    binary = tmp_path / "rt.x86_64"
    _build_fake_binary(binary, _BOF_PCK_MAGIC)
    original = binary.read_bytes()

    s1 = _run_patch_script(binary, _BOF_PCK_MAGIC, _GODOT_PCK_MAGIC)
    assert s1.startswith("patched"), s1
    s2 = _run_patch_script(binary, _GODOT_PCK_MAGIC, _BOF_PCK_MAGIC)
    assert s2.startswith("patched"), s2

    assert binary.read_bytes() == original


def test_patch_too_small_file(tmp_path):
    binary = tmp_path / "tiny.x86_64"
    binary.write_bytes(b"abc")  # 3 bytes — under the 12-byte trailer
    status = _run_patch_script(binary, _BOF_PCK_MAGIC, _GODOT_PCK_MAGIC)
    assert status == "skip:too_small"
