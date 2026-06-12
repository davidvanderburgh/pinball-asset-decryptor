#!/usr/bin/env python3
"""
build_extractor_card.py - Build a Stern "Spike 3" OTP-key extractor boot image.

Pure Python, cross-platform (Windows/macOS/Linux). No WSL, no cryptsetup.

It takes Stern's signed boot image and produces a patched copy whose initramfs
/init, at boot, writes the machine's 256-bit LUKS disk-encryption key (read from
the Raspberry Pi CM4 customer OTP via `vcmailbox 0x00030021`, exactly as Stern's
own code does) to a plain text file `OTP_KEY.TXT` on the FAT boot partition,
which any PC can read. The rest of the boot/unlock sequence is unchanged, so the
machine still boots the game normally.

  >>> READ docs/KEY_EXTRACTION.md FIRST. This only works if the machine does NOT
  >>> enforce Raspberry Pi secure boot. If it does, the patched card will refuse
  >>> to boot (harmless - restore the backed-up boot.img/boot.sig). See that doc.

Input may be EITHER:
  * a BOOT.IMG file copied off the card's first (FAT) partition, or
  * a raw SD card image (*.raw) - boot.img + boot.sig are extracted from its
    first partition automatically.

Output (default ./extractor_card_out/):
  * boot.img  - patched (replaces the boot.img on the card's FAT partition)
  * boot.sig  - its signature header, SHA-256 line regenerated to match boot.img
                (the RSA line is carried over unchanged; it is only enforced
                 under secure boot, in which case this whole approach is moot)

Usage:
  python build_extractor_card.py <BOOT.IMG | image.raw> [-o OUTDIR]
                                 [--boot-sig BOOT.SIG]

Requires: zstandard  (pip install zstandard)  -- already a project dependency.
"""
import argparse
import hashlib
import os
import struct
import sys

try:
    import zstandard as zstd
except ImportError:
    sys.exit("ERROR: this tool needs the 'zstandard' package (pip install zstandard)")


# ---------------------------------------------------------------------------
# The initramfs key-dump block, inserted right after /init creates /ktmp.
# Uses only tools present in Stern's initramfs (busybox applets + xxd). It is
# best-effort and never aborts the boot: vfat write first (kernel has VFAT
# built in), plus a raw last-sector fallback in case the mount ever fails.
# ---------------------------------------------------------------------------
DUMP_BLOCK = (
    "\n"
    "# === SPIKE3 OTP KEY DUMP (added by build_extractor_card.py) ===\n"
    "# Write the 64-hex LUKS keyfile to the FAT boot partition (mmcblk0p1)\n"
    "# so it can be read on any PC. Best-effort; does not affect normal boot.\n"
    "mkdir -p /fatboot\n"
    "mount -t vfat /dev/mmcblk0p1 /fatboot 2>/dev/null\n"
    "xxd -p -c 32 /ktmp > /fatboot/OTP_KEY.TXT 2>/dev/null\n"
    "sync\n"
    "umount /fatboot 2>/dev/null\n"
    "# raw fallback: write the key to the LAST sector of p1 (no filesystem needed)\n"
    "xxd -p -c 32 /ktmp > /ktmp.hex 2>/dev/null\n"
    "dd if=/ktmp.hex of=/dev/mmcblk0p1 bs=512 seek=131071 count=1 conv=notrunc 2>/dev/null\n"
    "rm -f /ktmp.hex\n"
    "sync\n"
    "# === END OTP KEY DUMP ===\n"
)
KTMP_MARKER = "xxd -r -p > /ktmp\n"


