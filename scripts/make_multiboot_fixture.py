#!/usr/bin/env python3
"""Build a small, REAL multi-boot Spike 2 card image (PAD-122).

Three games and a rootfs, each a genuine ext4 filesystem made by ``mke2fs
-d``, laid out the way ``tools/spike2_emu/mkmulticard.py --layout parts``
lays a card out: the primary game in p3 and the extras appended to the EBR
chain as p7 and p8, behind the Spike 2 boot/rootfs partition signature the
detector looks for.  128 MB instead of three 7 GB cards, and the app cannot
tell the difference: the probe (``plugins.stern.multiimage``), the extract's
own locator and a whole images-only Extract all run over it unmodified.

Run it under WSL (Windows has no mke2fs), naming the output on the Windows
side so the app can open it:

    wsl python3 /mnt/c/<repo>/scripts/make_multiboot_fixture.py \\
        /mnt/c/tmp/pad122/godzilla_multi-1_16_0.Release.16G.sdcard.raw

The name matters as much as the bytes: ``formats.detect_game`` claims a
``.img``/``.bin``/``.raw`` with the Spike 2 partition shape, and the title in
the filename is what the window then reports.  ``scripts/shot_pad122.py``
shoots the proof pair against the result.
"""
import os
import struct
import subprocess
import sys

SECTOR = 512
W = "/tmp/pad122"

# (name, game folder, sectors)
GAMES = [("games1", "godzilla_pro", 65536),
         ("games2", "jaws_pro", 65536),
         ("games3", "venom_le", 65536)]

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082")

# A 32-bit ARM ELF header — engine._locate validates the magic before it
# accepts a file as the game firmware.
ELF = (b"\x7fELF\x01\x01\x01\x00" + b"\x00" * 8
       + struct.pack("<HH", 2, 40) + b"\x00" * (192 * 1024))


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def make_tree(name, folder):
    root = "%s/%s" % (W, name)
    write("%s/spk/index/%s-1_16_0.sidx" % (root, folder), b"FI64" + b"\x00" * 60)
    write("%s/%s/image.bin" % (root, folder), b"\x00" * 4096)
    write("%s/%s/game" % (root, folder), ELF)
    for n in ("Attract_Logo", "Menu_Background"):
        write("%s/%s/lcd/scene.assets/00/%s.png" % (root, folder, n), PNG)
    return root


def mkfs(img, sectors, tree=None):
    run("dd", "if=/dev/zero", "of=%s" % img, "bs=512", "count=0",
        "seek=%d" % sectors, "status=none")
    args = ["mke2fs", "-q", "-F", "-t", "ext4", "-b", "4096", "-L",
            os.path.basename(img)]
    if tree:
        args += ["-d", tree]
    run(*(args + [img]))


def main(out):
    os.makedirs(W, exist_ok=True)
    for name, folder, sectors in GAMES:
        mkfs("%s/%s.img" % (W, name), sectors, make_tree(name, folder))
    write("%s/rootfs/etc/version" % W, b"1.16.0\n")
    write("%s/rootfs/usr/local/codeselect/images.conf" % W,
          b"godzilla_pro\njaws_pro\nvenom_le\n")
    write("%s/rootfs/lib/ld.so" % W, b"\x00" * 16)
    mkfs("%s/rootfs.img" % W, 16384, "%s/rootfs" % W)
    for empty in ("data", "dump"):
        mkfs("%s/%s.img" % (W, empty), 8192)

    # ---- the card ----------------------------------------------------------
    p1 = (0x0C, 8192, 16384)                       # FAT boot (zeros)
    p2 = (0x83, 24576, 16384, "rootfs")
    p3 = (0x83, 40960, 65536, "games1")
    ext_base = 106496
    # (ebr_lba, sectors, source) — each logical sits 2048 sectors after its EBR
    chain = [(106496, 8192, "data"), (116736, 8192, "dump"),
             (126976, 65536, "games2"), (194560, 65536, "games3")]
    total = 262144

    with open(out, "wb") as f:
        f.truncate(total * SECTOR)
        mbr = bytearray(512)
        prims = [p1, (p2[0], p2[1], p2[2]), (p3[0], p3[1], p3[2]),
                 (0x0F, ext_base, total - ext_base)]
        for i, (ptype, lba, sectors) in enumerate(prims):
            off = 446 + i * 16
            mbr[off + 4] = ptype
            struct.pack_into("<II", mbr, off + 8, lba, sectors)
        mbr[510:512] = b"\x55\xaa"
        f.seek(0)
        f.write(bytes(mbr))

        for i, (ebr_lba, sectors, src) in enumerate(chain):
            ebr = bytearray(512)
            ebr[446 + 4] = 0x83
            struct.pack_into("<II", ebr, 446 + 8, 2048, sectors)
            if i + 1 < len(chain):
                ebr[446 + 16 + 4] = 0x0F
                struct.pack_into("<II", ebr, 446 + 16 + 8,
                                 chain[i + 1][0] - ext_base, 4096)
            ebr[510:512] = b"\x55\xaa"
            f.seek(ebr_lba * SECTOR)
            f.write(bytes(ebr))
            with open("%s/%s.img" % (W, src), "rb") as g:
                f.seek((ebr_lba + 2048) * SECTOR)
                while True:
                    chunk = g.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)

        for lba, src in ((p2[1], p2[3]), (p3[1], p3[3])):
            with open("%s/%s.img" % (W, src), "rb") as g:
                f.seek(lba * SECTOR)
                while True:
                    chunk = g.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)

    print("wrote %s (%d MB)" % (out, os.path.getsize(out) >> 20))


if __name__ == "__main__":
    main(sys.argv[1])
