#!/bin/bash
# Save the running Spike 1 game to a named slot - and KEEP PLAYING. (item 87)
#
#   wsl -u root -e bash s1savestate.sh [slot] [label]
#
# Needs root (criu does).  The guest must have been booted with S1_PIVOT=1 - a
# chroot guest cannot be checkpointed at all ("The root task has another root
# than mntns", the same criu law the Spike 2 rig met first).  The game keeps
# playing after the save (frozen a second or two for the dump); pass
# S1_SAVE_STOP=1 to end it instead.
#
# Slots live at $S1_WORK/saves/<cache label>/<slot> - the label carries the
# title AND its card version, which is the honest key: a different card
# version is a different game ELF and a slot from one cannot restore into the
# other.  slot.meta (label, game, epoch) travels in the slot.
#
# What a slot carries beyond criu's images:
#   restore.env - one line per external the restore must resolve:
#       mnt <key> <mountpoint> <source|@PTY@>   (source resolved generically:
#           host mountpoint of the mount's major:minor + its root field - the
#           savestate.sh fuse-card trick, applied to every bind)
#       tty <fd> <rdev:dev> <path>
#       bin <sha1> <dest path> <stash name>     (rebuild-proofing, below)
#       game <cache label>
#   bin/ - the two binaries criu maps from disk and validates byte-for-byte:
#       the in-rootfs qemu copy (.padqemu/game) and the game ELF.  A qemu
#       rebuild or an s1patch.py change would otherwise kill every slot
#       (Spike 2 learned this as "slots carry their libs"); the restore
#       reinstalls the slot's own copies when the sha1s differ.
#   s1cuse.map - written by the s1criu.so plugin during the dump: one line per
#       CUSE device fd, reopened by path at restore.
set -u
SLOT=${1:-quicksave}
LABEL=${2:-}
HERE="$(cd "$(dirname "$0")" && pwd)"
S1_WORK=${S1_WORK:-/home/david/s1emu}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
PLUGDIR=${S1CRIU_PLUGIN_DIR:-$S1_WORK/criuplug}

case "$SLOT" in
    ""|*[!A-Za-z0-9_.-]*|.|..)
        echo "[s1save] bad slot name '$SLOT' - letters, digits, _ . - only"; exit 2 ;;
esac
[ "$(id -u)" = 0 ] || { echo "s1save: needs root. Use: wsl -u root -e bash $0 ..."; exit 2; }
[ -x "$CRIU" ] || { echo "[s1save] no criu at $CRIU - save states need it"; exit 2; }

# the plugin, compiled on demand (cc is present wherever the rig builds qemu)
if [ ! -e "$PLUGDIR/s1criu.so" ] || [ "$HERE/s1criu.c" -nt "$PLUGDIR/s1criu.so" ]; then
    mkdir -p "$PLUGDIR"
    gcc -shared -fPIC -O2 -o "$PLUGDIR/s1criu.so" "$HERE/s1criu.c" -I"$HERE" \
        || { echo "[s1save] could not compile the criu plugin"; exit 2; }
fi

PID=$(ps -eo pid,comm | awk '$2=="game"{print $1; exit}')
[ -n "$PID" ] || { echo "[s1save] no game is running - start one with S1_PIVOT=1 first"; exit 1; }
GROOT=$(readlink "/proc/$PID/root" 2>/dev/null)
if [ "$GROOT" != "/" ]; then
    echo "s1save: the running game is an ordinary chroot run (root=$GROOT),"
    echo "which criu cannot checkpoint. Enable save states so the emulator"
    echo "boots checkpointable (S1_PIVOT=1), then save again."
    echo "[s1save] this run is not checkpointable - start with S1_PIVOT=1"
    exit 1
fi

GAMEDIR=$(readlink -f "$S1_WORK/game")
CLABEL=$(basename "$(dirname "$GAMEDIR")")
GAME_NAME="$(tr -d '[:space:]' < "$GAMEDIR/.game_name" 2>/dev/null)"; : "${GAME_NAME:=$CLABEL}"
R=$(readlink -f "$S1_WORK/rootfs")
DDIR="$S1_WORK/saves/$CLABEL/$SLOT"
rm -rf "$DDIR"; mkdir -p "$DDIR"
: > "$DDIR/restore.env"
echo "game $CLABEL" >> "$DDIR/restore.env"

