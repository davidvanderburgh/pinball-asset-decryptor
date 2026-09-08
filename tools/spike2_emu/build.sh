#!/bin/bash
. "$(dirname "$0")/padpath.sh"
set -e
R=$ROOT
# The staging directory the sources are copied into. Created here: it
# was simply assumed to exist, which is fine on the machine where it was
# made by hand once and is a `cp: No such file or directory` on any
# other. Compiling from /mnt/c is what it avoids - drvfs is slow enough
# to matter over a few thousand lines of C.
mkdir -p "$HOME/emusrc"
# Sync EVERY source this build compiles, and COMPILE THE SAME LIST. alsastub.c
# used to be missing from the copy list while still being on the compile line,
# so an edit to the Windows copy was silently never built - and the build still
# said "built ok". It only surfaced as `undefined symbol` at guest start, one
# full run later. Both halves now come from PAD_SHIM_SRCS (padpath.sh), so the
# two cannot disagree again, and watch.sh's staleness check reads the same list.
CC_SRCS=()
for f in $PAD_SHIM_SRCS; do
    cp "$RIG/$f" "$HOME/emusrc/$f"
    case $f in *.c) CC_SRCS+=("$HOME/emusrc/$f") ;; esac
done
# THE SAME VERDICT ON EVERY COMPILER, and that flag is the whole of it.
#
# An implicit declaration is a WARNING up to GCC 13 and an ERROR from GCC 14 on
# (Ubuntu 24.10+, Debian trixie, Fedora 40+). hwshim.c had three, and they cost
# a user a shim that would not build on a distro newer than the one this rig is
# developed on - while the same sources compiled here without complaint. That is
# the worst shape a build fault can have: it cannot happen on the machine that
# could fix it. Asking GCC 13 for GCC 14's answer means the next one fails HERE.
# -std=gnu17 for the OTHER half of that thought: the flag above makes a newer
# compiler's stricter verdict happen here too, and this makes sure there is no
# newer LANGUAGE to be strict about.  gcc 11 (22.04) and 13 (24.04) both default
# to gnu17, so this changes nothing on either; gcc 15 defaults to gnu23, where
# `bool`, `true` and `false` are keywords and a redefinition is an error - the
# change that already broke criu here (getcriu.sh) and would otherwise reach
# these sources on the next LTS with no warning at all.  The dialect a build
# uses should be a decision, not whatever the distro shipped this year.
arm-linux-gnueabihf-gcc -std=gnu17 -fno-stack-protector -shared -fPIC -O2 -nostdlib \
  -Werror=implicit-function-declaration \
  -Wl,-soname,hwshim.so -o "$R/lib/hwshim.so" \
  "${CC_SRCS[@]}" \
  -L"$R/lib" -l:libdl.so.2 -l:libc.so.6
# WHAT WAS COMPILED, recorded beside what came out of it. This is the whole
# input to watch.sh's decision to rebuild; see pad_shim_hash() for why it is a
# digest of the bytes and not a comparison of file times. Written only after a
# successful compile (set -e), so a failed build never claims to be current.
pad_shim_hash "$RIG" > "$PAD_SHIM_STAMP"
echo "built ok: $(ls -l "$R/lib/hwshim.so" | awk '{print $5}') bytes"
