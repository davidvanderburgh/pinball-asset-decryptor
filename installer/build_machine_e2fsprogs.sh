#!/usr/bin/env bash
# Build the two e2fsprogs tools a card grown over the network uses on a Stern Spike 2 machine:
#     bash installer/build_machine_e2fsprogs.sh [<out dir>]
# leaves resize2fs and e2fsck (static, 32-bit ARM hard float) plus e2fsprogs' NOTICE and SOURCE in <out dir>
# (default pinball_decryptor/resources/remote/padgrow, where PAD ships them).
#
# Simon (2026-11-26): "all tests should be done via network updates" - a card in the machine grows without losing
# its games, so the games partition is enlarged where it is (core/testcard_grow.py).  The machine's own system has
# e2fsck 1.42.9 (2013) and no resize2fs at all, so PAD carries both: they go onto the machine for the one start-up that
# grows the card, and are removed with the rest of the grow's files.
#
# Built from the release tarball (as build_mac_e2fsprogs.sh, same version), with Ubuntu's arm-linux-gnueabihf
# cross compiler (apt install gcc-arm-linux-gnueabihf), linked statically: the machine's C library is glibc 2.21 and
# its kernel 3.14, and a static binary needs neither to match.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$HERE/pinball_decryptor/resources/remote/padgrow}"
VER=1.47.3
# From kernel.org's signed sha256sums.asc for v1.47.3.
SHA256=7d4612f4e4f7ca6c2f669679028bcb02763e3b6280c9c19b2cf168eaf65e88af
SRC="pub/linux/kernel/people/tytso/e2fsprogs/v$VER/e2fsprogs-$VER.tar.gz"
MIRRORS="https://mirrors.edge.kernel.org https://cdn.kernel.org https://www.kernel.org"
HOST=arm-linux-gnueabihf

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
URL=""
for m in $MIRRORS; do
    if curl -fsSL --retry 3 --retry-all-errors --retry-delay 5 -o "$WORK/src.tar.gz" "$m/$SRC"; then
        URL="$m/$SRC"
        break
    fi
    echo "download from $m failed, trying the next mirror" >&2
done
[ -n "$URL" ] || { echo "ERROR: e2fsprogs $VER download failed" >&2; exit 1; }
echo "$SHA256  $WORK/src.tar.gz" | sha256sum -c -
tar -xzf "$WORK/src.tar.gz" -C "$WORK"
cd "$WORK/e2fsprogs-$VER"

# -std=gnu11: gcc 15 defaults to C23, where lib/ext2fs/tdb.c's "typedef int bool" is an error
./configure --host=$HOST --disable-nls --disable-fuse2fs --disable-elf-shlibs --disable-uuidd --disable-fsck \
    --disable-e2initrd-helper --without-libarchive CFLAGS="-O2 -std=gnu11" LDFLAGS=-static >/dev/null
make -j"$(nproc)" libs >/dev/null
make -j"$(nproc)" -C resize resize2fs >/dev/null
make -j"$(nproc)" -C e2fsck e2fsck >/dev/null

mkdir -p "$OUT"
$HOST-strip -o "$OUT/resize2fs" resize/resize2fs
$HOST-strip -o "$OUT/e2fsck" e2fsck/e2fsck
chmod 755 "$OUT/resize2fs" "$OUT/e2fsck"
cp NOTICE "$OUT/NOTICE"
echo "e2fsprogs $VER, built from $URL for $HOST (static)" > "$OUT/SOURCE"

# Prove what was built: 32-bit ARM, static.
for b in "$OUT/resize2fs" "$OUT/e2fsck"; do
    file "$b" | grep -q "ARM, EABI5.*statically linked" || { echo "ERROR: $b is not a static ARM program" >&2; exit 1; }
done
(cd "$OUT" && sha256sum resize2fs e2fsck)
