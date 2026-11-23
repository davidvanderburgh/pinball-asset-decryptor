#!/bin/bash
# PAD-1515: "Show it in the game" - the game's own screens, each part it draws named, for the layout
# editor. Boots the title's stock ISO on the rig HIDDEN and MUTED with the custom-modes runtime and a
# mode folder, takes a census (jjpmodes.c gs_frame) in attract and with a ball in play, and leaves
# <screen>.png + <screen>.json in the out folder (the mode folder's .layout/). As root:
#   bash jjpscreens.sh --iso <stock.iso> --so <jjpmodes.so> --modes <mode folder> --out <folder>
#                      [--menu] [--start "<switch> <hits>"]
# --menu: the attract game type menu opened too (both flipper buttons held), --start: a mode started by
# hitting a switch; each grabbed as the screen shows it, ours drawn (in_game_menu.png, in_game_mode.png):
# the true look beside the editor's preview.
# rc 0 = every screen taken; 3 the game did not come up (no key, no mount); 4 a screen was not taken.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ISO= SO= MODES= OUT= MENU= START=
while [ $# -gt 0 ]; do
    case "$1" in
        --iso) ISO=$2; shift 2 ;;
        --so) SO=$2; shift 2 ;;
        --modes) MODES=$2; shift 2 ;;
        --out) OUT=$2; shift 2 ;;
        --menu) MENU=1; shift ;;
        --start) START=$2; shift 2 ;;
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
EOF
if [ -n "$MENU" ]; then cat >> "$STAGE/steps.txt" <<EOF
note the game type menu: both flipper buttons held a second
hold dswitch_l_flipper_lo,dswitch_l_flipper_hi,dswitch_r_flipper_lo,dswitch_r_flipper_hi 1.6
wait game type menu OPEN 5
hold dswitch_r_flipper_lo,dswitch_r_flipper_hi 0.3
sleep 1
shot $STAGE/in_game_menu.png
hold dswitch_l_flipper_lo,dswitch_l_flipper_hi 0.3
sleep 9
EOF
fi
cat >> "$STAGE/steps.txt" <<EOF
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
if [ -n "$START" ]; then
    set -- $START
    echo "note the mode, started by $2 hit(s) of $1" >> "$STAGE/steps.txt"
    for _ in $(seq 1 "${2:-1}"); do printf 'press %s\nsleep 0.6\n' "$1" >> "$STAGE/steps.txt"; done
    printf 'sleep 2\nshot %s/in_game_mode.png\n' "$STAGE" >> "$STAGE/steps.txt"
fi
python3 "$HERE/jjpdrive.py" "$STAGE/steps.txt"
rc=$?
n=0
for s in attract game; do
    if [ -f "$STAGE/$s.json" ]; then cp -f "$STAGE/$s.json" "$STAGE/$s.png" "$OUT/" 2>/dev/null && n=$((n + 1)); echo "screen $s: taken"; fi
done
for s in in_game_menu in_game_mode; do
    [ -f "$STAGE/$s.png" ] && cp -f "$STAGE/$s.png" "$OUT/" && echo "screen $s: taken"
done
[ "$n" -eq 2 ] || { echo "refused: $n of 2 screens taken (the game stopped early?)"; exit 4; }
exit $rc