# --- externals: every mount except /, /proc, /sys, source resolved ---------
DUMP_EXT=()
while IFS= read -r line; do
    mp=$(awk '{print $5}' <<<"$line")
    case "$mp" in /|/proc|/sys) continue ;; esac
    fstype=$(awk '{for(i=7;i<=NF;i++) if($i=="-"){print $(i+1); exit}}' <<<"$line")
    majmin=$(awk '{print $3}' <<<"$line")
    fsroot=$(awk '{print $4}' <<<"$line")
    key="ext_$(echo "${mp#/}" | tr '/.' '__')"
    if [ "$fstype" = devpts ]; then
        src='@PTY@'                       # the live node-bus pty, at restore
    else
        hostmnt=$(awk -v mm="$majmin" '$3==mm {print $5; exit}' /proc/self/mountinfo)
        if [ -z "$hostmnt" ]; then
            echo "[s1save] cannot resolve the host mount behind $mp ($majmin)"; exit 1
        fi
        src=$hostmnt
        [ "$fsroot" != "/" ] && src="$hostmnt$fsroot"
        src=${src//\/\///}
    fi
    DUMP_EXT+=(--external "mnt[$mp]:$key")
    echo "mnt $key $mp $src" >> "$DDIR/restore.env"
done < "/proc/$PID/mountinfo"

# --- the tty fd (node-bus pty slave bound at /dev/ttyS4) -------------------
TTY_EXT=()
for fd in /proc/$PID/fd/*; do
    tgt=$(readlink "$fd" 2>/dev/null) || continue
    case "$tgt" in
    /dev/pts/*|*ttyS4*)
        key=$(python3 -c 'import os,sys;s=os.stat(sys.argv[1]);print("%x:%x"%(s.st_rdev,s.st_dev))' "$fd" 2>/dev/null) || continue
        TTY_EXT+=(--external "tty[$key]")
        echo "tty ${fd##*/} $key $tgt" >> "$DDIR/restore.env"
        ;;
    esac
done

# --- rebuild-proofing: the mapped binaries ride IN the slot ----------------
# Recorded by their HOST-side canonical paths (the bind SOURCES), which is
# where a restore can honestly compare and reinstall: the guest path
# /games/<title>/game resolves only inside the namespace, and its host-side
# mountpoint is an empty dir - comparing there "mismatches" every time.
mkdir -p "$DDIR/bin"
for spec in "$R/.padqemu/game qemu" "$GAMEDIR/game gamelf"; do
    f=${spec% *}; name=${spec#* }
    [ -f "$f" ] || continue
    sum=$(sha1sum "$f" | cut -d' ' -f1)
    cp -f "$f" "$DDIR/bin/$name"
    echo "bin $sum $f $name" >> "$DDIR/restore.env"
done

# --- dump ------------------------------------------------------------------
echo "[s1save] dumping pid $PID to $DDIR"
"$CRIU" dump -t "$PID" -D "$DDIR" -v4 -o dump.log --leave-stopped \
    -L "$PLUGDIR" \
    ${DUMP_EXT[@]+"${DUMP_EXT[@]}"} ${TTY_EXT[@]+"${TTY_EXT[@]}"}
RC=$?
if [ "$RC" != 0 ] || grep -aq 'Dumping FAILED' "$DDIR/dump.log"; then
    echo "[s1save] FAILED (exit $RC):"
    grep -aE 'Error' "$DDIR/dump.log" | tail -8 | sed 's/^/    /'
    kill -CONT "$PID" 2>/dev/null
    rm -rf "$DDIR"
    echo "[s1save] save failed - the game keeps playing"
    exit 1
fi

# --- the ball keeper's state rides in the slot -----------------------------
# (the keeper is not in the checkpoint; a mid-game load must hand the fresh
# keeper the balls-in-play picture the restored game believes in)
cp -f "$S1_WORK/s1ball.state" "$DDIR/s1ball.state" 2>/dev/null || true

# --- meta + thaw -----------------------------------------------------------
{
    echo "label=${LABEL}"
    echo "game=$CLABEL"
    echo "title=$GAME_NAME"
    echo "epoch=$(date +%s)"
} > "$DDIR/slot.meta"

if [ "${S1_SAVE_STOP:-0}" = 1 ]; then
    kill -9 "$PID" 2>/dev/null
    echo "[s1save] guest ended (S1_SAVE_STOP=1)"
else
    kill -CONT "$PID" 2>/dev/null
    for _ in 1 2 3 4 5; do
        st=$(awk '{print $3}' "/proc/$PID/stat" 2>/dev/null)
        [ "$st" != T ] && break
        kill -CONT "$PID" 2>/dev/null; sleep 0.2
    done
fi
echo "[s1save] ok - $CLABEL/$SLOT, $(du -sh "$DDIR" | cut -f1)"
