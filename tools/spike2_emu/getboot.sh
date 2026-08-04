#!/bin/bash
# getboot.sh - populate the guest's /mnt/boot from the card's OWN boot partition.
#
# WHY THIS EXISTS
# ---------------
# GAME VALIDATION ERROR #3 is raised by alert provider 0x24a018 when the ZK
# track's state byte [0x7b7c30]+44 is 2 or 3. The ZK track validates the KERNEL:
#
#     0x24a810   system("/bin/mount /dev/mmcblk0p1 /mnt/boot")
#     0x24a814   decrypt "/mnt/boot/zImage" into ctx+0
#     0x24a8f8   fopen(ctx, "rb")
#     0x24a914   if (!f) -> 0x24b6e0, which writes ZK = 3 (E)   <-- the error
#
# The mount can never work inside the chroot, so /mnt/boot stays empty and the
# fopen returns NULL. Copying the card's real zImage to that exact path is not
# faking the check - it is giving the guest the same bytes the machine has, and
# the game then hashes it for real and grades it itself.
#
# The boot partition is p1: FAT12 (despite the 0x0c partition type), 8 MB at
# LBA 8192. mtools is not installed, so the directory is walked in Python.
set -eu

IMG=${1:-/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/images/Stern/spike2/godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw}
R=${2:-/home/david/spike2root}
TMP=/home/david/bootp1

[ -f "$IMG" ] || { echo "no card image at $IMG" >&2; exit 1; }

mkdir -p "$TMP" "$R/mnt/boot"
echo "[getboot] reading p1 (LBA 8192, 8 MB) out of $(basename "$IMG")"
dd if="$IMG" of="$TMP/p1.img" bs=512 skip=8192 count=16384 status=none

python3 - "$TMP/p1.img" "$R/mnt/boot" <<'PY'
import hashlib
import os
import sys

img, dest = sys.argv[1], sys.argv[2]
d = open(img, 'rb').read()

bps = int.from_bytes(d[11:13], 'little')
spc = d[13]
rsvd = int.from_bytes(d[14:16], 'little')
nfat = d[16]
rootent = int.from_bytes(d[17:19], 'little')
fatsz = int.from_bytes(d[22:24], 'little')
if d[0x36:0x3b] != b'FAT12':
    raise SystemExit('not FAT12: %r' % d[0x36:0x3e])

fat_off = rsvd * bps
root_off = (rsvd + nfat * fatsz) * bps
data_off = root_off + rootent * 32


def fat12(n):
    o = fat_off + (n * 3) // 2
    v = d[o] | (d[o + 1] << 8)
    return (v >> 4) if (n & 1) else (v & 0xfff)


# Long file names come from the 0x0F entries preceding each 8.3 entry; the game
# opens "/mnt/boot/zImage", so the mixed-case long name is the one that matters,
# not the ZIMAGE short name a naive walk would produce on a case-sensitive fs.
lfn = {}
pend = []
for i in range(rootent):
    e = d[root_off + i * 32: root_off + i * 32 + 32]
    if e[0] == 0:
        break
    if e[0] == 0xE5:
        continue
    if e[11] == 0x0F:
        pend.append((e[0] & 0x3f,
                     (e[1:11] + e[14:26] + e[28:32]).decode('utf-16-le', 'replace')))
        continue
    if e[11] & 0x08:                       # volume label
        pend = []
        continue
    name = ''.join(t for _, t in sorted(pend)).split('\x00')[0] if pend else None
    pend = []
    short = e[0:8].decode('ascii', 'replace').strip() + \
        ('.' + e[8:11].decode('ascii', 'replace').strip()
         if e[8:11].strip() else '')
    name = name or short
    clus = int.from_bytes(e[26:28], 'little')
    size = int.from_bytes(e[28:32], 'little')
    if not size:
        continue
    out = bytearray()
    c = clus
    while 2 <= c < 0xFF8 and len(out) < size:
        o = data_off + (c - 2) * spc * bps
        out += d[o:o + spc * bps]
        c = fat12(c)
    out = bytes(out[:size])
    if len(out) != size:
        raise SystemExit('%s: short read %d of %d' % (name, len(out), size))
    p = os.path.join(dest, name)
    open(p, 'wb').write(out)
    print('[getboot] %-20s %9d bytes  md5=%s' % (name, size, hashlib.md5(out).hexdigest()))
PY

echo "[getboot] /mnt/boot now:"
ls -l "$R/mnt/boot"