# ===========================================================================
# Minimal FAT16/FAT32 reader (read-only) - to locate/extract files
# ===========================================================================
class FatReader:
    def __init__(self, data):
        self.data = data
        bpb = data[:512]
        self.bytes_per_sector = struct.unpack_from("<H", bpb, 11)[0]
        self.sectors_per_cluster = bpb[13]
        self.reserved = struct.unpack_from("<H", bpb, 14)[0]
        self.num_fats = bpb[16]
        self.root_entry_count = struct.unpack_from("<H", bpb, 17)[0]
        tot16 = struct.unpack_from("<H", bpb, 19)[0]
        tot32 = struct.unpack_from("<I", bpb, 32)[0]
        fat16 = struct.unpack_from("<H", bpb, 22)[0]
        fat32 = struct.unpack_from("<I", bpb, 36)[0]
        self.fat_size = fat16 if fat16 else fat32
        self.root_cluster = struct.unpack_from("<I", bpb, 44)[0]
        total = tot16 if tot16 else tot32
        root_dir_sectors = (self.root_entry_count * 32 + self.bytes_per_sector - 1) // self.bytes_per_sector
        data_sectors = total - (self.reserved + self.num_fats * self.fat_size + root_dir_sectors)
        clusters = data_sectors // self.sectors_per_cluster
        self.fat_type = 12 if clusters < 4085 else (16 if clusters < 65525 else 32)
        self.cluster_size = self.bytes_per_sector * self.sectors_per_cluster
        self.fat_offset = self.reserved * self.bytes_per_sector
        self.root_dir_offset = self.fat_offset + self.num_fats * self.fat_size * self.bytes_per_sector
        self.data_offset = self.root_dir_offset + root_dir_sectors * self.bytes_per_sector

    def _fat_entry(self, c):
        if self.fat_type == 16:
            return struct.unpack_from("<H", self.data, self.fat_offset + c * 2)[0]
        return struct.unpack_from("<I", self.data, self.fat_offset + c * 4)[0] & 0x0FFFFFFF

    def _eoc(self, v):
        return v >= (0xFFF8 if self.fat_type == 16 else 0x0FFFFFF8)

    def _chain(self, start, max_size=None):
        out = bytearray()
        c = start
        seen = set()
        while c >= 2 and not self._eoc(c) and c not in seen:
            seen.add(c)
            off = self.data_offset + (c - 2) * self.cluster_size
            out += self.data[off:off + self.cluster_size]
            if max_size and len(out) >= max_size:
                break
            c = self._fat_entry(c)
        return bytes(out[:max_size]) if max_size else bytes(out)

    def _root_entries(self):
        if self.fat_type == 32:
            return self._chain(self.root_cluster)
        return self.data[self.root_dir_offset:self.root_dir_offset + self.root_entry_count * 32]

    def find(self, name_upper):
        """Find a file in the root dir by 8.3 name (case-insensitive). Returns bytes or None."""
        d = self._root_entries()
        for i in range(0, len(d), 32):
            e = d[i:i + 32]
            if len(e) < 32 or e[0] == 0x00:
                break
            if e[0] == 0xE5 or (e[11] & 0x0F) == 0x0F or (e[11] & 0x08):
                continue
            nm = e[0:8].decode("ascii", "replace").rstrip()
            ext = e[8:11].decode("ascii", "replace").rstrip()
            full = f"{nm}.{ext}" if ext else nm
            if full.upper() == name_upper.upper():
                cluster = struct.unpack_from("<H", e, 26)[0]
                size = struct.unpack_from("<I", e, 28)[0]
                return self._chain(cluster, size)
        return None


# ===========================================================================
# FAT16 in-place file replacement (for the inner boot.img)
# ===========================================================================
def _fat16_params(img):
    bpb = img[:512]
    bps = struct.unpack_from("<H", bpb, 11)[0]
    spc = bpb[13]
    reserved = struct.unpack_from("<H", bpb, 14)[0]
    nfats = bpb[16]
    rec = struct.unpack_from("<H", bpb, 17)[0]
    spf = struct.unpack_from("<H", bpb, 22)[0]
    fat_start = reserved * bps
    root_start = fat_start + nfats * spf * bps
    data_start = root_start + rec * 32
    return dict(bps=bps, spc=spc, nfats=nfats, rec=rec, spf=spf,
                fat_start=fat_start, root_start=root_start, data_start=data_start,
                cluster_size=spc * bps)


def _chain16(img, p, start):
    chain, c = [], start
    while 2 <= c <= 0xFFF6:
        chain.append(c)
        c = struct.unpack_from("<H", img, p["fat_start"] + c * 2)[0]
        if len(chain) > 100000:
            break
    return chain


