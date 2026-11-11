#!/bin/bash
# prepare.sh <card.img> - take a Chicago Gaming card image apart into the
# build cache the rig runs from, and print the build's path.
#
#   stdout:  build=<path>      last line on success
#   exit:    0 ok, 2 bad args, 3 no space, 4 not a title this rig runs,
#            5 unpack failed
#
# A CGC card (the "...Installer.img" CGC publishes, or a dump of a card) is
# an SD image whose third partition holds /emmc.img - the image the
# installer writes to the BeagleBone's eMMC - and that image's second
# partition is the game's Debian 7 (armhf).  Both are mounted READ-ONLY on
# loop devices, one inside the other, so nothing the size of either is
# ever copied: only
#
#   <build>/<emumm|pin>/   the game folder (/home/debian/<program>): the
#                          program, the Williams ROM, CGC's art and sounds
#                          (pin: Cactus Canyon's Z5 engine, ccdata/)
#   <build>/sysroot/       the machine's own libraries the program loads
#                          (glibc 2.13, SDL 1.2, libdrm...) - qemu-arm's -L
#   <build>/names.json     the ROM's switch / coil names (cgcroms.py)
#   <build>/.pad_*         title, program, $CGC_BALLS, the source image
#
# The build is named after the image and keyed by its size + mtime, so the
# same card starts at once the next time.  The image is only read.  Run as
# root (loop devices).
set -u
. "$(dirname "$0")/cgcpath.sh"
IMG=${1:-}
[ -n "$IMG" ] && [ -f "$IMG" ] || { echo "usage: prepare.sh <card.img>" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "prepare.sh: run as root (it mounts the image read-only)" >&2; exit 2; }

name=$(basename "$IMG" .img | tr -c 'A-Za-z0-9_\n-' '_')
key=$(stat -c '%s-%Y' "$IMG" | md5sum | cut -c1-8)
DEST=$CGC_CACHE/$name-$key
if [ -f "$DEST/.complete" ]; then
    touch "$DEST/.complete"
    echo "build=$DEST"
    exit 0
fi

