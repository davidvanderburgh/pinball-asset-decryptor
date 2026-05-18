"""Generators for tiny but format-valid game files.

Each function builds the smallest file that satisfies a manufacturer's
detection + extraction rules — typically a handful of bytes wrapped in
the right container.  This lets us exercise the full
extract -> modify -> write pipeline end-to-end without shipping any
copyrighted real game data.

Formats covered:
  - PB .upd     (gzip+tar with game/<key>/ internal prefix)
  - Spooky .ed  (plain tar.gz)
  - Spooky .scooby (plain tar.gz, different ext)
  - Spooky .looney (plain tar)
  - Spooky P3 .zip  (plain ZIP, name pattern triggers detection)
  - Spooky AES .pkg (R&M + AC; keys are baked into the plugin)
  - BOF .fun    (gpg symmetric — requires gpg binary at test time)

Formats deliberately NOT synthesized (too complex / not testable in CI):
  - Spooky GPG symmetric .pkg (UM/H78) — needs gpg + non-trivial wrapping
  - Spooky GPG-signed .pkg (Beetlejuice) — needs gpg + signing key dance
  - Spooky Clonezilla .iso/.zip — would need a valid partclone image
  - JJP .iso — would need a valid Clonezilla restore image
"""

import io
import os
import shutil
import struct
import subprocess
import tarfile
import zipfile


# ---------------------------------------------------------------------------
# Pinball Brothers .upd
# ---------------------------------------------------------------------------

def make_pb_upd(out_path, game_key="abba", extra_files=None):
    """Generate a minimal valid PB .upd file.

    Args:
        out_path: where to write the .upd
        game_key: one of pb's GAME_DB keys; the file's internal layout
            uses that game's `internal_dir` so detect_game() picks it.
        extra_files: optional dict of {relpath_inside_internal_dir: bytes}
            for write-back round-trip tests.
    """
    from pinball_decryptor.plugins.pb.games import GAME_DB
    internal_dir = GAME_DB[game_key]["internal_dir"]

    files = {
        "main.cfg": b"# synthetic PB config\nversion=test\n",
        "audio/intro.wav": b"RIFFsynthetic-wav-data",
        "video/title.mp4": b"\x00\x00\x00\x18ftypmp42synthetic-mp4",
    }
    if extra_files:
        files.update(extra_files)

    with tarfile.open(out_path, "w:gz") as tar:
        for relpath, data in files.items():
            info = tarfile.TarInfo(name=f"{internal_dir}/{relpath}")
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return out_path


# ---------------------------------------------------------------------------
# Spooky plain tar.gz formats — .ed, .scooby, TCM .pkg
# ---------------------------------------------------------------------------

def make_spooky_targz(out_path, files=None):
    """Generate a minimal plain tar.gz with arbitrary contents.

    Used for .ed (Evil Dead), .scooby (Scooby-Doo), and tcm-*.pkg.
    """
    files = files or {
        "game/data.bin": b"hello synthetic",
        "game/config.json": b'{"version": "test"}',
    }
    with tarfile.open(out_path, "w:gz") as tar:
        for relpath, data in files.items():
            info = tarfile.TarInfo(name=relpath)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return out_path


def make_spooky_plain_tar(out_path, files=None):
    """Generate a minimal plain (uncompressed) tar — for .looney."""
    files = files or {"game/data.bin": b"looney tunes test"}
    with tarfile.open(out_path, "w:") as tar:
        for relpath, data in files.items():
            info = tarfile.TarInfo(name=relpath)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return out_path


def make_spooky_p3_zip(out_path, files=None):
    """Generate a minimal plain ZIP — for P3 DMD games (AMH, Jetsons, etc.)."""
    files = files or {
        "Jetsons/ATTRACT.VID": b"\x80\x20\x40\x20\x40\x08\x0f\x00",
        "Jetsons/SFX/snd1.wav": b"RIFF...synthetic",
    }
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for relpath, data in files.items():
            zf.writestr(relpath, data)
    return out_path


# ---------------------------------------------------------------------------
# Spooky AES .pkg (R&M, AC) — uses the known keys baked into the plugin
# ---------------------------------------------------------------------------

def make_spooky_aes_pkg(out_path, key_name="rm_pkg", files=None):
    """Generate a minimal AES-256-CBC .pkg (rm_pkg or ac_pkg).

    Builds a tiny ZIP in memory, encrypts it via the plugin's
    own encrypt_aes_pkg helper.
    """
    from pinball_decryptor.plugins.spooky.crypto import (
        AES_KEYS, encrypt_aes_pkg)

    files = files or {
        "game.txt": b"R&M synthetic content",
        "config.json": b'{"version": "test"}',
    }

    # Write a tiny intermediate ZIP, then encrypt it.
    tmp_zip = str(out_path) + ".tmp.zip"
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for relpath, data in files.items():
            zf.writestr(relpath, data)
    try:
        encrypt_aes_pkg(tmp_zip, str(out_path), AES_KEYS[key_name])
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)
    return out_path


# ---------------------------------------------------------------------------
# BOF .fun — gpg symmetric over a tar.gz, requires gpg binary
# ---------------------------------------------------------------------------

def make_bof_fun(out_path, game_key="labyrinth", files=None):
    """Generate a minimal valid BOF .fun.

    The .fun format is: gpg --symmetric over a tar.gz containing a
    Godot binary (main.x86_64) + companion files.  We use the
    passphrase baked into the plugin's GAME_DB.

    Skips with FileNotFoundError if no `gpg` binary is on PATH.
    """
    if shutil.which("gpg") is None:
        raise FileNotFoundError("gpg binary required for BOF fixtures")

    from pinball_decryptor.plugins.bof.games import GAME_DB
    info = GAME_DB[game_key]
    passphrase = info["passphrase"]

    files = files or {
        "main.x86_64": b"#!/bin/sh\necho synthetic godot bin\n",
        "md5": b"deadbeef  main.x86_64\n",
    }

    # Inner tar.gz
    tmp_tar = str(out_path) + ".tmp.tar.gz"
    with tarfile.open(tmp_tar, "w:gz") as tar:
        for relpath, data in files.items():
            tar_info = tarfile.TarInfo(name=relpath)
            tar_info.size = len(data)
            tar_info.mtime = 0
            tar.addfile(tar_info, io.BytesIO(data))

    # gpg --symmetric --cipher-algo AES256
    try:
        subprocess.run(
            ["gpg", "--batch", "--yes",
             "--passphrase", passphrase,
             "--symmetric", "--cipher-algo", "AES256",
             "--output", str(out_path), tmp_tar],
            check=True, capture_output=True, timeout=30)
    finally:
        if os.path.exists(tmp_tar):
            os.remove(tmp_tar)
    return out_path
