"""Cactus Canyon original DCS audio — addressable-stream extract + repack.

The 1998 Bally Cactus Canyon audio lives in the Williams DCS sound-ROM set
(``ccdata/rom/s2..s7.rom``).  For modding we use the **stream** granularity
(the individual decoded audio samples, addressable by ROM address) rather than
"tracks" (assembled playback programs), because DCSEncoder's patch facility
replaces audio by *stream address*.

Extract: ``DCSExplorer --extract-streams`` → one WAV per stream, named
``st__<track>_<idx>_<ADDR>.wav`` where ``ADDR`` is the stream's ROM address.

Repack: for each edited stream WAV, emit a ``Stream s "<wav>" replaces $ADDR;``
line and run ``DCSEncoder --patch`` against the original ROM set (which copies
every unmodified track/stream verbatim and swaps in the edits), producing a new
``s2..s7.rom`` set.  Verified round-trip: silencing one stream re-extracts as
silent while every other stream is preserved.

Both tools come from mjrgh's DCSExplorer project (BSD), bundled in
``williams/vendor/``.  The ROM zip handed to them MUST be named ``cc_<digit>*``
(``_ZIP_NAME``) — see :mod:`pinball_decryptor.plugins.williams.dcs_decode` and
``docs/CC_REVISITED_RE.md`` for the Cactus-Canyon U7-mislabel special case.
"""

from __future__ import annotations

import glob as _glob
import os
import re
import subprocess
import sys
import tempfile
import wave
import zipfile
import zipfile as _zip
from typing import Callable, List, Optional

from ..williams.dcs_decode import find_dcs_encoder, find_dcs_explorer

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_ZIP_NAME = "cc_113.zip"          # basename must match ^cc_\d.*  (loader rule)
_ROM_RE = re.compile(r"^s\d+\.rom$", re.IGNORECASE)
_ADDR_RE = re.compile(r"_([0-9A-Fa-f]{4,8})\.wav$")
_EXTRACT_TIMEOUT = 600
_ENCODE_TIMEOUT = 900


class DcsRepackError(Exception):
    pass


def _sound_roms(rom_dir: str) -> List[str]:
    if not os.path.isdir(rom_dir):
        return []
    return sorted(os.path.join(rom_dir, fn) for fn in os.listdir(rom_dir)
                  if _ROM_RE.match(fn))


def _build_zip(rom_paths: List[str], dest_zip: str):
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_STORED) as zf:
        for rp in rom_paths:
            zf.write(rp, arcname=os.path.basename(rp))


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=timeout,
                          creationflags=_CREATE_FLAGS)


def available() -> bool:
    """True if both DCSExplorer (extract) and DCSEncoder (repack) are present."""
    return find_dcs_explorer() is not None and find_dcs_encoder() is not None


def extract_streams(rom_dir: str, out_dir: str,
                    log_cb: Optional[Callable[[str, str], None]] = None) -> int:
    """Decode every DCS stream in *rom_dir*'s s*.rom set to a WAV in *out_dir*.
    Returns the stream count (0 if the decoder or ROMs are absent)."""
    exe = find_dcs_explorer()
    roms = _sound_roms(rom_dir)
    if exe is None or len(roms) < 2:
        return 0
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cc_dcs_") as td:
        zp = os.path.join(td, _ZIP_NAME)
        _build_zip(roms, zp)
        _run([exe, "-I", "--silent", "--terse",
              f"--extract-streams={os.path.join(out_dir, 'st_')}", zp],
             _EXTRACT_TIMEOUT)
    return len(_glob.glob(os.path.join(out_dir, "*.wav")))


def _wav_pcm(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        return w.readframes(w.getnframes())


def repack(rom_dir: str, streams_dir: str, out_rom_dir: str,
           log_cb: Optional[Callable[[str, str], None]] = None) -> dict:
    """Rebuild the s*.rom set with edited stream WAVs from *streams_dir*.

    Detects edits by re-decoding the current ROMs and comparing PCM per stream
    (so unmodified streams are never re-encoded / degraded), emits a DCSEncoder
    ``--patch`` script replacing only the changed streams (by ROM address from
    the filename), and writes the new s*.rom into *out_rom_dir*.

    Returns ``{"modified_count": n, "total": total}``.  A no-op leaves the ROMs
    untouched (writes nothing).
    """
    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    explorer = find_dcs_explorer()
    encoder = find_dcs_encoder()
    roms = _sound_roms(rom_dir)
    edited = _glob.glob(os.path.join(streams_dir, "*.wav"))
    if explorer is None or encoder is None or len(roms) < 2 or not edited:
        return {"modified_count": 0, "total": 0}

    with tempfile.TemporaryDirectory(prefix="cc_dcs_rp_") as td:
        zp = os.path.join(td, _ZIP_NAME)
        _build_zip(roms, zp)
        # Baseline: re-decode the current ROMs so we can tell which streams the
        # user actually changed (DCS is lossy — never re-encode an untouched one).
        base_dir = os.path.join(td, "base")
        os.makedirs(base_dir)
        _run([explorer, "-I", "--silent", "--terse",
              f"--extract-streams={os.path.join(base_dir, 'st_')}", zp],
             _EXTRACT_TIMEOUT)
        baseline = {os.path.basename(p): p
                    for p in _glob.glob(os.path.join(base_dir, "*.wav"))}
        total = len(baseline)

        replacements = []  # (addr_hex, wav_path)
        for wav in edited:
            name = os.path.basename(wav)
            base = baseline.get(name)
            if base is None:
                continue
            m = _ADDR_RE.search(name)
            if not m:
                continue
            try:
                if _wav_pcm(wav) == _wav_pcm(base):
                    continue  # unchanged
            except wave.Error:
                continue
            replacements.append((m.group(1).upper(), wav))

        if not replacements:
            return {"modified_count": 0, "total": total}

        script = os.path.join(td, "patch.dcsprog")
        with open(script, "w", encoding="utf-8") as f:
            for i, (addr, wav) in enumerate(replacements):
                f.write(f'Stream s{i} "{wav}" replaces ${addr};\n')
        out_zip = os.path.join(td, "out.zip")
        proc = _run([encoder, "--patch", "--rom-size=*", "-q",
                     "-o", out_zip, zp, script], _ENCODE_TIMEOUT)
        if not os.path.isfile(out_zip):
            tail = (proc.stdout + proc.stderr).strip().splitlines()
            raise DcsRepackError(
                "DCSEncoder failed: "
                + (tail[-1] if tail else f"exit {proc.returncode}"))

        os.makedirs(out_rom_dir, exist_ok=True)
        with _zip.ZipFile(out_zip) as z:
            for member in z.namelist():
                base = os.path.basename(member)
                if _ROM_RE.match(base):
                    with z.open(member) as src, \
                            open(os.path.join(out_rom_dir, base), "wb") as dst:
                        dst.write(src.read())
    return {"modified_count": len(replacements), "total": total}
