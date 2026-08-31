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


# ---------------------------------------------------------------------------
# Stern Spike 1 (raw MBR SD-card .iso; plaintext image.bin container)
# ---------------------------------------------------------------------------

def make_spike1_mbr(out_path, with_logicals=True):
    """A minimal Spike 1 card image: the fixed partition signature (FAT12 at
    LBA 35, 0xDA kernel at 7000, Linux rootfs at 14000) plus an extended
    partition whose EBR chain carries two logical Linux partitions — enough
    for parse_all_partitions / is_spike1_card_parts / detect_spike1_game;
    the partitions hold no filesystems."""
    ext_base = 16384
    total_sectors = ext_base + 4096
    img = bytearray(total_sectors * 512)

    def entry(ptype, lba, sectors, boot=0):
        return bytes([boot, 0, 0, 0, ptype, 0, 0, 0]) + \
            struct.pack("<II", lba, sectors)

    mbr = bytearray(512)
    mbr[446:462] = entry(0x01, 35, 6965, boot=0x80)
    mbr[462:478] = entry(0xda, 7000, 7000)
    mbr[478:494] = entry(0x83, 14000, 2000)
    if with_logicals:
        mbr[494:510] = entry(0x05, ext_base, 4096)
    mbr[510:512] = b"\x55\xaa"
    img[0:512] = mbr

    if with_logicals:
        # EBR 1 at ext_base: logical at +8 (1024 sectors), link to +2048
        ebr1 = bytearray(512)
        ebr1[446:462] = entry(0x83, 8, 1024)
        ebr1[462:478] = entry(0x05, 2048, 2048)
        ebr1[510:512] = b"\x55\xaa"
        img[ext_base * 512:ext_base * 512 + 512] = ebr1
        # EBR 2 at ext_base+2048: logical at +8 (1024 sectors), end of chain
        ebr2 = bytearray(512)
        ebr2[446:462] = entry(0x83, 8, 1024)
        ebr2[510:512] = b"\x55\xaa"
        img[(ext_base + 2048) * 512:(ext_base + 2048) * 512 + 512] = ebr2

    with open(out_path, "wb") as f:
        f.write(img)
    return out_path