def _find_entry16(img, p, name_upper):
    for i in range(p["rec"]):
        off = p["root_start"] + i * 32
        e = img[off:off + 32]
        if e[0] == 0x00:
            break
        if e[0] == 0xE5 or (e[11] & 0x0F) == 0x0F or (e[11] & 0x08):
            continue
        nm = e[0:8].decode("ascii", "replace").rstrip()
        ext = e[8:11].decode("ascii", "replace").rstrip()
        full = f"{nm}.{ext}" if ext else nm
        if full.upper() == name_upper.upper() or ("ROOTFS" in nm.upper() and "ZST" in ext.upper()):
            return dict(offset=off,
                        cluster=struct.unpack_from("<H", e, 26)[0],
                        size=struct.unpack_from("<I", e, 28)[0])
    return None


def _replace_file16(img, p, entry, new_data):
    chain = _chain16(img, p, entry["cluster"])
    cs = p["cluster_size"]
    need = (len(new_data) + cs - 1) // cs
    fat_start = p["fat_start"]
    if need > len(chain):
        last = chain[-1]
        search = last + 1
        for _ in range(need - len(chain)):
            for c in range(search, 0xFFF0):
                if struct.unpack_from("<H", img, fat_start + c * 2)[0] == 0:
                    struct.pack_into("<H", img, fat_start + last * 2, c)
                    chain.append(c)
                    last = c
                    search = c + 1
                    break
            else:
                raise RuntimeError("no free clusters in boot.img")
        struct.pack_into("<H", img, fat_start + chain[-1] * 2, 0xFFFF)
    # write data
    pos = 0
    for c in chain[:need]:
        off = p["data_start"] + (c - 2) * cs
        chunk = new_data[pos:pos + cs]
        img[off:off + cs] = chunk + b"\x00" * (cs - len(chunk))
        pos += cs
    # free excess
    if need < len(chain):
        struct.pack_into("<H", img, fat_start + chain[need - 1] * 2, 0xFFFF)
        for c in chain[need:]:
            struct.pack_into("<H", img, fat_start + c * 2, 0x0000)
    # update dir size
    struct.pack_into("<I", img, entry["offset"] + 28, len(new_data))
    # mirror FAT2
    fat_bytes = p["spf"] * p["bps"]
    if p["nfats"] >= 2:
        img[fat_start + fat_bytes:fat_start + 2 * fat_bytes] = img[fat_start:fat_start + fat_bytes]


# ===========================================================================
# cpio (newc) parse + faithful repack with /init patched
# ===========================================================================
def _patch_cpio(cpio):
    N = len(cpio)
    pos = 0
    entries = []  # (name, mode, nlink, data)
    while pos + 110 <= N:
        if cpio[pos:pos + 6] != b"070701":
            nxt = cpio.find(b"070701", pos)
            if nxt < 0:
                break
            pos = nxt
            continue
        f = [int(cpio[pos + 6 + i * 8:pos + 6 + (i + 1) * 8], 16) for i in range(13)]
        mode, fsz, nsz = f[1], f[6], f[11]
        name = cpio[pos + 110:pos + 110 + nsz - 1].decode("latin1")
        foff = (pos + 110 + nsz + 3) & ~3
        data = cpio[foff:foff + fsz]
        pos = (foff + fsz + 3) & ~3
        if name == "TRAILER!!!":
            break
        entries.append([name, mode, f[4], data])

    patched = False
    for e in entries:
        if e[0] == "init":
            txt = e[3].decode("latin1")
            j = txt.find(KTMP_MARKER)
            if j < 0:
                raise SystemExit("could not find the /ktmp creation line in /init; "
                                 "is this really a Spike 3 initramfs?")
            j += len(KTMP_MARKER)
            e[3] = (txt[:j] + DUMP_BLOCK + txt[j:]).encode("latin1")
            patched = True
    if not patched:
        raise SystemExit("/init not found in initramfs cpio")

    out = bytearray()
    ino = 1000
    for name, mode, nlink, data in entries:
        nb = name.encode("latin1") + b"\x00"
        fields = [ino, mode, 0, 0, nlink or 1, 0, len(data), 0, 0, 0, 0, len(nb), 0]
        out += b"070701" + b"".join(b"%08X" % (v & 0xFFFFFFFF) for v in fields) + nb
        while len(out) % 4:
            out += b"\x00"
        out += data
        while len(out) % 4:
            out += b"\x00"
        ino += 1
    nb = b"TRAILER!!!\x00"
    fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(nb), 0]
    out += b"070701" + b"".join(b"%08X" % v for v in fields) + nb
    while len(out) % 512:
        out += b"\x00"
    return bytes(out)


