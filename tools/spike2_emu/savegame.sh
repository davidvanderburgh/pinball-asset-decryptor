#!/bin/bash
# Save the running game to a named slot - and KEEP PLAYING. (item 13)
#
#   wsl -u root -e bash savegame.sh [slot] [label]
#
# Needs root (criu does). The game must have been started with PAD_PIVOT=1 (a
# chroot guest cannot be checkpointed). Default slot is "quicksave". The game
# is left RUNNING - saving does not interrupt play - so pair this with
# loadgame.sh to jump back later. The optional LABEL is a human name for the
# slot; it travels IN the slot (slot.meta), so it survives sessions, machines
# and whoever lists it (slots.sh, the playfield picker, the app's manager).
#
# Slots live in <rootfs>/saves/<slot>, and the rootfs is read from the running
# guest's own environment, so you never have to tell it where anything is.

set -u
RIG=$(cd "$(dirname "$0")" && pwd)
SLOT=${1:-quicksave}
LABEL=${2:-}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}

# The slot name becomes `rm -rf $ROOT/saves/$SLOT` below, and a GUI feeds it
# now - so it is a filename, never a path. Reject anything else loudly.
case "$SLOT" in
    ""|*[!A-Za-z0-9_.-]*|.|..)
        echo "[savegame] bad slot name '$SLOT' - letters, digits, _ . - only"
        exit 2 ;;
esac

[ "$(id -u)" = 0 ] || { echo "savegame: needs root. Use: wsl -u root -e bash $0 [slot]"; exit 2; }
PID=$(pgrep -x game | head -1)
[ -n "$PID" ] || { echo "[savegame] no game is running - start one with PAD_PIVOT=1 first"; exit 1; }

# SAY WHY when the running game cannot be saved, before criu burns seconds
# discovering it the hard way. A pivot guest's root IS its mount-namespace
# root, so /proc/PID/root reads "/"; an ordinary chroot guest's reads the
# rootfs path, and criu refuses that shape outright ("The root task has
# another root than mntns" - the ladder's first finding). This is exactly
# what the playfield's Save state button hits on a run the app's Emulate tab
# launched (2026-08-09, "[savegame] FAILED" with the reason buried): the tab
# does not launch PAD_PIVOT yet. The LAST tagged line is what the button's
# status bar shows, so the reason goes there, not above it.
GROOT=$(readlink "/proc/$PID/root" 2>/dev/null)
if [ "$GROOT" != "/" ]; then
    echo "savegame: the running game is an ordinary chroot run (root=$GROOT),"
    echo "which criu cannot checkpoint. Start the emulator with PAD_PIVOT=1"
    echo "(as root) to use save states - the app's Emulate tab does not yet."
    echo "[savegame] this run is not checkpointable - start with PAD_PIVOT=1"
    exit 1
fi

# The rootfs and title straight from the guest's environment - no guessing, and
# correct even though this runs as root (whose \$HOME is /root, not the games').
envval() { tr '\0' '\n' < "/proc/$PID/environ" 2>/dev/null | sed -n "s/^$1=//p" | head -1; }
ROOT=$(envval PAD_ROOT)
GAME=$(envval PAD_GAME)
[ -n "$ROOT" ] || { echo "savegame: the guest has no PAD_ROOT - was it started with PAD_PIVOT=1?"; exit 1; }

# ★ ITEM 39: PER GAME - saves/<game>/<slot>, so every title has its own ten
# slots and turtles' slot 1 can never overwrite godzilla's. A LEGACY bare
# slot of this same game under this name is removed: slots.sh migrates those
# on sight, but a save landing between migrations must not leave a stale
# twin at the old path for the next list to resurrect.
[ -n "$GAME" ] || { echo "savegame: the guest has no PAD_GAME"; exit 1; }
DIR=$ROOT/saves/$GAME/$SLOT
rm -rf "$DIR"; mkdir -p "$DIR"
if [ -f "$ROOT/saves/$SLOT/slot.meta" ] && \
   [ "$(sed -n 's/^game=//p' "$ROOT/saves/$SLOT/slot.meta" | head -1)" = "$GAME" ]; then
    rm -rf "${ROOT:?}/saves/$SLOT"
fi

echo "[savegame] slot '$SLOT'  <-  $GAME (pid $PID)"
CRIU="$CRIU" bash "$RIG/savestate.sh" "$DIR" "$PID" || { echo "[savegame] FAILED"; exit 1; }

# Record what loadgame.sh needs: the rootfs, the title, and the guest log's
# size at this instant. leave-running keeps appending to that log, so a later
# restore would fail criu's "file changed size" check - loadgame truncates it
# back to exactly here, which is harmless (only post-save log lines are lost).
{
    echo "root=$ROOT"
    echo "game=$GAME"
    echo "logsize=$(stat -c %s "$ROOT/dump/game.out" 2>/dev/null || echo 0)"
    # One line, so slot.meta stays a key=value file whatever the label says.
    [ -n "$LABEL" ] && echo "label=$(printf '%s' "$LABEL" | tr '\n\r' '  ')"
} > "$DIR/slot.meta"

# --- pack the slot --------------------------------------------------------
# Measured on a real in-game slot: 1.23 GB -> 64 MB at zstd -3 in 2 s. The
# guest's RAM is over half zero pages, the ring stashes are mostly stale
# bytes, and the GL journal is texture pixels - all of it crushes. This runs
# HERE, after savestate.sh has already thawed the game, so the save feels
# identical; loadgame.sh unpacks into a staging dir (~1 s) before restoring.
# slot.meta stays PLAIN beside the pack so slots.sh and loadgame read the
# slot without unpacking it. No zstd, or a failed pack, keeps the raw slot -
# loudly, because a 1.2 GB surprise should say why. PAD_SAVE_NOPACK=1 skips.
if [ "${PAD_SAVE_NOPACK:-0}" = 0 ] && command -v zstd >/dev/null 2>&1; then
    PACK=$ROOT/saves/.pack.$SLOT.$$
    if tar -C "$DIR" -cf - --exclude='./slot.meta' . 2>/dev/null \
            | zstd -3 -T0 -q -f -o "$PACK"; then
        find "$DIR" -mindepth 1 ! -name slot.meta -delete
        mv "$PACK" "$DIR/slot.tar.zst"
        echo "[savegame] packed: $(du -h "$DIR/slot.tar.zst" | cut -f1) on disk"
    else
        rm -f "$PACK"
        echo "[savegame] NOTE: packing failed - the slot stays raw ($(du -sh "$DIR" | cut -f1))"
    fi
elif [ "${PAD_SAVE_NOPACK:-0}" = 0 ]; then
    echo "[savegame] NOTE: no zstd in WSL - the slot stays raw ($(du -sh "$DIR" | cut -f1))"
fi

echo "[savegame] saved to slot '$SLOT'. Keep playing; loadgame.sh $SLOT jumps back here."
