# build_probe.sh [OUT.so] - the runtime with mode files AND place_probe_mode.c (a rig instrument, never a card's mode),
# for PROOF=game runs of place / done (PAD-1286). As root in WSL; needs the Spike 3 cross compiler (xgcc.sh).
HERE=$(cd "$(dirname "$0")" && pwd)
SDK=$HERE/../../spike2_emu/modes/sdk
OUT=${1:-/var/tmp/pad-s3proof/probe64.so}; mkdir -p "$(dirname "$OUT")"
cd "$SDK" && CC=$(bash ../../../spike3_emu/xgcc.sh) bash build_mode.sh -a a64 -o "$OUT" mode_file.c "$HERE/place_probe_mode.c"
