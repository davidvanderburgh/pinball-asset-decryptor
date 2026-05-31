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
# American Pinball AES .pkg — uses the universal key baked into the plugin
# ---------------------------------------------------------------------------

def make_ap_aes_pkg(out_path, files=None):
    """Generate a minimal American Pinball AES-256-CBC .pkg.

    Builds a tiny ZIP in memory and encrypts it with the plugin's own
    encrypt_aes_pkg helper (universal AP key).
    """
    from pinball_decryptor.plugins.ap.crypto import encrypt_aes_pkg

    files = files or {
        "game.txt": b"AP synthetic content",
        "config.yaml": b"version: test\n",
    }

    tmp_zip = str(out_path) + ".tmp.zip"
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for relpath, data in files.items():
            zf.writestr(relpath, data)
    try:
        encrypt_aes_pkg(tmp_zip, str(out_path))
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


# ---------------------------------------------------------------------------
# Williams MAME ROM zip — synthetic ROM bytes embedding a few DMD frames
# ---------------------------------------------------------------------------

def make_williams_rom_zip(out_path, game_key="fish_tales"):
    """Generate a minimal Williams MAME ROM .zip.

    The zip carries the canonical game-ROM + sound-ROM filenames the
    plugin expects, with mostly-zero payloads padded out to the real
    file sizes (so size-based heuristics don't choke).  We embed a few
    synthetic 1024-byte 4-shade DMD frame chunks inside the game ROM
    so the scan pipeline has something plausible to find — useful for
    a tiny end-to-end test without shipping real ROM data.
    """
    from pinball_decryptor.plugins.williams.games import GAME_DB
    info = GAME_DB[game_key]

    def synth_dmd_frame():
        # Three horizontal "lit" stripes at varied densities + blank
        # rows in between.  Each lit row has holes so the solid-band
        # filter doesn't fire, and the bands give the band-spread
        # heuristic something to chew on.
        lit_row = (b"\x00\x00\xff\xff\xff\xff\xff\xff"
                   b"\xff\xff\xff\xff\x00\x00\x00\x00")
        dim_row = (b"\x00\x00\x0f\x0f\x0f\x0f\x0f\x0f"
                   b"\x0f\x0f\x0f\x0f\x00\x00\x00\x00")
        plane = bytearray()
        for r in range(32):
            if 4 <= r < 8:
                plane.extend(lit_row)
            elif 12 <= r < 16:
                plane.extend(dim_row)
            elif 20 <= r < 24:
                plane.extend(lit_row)
            else:
                plane.extend(b"\x00" * 16)
        return bytes(plane) + bytes(plane)  # low + high planes

    # First game-ROM file gets the embedded frames; the rest are filler.
    rom_size = 524288  # 512 KB matches real WPC game ROM
    sound_size = 524288

    primary = bytearray(b"\x00" * rom_size)
    # Place 8 contiguous frames inside the primary ROM at offset 0x4000.
    frame = synth_dmd_frame()
    base = 0x4000
    for i in range(8):
        start = base + i * 1024
        primary[start:start + 1024] = frame
    primary_bytes = bytes(primary)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # game ROM(s) — first one is the populated one
        game_roms = info["game_roms"]
        zf.writestr(game_roms[0], primary_bytes)
        for n in game_roms[1:]:
            zf.writestr(n, b"\x00" * 256)  # placeholder; not parsed
        # sound ROM(s) — passthrough copies, no DMD data
        for n in info["sound_roms"]:
            zf.writestr(n, b"\x00" * sound_size)
    return out_path


# ---------------------------------------------------------------------------
# Dutch Pinball — TBL .cdmd video, TBL update .zip, AAIW installer .img,
# and a partclone v2 image (for the pure-Python reader)
# ---------------------------------------------------------------------------

def make_cdmd(nframes=2, w=2, h=2):
    """Build a minimal but format-valid TBL ``.cdmd`` video byte string.

    Header: magic 01 02 15 20 + nframes + canvasW + canvasH, then each
    frame is x,y,w,h + w*h*4 ARGB bytes (here a full-canvas solid colour).
    """
    out = bytearray(b"\x01\x02\x15\x20")
    out += struct.pack("<3I", nframes, w, h)
    for i in range(nframes):
        out += struct.pack("<4I", 0, 0, w, h)
        # opaque colour that varies per frame: A=0xff, R=i, G=0x40, B=0x80
        out += bytes([0xff, i & 0xff, 0x40, 0x80]) * (w * h)
    return bytes(out)


