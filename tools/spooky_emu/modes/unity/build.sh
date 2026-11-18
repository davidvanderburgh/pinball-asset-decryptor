#!/bin/bash
# build.sh <game Managed dir> [out dir] - build padunity.so and PadModes.dll
# (PAD-1387 proof of concept).  Run in a distro with gcc and mcs (Ubuntu
# here: mono-mcs; PAD-Runtime has gcc only).  PadModes.dll is compiled
# against the title's own Managed/ assemblies - it subclasses its Mode.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MAN=${1:?usage: build.sh <..._Data/Managed> [out]}
OUT=${2:-$HERE/out}
mkdir -p "$OUT"
gcc -shared -fPIC -O2 -Wall -o "$OUT/padunity.so" "$HERE/padunity.c" -ldl -lpthread
refs=
for d in "$MAN"/*.dll; do
    case $(basename "$d") in mscorlib.dll) continue ;; esac
    refs="$refs -r:$d"
done
mcs -nologo -target:library -nostdlib -noconfig -r:"$MAN/mscorlib.dll" $refs \
    -out:"$OUT/PadModes.dll" "$HERE/PadModes.cs" 2>&1 | grep -v 'warning CS' || true
ls -l "$OUT/padunity.so" "$OUT/PadModes.dll"
