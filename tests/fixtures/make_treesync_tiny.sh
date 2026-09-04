#!/bin/bash
# Makes tests/fixtures/treesync_tiny.ext4.gz - the 4 MiB ext4 image tests/test_ext4_reader.py
# reads (fast + slow symlinks, a uid-1000 file, a hole, an uninitialised extent, a
# multi-extent file, two files with the same bytes and different modes, a latin-1 name).
# Needs root under WSL/Linux (a loop mount, fallocate).  Every file's bytes come from
# tests/fixtures/treesync_tiny.py's generator, so the tests recompute what they expect.
#
#   wsl.exe -u root -e bash tests/fixtures/make_treesync_tiny.sh
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/treesync_tiny.ext4.gz
IMG=$(mktemp /tmp/treesync_tiny.XXXXXX.img)
MP=$(mktemp -d /tmp/treesync_tiny.XXXXXX)
cleanup() { umount "$MP" 2>/dev/null || true; [ -n "${LOOP:-}" ] && losetup -d "$LOOP" 2>/dev/null || true; rmdir "$MP" 2>/dev/null || true; rm -f "$IMG"; }
trap cleanup EXIT
truncate -s 4M "$IMG"
# the stock games partition's feature set, 256-byte inodes, 4 KiB blocks
mke2fs -q -F -t ext4 -b 4096 -I 256 -O ^metadata_csum,^metadata_csum_seed,^64bit,^orphan_file,^has_journal "$IMG"
LOOP=$(losetup --find --show "$IMG")
mount -t ext4 "$LOOP" "$MP"
python3 "$HERE/treesync_tiny.py" populate "$MP"
sync
umount "$MP"
losetup -d "$LOOP"; LOOP=
e2fsck -fn "$IMG" >/dev/null
gzip -9 -n -c "$IMG" > "$OUT"
echo "wrote $OUT ($(stat -c %s "$OUT") bytes)"
