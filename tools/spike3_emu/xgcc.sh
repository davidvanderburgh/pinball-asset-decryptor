#!/bin/bash
# xgcc.sh - the aarch64 cross gcc for Spike 3: the rig's shims and a project's code modes.
#
#   bash xgcc.sh            # make sure it is there; prints the s3cc wrapper's path
#   $(bash xgcc.sh) -shared -fPIC -o x.so x.c
#
# The Spike 2 side builds with the PAD Runtime's arm-linux-gnueabihf-gcc. Spike 3's game is
# aarch64 and no aarch64 gcc is in the runtime image, so this unpacks one into a private
# prefix: the packages xgcc.pins names (PAD-1295), each fetched from the Ubuntu snapshot the
# runtime itself is built from and checked against its SHA-256 before `dpkg-deb -x` (no root
# needed, no dpkg database touched). It used to `apt-get download` whatever the distro's
# lists offered, which the shipped runtime cannot do at all (its image keeps no apt lists)
# and which gave each machine the compiler of its own day. Now every machine gets the same
# bytes: gcc 13.3.0 and binutils 2.42, the versions of the runtime's own toolchains, whose
# libraries are therefore already there. binutils comes in the kit too, so `as`/`ld`/`nm`
# need nothing installed.
#
# The kit is unpacked once per pins file (the stamp is the file's SHA-256); a changed pin
# unpacks the new set. PAD_XGCC_DEBS=<dir> takes the .debs from a folder instead of the
# network (each still checked). Off x86-64 (an arm64 Mac's container) the pinned host
# binaries cannot run, so a system aarch64-linux-gnu-gcc - or the host's own gcc on an
# aarch64 host - is used instead.
#
# The wrapper passes --sysroot (the cross libc's linker script names absolute
# /usr/aarch64-linux-gnu paths) and the -B paths gcc needs to find cc1, crt*.o
# and the assembler in a prefix it was not built for. s3nm beside it is the kit's nm
# (build_mode.sh's check of what an object leaves undefined).
#
# GLIBC: the cross libc is Ubuntu 24.04's 2.39, and the cards' Buildroot rootfs
# is also glibc 2.39 (pokemon_le 0.82.0, measured), so a shim built here asks
# for no symbol version the card lacks. A card on a newer OS build could differ:
# `readelf -V` the .so against the card's libc if one ever refuses to load.
set -eu
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PINS=$HERE/xgcc.pins
P=${PAD_S3_XGCC:-${PAD_S3_HOME:-/var/lib/pad-s3}/xgcc}
W=$P/s3cc
say() { echo "xgcc.sh: $*" >&2; }

# Off x86-64: the system's compiler (the pinned kit is amd64 programs).
if [ "$(uname -m)" != x86_64 ]; then
    for c in aarch64-linux-gnu-gcc aarch64-linux-gnu-gcc-13 aarch64-linux-gnu-gcc-12; do
        command -v "$c" >/dev/null && { command -v "$c"; exit 0; }
    done
    [ "$(uname -m)" = aarch64 ] && command -v gcc >/dev/null && { command -v gcc; exit 0; }
    say "no aarch64 gcc on this $(uname -m) machine (install gcc-aarch64-linux-gnu)"; exit 1
fi

# (CRs dropped: a Windows checkout or copy may have rewritten the list's line ends)
STAMP=$(tr -d $'\r' < "$PINS" | sha256sum | cut -d' ' -f1)
CC=$P/root/usr/bin/aarch64-linux-gnu-gcc-13