def make_spike1_image_bin(front_header=True, multi_track=True, h2_at=None):
    """A tiny but structurally-complete Spike 1 ``image.bin``: front header
    (or erased front page, exercising the fixed-location fallback), header2,
    x5-grouped pointer table, PCM bodies, and master records — one single-
    track mono sound and (optionally) one two-track record whose extra body
    hangs off an ``0a 00`` tag.  Returns ``(blob, expected)`` where expected
    is ``[(idx, [(frames, ch, div), ...]), ...]``.  ``h2_at`` overrides the
    erased-front header2 page (default 0x120000; 0x120038 is the other fixed
    candidate real cards use)."""
    frames1, ch1, div1 = 100, 1, 1
    frames2, ch2, div2 = 60, 2, 2
    frames3, ch3, div3 = 30, 1, 2

    if front_header:
        h2_off = 0x78
        table_off = 0xC0
        body_base = 0x200
    else:
        h2_off = h2_at if h2_at is not None else 0x120000
        table_off = h2_off + 0x48
        body_base = h2_off + 0x100

    def body(seed, frames, ch, div):
        pcm = bytes((seed + i) & 0xff for i in range(2 * ch * frames))
        return struct.pack("<IHH", frames, ch, div) + pcm

    b1 = body(1, frames1, ch1, div1)
    b2 = body(2, frames2, ch2, div2)
    b3 = body(3, frames3, ch3, div3)
    b1_off = body_base
    b2_off = (b1_off + len(b1) + 7) & ~7
    b3_off = (b2_off + len(b2) + 7) & ~7
    md_start = (b3_off + len(b3) + 15) & ~15

    def rec_header(len_ticks):
        return bytes([0x05, 0x04, 0x01]) + struct.pack("<I", len_ticks) + \
            bytes([0x02, 0x00, 0x00, 0x00, 0x00])

    # record 0: single-track, inline pointer at +12
    rec0 = rec_header((frames1 * div1 + 5) // 6) + \
        struct.pack("<Q", b1_off) + bytes.fromhex("100100ff")
    recs = [rec0]
    if multi_track:
        # record 1: sentinel inline field + two 0a-tagged body pointers
        rec1 = rec_header((frames2 * div2 + 5) // 6) + \
            struct.pack("<Q", 1) + \
            b"\x0a\x00" + struct.pack("<Q", b2_off) + \
            b"\x0a\x00" + struct.pack("<Q", b3_off) + \
            bytes.fromhex("100100ff")
        recs.append(rec1)

    rec_offs = []
    pos = md_start
    for r in recs:
        rec_offs.append(pos)
        pos += (len(r) + 7) & ~7
    size = pos

    blob = bytearray(size)
    if front_header:
        struct.pack_into("<7Q", blob, 0, h2_off, size - 36, size - 40,
                         size - 44, size - 48, table_off, table_off)
    else:
        blob[0:0x80] = b"\xff" * 0x80
    struct.pack_into("<6Q", blob, h2_off, 0, h2_off - 1, 0xEE11FFFF,
                     table_off, size - 5, 0x12345678)
    tpos = table_off
    for ro in rec_offs:
        for _ in range(5):
            struct.pack_into("<Q", blob, tpos, ro)
            tpos += 8
    for off, data in ((b1_off, b1), (b2_off, b2), (b3_off, b3)):
        blob[off:off + len(data)] = data
    for off, r in zip(rec_offs, recs):
        blob[off:off + len(r)] = r

    expected = [(0, [(frames1, ch1, div1)])]
    if multi_track:
        expected.append((1, [(frames2, ch2, div2), (frames3, ch3, div3)]))
    return bytes(blob), expected


def make_ext2_fs(files, fs_blocks=512):
    """A minimal but real ext2 filesystem image (1 KB blocks, classic direct
    block pointers) that :class:`Ext4Reader` can walk.

    *files* is ``{path: bytes}`` with ``/``-separated paths; intermediate
    directories are created.  Small scale only: every file must fit in 12
    direct blocks (12 KB) and everything in one block group.
    """
    BS = 1024
    INODE_SIZE = 128
    N_INODES = 64
    it_blocks = (N_INODES * INODE_SIZE + BS - 1) // BS
    first_data = 3 + it_blocks          # 0 boot, 1 sb, 2 gdt, 3.. itable

    img = bytearray(fs_blocks * BS)

    # superblock (fields Ext4Reader reads)
    sb = bytearray(1024)
    struct.pack_into("<I", sb, 0x00, N_INODES)          # inodes_count
    struct.pack_into("<I", sb, 0x04, fs_blocks)         # blocks_count
    struct.pack_into("<I", sb, 0x14, 1)                 # first_data_block
    struct.pack_into("<I", sb, 0x18, 0)                 # log_block_size
    struct.pack_into("<I", sb, 0x20, 8192)              # blocks_per_group
    struct.pack_into("<I", sb, 0x28, N_INODES)          # inodes_per_group
    struct.pack_into("<H", sb, 0x38, 0xEF53)            # magic
    struct.pack_into("<H", sb, 0x58, INODE_SIZE)        # inode_size
    struct.pack_into("<I", sb, 0x60, 0x2)               # incompat: FILETYPE
    img[1024:2048] = sb

    # group descriptor 0: inode table block
    struct.pack_into("<I", img, 2 * BS + 8, 3)

    next_block = [first_data]
    next_ino = [11]                     # first non-reserved inode

    def alloc_blocks(data):
        n = max(1, (len(data) + BS - 1) // BS)
        assert n <= 12, "make_ext2_fs: file too big for direct blocks"
        start = next_block[0]
        next_block[0] += n
        img[start * BS:start * BS + len(data)] = data
        return list(range(start, start + n))

    def write_inode(ino, mode, size, blocks):
        off = 3 * BS + (ino - 1) * INODE_SIZE
        struct.pack_into("<H", img, off, mode)
        struct.pack_into("<I", img, off + 4, size)
        struct.pack_into("<I", img, off + 0x20, 0)      # flags
        for i, b in enumerate(blocks):
            struct.pack_into("<I", img, off + 0x28 + 4 * i, b)

    def dir_block(entries):
        """entries: [(ino, name, ftype)] -> one directory data block."""
        out = bytearray()
        for i, (ino, name, ftype) in enumerate(entries):
            nb = name.encode()
            rec = 8 + ((len(nb) + 3) & ~3)
            if i == len(entries) - 1:
                rec = BS - len(out)
            out += struct.pack("<IHBB", ino, rec, len(nb), ftype) + nb
            out += b"\x00" * (rec - 8 - len(nb))
        return bytes(out)

    # build the tree: dirs as {name: (ino, entries)}, files appended later
    tree = {}                           # dir path -> (ino, [(ino,name,ftype)])
    tree[""] = (2, [(2, ".", 2), (2, "..", 2)])

    def ensure_dir(path):
        if path in tree:
            return tree[path][0]
        parent, _, name = path.rpartition("/")
        pino = ensure_dir(parent)
        ino = next_ino[0]
        next_ino[0] += 1
        tree[path] = (ino, [(ino, ".", 2), (pino, "..", 2)])
        tree[parent][1].append((ino, name, 2))
        return ino

    for path, data in files.items():
        parent, _, name = path.rpartition("/")
        ensure_dir(parent)
        ino = next_ino[0]
        next_ino[0] += 1
        write_inode(ino, 0x8000 | 0o644, len(data), alloc_blocks(data))
        tree[parent][1].append((ino, name, 1))

    for path, (ino, entries) in tree.items():
        data = dir_block(entries)
        write_inode(ino, 0x4000 | 0o755, len(data), alloc_blocks(data))

    assert next_block[0] <= fs_blocks, "make_ext2_fs: filesystem full"
    return bytes(img)


def make_spike1_sidx(game_dir, image_bin):
    """A real FINF ``.sidx`` manifest whose ``<game_dir>/image.bin`` record
    carries the true HMAC + MD5 of *image_bin* (same key/scheme the shipping
    sidx module validates)."""
    import hashlib
    import hmac as hmac_mod

    from pinball_decryptor.plugins.stern.sidx import SIDX_KEY

    h = hmac_mod.new(SIDX_KEY, image_bin, hashlib.sha1).digest()
    m = hashlib.md5(image_bin).digest()
    paths = ("%s/image.bin" % game_dir).encode() + b"\x00"
    payload = bytearray(57)
    struct.pack_into("<I", payload, 4, len(image_bin))
    struct.pack_into("<I", payload, 12, len(image_bin))
    payload[21:41] = h
    payload[41:57] = m
    return (b"SIDX" + b"\x00" * 0x34
            + b"STRS" + struct.pack("<I", len(paths)) + paths
            + b"FINF" + struct.pack("<I", len(payload)) + bytes(payload))


def make_spike1_card(out_path, game_dir="GAME_LE", **image_kwargs):
    """A complete synthetic Spike 1 card: the fixed MBR/EBR signature with a
    real ext2 filesystem on the first logical partition holding
    ``<game_dir>/image.bin`` (from :func:`make_spike1_image_bin`) and a valid
    ``/spk/index/<game_dir>-0_1.sidx``.  Returns ``(out_path, expected,
    image_bin)`` — enough to run extract_all / write_image / revert_assets
    end to end without a multi-GB fixture."""
    image_bin, expected = make_spike1_image_bin(**image_kwargs)
    sidx = make_spike1_sidx(game_dir, image_bin)
    fs = make_ext2_fs({
        "%s/image.bin" % game_dir: image_bin,
        "%s/game" % game_dir: b"\x7fELF" + b"\x00" * 60,
        "spk/index/%s-0_1.sidx" % game_dir: sidx,
    })
    make_spike1_mbr(out_path)
    with open(out_path, "r+b") as f:
        f.seek((16384 + 8) * 512)       # first logical partition
        f.write(fs)
    return out_path, expected, image_bin
