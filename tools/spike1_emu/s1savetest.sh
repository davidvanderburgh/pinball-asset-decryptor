#!/bin/bash
# item 87 PROTOTYPE: first criu dump of a pivoted Spike 1 guest.  Not the
# shipping script — this is the instrument that discovers what criu refuses.
#   wsl -u root -e bash s1savetest.sh <dumpdir> [pid]
set -u
DDIR=${1:?usage: s1savetest.sh <dumpdir> [pid]}
ARGPID=${2:-}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
[ "$(id -u)" = 0 ] || { echo "needs root"; exit 2; }
[ -x "$CRIU" ] || { echo "no criu at $CRIU"; exit 2; }

PID=$ARGPID
[ -z "$PID" ] && PID=$(ps -eo pid,comm --sort=-pcpu | awk '$2=="game"{print $1; exit}')
[ -n "$PID" ] || { echo "no guest (comm=game)"; exit 1; }
echo "[t] guest pid $PID  root $(readlink /proc/$PID/root)  NSpid: $(grep NSpid /proc/$PID/status)"

mkdir -p "$DDIR"
: > "$DDIR/restore.env"

# --- mount externals: every mount except /, /proc, /sys gets one -----------
DUMP_EXT=()
while IFS= read -r line; do
    mp=$(awk '{print $5}' <<<"$line")
    fstype=$(awk '{for(i=7;i<=NF;i++) if($i=="-"){print $(i+1); exit}}' <<<"$line")
    case "$mp" in
    /|/proc|/sys) continue ;;
    esac
    key="ext_$(echo "${mp#/}" | tr '/.' '__')"
    DUMP_EXT+=(--external "mnt[$mp]:$key")
    # record source hints for the restore half (fstype + the guest mountpoint)
    echo "mnt $key $mp $fstype" >> "$DDIR/restore.env"
done < "/proc/$PID/mountinfo"

# --- tty externals for pty fds (the ttyS4 node-bus slave) ------------------
TTY_EXT=()
for fd in /proc/$PID/fd/*; do
    tgt=$(readlink "$fd" 2>/dev/null) || continue
    case "$tgt" in
    /dev/pts/*|*ttyS4*)
        rl=$(readlink "/proc/$PID/fd/${fd##*/}")
        key=$(python3 -c 'import os,sys;s=os.stat(sys.argv[1]);print("%x:%x"%(s.st_rdev,s.st_dev))' "$fd" 2>/dev/null) || continue
        TTY_EXT+=(--external "tty[$key]")
        echo "tty ${fd##*/} $key $rl" >> "$DDIR/restore.env"
        ;;
    esac
done

echo "[t] externals: ${#DUMP_EXT[@]} mnt args, ${#TTY_EXT[@]} tty args"
PLUGDIR=${S1CRIU_PLUGIN_DIR:-}
PLUG=()
[ -n "$PLUGDIR" ] && PLUG=(-L "$PLUGDIR")
"$CRIU" dump -t "$PID" -D "$DDIR" -v4 -o dump.log --leave-stopped \
    ${PLUG[@]+"${PLUG[@]}"} \
    ${DUMP_EXT[@]+"${DUMP_EXT[@]}"} ${TTY_EXT[@]+"${TTY_EXT[@]}"}
RC=$?
if [ "$RC" != 0 ] || grep -aq 'Dumping FAILED' "$DDIR/dump.log"; then
    echo "[t] DUMP FAILED (exit $RC) - errors:"
    grep -aE 'Error|Can.t' "$DDIR/dump.log" | sort | uniq -c | sort -rn | head -20
    kill -CONT "$PID" 2>/dev/null
    exit 1
fi
echo "[t] DUMP OK - $(ls "$DDIR"/*.img 2>/dev/null | wc -l) images, $(du -sh "$DDIR" | cut -f1)"
kill -CONT "$PID" 2>/dev/null