unpack() {
    local base= sum size path f got n=0 new=$P/root.new
    mkdir -p "$P/debs"
    rm -rf "$new"
    mkdir -p "$new"
    while read -r sum size path; do
        case $sum in ''|'#'*) continue ;; snapshot) base=$size; continue ;; esac
        f=$P/debs/${path##*/}
        if [ ! -f "$f" ] || [ "$(sha256sum "$f" | cut -d' ' -f1)" != "$sum" ]; then
            rm -f "$f"
            if [ -n "${PAD_XGCC_DEBS:-}" ] && [ -f "$PAD_XGCC_DEBS/${path##*/}" ]; then
                cp "$PAD_XGCC_DEBS/${path##*/}" "$f.part"
            elif command -v curl >/dev/null; then
                curl -fsSL --retry 5 --retry-delay 3 -o "$f.part" "$base/$path" \
                    || { say "could not download ${path##*/} from the Ubuntu snapshot archive"; return 1; }
            else
                wget -q -t 5 -O "$f.part" "$base/$path" \
                    || { say "could not download ${path##*/} from the Ubuntu snapshot archive"; return 1; }
            fi
            got=$(sha256sum "$f.part" | cut -d' ' -f1)
            [ "$got" = "$sum" ] || { rm -f "$f.part"; say "${path##*/} is not the pinned file (sha256 $got)"; return 1; }
            mv "$f.part" "$f"
        fi
        dpkg-deb -x "$f" "$new"
        n=$((n + 1))
    done < <(tr -d $'\r' < "$PINS")
    [ -x "$new/usr/bin/aarch64-linux-gnu-gcc-13" ] || { say "the kit unpacked without its gcc"; return 1; }
    rm -rf "$P/root"
    mv "$new" "$P/root"
    echo "$STAMP" > "$P/stamp"
    say "unpacked the pinned aarch64 compiler ($n packages) into $P"
}

if [ "$(cat "$P/stamp" 2>/dev/null)" != "$STAMP" ] || [ ! -x "$CC" ]; then
    mkdir -p "$P"
    # one unpack at a time (rigs and a Write can ask at once); the second finds it done
    exec 9>"$P/.lock"
    command -v flock >/dev/null && flock 9
    if [ "$(cat "$P/stamp" 2>/dev/null)" != "$STAMP" ] || [ ! -x "$CC" ]; then
        say "getting the pinned aarch64 compiler (about 41 MB, once)"
        unpack || exit 1
    fi
fi
# THE WRAPPER FINDS ITS COMPILER BESIDE ITSELF (PAD-1090): it used to name the
# prefix it was made in, and a rig home moved (/var/tmp/... -> /var/lib/pad-s3)
# left a wrapper exec-ing a gcc that was not there. Rewritten when it is not this
# version's (no "own libs" mark) or missing.
# THE KIT'S BINUTILS LOAD THE KIT'S OWN LIBRARIES (PAD-1343): as, ld and nm need
# libopcodes/libbfd/libctf-...-arm64.so, which the binutils package unpacks under
# root/usr/lib/x86_64-linux-gnu - a folder the loader never looks in.  They were found
# only where the system's own binutils-aarch64-linux-gnu was installed too, so a
# machine without it (the shipped runtime, a CI runner) failed every Spike 3 code
# mode with "libopcodes-2.42-arm64.so: cannot open shared object file".  The folder
# also holds the pinned host libraries those programs load (libsframe, libisl, libmpc,
# libmpfr, libjansson; PAD-1345), so a newer Linux without them builds too; only the
# kit's own programs run under the wrapper, so nothing else sees them.
if ! grep -qs "own libs" "$W" || ! grep -qs "own libs" "$P/s3nm"; then
    cat > "$W.tmp" <<'EOF'
#!/bin/sh
# s3cc - self-located, pinned kit: the aarch64 gcc and binutils unpacked beside this file (xgcc.sh), own libs
P=$(cd "$(dirname "$0")" && pwd)
LD_LIBRARY_PATH=$P/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; export LD_LIBRARY_PATH
G=$P/root/usr/lib/gcc-cross/aarch64-linux-gnu/13
exec "$P/root/usr/bin/aarch64-linux-gnu-gcc-13" -B"$P"/root/usr/aarch64-linux-gnu/bin/ -B"$G"/ -B"$P"/root/usr/aarch64-linux-gnu/lib/ \
    --sysroot="$P"/root -isystem "$G"/include -isystem "$P"/root/usr/aarch64-linux-gnu/include \
    -L"$P"/root/usr/aarch64-linux-gnu/lib "$@"
EOF
    cat > "$P/s3nm" <<'EOF'
#!/bin/sh
# s3nm - the pinned kit's aarch64 nm (xgcc.sh), own libs
P=$(cd "$(dirname "$0")" && pwd)
LD_LIBRARY_PATH=$P/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; export LD_LIBRARY_PATH
exec "$P/root/usr/bin/aarch64-linux-gnu-nm" "$@"
EOF
    chmod +x "$W.tmp" "$P/s3nm"
    mv "$W.tmp" "$W"
fi
echo "$W"
