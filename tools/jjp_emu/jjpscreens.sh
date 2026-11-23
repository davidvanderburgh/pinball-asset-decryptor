#!/bin/bash
# PAD-1515: "Show it in the game" - the game's own screens, each part it draws named, for the layout
# editor. Boots the title's stock ISO on the rig HIDDEN and MUTED with the custom-modes runtime and a
# mode folder, takes a census (jjpmodes.c gs_frame) in attract and with a ball in play, and leaves
# <screen>.png + <screen>.json in the out folder (the mode folder's .layout/). As root:
#   bash jjpscreens.sh --iso <stock.iso> --so <jjpmodes.so> --modes <mode folder> --out <folder>
# rc 0 = every screen taken; 3 the game did not come up (no key, no mount); 4 a screen was not taken.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ISO= SO= MODES= OUT=
while [ $# -gt 0 ]; do
    case "$1" in
        --iso) ISO=$2; shift 2 ;;
        --so) SO=$2; shift 2 ;;
        --modes) MODES=$2; shift 2 ;;
        --out) OUT=$2; shift 2 ;;
        *) echo "jjpscreens.sh: unknown argument $1" >&2; exit 2 ;;
    esac
done
[ -f "$ISO" ] && [ -f "$SO" ] && [ -d "$MODES" ] && [ -n "$OUT" ] || { echo "refused: jjpscreens.sh needs --iso --so --modes --out" >&2; exit 2; }
mkdir -p "$OUT" || exit 2
STAGE=$(mktemp -d /var/tmp/pad_jjpscreens.XXXXXX)
trap 'bash "$HERE/killgame.sh" >/dev/null 2>&1; rm -rf "$STAGE"' EXIT
export PAD_HIDDEN=1 PAD_AUDIO=0 PAD_LABEL=${PAD_LABEL:-PAD-screens} JJP_ISO=$ISO JJP_MODS_SO=$SO JJP_MODS_DIR=$MODES
echo "== the game, hidden and muted"
bash "$HERE/watch.sh" || { echo "refused: the game did not come up (is the purple JJP key attached?)"; exit 3; }
export JJP_DISPLAY=${JJP_NESTED:-:1}
cat > "$STAGE/steps.txt" <<EOF
note waiting for the game's attract
wait installed: 240
wait game state 2 -> 4 240
sleep 20
census attract $STAGE
note coins and Start: a game, a ball in play
press dswitch_coin_1
press dswitch_coin_1
sleep 1
press dswitch_start
wait game state \\d+ -> 5 90
sleep 3
plunge
sleep 6
census game $STAGE
EOF
python3 "$HERE/jjpdrive.py" "$STAGE/steps.txt"
rc=$?
n=0
for s in attract game; do
    if [ -f "$STAGE/$s.json" ]; then cp -f "$STAGE/$s.json" "$STAGE/$s.png" "$OUT/" 2>/dev/null && n=$((n + 1)); echo "screen $s: taken"; fi
done
[ "$n" -eq 2 ] || { echo "refused: $n of 2 screens taken (the game stopped early?)"; exit 4; }
exit $rc