# ===========================================================================
def patch_boot_img(boot_img):
    img = bytearray(boot_img)
    p = _fat16_params(img)
    entry = _find_entry16(img, p, "ROOTFS.CPIO.ZST")
    if entry is None:
        raise SystemExit("rootfs.cpio.zst not found in boot.img")
    original_zst = bytearray()
    for c in _chain16(img, p, entry["cluster"]):
        off = p["data_start"] + (c - 2) * p["cluster_size"]
        original_zst += img[off:off + p["cluster_size"]]
    original_zst = bytes(original_zst[:entry["size"]])
    if original_zst[:4] != b"\x28\xB5\x2F\xFD":
        print(f"  warning: rootfs file does not start with zstd magic ({original_zst[:4].hex()})")
    cpio = zstd.ZstdDecompressor().decompress(original_zst, max_output_size=64 * 1024 * 1024)
    new_cpio = _patch_cpio(cpio)
    new_zst = zstd.ZstdCompressor(level=19).compress(new_cpio)
    print(f"  initramfs: cpio {len(cpio):,} -> {len(new_cpio):,} bytes; "
          f"zst {len(original_zst):,} -> {len(new_zst):,} bytes")
    _replace_file16(img, p, entry, new_zst)
    return bytes(img)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a Spike 3 OTP-key extractor boot image")
    ap.add_argument("input", help="BOOT.IMG file, or a raw SD card image (*.raw)")
    ap.add_argument("-o", "--outdir", default="extractor_card_out")
    ap.add_argument("--boot-sig", help="path to BOOT.SIG (if input is a bare boot.img)")
    args = ap.parse_args(argv)

    boot_sig = None
    with open(args.input, "rb") as f:
        head = f.read(512)
        is_fat_bootsector = (head[3:11] == b"mkfs.fat"
                             or head[54:62].startswith(b"FAT")
                             or head[82:90].startswith(b"FAT"))
        if is_fat_bootsector:
            f.seek(0)
            boot_img = f.read()  # a FAT boot.img directly (~20 MB)
            if args.boot_sig and os.path.exists(args.boot_sig):
                boot_sig = open(args.boot_sig, "rb").read()
        elif head[510:512] == b"\x55\xaa":
            # raw SD image: read ONLY the first partition (do not load 60+ GB).
            print("Input looks like a raw SD image; extracting boot.img/boot.sig from partition 1...")
            e = head[446:446 + 16]
            lba = struct.unpack_from("<I", e, 8)[0]
            nsec = struct.unpack_from("<I", e, 12)[0]
            f.seek(lba * 512)
            part = f.read(min(nsec * 512, 256 * 1024 * 1024))
            fat = FatReader(part)
            boot_img = fat.find("BOOT.IMG")
            boot_sig = fat.find("BOOT.SIG")
            if boot_img is None:
                sys.exit("BOOT.IMG not found in the first partition of the raw image.")
        else:
            sys.exit("Unrecognized input: not a FAT boot.img and not an MBR raw image.")

    print(f"boot.img: {len(boot_img):,} bytes")
    patched = patch_boot_img(boot_img)

    os.makedirs(args.outdir, exist_ok=True)
    out_img = os.path.join(args.outdir, "boot.img")
    with open(out_img, "wb") as f:
        f.write(patched)
    new_hash = hashlib.sha256(patched).hexdigest()
    print(f"wrote {out_img}  (sha256 {new_hash})")

    out_sig = os.path.join(args.outdir, "boot.sig")
    lines = [new_hash]
    if boot_sig:
        for ln in boot_sig.decode("ascii", "replace").splitlines():
            if ln.startswith("ts:") or ln.startswith("rsa2048:"):
                lines.append(ln.strip())
    with open(out_sig, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {out_sig}  (SHA-256 line regenerated; RSA line carried over)")
    print("\nDONE. See docs/KEY_EXTRACTION.md for how to deploy + the secure-boot caveat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
