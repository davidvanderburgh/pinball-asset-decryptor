#!/bin/bash
# build.sh <game Managed dir> [out dir] [framework] - build padunity.so, padunity_dllmap.so and
# PadModes.dll (PAD-1387, PAD-1417, PAD-1418).  Run in a distro with gcc and mcs (Ubuntu here:
# mono-mcs; PAD-Runtime has gcc only).  PadModes.dll is compiled against the title's own Managed/
# assemblies (it subclasses its Mode): the core (PadModes.cs) and the framework's glue:
#
#   scooby   Scooby-Doo (the default)        glue_scooby.cs
#   bj       Beetlejuice                     glue_bj.cs
#   pc       Halloween, Ultraman             glue_pc.cs
#   pc-tcm   Texas Chainsaw Massacre         glue_pc.cs -d:TCM
#   ed       Evil Dead                       glue_ed.cs
#
# padunity.so is preloaded (Scooby-Doo's launch line, the rig's Try it); padunity_dllmap.so is the
# same loader for the titles whose update maps Mono's MonoPosixHelper to it (their own
# main_Data/MonoBleedingEdge/etc/mono/config): Mono looks the serial port's functions up in it, so
# it needs the game's libMonoPosixHelper.so (found beside the game by its RUNPATH).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MAN=${1:?usage: build.sh <..._Data/Managed> [out] [scooby|bj|pc|pc-tcm|ed]}
OUT=${2:-$HERE/out}
FW=${3:-scooby}
case $FW in
    scooby) GLUE=glue_scooby.cs; DEF= ;;
    bj)     GLUE=glue_bj.cs;     DEF= ;;
    pc)     GLUE=glue_pc.cs;     DEF= ;;
    pc-tcm) GLUE=glue_pc.cs;     DEF=-d:TCM ;;
    ed)     GLUE=glue_ed.cs;     DEF= ;;
    *) echo "build.sh: unknown framework $FW" >&2; exit 2 ;;
esac
mkdir -p "$OUT"
gcc -shared -fPIC -O2 -Wall -o "$OUT/padunity.so" "$HERE/padunity.c" -ldl -lpthread
# the dllmap variant: NEEDED libMonoPosixHelper.so, linked against a stub of that name
STUB=$(mktemp -d)
echo 'void pad_posix_helper_stub(void) {}' > "$STUB/stub.c"
gcc -shared -fPIC -o "$STUB/libMonoPosixHelper.so" "$STUB/stub.c"
gcc -shared -fPIC -O2 -Wall -o "$OUT/padunity_dllmap.so" "$HERE/padunity.c" -ldl -lpthread \
    -Wl,--no-as-needed -L"$STUB" -l:libMonoPosixHelper.so \
    -Wl,-rpath,'$ORIGIN/../main_Data/MonoBleedingEdge/x86_64'
rm -rf "$STUB"
refs=
for d in "$MAN"/*.dll; do
    case $(basename "$d") in mscorlib.dll) continue ;; esac
    refs="$refs -r:$d"
done
rm -f "$OUT/PadModes.dll"
mcs -nologo -target:library -nostdlib -noconfig $DEF -r:"$MAN/mscorlib.dll" $refs \
    -out:"$OUT/PadModes.dll" "$HERE/PadModes.cs" "$HERE/$GLUE" 2>&1 | grep -v 'warning CS' || true
ls -l "$OUT/padunity.so" "$OUT/padunity_dllmap.so" "$OUT/PadModes.dll"