M=$(mktemp -d /tmp/cgcprep.XXXXXX)
LOOPS=()
# Innermost first: the eMMC's loop device holds a file on the outer mount,
# so the outer one cannot unmount until that is gone.  Never rm -r here: a
# mount that would not come off is the card itself.
cleanup() {
    mountpoint -q "$M/game" && umount "$M/game"
    for ((i=${#LOOPS[@]}-1; i>=0; i--)); do
        case $(losetup -n -O BACK-FILE "${LOOPS[$i]}" 2>/dev/null) in
            */emmc.img) losetup -d "${LOOPS[$i]}" 2>/dev/null ;;
        esac
    done
    mountpoint -q "$M/outer" && umount "$M/outer"
    for ((i=${#LOOPS[@]}-1; i>=0; i--)); do losetup -d "${LOOPS[$i]}" 2>/dev/null; done
    rmdir "$M/game" "$M/outer" "$M" 2>/dev/null
}
trap cleanup EXIT
mkdir -p "$M/outer" "$M/game"

# <file> -> "<offset> <size>" of each Linux (0x83) partition in its MBR
parts() {
    python3 - "$1" <<'EOF'
import struct, sys
with open(sys.argv[1], "rb") as f:
    mbr = f.read(512)
if mbr[510:512] == b"\x55\xaa":
    for i in range(4):
        e = mbr[0x1BE + 16 * i:0x1CE + 16 * i]
        start, count = struct.unpack("<II", e[8:16])
        if e[4] == 0x83 and count:
            print(start * 512, count * 512)
EOF
}
mount_part() {      # <file> <offset> <size> <dir>
    local l
    l=$(losetup -f --show -r -o "$2" --sizelimit "$3" "$1") || return 1
    LOOPS+=("$l")
    mount -t ext4 -o ro,noload "$l" "$4" 2>/dev/null
}

# The outer partition with /emmc.img (installer / card), or the game's own
# root if this image IS the eMMC.
GAME=
while read -r off size; do
    mount_part "$IMG" "$off" "$size" "$M/outer" || continue
    if [ -f "$M/outer/emmc.img" ]; then
        while read -r o2 s2; do
            mount_part "$M/outer/emmc.img" "$o2" "$s2" "$M/game" || continue
            [ -d "$M/game/home/debian" ] && { GAME=$M/game; break; }
            umount "$M/game"
        done < <(parts "$M/outer/emmc.img")
    elif [ -d "$M/outer/home/debian" ]; then
        GAME=$M/outer
    fi
    [ -n "$GAME" ] && break
    cleanup; mkdir -p "$M/outer" "$M/game"; LOOPS=()
done < <(parts "$IMG")
[ -n "$GAME" ] || { echo "prepare.sh: $IMG holds no Chicago Gaming game (no /emmc.img, no /home/debian)" >&2; exit 4; }

PROG=
for p in emumm pin; do
    [ -f "$GAME/home/debian/$p/$p" ] && { PROG=$p; break; }
done
[ -n "$PROG" ] || { echo "prepare.sh: no emumm or pin program on the card" >&2; exit 4; }
TITLE=$(python3 "$CGC_TOOLS/cgctitles.py" detect "$GAME/home/debian/$PROG") ||
    { echo "prepare.sh: a CGC card, but not a title this rig knows" >&2; exit 4; }

need=$(( $(du -sk "$GAME/home/debian/$PROG" | cut -f1) + 64 * 1024 ))
mkdir -p "$CGC_CACHE"
free=$(df -Pk "$CGC_CACHE" | awk 'NR==2 {print $4}')
if [ "$free" -lt "$need" ]; then
    echo "prepare.sh: need about $((need / 1024)) MB free in $CGC_CACHE, have $((free / 1024)) MB" >&2
    exit 3
fi

rm -rf "$DEST.tmp"
mkdir -p "$DEST.tmp/sysroot"
echo "progress 5"
cp -a "$GAME/home/debian/$PROG" "$DEST.tmp/$PROG" ||
    { rm -rf "$DEST.tmp"; echo "prepare.sh: copying the game folder failed" >&2; exit 5; }
echo "progress 80"
# The libraries: the program's DT_NEEDED, and theirs, from the card's own
# Debian - plus libdl (build.sh links the shim against it).
python3 - "$GAME" "$DEST.tmp/$PROG/$PROG" "$DEST.tmp/sysroot" <<'EOF' ||
import os, shutil, struct, sys
root, prog, out = sys.argv[1:4]
DIRS = ["lib/arm-linux-gnueabihf", "usr/lib/arm-linux-gnueabihf", "lib", "usr/lib"]


def needed(path):
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"\x7fELF" or d[4] != 1:
        return []
    shoff, = struct.unpack_from("<I", d, 0x20)
    shentsize, shnum = struct.unpack_from("<HH", d, 0x2E)
    secs = [struct.unpack_from("<IIIIIIIIII", d, shoff + i * shentsize) for i in range(shnum)]
    out = []
    for s in secs:
        if s[1] != 6:                      # SHT_DYNAMIC
            continue
        strtab = secs[s[6]]
        for off in range(s[4], s[4] + s[5], 8):
            tag, val = struct.unpack_from("<iI", d, off)
            if tag == 0:
                break
            if tag == 1:                   # DT_NEEDED
                a = strtab[4] + val
                out.append(d[a:d.index(b"\0", a)].decode())
    return out


todo = needed(prog) + ["ld-linux-armhf.so.3", "libdl.so.2", "libpthread.so.0", "libc.so.6"]
seen = set()
while todo:
    n = todo.pop()
    if n in seen:
        continue
    seen.add(n)
    for d in DIRS:
        src = os.path.join(root, d, n)
        if os.path.exists(src):
            dst = os.path.join(out, d, n)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.realpath(src), dst)
            todo += needed(dst)
            break
    else:
        # not where Debian keeps it (AFM's libSDL_mixer): anywhere on the card
        hit = None
        for d in ("usr/local/lib", "home", "opt", "usr", "lib"):
            for dp, _dn, fn in os.walk(os.path.join(root, d)):
                if n in fn:
                    hit = os.path.join(dp, n)
                    break
            if hit:
                break
        if hit:
            dst = os.path.join(out, "usr/lib/arm-linux-gnueabihf", n)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.realpath(hit), dst)
            todo += needed(dst)
        else:
            print("prepare.sh: %s not on the card" % n, file=sys.stderr)
print("libraries: %d" % len(seen))
EOF
    { rm -rf "$DEST.tmp"; echo "prepare.sh: collecting the libraries failed" >&2; exit 5; }
# /lib/ld-linux-armhf.so.3 is where the program asks for its loader
[ -f "$DEST.tmp/sysroot/lib/ld-linux-armhf.so.3" ] ||
    cp "$DEST.tmp/sysroot/lib/arm-linux-gnueabihf/ld-linux-armhf.so.3" "$DEST.tmp/sysroot/lib/" 2>/dev/null ||
    { rm -rf "$DEST.tmp"; echo "prepare.sh: no loader on the card" >&2; exit 5; }

ROM=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import cgctitles; print(cgctitles.find_rom(sys.argv[2]) or "")' \
    "$CGC_TOOLS" "$DEST.tmp/$PROG")
[ -n "$ROM" ] && python3 "$CGC_TOOLS/cgcroms.py" "$ROM" --json > "$DEST.tmp/names.json" ||
    { rm -rf "$DEST.tmp"; echo "prepare.sh: no switch table in the ROM ($ROM)" >&2; exit 5; }
python3 "$CGC_TOOLS/cgctitles.py" balls "$TITLE" "$DEST.tmp/names.json" > "$DEST.tmp/.pad_balls"
echo "$TITLE" > "$DEST.tmp/.pad_title"
echo "$PROG" > "$DEST.tmp/.pad_program"
echo "$IMG" > "$DEST.tmp/.pad_source"
chmod -R a+rX "$DEST.tmp"
mv "$DEST.tmp" "$DEST"
touch "$DEST/.complete"
echo "progress 100"
echo "build=$DEST"
