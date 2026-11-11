#!/bin/bash
# s3state.sh - Spike 3 save states, the way the Spike 2 rig's are used
# (PAD-1147). The playfield window's Save state / Load state run Spike 2's
# savegame.sh / loadgame.sh, which hand a Spike 3 rig slot over to this.
#
#   s3state.sh save RIGSLOT NAME [LABEL]   checkpoint the slot's game into NAME
#   s3state.sh load RIGSLOT NAME           bring NAME back into the slot's run
#   s3state.sh unpack GAME/NAME DEST       the slot, unpacked into DEST
#   s3state.sh root                        the saves directory (slots.sh)
#   s3state.sh running RIGSLOT             exit 0 when a Spike 3 game runs there
#
# Slots are Spike 2's shape, so slots.sh lists, renames and deletes them as
# they are: $SAVES/<title>/<NAME>/slot.meta (game= label= card= saved=) beside
# slot.tar.zst (s3save.sh's directory, packed). NAME is a file name.
# Root (criu); the [savegame] / [loadgame] lines are what the window's status
# bar shows, the last one that says something.
set -u
S=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SAVES=${PAD_S3_SAVES:-${PAD_S3_HOME:-/var/lib/pad-s3}/saves}

# s3_game_pid RIGSLOT: the slot's Spike 3 game - comm "game" whose root
# overlay's upper layer is the slot's (s3run.sh). Empty when none runs.
s3_game_pid() {
    local p
    for p in $(pgrep -x game 2>/dev/null); do
        grep -q " / / .*upperdir=/var/tmp/pad-s3/slot$1/root.up," "/proc/$p/mountinfo" 2>/dev/null \
            && { echo "$p"; return 0; }
    done
    return 1
}
ok_name() { case "$1" in ""|*[!A-Za-z0-9_.-]*|.|..) return 1 ;; esac; }
# the title of the card a game runs: its /games overlay's lower layer is
# <store>/<card>/games, whose `game` link names the title's directory
title_of() {
    local tree
    tree=$(awk '$5 == "/games" {print}' "/proc/$1/mountinfo" | tr ',' '\n' | sed -n 's/^lowerdir=//p' | head -1)
    basename "$(dirname "$(readlink "$tree/game" 2>/dev/null)")" 2>/dev/null
}

# unpack_slot DIR DEST: a slot's checkpoint, unpacked (or copied) into DEST
unpack_slot() {
    rm -rf "$2"; mkdir -p "$2"
    if [ -f "$1/slot.tar.zst" ]; then
        zstd -d -q -c "$1/slot.tar.zst" | tar -C "$2" -xf - || { rm -rf "$2"; return 1; }
    else
        cp -a "$1/." "$2/" || return 1
    fi
}

CMD=${1:-}
case "$CMD" in
root)    echo "$SAVES"; exit 0 ;;
unpack)
    REF=${2:?usage: s3state.sh unpack GAME/NAME DEST}; DEST=${3:?}
    { ok_name "${REF%%/*}" && ok_name "${REF#*/}" && [ "${REF#*/}" != "$REF" ]; } \
        || { echo "[loadgame] bad slot '$REF'"; exit 2; }
    [ -f "$SAVES/$REF/slot.meta" ] || { echo "[loadgame] no save state '$REF'"; exit 1; }
    unpack_slot "$SAVES/$REF" "$DEST"; exit $? ;;
running) [ -n "$(s3_game_pid "${2:?}")" ]; exit $? ;;
save|load) ;;
*) sed -n 2,14p "$0"; exit 2 ;;
esac
RIG=${2:?usage: s3state.sh $CMD RIGSLOT NAME}
NAME=${3:-quicksave}
ok_name "$NAME" || { echo "[savegame] bad slot name '$NAME' - letters, digits, _ . - only"; exit 2; }
[ "$(id -u)" = 0 ] || { echo "[savegame] needs root"; exit 2; }
PID=$(s3_game_pid "$RIG")
[ -n "$PID" ] || { echo "[$CMD""game] no Spike 3 game is running in this rig slot"; exit 1; }
GAME=$(title_of "$PID")
ok_name "$GAME" || { echo "[$CMD""game] cannot tell which title is running"; exit 1; }
DIR=$SAVES/$GAME/$NAME
SD=/var/tmp/pad-s3/slot$RIG

if [ "$CMD" = save ]; then
    LABEL=${4:-}
    STAGE=$SAVES/.stage.$NAME.$$
    rm -rf "$STAGE"; mkdir -p "$SAVES/$GAME"
    echo "[savegame] slot '$NAME'  <-  $GAME (pid $PID)"
    if ! bash "$S/s3save.sh" "$RIG" "$STAGE" | grep -v '^\[s3save\] externals' | sed 's/^\[s3save\]/[save]/'; then
        :
    fi
    if ! grep -q '^tree ' "$STAGE/restore.env" 2>/dev/null || ! [ -s "$STAGE/inventory.img" ]; then
        rm -rf "$STAGE"
        echo "[savegame] FAILED"
        exit 1
    fi
    {
        echo "game=$GAME"
        echo "card=$(awk '$1 == "tree" {print $2}' "$STAGE/restore.env")"
        echo "saved=$(date +%s)"
        [ -n "$LABEL" ] && echo "label=$(printf '%s' "$LABEL" | tr '\n\r|' '   ')"
    } > "$STAGE/slot.meta.new"
    # PACKED, as Spike 2's slots: ~1.2 GB of RAM pages and GL journal crush
    # to a small fraction (zero pages, texture pixels). The game already
    # plays on; only the disk waits for this.
    if command -v zstd >/dev/null 2>&1; then
        if tar -C "$STAGE" -cf - --exclude='./slot.meta.new' . 2>/dev/null \
                | zstd -3 -T0 -q -f -o "$STAGE.zst"; then
            find "$STAGE" -mindepth 1 ! -name slot.meta.new -delete
            mv "$STAGE.zst" "$STAGE/slot.tar.zst"
        else
            rm -f "$STAGE.zst"
            echo "[savegame] NOTE: packing failed - the slot stays raw"
        fi
    fi
    mv "$STAGE/slot.meta.new" "$STAGE/slot.meta"
    rm -rf "$DIR"; mv "$STAGE" "$DIR"
    echo "[savegame] saved to slot '$NAME' ($(du -sh "$DIR" | cut -f1)). Keep playing."
    exit 0
fi

# --- load: unpack beside the rig slot, then ask the run to swap its game ---
[ -f "$DIR/slot.meta" ] || { echo "[loadgame] slot '$NAME' is empty - nothing to load"; exit 1; }
if ! pgrep -f "s3run.sh .*--slot $RIG( |\$)" >/dev/null; then
    echo "[loadgame] this game was not started by the emulator's run; start it from the Emulate tab"
    exit 1
fi
LD=$SD.load
unpack_slot "$DIR" "$LD" || { echo "[loadgame] the slot could not be unpacked"; exit 1; }
rm -f "$SD/load.result"
echo "$LD" > "$SD/load.req.tmp" && mv "$SD/load.req.tmp" "$SD/load.req"
echo "[loadgame] loading slot '$NAME' ($GAME)"
for _ in $(seq 1 1200); do
    [ -s "$SD/load.result" ] && break
    sleep 0.1
done
R=$(cat "$SD/load.result" 2>/dev/null)
case "$R" in
ok)   echo "[loadgame] loaded slot '$NAME'"; exit 0 ;;
"")   rm -f "$SD/load.req"; echo "[loadgame] the run did not answer the load"; exit 1 ;;
*)    echo "[loadgame] could not load: ${R#fail }"; exit 1 ;;
esac