def make_tbl_zip(out_path, version="1.00", delta_bases=None, extra_files=None):
    """Generate a minimal TBL update zip (full, or a delta if delta_bases set).

    Carries a ``<version>/assets/sequences/clip/clip.cdmd`` video plus a
    sound ``.wav`` so detection and the cdmd-decode pass have real input.
    *delta_bases* (a list of compatible base versions) writes the
    ``<version>/delta`` marker that identifies the zip as a delta.
    *extra_files* maps ``<version>``-relative paths to bytes (used to give a
    delta a recognisable changed/added file).
    """
    files = {
        f"{version}/start": b"#!/bin/sh\n",
        f"{version}/assets/sequences/clip/clip.cdmd": make_cdmd(2, 2, 2),
        f"{version}/assets/sequences/clip/clip.wav": b"RIFFsynthetic-wav",
        f"{version}/assets/sound/beep.wav": b"RIFFbeep",
    }
    if delta_bases:
        files[f"{version}/delta"] = (",".join(delta_bases)).encode()
    for rel, data in (extra_files or {}).items():
        files[f"{version}/{rel}"] = data
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for relpath, data in files.items():
            zf.writestr(relpath, data)
    return out_path


def make_aaiw_img(out_path, hint_name=True):
    """Generate a tiny file with an AAIW-shaped MBR (2 parts: FAT + Linux).

    Only the 512-byte MBR matters for ``is_aaiw_img`` detection; the rest
    is a sparse placeholder so we don't write gigabytes.
    """
    mbr = bytearray(512)
    # Partition 1: FAT (type 0x0c), start LBA 2048, 1024000 sectors.
    struct.pack_into("<B", mbr, 446 + 4, 0x0c)
    struct.pack_into("<II", mbr, 446 + 8, 2048, 1024000)
    # Partition 2: Linux (type 0x83), start LBA 1026048, 4096000 sectors.
    struct.pack_into("<B", mbr, 446 + 16 + 4, 0x83)
    struct.pack_into("<II", mbr, 446 + 16 + 8, 1026048, 4096000)
    mbr[510:512] = b"\x55\xaa"
    name = out_path
    with open(name, "wb") as f:
        f.write(mbr)
    return out_path


def make_partclone_v2(out_path, used_blocks=(0, 2), totalblock=4,
                      block_size=512, blocks_per_checksum=2):
    """Build a tiny partclone **image format v2** for the reader round-trip.

    Each used block is filled with a recognisable byte (block index + 1).
    Returns ``(path, expected_raw_bytes)`` so a test can assert the restore.
    """
    used = set(used_blocks)
    # --- image_desc_v2 header (110 bytes) ---
    head = bytearray()
    head += b"partclone-image\x00"                 # magic[16]
    head += b"0.3.36".ljust(14, b"\x00")           # ptc_version[14]
    head += b"0002"                                 # version[4]
    head += struct.pack("<H", 0xC0DE)               # endianess
    head += b"EXTFS".ljust(16, b"\x00")             # fs[16]
    head += struct.pack("<4Q", totalblock * block_size, totalblock,
                        len(used), len(used))        # sizes/usedblocks
    head += struct.pack("<I", block_size)            # block_size
    head += struct.pack("<I", 18)                    # feature_size
    head += struct.pack("<H", 2)                     # image_version
    head += struct.pack("<H", 64)                    # cpu_bits
    head += struct.pack("<H", 32)                    # checksum_mode (CRC32)
    head += struct.pack("<H", 4)                     # checksum_size
    head += struct.pack("<I", blocks_per_checksum)   # blocks_per_checksum
    head += bytes([1, 1])                            # reseed, bitmap_mode
    head += struct.pack("<I", 0)                     # header crc (unverified)
    assert len(head) == 110, len(head)

    # --- bitmap (1 bit/block, LSB first) + its CRC ---
    nbytes = (totalblock + 7) // 8
    bitmap = bytearray(nbytes)
    for b in used:
        bitmap[b >> 3] |= 1 << (b & 7)
    body = bytes(bitmap) + b"\x00\x00\x00\x00"

    # --- data blocks (in block order) with interleaved CRCs ---
    expected = bytearray(totalblock * block_size)
    written = 0
    for blk in range(totalblock):
        if blk not in used:
            continue
        data = bytes([(blk + 1) & 0xff]) * block_size
        expected[blk * block_size:(blk + 1) * block_size] = data
        body += data
        written += 1
        if written % blocks_per_checksum == 0:
            body += b"\x00\x00\x00\x00"  # interleaved CRC (unverified)

    with open(out_path, "wb") as f:
        f.write(head + body)
    return out_path, bytes(expected)
