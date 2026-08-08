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
        # ONLY THE GUEST, never killgame.sh. killgame.sh is the rig's GLOBAL
        # teardown - it takes padglhost, the playfield, audio and video with it,
        # which would close the window you are playing in every time you loaded
        # a save. Those helpers talk to the guest through the file-backed rings
        # and reattach to the restored one, so they must stay up.
        echo "[restore] a guest is up - killing just the guest (PAD_RESTORE_KILL=1)"
        pkill -9 -x game 2>/dev/null
        pkill -9 -f '\.padqemu/game' 2>/dev/null
        pkill -9 -f arm-binfmt 2>/dev/null
        sleep 1
    else
        echo "[restore] a guest (comm=game) is already running; set PAD_RESTORE_KILL=1 to replace it"
        exit 1
    fi
fi

# --- the node bus and a pty for the restored guest -----------------------
# The restored guest needs a pty on /dev/ttymxc1 (criu bridges the dumped one
# to whatever fd we hand it, so ANY pty works). Two cases:
#   REUSE - a node bus is already running (a live watch.sh session, the
#           windowed case): open ITS existing slave. Starting a second nodebus
#           would orphan the first and leak a pty on every loadgame.
#   START - none running (a headless load): start one, exactly the design's
#           restart-the-helpers step.
NEWPTY=""
if grep -q '@PTY@' "$DDIR/restore.env"; then
    export PAD_NODEBUS_DIR="$R/dump"
    RUNNING_PTY=$(cat "$R/dump/nodebus.path" 2>/dev/null)
    if pgrep -f 'nodebus\.py' >/dev/null && [ -n "$RUNNING_PTY" ] && [ -e "$RUNNING_PTY" ]; then
        NEWPTY=$RUNNING_PTY
        echo "[restore] reusing the running node bus pty: $NEWPTY"
    else
        rm -f "$R/dump/nodebus.path"
        # The pty must be owned by the SAME user the guest ran as, or criu
        # cannot set the tty owner on restore ("Can't setup uid ... Operation
        # not permitted"). PAD_NB_USER names that user when the restore runs as
        # root for a guest that ran as someone else (the legacy david case).
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
    fifo)
        # a=guest path. criu re-opens a named fifo by path; playaudio.sh
        # deletes it when its reader ends, which killing the guest causes.
        # Recreate it empty so the restore can proceed - the guest just goes on
        # writing PCM into it. (Hearing it again needs the audio helper
        # restarted; that is the outstanding reattach work.)
        if [ ! -p "$R$a" ]; then
            mkdir -p "$(dirname "$R$a")"
            rm -f "$R$a" 2>/dev/null
            mkfifo "$R$a" 2>/dev/null && echo "[restore] recreated the missing fifo $a"
        fi
        ;;
    ring)
        # a=guest path  b=stashed filename. criu re-opens a file-backed
        # MAP_SHARED mapping from the FILE, so it has to be there - and
        # watch.sh's teardown deletes dump/padled by design. Put back ONLY what
        # is missing: a live session's ring is newer than this snapshot and
        # clobbering it would throw away the state the helpers are using.
        if [ ! -f "$R$a" ] && [ -f "$DDIR/rings/$b" ]; then
            mkdir -p "$(dirname "$R$a")"
            cp -f "$DDIR/rings/$b" "$R$a"
            echo "[restore] put back the missing ring $a"
        fi
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

# The mount engine. mount-v2 is the DEFAULT because a PAD_PIVOT guest launched
# as root has NO user namespace (run_game.sh drops `unshare -r` for root), and
# for that guest the COMPAT engine BUG_ON's at `pivot_root(., tmp)` while
# mount-v2 restores cleanly - measured on the real game. PAD_RESTORE_COMPAT=1
# forces the old compat engine, which is only right for the legacy case of a
# guest that kept its user namespace (mount-v2 BUG_ON'd there instead). The two
# are exact opposites, which is why this is a knob and not a guess.
COMPAT=()
[ "${PAD_RESTORE_COMPAT:-0}" = 1 ] && COMPAT=(--mntns-compat-mode)

do_restore() {
    unshare -m bash "$NSCLEAN" \
        "$CRIU" restore -D "$DDIR" -v4 -o restore.log -d \
            --pidfile "$DDIR/restored.pid" \
            --root "$R" ${COMPAT[@]+"${COMPAT[@]}"} \
            ${REST_EXT[@]+"${REST_EXT[@]}"} ${INHERIT[@]+"${INHERIT[@]}"}
}

# THE GROWING-OUTPUT RETRY. A save that left the game RUNNING (a quicksave)
# keeps writing its append-only outputs - the log (game.out) and the audio
# streams (audio.raw, audio.raw.center) - so by restore time each is bigger
# than the size criu recorded for its fd, and criu refuses it:
#   "File dump/audio.raw has bad size N (expect M)".
# criu names the exact size it wants for EACH such file (one per attempt), so
# truncate every one it names back to M - harmless, they are output streams and
# the guest just keeps appending after restore - and retry until it stops
# complaining about sizes. The error is the one authority; a stat guess is
# unreliable because the guest appends between the dump and the stat. Only ever
# truncates files criu itself names, only on this exact error, bounded.
echo "[restore] restoring...${COMPAT:+ (compat engine)}"
for _attempt in 1 2 3 4 5 6; do
    do_restore
    RC=$?
    { [ "$RC" = 0 ] && ! grep -aq 'Restoring FAILED' "$DDIR/restore.log"; } && break
    # truncate every growing file this attempt named; stop if it named none
    # (then it is a real failure, not a size mismatch).
    fixed=0
    while read -r path want; do
        [ -f "$R/$path" ] || continue
        truncate -s "$want" "$R/$path" && {
            echo "[restore] $path grew since the save; truncated to $want"; fixed=1; }
    done < <(grep -aoE 'File [^ ]+ has bad size [0-9]+ \(expect [0-9]+\)' "$DDIR/restore.log" \
             | sed -E 's/^File (\S+) has bad size [0-9]+ \(expect ([0-9]+)\)/\1 \2/' | sort -u)
    [ "$fixed" = 1 ] || break
done
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
