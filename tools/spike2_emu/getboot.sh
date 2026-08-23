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
# The boot partition is FAT12 (despite the 0x0c partition type). mtools is not
# installed, so the directory is walked in Python.
#
# THE LBA IS READ OFF THE PARTITION TABLE, not assumed. It was 8192 on the one
# card this was written against, which says nothing about the next one; the MBR
# has said so all along and asking it costs one dd of the first sector.
set -eu
. "$(dirname "$0")/padpath.sh"

IMG=${1:-${PAD_CARD:-}}
R=${2:-$ROOT}
LBA=${3:-}
TMP=$(mktemp -d "${TMPDIR:-/var/tmp}/getboot.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

[ -n "$IMG" ] || { echo "usage: getboot.sh <card.raw> [rootfs] [lba]" >&2; exit 1; }
[ -f "$IMG" ] || { echo "no card image at $IMG" >&2; exit 1; }

# ONCE PER CARD, NOT ONCE PER ROOTFS (item 62). This used to run only from
# rootfs.sh, so /mnt/boot/zImage was the rootfs-build card's forever and every
# OTHER title hash-mismatched it - the provider raises #3 for state 2 (bad
# hash) and 3 (missing file) alike, so a wrong kernel reads exactly like a
# missing one. Now that cardmount.sh calls this on every card mount, a stamp
# makes the repeat calls free.
#
# The stamp is SIZE+MTIME, deliberately not the path: item 34 is the tale of a
# path-keyed stamp re-copying 7.3 GB whenever David launched the same card
# from a different folder. The same trade too: two different cards with
# coincidentally identical size AND mtime would wrongly share a staging -
# vanishingly unlikely for card images, and a re-exported card gets a new
# mtime and restages.
STAMP="$R/mnt/boot/.pad_card_stamp"
want=$(stat -c '%s %Y' "$IMG")
if [ -f "$STAMP" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$want" ]; then
    echo "[getboot] /mnt/boot already staged from this card - nothing to do"
    exit 0
fi

if [ -z "$LBA" ]; then
    read -r LBA COUNT <<EOF
$(python3 "$RIG/parts.py" --fat "$IMG")
EOF
    [ -n "${LBA:-}" ] || { echo "[getboot] no FAT partition in $IMG" >&2; exit 1; }
else
    COUNT=16384
fi

mkdir -p "$R/mnt/boot"
echo "[getboot] reading the boot partition (LBA $LBA, $((COUNT / 2048)) MB) out of $(basename "$IMG")"
dd if="$IMG" of="$TMP/p1.img" bs=512 skip="$LBA" count="$COUNT" status=none

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

# The stamp is written AFTER the copy, so a failed stage retries next mount
# rather than being remembered as done. set -eu means reaching here is success.
#
# AN UNWRITABLE STAMP IS NOT A FAILED STAGE, and conflating the two cost a whole
# turtles run on 2026-08-23. `$R/mnt/boot` was created root-owned by an old
# rootfs build while the files inside it are the user's, so a plain run can
# OVERWRITE zImage but cannot CREATE a new file beside it. The copy above had
# already succeeded; only this memo failed, and with `set -e` the failed
# redirect aborted the script, which made cardmount.sh announce "getboot failed
# - the game will raise VALIDATION ERROR #3" about a boot partition that was
# correctly staged. The cost of a missing stamp is one repeated copy per mount,
# which is a few seconds; the cost of a false failure is chasing a fault that
# is not there.
if ! echo "$want" > "$STAMP" 2>/dev/null; then
    echo "[getboot] staged OK, but the stamp at $STAMP is not writable" >&2
    echo "[getboot] (is $R/mnt/boot root-owned?) - staging will simply repeat" >&2
    echo "[getboot] next mount. This is NOT a validation problem." >&2
fi

# A PAD_PIVOT (root) run must not leave root-owned files where the next plain
# user run cannot overwrite them - the same handback watch.sh does for logs.
# --reference, so this needs to know nothing about which user owns the rootfs.
[ "$(id -u)" = 0 ] && chown --reference="$R/mnt" "$R/mnt/boot" "$R/mnt/boot"/* 2>/dev/null

echo "[getboot] /mnt/boot now:"
ls -l "$R/mnt/boot"
