#!/bin/bash
# Restore a PAD_PIVOT guest from a checkpoint made by savestate.sh. (item 13)
#
#   wsl -u root -e bash restorestate.sh <dumpdir>
#
# Needs root. Restarts the host helpers the guest talks to (the node bus pty),
# resolves the externals savestate.sh recorded, and runs criu restore with the
# recipe criuladder.sh proved. The restored guest is detached and left running.
#
# It does NOT restart padglhost / audio / video / playfield - those reconnect
# to the guest through the file-backed rings (whose content is on disk, not in
# the checkpoint) and are watch.sh's job, not this script's. This restores the
# GUEST; the caller re-attaches the rest.

set -u
DDIR=${1:?usage: restorestate.sh <dumpdir>}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
. "$(dirname "$0")/padpath.sh"
R=$ROOT

[ "$(id -u)" = 0 ] || { echo "restorestate: needs root. Use: wsl -u root -e bash $0 ..."; exit 2; }
[ -x "$CRIU" ] || { echo "restorestate: no criu at $CRIU"; exit 2; }
[ -f "$DDIR/restore.env" ] || { echo "restorestate: no restore.env in $DDIR"; exit 1; }

# A guest already running would collide on the restored pids; refuse unless
# told to clear it (killgame is the rig's own teardown).
if pgrep -x game >/dev/null; then
    if [ "${PAD_RESTORE_KILL:-0}" = 1 ]; then
        echo "[restore] a guest is up - killing it first (PAD_RESTORE_KILL=1)"
        bash "$RIG/killgame.sh" >/dev/null 2>&1
        sleep 1
    else
        echo "[restore] a guest (comm=game) is already running; set PAD_RESTORE_KILL=1 to replace it"
        exit 1
    fi
fi

# --- restart the node bus and get a fresh pty ----------------------------
# nodebus.py holds the master and writes the slave path; the same helper the
# original run used, restarted, exactly the design's restart-the-helpers step.
NEWPTY=""
if grep -q '@PTY@' "$DDIR/restore.env"; then
    export PAD_NODEBUS_DIR="$R/dump"
    rm -f "$R/dump/nodebus.path"
    # The pty must be owned by the SAME user the guest ran as, or criu cannot
    # set the tty owner on restore ("Can't setup uid ... Operation not
    # permitted"). The guest runs as an unprivileged user (watch.sh is david);
    # criu needs root. When those differ - root running the restore for a
    # david guest - start nodebus as that user. PAD_NB_USER names it.
    if [ "$(id -u)" = 0 ] && [ -n "${PAD_NB_USER:-}" ]; then
        runuser -u "$PAD_NB_USER" -- env PAD_NODEBUS_DIR="$R/dump" \
            python3 "$RIG/nodebus.py" >/dev/null 2>&1 &
    else
        python3 "$RIG/nodebus.py" >/dev/null 2>&1 &
    fi
    NBPID=$!
    for _ in $(seq 1 50); do [ -s "$R/dump/nodebus.path" ] && break; sleep 0.1; done
    NEWPTY=$(cat "$R/dump/nodebus.path" 2>/dev/null)
    [ -e "$NEWPTY" ] || { echo "[restore] node bus did not come up"; exit 1; }
    echo "[restore] node bus pty: $NEWPTY (pid $NBPID)"
fi

# --- build the restore externals from restore.env ------------------------
REST_EXT=(); INHERIT=(); TTYFD=""
while read -r kind a b c; do
    case "$kind" in
    mnt)
        # a=key b=mountpoint c=source (@PTY@/@CARD@ resolved here)
        src=$c
        [ "$src" = '@PTY@' ]  && src=$NEWPTY
        [ "$src" = '@CARD@' ] && { echo "[restore] a card mount is needed but re-mounting the card is not automated yet"; exit 1; }
        REST_EXT+=(--external "mnt[$a]:$src")
        ;;
    tty)
        # a=old fd number  b=tty[key]  c=old slave path. The NEW slave carries
        # the fd (opened on 9 below); the OLD key names the resource in images.
        INHERIT+=(--inherit-fd "fd[9]:tty[$b]")
        TTYFD=$NEWPTY
        ;;
    esac
done < "$DDIR/restore.env"

# --- the nsclean the restore runs inside ---------------------------------
# criu's compat mount engine umounts a copy of ITS namespace, and WSL's
# init-namespace mounts refuse a plain umount (EINVAL). So run the restore in a
# throwaway mount namespace stripped to almost nothing - keeping only what a
# restore external resolves through (/dev, /dev/pts for the pty) plus a fresh
# /proc and a re-bind of the rootfs for --root. See criuladder.sh for the full
# story of why each of these is here.
NSCLEAN=$DDIR/nsclean.sh
cat > "$NSCLEAN" <<EOF
mount --make-rprivate /
awk '\$5 != "/" && \$5 != "/proc" && \$5 != "/dev" && \$5 != "/dev/pts" { print \$5 }' \
    /proc/self/mountinfo | sort -r | while read -r mp; do umount -l "\$mp" 2>/dev/null; done
umount -l /proc 2>/dev/null
mount -t proc proc /proc
mount --bind "$R" "$R"
exec "\$@"
EOF

# fd 9 = the new pty slave, for --inherit-fd; rides plain fd inheritance
# through unshare/bash into criu.
if [ -n "$TTYFD" ]; then
    exec 9<>"$TTYFD" || { echo "[restore] could not open $TTYFD on fd 9"; exit 1; }
fi

# The mount engine. Compat mode is what the criuladder.sh rungs needed (mount-v2
# BUG_ON'd for a root-userns guest). PAD_RESTORE_V2=1 tries mount-v2 instead -
# under test for the david-userns real game, whose restore hits a pivot_root
# EINVAL in the compat engine.
COMPAT=(--mntns-compat-mode)
[ "${PAD_RESTORE_V2:-0}" = 1 ] && COMPAT=()
echo "[restore] restoring...${COMPAT:+ (compat engine)}"
unshare -m bash "$NSCLEAN" \
    "$CRIU" restore -D "$DDIR" -v4 -o restore.log -d \
        --pidfile "$DDIR/restored.pid" \
        --root "$R" ${COMPAT[@]+"${COMPAT[@]}"} \
        ${REST_EXT[@]+"${REST_EXT[@]}"} ${INHERIT[@]+"${INHERIT[@]}"}
RC=$?
[ -n "$TTYFD" ] && exec 9>&-

if [ "$RC" != 0 ] || grep -aq 'Restoring FAILED' "$DDIR/restore.log"; then
    echo "[restore] FAILED (exit $RC):"
    grep -aE 'Error' "$DDIR/restore.log" | tail -12 | sed 's/^/    /'
    exit 1
fi
sleep 1
NEWPID=$(cat "$DDIR/restored.pid" 2>/dev/null)
if [ -n "$NEWPID" ] && kill -0 "$NEWPID" 2>/dev/null; then
    echo "[restore] ok - guest restored, pid $NEWPID"
else
    echo "[restore] restore reported ok but the guest is not alive"; exit 1
fi
