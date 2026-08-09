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
    fuse*)
        # THE CARD - record WHERE IT LIVES ON THE HOST, not a placeholder.
        # `fuse*`, NOT `fuse|fuseblk`: fuse2fs registers as `fuse.ext4`, which
        # the exact match missed - found on the FIRST real card save ever run
        # (2026-08-09, David's button): no external was recorded and criu died
        # "607:./games/godzilla_pro doesn't have a proper root mount". Every
        # earlier save was an extracted-tree run with no fuse mount to see.
        # The guest line's major:minor names the fuse fs; the same fs appears
        # in OUR mountinfo at its host mountpoint, and the guest line's root
        # field (the bind's subdir, e.g. /godzilla_pro) completes the path.
        # restorestate can then reattach to the LIVE mount - in a windowed
        # session the card mount SURVIVES the guest swap (cardmount setsids
        # fuse2fs so no teardown reaches it), so a load needs no re-mount
        # machinery at all. @CARD@ only when the host lookup fails, and the
        # old restorestate error for it still stands.
        majmin=$(awk '{print $3}' <<<"$line")
        fsroot=$(awk '{print $4}' <<<"$line")
        hostmnt=$(awk -v mm="$majmin" '$3==mm {print $5; exit}' /proc/self/mountinfo)
        if [ -n "$hostmnt" ]; then
            src=$hostmnt
            [ "$fsroot" != "/" ] && src="$hostmnt$fsroot"
            echo "card $key $mp $src" >> "$DDIR/restore.env"
        else
            echo "card $key $mp @CARD@" >> "$DDIR/restore.env"
        fi
        DUMP_EXT+=(--external "mnt[$mp]:$key")
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
    *'(deleted)'*)
        # A DEAD PTY MAKES AN UNLOADABLE SAVE - refuse now, loudly, rather
        # than hand back a slot that fails at restore ("tty: Corrupted
        # master peer", David's second load 2026-08-09). The pty dies when
        # its nodebus exits; nodebus.py holds the pty for the session's
        # life now, so this only fires on a session from before that fix.
        case "$tgt" in
        /dev/pts/*)
            echo "[save] REFUSED: the game's node-bus tty is dead ($tgt) -"
            echo "[save] a save of it could never be loaded. This session"
            echo "[save] predates the nodebus hold fix; restart it and save"
            echo "[save] again."
            exit 1
            ;;
        esac
        ;;
    /dev/pts/*|*ttymxc1*)
        key=$(python3 -c 'import os,sys;s=os.stat(sys.argv[1]);print("%x:%x"%(s.st_rdev,s.st_dev))' "$fd" 2>/dev/null) || continue
        n=${fd##*/}
        TTY_EXT+=(--external "tty[$key]")
        echo "tty $n $key $tgt" >> "$DDIR/restore.env"
        ;;
    esac
done

# --- the guest's supplementary groups ------------------------------------
# ★ THIS IS WHAT LETS A GUEST IN AN UNPRIVILEGED USER NAMESPACE BE RESTORED.
# In such a namespace the kernel disables setgroups, so criu cannot restore a
# process's groups - and a david guest under `unshare -r` died exactly there:
#   "Can't setgroups([7 gids]): -22" then "BUG at restorer.c:819".
# But criu's restorer SKIPS the setgroups call entirely when the RESTORING
# process's own group list already equals the dumped one (pie/restorer.c:215,
# "If the current list of groups is already what we want"). criu runs as root,
# whose groups are not david's, which is why it never skipped. So record the
# guest's groups here and let restorestate.sh adopt them before restoring.
GRP=$(awk '/^Groups:/{ $1=""; print }' "/proc/$PID/status" 2>/dev/null \
      | tr -s ' ' | sed 's/^ *//; s/ *$//' | tr ' ' ',')
echo "groups ${GRP:-none}" >> "$DDIR/restore.env"

# --- FIFOs the guest holds (the audio pipe) ------------------------------
# The guest writes PCM into dump/audio.fifo, made by playaudio.sh. criu restores
# a named fifo by re-opening its PATH (a "fake fifo"), so it must exist at
# restore - and playaudio.sh removes it when its reader ends, which is exactly
# what killing the guest for a load causes:
#   "Can't open fake fifo 0x74 [dump/audio.fifo]: No such file or directory"
# Record each so restorestate can mkfifo what is missing. NOTE this makes the
# RESTORE work; the audio HELPER still has to be restarted to hear anything,
# which is the outstanding reattach work.
while read -r p; do
    echo "fifo $p" >> "$DDIR/restore.env"
done < <(for fd in /proc/$PID/fd/*; do
             [ -p "$fd" ] || continue
             t=$(readlink "$fd" 2>/dev/null)
             case "$t" in /*) printf '%s\n' "$t" ;; esac
         done | sort -u)

# --- the rig's shared rings ----------------------------------------------
# The guest maps dump/padled, dump/padgl, dump/padsw (and padvid) MAP_SHARED.
# criu re-opens such a mapping FROM THE FILE at restore, so the file must exist
# then - and its CONTENT is the ring state, which is NOT in the checkpoint.
# watch.sh's teardown DELETES dump/padled on purpose (it is the playfield's
# liveness signal), so a load after any teardown found it gone:
#   "Can't open file dump/padled on restore: No such file or directory"
# So stash every mapped ring in the slot; restorestate puts back any that have
# gone missing, content and all.
mkdir -p "$DDIR/rings"
while read -r p; do
    case "$p" in /dump/*) ;; *) continue ;; esac
    src=/proc/$PID/root$p
    [ -f "$src" ] || continue
    stash=$(echo "${p#/}" | tr '/' '_')
    cp -f "$src" "$DDIR/rings/$stash" 2>/dev/null \
        && echo "ring $p $stash" >> "$DDIR/restore.env"
done < <(awk '$2 ~ /s/ && $4 !~ /^00:00/ {print $6}' "/proc/$PID/maps" 2>/dev/null | sort -u)

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
