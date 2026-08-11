#!/bin/bash
# Jump the game back to a saved slot. (item 13)
#
#   wsl -u root -e bash loadgame.sh [slot]
#
# Needs root. Kills the currently running game (if any) and restores the one
# saved in the slot, which resumes at the exact ball, score and mode it was
# saved at. Default slot is "quicksave".

set -u
RIG=$(cd "$(dirname "$0")" && pwd)
SLOT=${1:-quicksave}
# A SUBSHELL, because padpath.sh sets ROOT and this script's ROOT comes from
# the RUNNING GUEST's own environment first (see below) - sourcing it here
# would quietly overrule that. All that is wanted is the one definition of
# where criu is.
CRIU=${CRIU:-$(. "$RIG/padpath.sh"; pad_criu)}

# Filenames, never paths - same rule as savegame.sh, same GUI feeding it.
# ★ ITEM 39: slots are per game (saves/<game>/<slot>), and the argument may
# name the game explicitly ("godzilla_pro/slot1") or stay bare ("slot1"),
# in which case the game is the RUNNING guest's - which is what every
# existing caller means by it.
ok_name() {
    case "$1" in ""|*[!A-Za-z0-9_.-]*|.|..) return 1 ;; esac
    return 0
}
SGAME=""
case "$SLOT" in
*/*)
    SGAME=${SLOT%%/*}; SLOT=${SLOT#*/}
    case "$SLOT" in */*) echo "loadgame: bad slot name"; exit 2 ;; esac
    ok_name "$SGAME" && ok_name "$SLOT" \
        || { echo "loadgame: bad slot name '$SGAME/$SLOT'"; exit 2; }
    ;;
*)
    ok_name "$SLOT" || { echo "loadgame: bad slot name '$SLOT'"; exit 2; }
    ;;
esac

[ "$(id -u)" = 0 ] || { echo "loadgame: needs root. Use: wsl -u root -e bash $0 [slot]"; exit 2; }

# Find the slot. It lives under the running guest's rootfs if one is up, else
# read the rootfs from the slot meta of any guest - but the simplest robust
# path is the slot's own recorded rootfs, so try the common locations.
PID=$(pgrep -x game | head -1)
ROOT=""
GGAME=""
if [ -n "$PID" ]; then
    ROOT=$(tr '\0' '\n' < "/proc/$PID/environ" 2>/dev/null | sed -n 's/^PAD_ROOT=//p' | head -1)
    GGAME=$(tr '\0' '\n' < "/proc/$PID/environ" 2>/dev/null | sed -n 's/^PAD_GAME=//p' | head -1)
fi
# If no guest is up, fall back to the rootfs padpath would pick, then to the
# slot meta once found.
[ -n "$ROOT" ] || { . "$RIG/padpath.sh"; ROOT=$PAD_ROOT; }
[ -n "$SGAME" ] || SGAME=$GGAME

# The per-game path first; the LEGACY bare path is honoured only while its
# meta agrees about the game, so a bare name can never quietly load another
# title's save - that is the exact confusion this layout ended.
DIR=""
if [ -n "$SGAME" ] && [ -f "$ROOT/saves/$SGAME/$SLOT/slot.meta" ]; then
    DIR=$ROOT/saves/$SGAME/$SLOT
elif [ -f "$ROOT/saves/$SLOT/slot.meta" ]; then
    MGAME=$(sed -n 's/^game=//p' "$ROOT/saves/$SLOT/slot.meta" | head -1)
    if [ -z "$SGAME" ] || [ "$MGAME" = "$SGAME" ]; then
        DIR=$ROOT/saves/$SLOT
    fi
fi
[ -n "$DIR" ] || { echo "loadgame: no save in slot '$SLOT'${SGAME:+ for $SGAME} (looked under $ROOT/saves)"; exit 1; }
# The slot's own recorded rootfs wins - it is where the guest really lived.
SROOT=$(sed -n 's/^root=//p' "$DIR/slot.meta")
[ -n "$SROOT" ] && ROOT=$SROOT

echo "[loadgame] slot '$SLOT'  ->  restoring the game"

# TELL A LIVE watch.sh SESSION THAT THE GUEST IS ABOUT TO VANISH ON PURPOSE.
# Restoring means killing the running guest and putting another in its place;
# watch.sh's poll loop would otherwise read that gap as "the game exited" and
# tear down the whole session - window, playfield and audio included, which is
# what you are playing in. The flag makes it wait instead. Always cleared, even
# if the restore fails, so a failed load cannot wedge the session.
RELOAD_FLAG=$ROOT/dump/reloading
: > "$RELOAD_FLAG" 2>/dev/null
STAGE=""
trap 'rm -f "$RELOAD_FLAG" 2>/dev/null; [ -n "$STAGE" ] && rm -rf "$STAGE"' EXIT

# --- unpack a packed slot into a staging dir ------------------------------
# savegame.sh packs slots (tar|zstd, ~5% of raw size); the restore machinery
# wants a plain directory of criu images, restore.env and ring stashes, so a
# packed slot is unpacked HERE, into /var/tmp - NOT /tmp, which is tmpfs and
# vanishes on a WSL restart (the staging trap this rig already paid for) -
# and the stage is removed again on every exit path via the trap above. An
# unpacked (old) slot passes straight through: DDIR stays the slot itself.
DDIR=$DIR
if [ -f "$DIR/slot.tar.zst" ]; then
    command -v zstd >/dev/null 2>&1 \
        || { echo "loadgame: slot '$SLOT' is packed but WSL has no zstd"; exit 1; }
    STAGE=$(mktemp -d /var/tmp/padslot.XXXXXX) \
        || { echo "loadgame: cannot make a staging dir"; exit 1; }
    if ! zstd -d -q -c "$DIR/slot.tar.zst" | tar -C "$STAGE" -xf -; then
        echo "loadgame: unpacking slot '$SLOT' failed (disk full? corrupt pack?)"
        exit 1
    fi
    cp -f "$DIR/slot.meta" "$STAGE/slot.meta" 2>/dev/null
    DDIR=$STAGE
fi

# The guest log grew while you kept playing after the save; restorestate.sh
# truncates it back to the size criu recorded and retries - see there.

# PAD_RESTORE_KILL clears the currently-running game (pid collision otherwise);
# PAD_ROOT points restorestate at the right rootfs; PAD_GAME names the title
# for the video host's resume restart (restorestate falls back to the restored
# guest's environ if the slot predates this field).
SGAME=$(sed -n 's/^game=//p' "$DIR/slot.meta")
PAD_ROOT="$ROOT" PAD_GAME="$SGAME" PAD_RESTORE_KILL=1 CRIU="$CRIU" \
    bash "$RIG/restorestate.sh" "$DDIR" \
    || { echo "[loadgame] FAILED"; exit 1; }
rm -f "$RELOAD_FLAG" 2>/dev/null
echo "[loadgame] restored slot '$SLOT'."
