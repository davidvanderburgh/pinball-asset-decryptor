#!/bin/bash
# ISO -> a loop-mounted, READ-ONLY game filesystem.
#
# A JJP release ISO is a Clonezilla image: a GPT layout plus partclone images,
# one per partition, gzipped and split into 1 GB chunks.  sda3 is the whole
# Ubuntu root and carries /jjpe/gen1/<Game>.  That is the only one the emulator
# needs; sda2 (/boot) and sda4 (persistent) are restored too because they are
# small and make the tree honest.
#
# The restore is CACHED on the ISO's basename, because it is minutes of work
# and several GB.  Re-running this against the same ISO is a no-op that just
# re-mounts.
#
# Everything is mounted READ ONLY.  The game runs against an overlay built by
# jail.sh, so the restored image is never written to and a run always starts
# from a known state.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

[ "$(id -u)" = "0" ] || { echo "mount.sh: must run as root" >&2; exit 2; }

ISO=${1:-${JJP_ISO:-}}
if [ -z "$ISO" ]; then
    echo "usage: mount.sh <path-to-iso>   (or set JJP_ISO)" >&2
    exit 64
fi
# Accept a Windows path for convenience; the GUI hands us whatever the user
# picked in the file dialog.
case "$ISO" in
    [A-Za-z]:*) ISO="/mnt/$(echo "${ISO%%:*}" | tr 'A-Z' 'a-z')$(echo "${ISO#*:}" | tr '\\' '/')" ;;
esac
[ -f "$ISO" ] || { echo "mount.sh: no such ISO: $ISO" >&2; exit 3; }

for tool in partclone.restore gunzip; do
    command -v "$tool" >/dev/null || {
        echo "mount.sh: missing $tool.  apt-get install -y partclone" >&2; exit 4; }
done

BASE=$JJP_BASE
mkdir -p "$BASE"

# Already restored and mounted?  Then there is nothing to do.
if mountpoint -q "$JJP_ROOT"; then
    echo "already mounted: $JJP_ROOT"
    echo "game: $(ls -d "$JJP_ROOT"/jjpe/gen1/*/ 2>/dev/null | head -3 | tr '\n' ' ')"
    exit 0
fi

ISOMNT=$BASE/iso
mkdir -p "$ISOMNT"
mountpoint -q "$ISOMNT" || mount -o ro,loop "$ISO" "$ISOMNT" || {
    echo "mount.sh: could not loop-mount the ISO" >&2; exit 5; }

IMG=$(ls -d "$ISOMNT"/home/partimag/img 2>/dev/null | head -1)
[ -d "$IMG" ] || { echo "mount.sh: $ISO does not look like a JJP Clonezilla image" >&2; exit 6; }
echo "partitions in image: $(cat "$IMG/parts" 2>/dev/null)"

restore_one() {
    part=$1; dest=$2
    if [ -s "$dest" ]; then
        echo "  $part: already restored ($(stat -c%s "$dest") bytes)"
        return 0
    fi
    set -- "$IMG/$part".*-ptcl-img.gz.*
    [ -e "$1" ] || { echo "  $part: not in this image, skipping"; return 1; }
    echo "  $part: restoring $# chunk(s) -> $dest"
    cat "$IMG/$part".*-ptcl-img.gz.* | gunzip -c \
        | partclone.restore -N -s - -o "$dest" 2>/dev/null || {
            echo "  $part: partclone failed" >&2; rm -f "$dest"; return 1; }
}

restore_one sda3 "$BASE/sda3.raw" || { echo "mount.sh: sda3 is required" >&2; exit 7; }
restore_one sda2 "$BASE/sda2.raw" || true
restore_one sda4 "$BASE/sda4.raw" || true

mkdir -p "$JJP_ROOT" "$JJP_BOOTP" "$JJP_PERM"
mountpoint -q "$JJP_ROOT"  || mount -o ro,loop "$BASE/sda3.raw" "$JJP_ROOT"
[ -s "$BASE/sda2.raw" ] && { mountpoint -q "$JJP_BOOTP" || mount -o ro,loop "$BASE/sda2.raw" "$JJP_BOOTP" 2>/dev/null; }
[ -s "$BASE/sda4.raw" ] && { mountpoint -q "$JJP_PERM"  || mount -o ro,loop "$BASE/sda4.raw" "$JJP_PERM" 2>/dev/null; }

echo "mounted: $(mount | grep -c jjp_wonka) filesystem(s)"
GAME=$(ls -d "$JJP_ROOT"/jjpe/gen1/*/ 2>/dev/null | while read -r d; do
    [ -x "$d/game" ] && basename "$d"; done | head -1)
echo "game=${GAME:-unknown}"
