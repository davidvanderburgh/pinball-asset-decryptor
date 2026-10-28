#!/usr/bin/env bash
# Build the e2fsprogs tools the macOS app ships inside itself:
#     bash installer/build_mac_e2fsprogs.sh <out dir>
# leaves debugfs, e2fsck, dumpe2fs and mke2fs plus e2fsprogs' NOTICE in
# <out dir>.
#
# Every Chicago Gaming extract and write reads and writes ext4 with them.
# A Mac has none of them, and telling the user to "brew install e2fsprogs"
# left a Mac with no Homebrew at the same pop-up with nothing they could do
# (PAD-571, PAD-573), so the app carries its own.
#
# BUILT FROM THE RELEASE TARBALL, NOT COPIED FROM HOMEBREW: a Homebrew
# bottle is built for the runner's own macOS (15) and links Homebrew's
# dylibs by absolute path, so it would not load on an older Mac or one
# without Homebrew.  e2fsprogs' default build links its own libraries
# statically, so these binaries need only libSystem, and the deployment
# target lets them run on any macOS the app itself runs on.
set -euo pipefail

OUT="${1:?usage: build_mac_e2fsprogs.sh <out dir>}"
VER=1.47.3
# From kernel.org's signed sha256sums.asc for v1.47.3.
SHA256=7d4612f4e4f7ca6c2f669679028bcb02763e3b6280c9c19b2cf168eaf65e88af
# The same tarball on kernel.org's three hosts, tried in turn: one host
# resetting the connection failed the macOS CI run (PAD-792).
SRC="pub/linux/kernel/people/tytso/e2fsprogs/v$VER/e2fsprogs-$VER.tar.gz"
MIRRORS="https://mirrors.edge.kernel.org https://cdn.kernel.org https://www.kernel.org"
TOOLS="debugfs/debugfs e2fsck/e2fsck misc/dumpe2fs misc/mke2fs"

export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# --retry alone skips a reset connection (curl exit 35); --retry-all-errors
# retries those too.
URL=""
for m in $MIRRORS; do
    if curl -fsSL --retry 3 --retry-all-errors --retry-delay 5 \
            -o "$WORK/src.tar.gz" "$m/$SRC"; then
        URL="$m/$SRC"
        break
    fi
    echo "download from $m failed, trying the next mirror" >&2
done
[ -n "$URL" ] || { echo "ERROR: e2fsprogs $VER download failed" >&2; exit 1; }
echo "$SHA256  $WORK/src.tar.gz" | shasum -a 256 -c -
tar -xzf "$WORK/src.tar.gz" -C "$WORK"
cd "$WORK/e2fsprogs-$VER"

./configure --disable-nls --disable-fuse2fs --disable-e2initrd-helper \
    >/dev/null
make -j"$(sysctl -n hw.ncpu)" >/dev/null

mkdir -p "$OUT"
for t in $TOOLS; do
    install -m 755 "$t" "$OUT/"
done
cp NOTICE "$OUT/NOTICE"
echo "e2fsprogs $VER, built from $URL" > "$OUT/SOURCE"

# Prove what was built: each tool runs and links nothing outside the OS.
for t in $TOOLS; do
    b="$OUT/$(basename "$t")"
    if otool -L "$b" | tail -n +2 | grep -v -E '^\s+(/usr/lib/|/System/)'; then
        echo "ERROR: $b links a library outside the OS" >&2
        exit 1
    fi
done
"$OUT/debugfs" -V
"$OUT/e2fsck" -V
otool -l "$OUT/debugfs" | grep -A3 LC_BUILD_VERSION | grep minos
