#!/bin/bash
# xgcc.sh - an aarch64 cross gcc for the Spike 3 shims, with no package installed.
#
#   bash xgcc.sh            # make sure it is there; prints the s3cc wrapper's path
#   $(bash xgcc.sh) -shared -fPIC -o x.so x.c
#
# The Spike 2 rig builds its ARM shims with the system's arm-linux-gnueabihf-gcc.
# Spike 3's game is aarch64 and gcc-aarch64-linux-gnu is not on the rig, so this
# does what the README does for fuse2fs: `apt-get download` the cross compiler's
# packages and `dpkg-deb -x` them into a private prefix under $HOME (no root, no
# dpkg database touched). binutils-aarch64-linux-gnu is already a dependency of
# the rig (qemu tooling) and supplies `as`/`ld`.
#
# The wrapper passes --sysroot (the cross libc's linker script names absolute
# /usr/aarch64-linux-gnu paths) and the -B paths gcc needs to find cc1, crt*.o
# and the assembler in a prefix it was not built for.
#
# GLIBC: the cross libc is Ubuntu 24.04's 2.39, and the cards' Buildroot rootfs
# is also glibc 2.39 (pokemon_le 0.82.0, measured), so a shim built here asks
# for no symbol version the card lacks. A card on a newer OS build could differ:
# `readelf -V` the .so against the card's libc if one ever refuses to load.
set -eu
P=${PAD_S3_XGCC:-${PAD_S3_HOME:-/var/lib/pad-s3}/xgcc}
CC=$P/root/usr/bin/aarch64-linux-gnu-gcc-13
W=$P/s3cc
if [ ! -x "$CC" ] || [ ! -x "$W" ]; then
    command -v aarch64-linux-gnu-as >/dev/null || {
        echo "xgcc.sh: binutils-aarch64-linux-gnu is missing (apt install binutils-aarch64-linux-gnu)" >&2; exit 1; }
    mkdir -p "$P/debs"
    ( cd "$P/debs" && apt-get download \
        gcc-13-aarch64-linux-gnu cpp-13-aarch64-linux-gnu gcc-13-aarch64-linux-gnu-base \
        libgcc-13-dev-arm64-cross libc6-dev-arm64-cross libc6-arm64-cross \
        linux-libc-dev-arm64-cross libgcc-s1-arm64-cross libatomic1-arm64-cross \
        libasan8-arm64-cross libhwasan0-arm64-cross liblsan0-arm64-cross \
        libtsan2-arm64-cross libubsan1-arm64-cross libitm1-arm64-cross \
        libgomp1-arm64-cross >&2 )
    for d in "$P"/debs/*.deb; do dpkg-deb -x "$d" "$P/root"; done
    G=$P/root/usr/lib/gcc-cross/aarch64-linux-gnu/13
    cat > "$W" <<EOF
#!/bin/sh
exec "$CC" -B/usr/aarch64-linux-gnu/bin/ -B$G/ -B$P/root/usr/aarch64-linux-gnu/lib/ \\
    --sysroot=$P/root -isystem $G/include -isystem $P/root/usr/aarch64-linux-gnu/include \\
    -L$P/root/usr/aarch64-linux-gnu/lib "\$@"
EOF
    chmod +x "$W"
fi
echo "$W"
