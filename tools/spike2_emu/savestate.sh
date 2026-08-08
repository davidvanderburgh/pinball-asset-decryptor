#!/bin/bash
# Freeze a running PAD_PIVOT guest to a checkpoint on disk. (item 13)
#
#   wsl -u root -e bash savestate.sh <dumpdir> [pid]
#
# Needs root (criu does). The guest MUST have been booted with PAD_PIVOT=1 -
# a chroot guest cannot be checkpointed at all (criuladder.sh proved it: "The
# root task has another root than mntns"). By default the guest KEEPS RUNNING
# after the dump (--leave-running), so saving does not interrupt play; pass
# PAD_SAVE_STOP=1 to stop it instead.
#
# It reads the guest's ACTUAL /proc/PID/mountinfo and generates one --external
# per mount criu cannot resolve alone - every /dev bind and any fuse (card)
# mount - so nothing is assumed about the device list or whether a card was
# used. It also finds the tty fd the guest holds (the node bus). Both, plus the
# per-mount restore SOURCE, go to DDIR/restore.env, which restorestate.sh
# replays verbatim: this script is the one place that knows the mapping.
#
# The recipe (compat engine, --root, nsclean, mnt/tty externals) is the one
# criuladder.sh rungs D-G proved; see there for the failure behind each flag.

set -u
DDIR=${1:?usage: savestate.sh <dumpdir> [pid]}
ARGPID=${2:-}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
. "$(dirname "$0")/padpath.sh"

[ "$(id -u)" = 0 ] || { echo "savestate: needs root. Use: wsl -u root -e bash $0 ..."; exit 2; }
[ -x "$CRIU" ] || { echo "savestate: no criu at $CRIU"; exit 2; }

# comm=game is the rig's definition of the guest (alive.sh uses it). The
# pivoted guest is qemu running the game in-process, comm set to "game" by the
# game via prctl, so this is the pid-namespace init's HOST pid.
PID=$ARGPID
[ -z "$PID" ] && PID=$(pgrep -x game | head -1)
[ -n "$PID" ] || { echo "savestate: no guest (comm=game) - booted with PAD_PIVOT=1?"; exit 1; }
[ -d "/proc/$PID" ] || { echo "savestate: pid $PID is gone"; exit 1; }
echo "[save] guest pid $PID, root $(readlink /proc/$PID/root 2>/dev/null)"

mkdir -p "$DDIR"
: > "$DDIR/restore.env"

# --- externals from the guest's real mounts ------------------------------
# A mount needs --external when its backing is OUTSIDE the checkpoint. The
# honest test is the FSTYPE, not the path: run_game.sh's /dev holds both host
# binds AND a fresh tmpfs (/dev/shm), and only the binds are external. tmpfs,
# proc, sysfs and the rootfs self-binds are criu's to recreate.
#   devtmpfs -> a host /dev node bound in (null/zero/urandom/random, or a fake
#               bound from /dev/null: spidev, i2c, rtc, console...)
#   devpts   -> the node-bus pty; source is a fresh slave, filled in at restore
#   fuse     -> the card; re-mounted at restore
# The restore SOURCE is decided here (the one place that knows the mapping):
#   @PTY@ / @CARD@ placeholders, else a real host path.
DUMP_EXT=()
while IFS= read -r line; do
    mp=$(awk '{print $5}' <<<"$line")
    fstype=$(awk '{for(i=7;i<=NF;i++) if($i=="-"){print $(i+1); exit}}' <<<"$line")
    base=${mp##*/}
    key="ext_$(echo "${mp#/}" | tr '/.' '__')"
    case "$fstype" in
    devtmpfs)
        if [ "$base" = null ] || [ "$base" = zero ] || \
           [ "$base" = urandom ] || [ "$base" = random ]; then
            src="/dev/$base"          # the host has these, bind the same node
        else
            src='/dev/null'           # fakes: open ok, ioctls fail
        fi
        DUMP_EXT+=(--external "mnt[$mp]:$key")
        echo "mnt $key $mp $src" >> "$DDIR/restore.env"
        ;;
    devpts)
        DUMP_EXT+=(--external "mnt[$mp]:$key")
        echo "mnt $key $mp @PTY@" >> "$DDIR/restore.env"
        ;;
    fuse|fuseblk)
        DUMP_EXT+=(--external "mnt[$mp]:$key")
        echo "mnt $key $mp @CARD@" >> "$DDIR/restore.env"
        ;;
    esac
done < "/proc/$PID/mountinfo"

# --- the tty fd the guest holds (the node bus) ---------------------------
# criu's tty[] key is hex st_rdev:st_dev of the tty file; take the RAW numbers
# from stat via python (stat(1)'s %t:%T is major:minor, not the raw rdev criu
# prints). One holder = one tty; if the game ever holds more this loops them.
TTY_EXT=()
for fd in /proc/$PID/fd/*; do
    tgt=$(readlink "$fd" 2>/dev/null) || continue
    case "$tgt" in
    /dev/pts/*|*ttymxc1*)
        key=$(python3 -c 'import os,sys;s=os.stat(sys.argv[1]);print("%x:%x"%(s.st_rdev,s.st_dev))' "$fd" 2>/dev/null) || continue
        n=${fd##*/}
        TTY_EXT+=(--external "tty[$key]")
        echo "tty $n $key $tgt" >> "$DDIR/restore.env"
        ;;
    esac
done

# --- dump ----------------------------------------------------------------
LEAVE=--leave-running
[ "${PAD_SAVE_STOP:-0}" = 1 ] && LEAVE=
echo "[save] externals:${DUMP_EXT[*]+ ${DUMP_EXT[*]}}${TTY_EXT[*]+ ${TTY_EXT[*]}}"
"$CRIU" dump -t "$PID" -D "$DDIR" -v4 -o dump.log $LEAVE \
    ${DUMP_EXT[@]+"${DUMP_EXT[@]}"} ${TTY_EXT[@]+"${TTY_EXT[@]}"}
RC=$?
if [ "$RC" != 0 ] || grep -aq 'Dumping FAILED' "$DDIR/dump.log"; then
    echo "[save] FAILED (exit $RC):"
    grep -aE 'Error' "$DDIR/dump.log" | tail -12 | sed 's/^/    /'
    exit 1
fi
echo "[save] ok - $(ls "$DDIR"/*.img 2>/dev/null | wc -l) images, $(du -sh "$DDIR" | cut -f1)"
echo "[save] restore.env:"; sed 's/^/    /' "$DDIR/restore.env"
