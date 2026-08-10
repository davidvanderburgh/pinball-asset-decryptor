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

# --- PRE-FLIGHT: refuse a doomed slot BEFORE anything is killed ----------
# A restore that fails after PAD_RESTORE_KILL has already killed the guest
# takes the WHOLE SESSION with it - watch.sh sees no guest, tears down, and
# the windows close on a game that was fine a second ago. That has happened
# twice now (the stale-pidfile load, then David's dead-tty load), so every
# check that can be made against the SLOT alone runs here, first.
card_live() {
    [ "$1" != '@CARD@' ] && [ -d "$1" ] || return 1
    case "$(findmnt -no FSTYPE --target "$1" 2>/dev/null)" in
        fuse*) return 0 ;;
    esac
    return 1
}
# A tty external recorded as "(deleted)" is a save of a DEAD pty - the old
# nodebus had exited and taken the pty with it before the save was made.
# criu dumps that without complaint and then dies restoring it ("tty:
# Corrupted master peer"). Nothing can load such a slot; say so and leave
# the running game alone. (nodebus.py holds its pty now, so new sessions
# do not produce these - this catches slots from before the fix.)
if grep -q '^tty .*(deleted)' "$DDIR/restore.env"; then
    echo "[restore] this save cannot be loaded: it was taken while the game's"
    echo "[restore] node-bus tty was dead (its pty had been deleted - a save"
    echo "[restore] made after a load, on a session from before the nodebus"
    echo "[restore] hold fix). Save again on a current session."
    exit 1
fi
while read -r kind a b c; do
    [ "$kind" = card ] || continue
    if ! card_live "$c"; then
        echo "[restore] the card mount behind $b is gone ($c)."
        echo "[restore] mount it and retry:  cardmount.sh <the card image>"
        exit 1
    fi
done < "$DDIR/restore.env"

# This session's identity, read from the LIVE guest before it is killed -
# through its own root, because padpath's $ROOT is wrong under root's $HOME.
# Compared against the slot's copy at the end for the cross-session note.
LIVE_BOOT=""
LIVEPID=$(pgrep -x game | head -1)
[ -n "$LIVEPID" ] && LIVE_BOOT=$(cat "/proc/$LIVEPID/root/dump/boot.id" 2>/dev/null)

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
#   REUSE - a node bus is already running: open ITS existing slave. Starting
#           a second nodebus would orphan the first and leak a pty.
#   START - none running: start one, exactly the design's restart-the-helpers
#           step.
# MEASURED 2026-08-08, first live windowed load: the windowed case ALWAYS
# takes START, and that is fine. run_game.sh's nodebus EOF-exits the moment
# the guest is killed (its os.read on the master breaks when the last slave
# fd closes), so by the time this runs it is already gone. The fresh pty
# satisfies criu's tty external; the recorder dying again later - the guest
# closes and reopens its tty once after restore - loses nothing, because
# nodebus only RECORDS: the game's real switch/coil traffic is SPI through
# the shim, and every ExchangeData timeout in the post-load log predates the
# save (1520 of 1520 in the pre-save bytes, zero new after restore).
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
        # Detached the same way the video host restart is (bash -c '... &'),
        # and for the same measured reason: a plain background child dies
        # with the wsl.exe session that ran loadgame - SIGHUP - and now that
        # nodebus HOLDS its pty instead of exiting on EOF, that HUP was the
        # one thing still killing it and deleting the guest's tty.
        NBCMD="setsid env PAD_NODEBUS_DIR='$R/dump' \
python3 '$RIG/nodebus.py' >/dev/null 2>&1 </dev/null &"
        if [ "$(id -u)" = 0 ] && [ -n "${PAD_NB_USER:-}" ]; then
            runuser -u "$PAD_NB_USER" -- bash -c "$NBCMD"
        else
            bash -c "$NBCMD"
        fi
        for _ in $(seq 1 50); do [ -s "$R/dump/nodebus.path" ] && break; sleep 0.1; done
        NEWPTY=$(cat "$R/dump/nodebus.path" 2>/dev/null)
        [ -e "$NEWPTY" ] || { echo "[restore] node bus did not come up"; exit 1; }
        echo "[restore] node bus pty: $NEWPTY (pid $(pgrep -nf 'nodebus\.py'))"
    fi
fi

# --- the video host: stop it BEFORE the ring is rewound ------------------
# The restored guest resumes mid-clip: its stream threads hold their consumed
# counts on their stacks and expect the padvid ring's gen/write_idx to be the
# SAVE-time values. A live session's video host has moved all of that on (and
# its serve threads write the ring), so it is stopped here, the ring is put
# back from the slot's stash below, and after a successful restore a fresh
# host is started with PAD_VID_RESUME=1 - which continues each mid-clip serve
# where the save left it instead of acking it away. Without this the guest's
# takeover check fires on the first frame ("TAKEN OVER: opened at gen N,
# channel is now at gen M"), the thread exits WITHOUT posting EOS, and the
# game holds a black/frozen background forever - David's "text but no
# background video" after the first windowed load.
# Headless runs have no video host and none is started for them.
VID_RESTART=0; VID_USER=""; VID_RING="$R/dump/padvid"
# The gate is "is this a WINDOWED session", not "is a video host running":
# padglhost (the renderer) is the definition of windowed, and a load that
# follows a FAILED video-host restart finds a renderer with no host - gating
# on the host alone would leave that session frozen forever. Measured
# 2026-08-08: exactly that state, padglhost at 59.5 fps with vid 0.0 NEW/s.
if [ "${PAD_VID_RESTART:-1}" = 1 ] \
        && { pgrep -f 'padvidhost\.py' >/dev/null || pgrep -x padglhost >/dev/null; }; then
    # WHOSE host is it? Match the PYTHON process, not whatever else carries
    # the script name on its command line: watch.sh launches helpers through
    # `runuser -u david -- setsid python3 padvidhost.py`, and the resident
    # runuser wrapper is a ROOT process with padvidhost.py in its cmdline -
    # `pgrep | head -1` picked exactly that on the first live load, so the
    # restart came up as root and logged to /root/padvid.log. uid via ps then
    # getent, because ps's user column truncates names longer than 8 chars.
    # No host at all -> the renderer's user is the helper user by definition
    # (watch.sh starts every helper as the same PAD_USER).
    VID_PID=""
    for p in $(pgrep -f 'padvidhost\.py'); do
        case "$(ps -o comm= -p "$p" 2>/dev/null)" in python*) VID_PID=$p; break ;; esac
    done
    [ -z "$VID_PID" ] && VID_PID=$(pgrep -x padglhost | head -1)
    if [ -n "$VID_PID" ]; then
        VID_UID=$(ps -o uid= -p "$VID_PID" 2>/dev/null | tr -d ' ')
        [ -n "$VID_UID" ] && VID_USER=$(getent passwd "$VID_UID" | cut -d: -f1)
        # A CARD run's video host reads clips off the card mount, not the
        # rootfs games tree, and only PAD_VID_ROOT says so (watch.sh sets it
        # at launch). Take it from the dying host itself so the resume restart
        # serves from the same tree - without this a card run resumes against
        # <rootfs>/games/<title>, which is empty, and every serve is
        # "cannot open".
        VID_ROOT_ENV=$(tr '\0' '\n' < "/proc/$VID_PID/environ" 2>/dev/null \
                       | sed -n 's/^PAD_VID_ROOT=//p' | head -1)
    fi
    VID_RESTART=1
    echo "[restore] stopping the video host (user ${VID_USER:-root}) to rewind its ring"
    pkill -9 -f 'padvidhost\.py' 2>/dev/null
    sleep 0.3
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
    card)
        # a=key b=guest mountpoint c=the card's HOST path as savestate saw it.
        # USE THE LIVE MOUNT: cardmount setsids fuse2fs, so in a windowed
        # session the card outlives the guest being swapped, and the recorded
        # path is still exactly the fs the dumped mapping came from. Already
        # VERIFIED by the pre-flight above (card_live, before the guest was
        # killed); re-checked here only because the kill takes real seconds.
        # A cold load (card unmounted, e.g. after a reboot) stays manual:
        # cardmount.sh the image first, then retry.
        src=$c
        if ! card_live "$src"; then
            echo "[restore] the card mount behind $b VANISHED mid-restore ($src)"
            exit 1
        fi
        REST_EXT+=(--external "mnt[$a]:$src")
        # nsclean must NOT strip the card out of the restore's namespace, or
        # criu cannot resolve the external it was just handed (the ladder's
        # rung E kept its card mount for the same reason).
        CARD_KEEP=$(findmnt -no TARGET --target "$src" 2>/dev/null)
        ;;
    tty)
        # a=old fd number  b=tty[key]  c=old slave path. The NEW slave carries
        # the fd (opened on 9 below); the OLD key names the resource in images.
        INHERIT+=(--inherit-fd "fd[9]:tty[$b]")
        TTYFD=$NEWPTY
        ;;
    groups)
        # a = the guest's supplementary gids (comma list, or "none"). Adopted
        # below so criu's restorer can SKIP setgroups - the only way to restore
        # into an unprivileged user namespace. See savestate.sh for the detail.
        GUEST_GROUPS=$a
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
        # THE ONE EXCEPTION IS THE VIDEO RING when its host is being
        # restarted: its "newer" state belongs to the guest that was just
        # killed, while the restored guest's stream threads expect the
        # SAVE-time gen/write_idx. Rewind it to the stash so the resumed
        # host and the restored guest agree (see the video-host block above).
        if [ "$VID_RESTART" = 1 ] && [ "$R$a" = "$VID_RING" ] && [ -f "$DDIR/rings/$b" ]; then
            # IN PLACE, NEVER TRUNCATING. cp -f truncates the file to zero
            # and rewrites all 95 MB - and PADGLHOST HAS THIS RING MMAPPED
            # the whole time (its mapping across the load is the design; the
            # surviving text after a restore is that mapping working).
            # Touching a mapped page past EOF during cp's truncate window is
            # a fatal signal, and it is a race decided by whether a clip is
            # actively on screen: three verification loads won it, David's
            # first real load lost it - padglhost died mid "video upload
            # from ch1 slot0", "Segmentation fault (core dumped)" as the
            # last line of its log, and the renderer's death took the whole
            # session down (2026-08-09 09:23). dd conv=notrunc keeps the
            # inode full-size throughout; a reader can see torn bytes for
            # one tick, which the renderer tolerates, unlike a lost page.
            dd if="$DDIR/rings/$b" of="$R$a" bs=4M conv=notrunc status=none
            echo "[restore] rewound the video ring to the save (in place)"
        elif [ ! -f "$R$a" ] && [ -f "$DDIR/rings/$b" ]; then
            mkdir -p "$(dirname "$R$a")"
            cp -f "$DDIR/rings/$b" "$R$a"
            echo "[restore] put back the missing ring $a"
        fi
        ;;
    esac
done < "$DDIR/restore.env"

# --- the GL world journal: hand the renderer the save's world ------------
# Runs with the guest DEAD (killed above) and BEFORE criu brings the new one
# back, so the replay races nothing: the renderer drains the dead guest's
# leftover ring bytes, goes idle, sees the request, resets its GL world and
# feeds the slot's journal back through its own dispatch - names, draw-guard
# masks and min-filters rebuilt exactly as a live guest would have built
# them. Same-session loads replay too: the journal also rolls back content
# the game overwrote AFTER the save, which the graveyards alone cannot.
# The ring counters are deliberately NOT touched - the restored guest's
# reserve() adopts whatever they say, and a guest checkpointed mid-emit is
# healed by the renderer's rewind resync, same as before the journal.
#
# TWO-PHASE ack. The renderer CLAIMS the request (unlinks the req) before
# the multi-second reset+replay, then writes glreplay.ok when the world is
# rebuilt. Phase 1 waits for the claim; still unclaimed after 15 s means
# the renderer never looked (wedged, or an old build) - clean up and carry
# on, the draw guard keeps the load safe. Phase 2, once claimed, WAITS for
# the finish: proceeding under an in-flight replay would let the world
# reset race the restored guest. A finished replay always removes
# glreplay.bin, so bin-gone-without-ok means it refused the file.
GLREPLAY=0
if [ -s "$DDIR/glstate.bin" ] && pgrep -x padglhost >/dev/null; then
    rm -f "$R/dump/glreplay.ok"
    cp -f "$DDIR/glstate.bin" "$R/dump/glreplay.bin"
    : > "$R/dump/glreplay.req"
    CLAIMED=0
    for _ in $(seq 1 150); do
        [ -e "$R/dump/glreplay.req" ] || { CLAIMED=1; break; }
        sleep 0.1
    done
    if [ "$CLAIMED" = 1 ]; then
        for _ in $(seq 1 300); do
            [ -e "$R/dump/glreplay.ok" ] && break
            [ -e "$R/dump/glreplay.bin" ] || break
            sleep 0.1
        done
    fi
    if [ -e "$R/dump/glreplay.ok" ]; then
        GLREPLAY=1
        rm -f "$R/dump/glreplay.ok"
        echo "[restore] the renderer rebuilt the save's GL world from the journal"
    else
        rm -f "$R/dump/glreplay.req" "$R/dump/glreplay.bin" "$R/dump/glreplay.ok"
        if [ "$CLAIMED" = 1 ]; then
            echo "[restore] NOTE: the renderer took the GL journal but did not"
            echo "[restore] finish replaying it; artwork may be partial until"
            echo "[restore] the game rebuilds scenes"
        else
            echo "[restore] NOTE: the renderer did not take the GL journal (15 s);"
            echo "[restore] artwork will rebuild only as the game rebuilds scenes"
        fi
    fi
elif [ ! -s "$DDIR/glstate.bin" ]; then
    echo "[restore] this slot carries no GL journal (saved by an older build)"
fi

# --- the nsclean the restore runs inside ---------------------------------
# criu's compat mount engine umounts a copy of ITS namespace, and WSL's
# init-namespace mounts refuse a plain umount (EINVAL). So run the restore in a
# throwaway mount namespace stripped to almost nothing - keeping only what a
# restore external resolves through (/dev, /dev/pts for the pty) plus a fresh
# /proc and a re-bind of the rootfs for --root. See criuladder.sh for the full
# story of why each of these is here.
NSCLEAN=$DDIR/nsclean.sh
# The card's mountpoint (when a card external was recorded above) joins the
# keep list, expanded NOW into the generated script - everything else here is
# escaped to expand inside nsclean instead.
KEEPCOND=""
[ -n "${CARD_KEEP:-}" ] && KEEPCOND=" && \$5 != \"$CARD_KEEP\""
cat > "$NSCLEAN" <<EOF
mount --make-rprivate /
awk '\$5 != "/" && \$5 != "/proc" && \$5 != "/dev" && \$5 != "/dev/pts"$KEEPCOND { print \$5 }' \
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

# Adopt the guest's supplementary groups before restoring, so criu's restorer
# finds them already correct and skips the setgroups it is not allowed to make.
# Costs nothing when the guest was root (the lists match anyway).
SETPRIV=()
if [ -n "${GUEST_GROUPS:-}" ]; then
    if [ "$GUEST_GROUPS" = none ]; then
        SETPRIV=(setpriv --clear-groups)
    else
        SETPRIV=(setpriv --groups "$GUEST_GROUPS")
    fi
    echo "[restore] adopting the guest's groups: $GUEST_GROUPS"
fi

do_restore() {
    unshare -m bash "$NSCLEAN" ${SETPRIV[@]+"${SETPRIV[@]}"} \
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
# A slot is restored MANY times (save once, load whenever), and criu opens
# its pidfile O_EXCL - the stale one from the last load fails the whole
# restore ("Can't write pidfile: File exists"), found on the first repeat
# load of one slot: every earlier load had a fresh slot because savegame
# rm -rf's it. The pid it held is dead or being replaced either way.
rm -f "$DDIR/restored.pid"
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
    # Two views, because they miss different things: criu's own error lines,
    # then the raw tail - a BUG/abort/pie message does not say "Error", and a
    # windowed load once failed with NOTHING captured because only the Error
    # grep printed. The log itself stays in the slot ($DDIR/restore.log).
    grep -aE 'Error|BUG|Aborted' "$DDIR/restore.log" | tail -12 | sed 's/^/    /'
    echo "[restore] last lines of $DDIR/restore.log:"
    tail -20 "$DDIR/restore.log" | sed 's/^/    /'
    exit 1
fi
sleep 1
NEWPID=$(cat "$DDIR/restored.pid" 2>/dev/null)
if [ -n "$NEWPID" ] && kill -0 "$NEWPID" 2>/dev/null; then
    echo "[restore] ok - guest restored, pid $NEWPID"
else
    echo "[restore] restore reported ok but the guest is not alive"; exit 1
fi

# What should the picture look like?  With the journal replayed, complete:
# the renderer holds the save's whole GL world whatever session it came
# from.  Without it (old slot, old renderer, or the replay timed out), a
# cross-session load resumes fine - the draw guard keeps the renderer alive
# - but artwork exists only as new scenes are built.  Say which one this
# was; a user who was not told assumes the load half worked.
SLOT_BOOT=$(cat "$DDIR/boot.id" 2>/dev/null)
if [ "$GLREPLAY" = 1 ]; then
    echo "[restore] scene artwork restored from the save's GL journal"
elif [ -z "$SLOT_BOOT" ] || [ -z "$LIVE_BOOT" ] || [ "$SLOT_BOOT" != "$LIVE_BOOT" ]; then
    echo "[restore] NOTE: this save is from an EARLIER session and carries no"
    echo "[restore] replayable GL journal. Game state, audio and video resume;"
    echo "[restore] the scene artwork rebuilds only as the game builds new"
    echo "[restore] scenes, so the picture can be incomplete for a while."
fi

# --- restart the video host in RESUME mode (see the stop block above) -----
if [ "$VID_RESTART" = 1 ]; then
    # The title, for padvidhost's guest->host path mapping: the caller's
    # PAD_GAME (loadgame reads it from slot.meta), else the restored guest's
    # own environment.
    VGAME=${PAD_GAME:-$(tr '\0' '\n' < "/proc/$NEWPID/environ" 2>/dev/null \
                        | sed -n 's/^PAD_GAME=//p' | head -1)}
    VHOME=$(getent passwd "${VID_USER:-root}" | cut -d: -f6)
    VLOG=${VHOME:-/root}/padvid.log
    # NOT watch.sh's `runuser -- setsid cmd &` shape, and the difference is
    # fatal here: runuser WAITS for its child and FORWARDS signals to it, and
    # this script - unlike watch.sh - exits immediately, so when the wsl.exe
    # invocation that ran loadgame ends, the backgrounded runuser takes the
    # session's SIGHUP and passes it straight to the host it just started.
    # Measured 2026-08-08: the restart came up, then died with "Hangup" in
    # padvid.log the moment loadgame returned; the first load's ROOT restart
    # survived only because it had no runuser in front. So the child is
    # backgrounded INSIDE a bash -c: that bash exits at once, runuser reaps
    # it and returns, and the setsid'd host belongs to nobody the teardown
    # can reach.
    VROOT_ARG=""
    [ -n "${VID_ROOT_ENV:-}" ] && VROOT_ARG="PAD_VID_ROOT='$VID_ROOT_ENV' "
    VCMD="setsid env PAD_ROOT='$R' PAD_GAME='$VGAME' ${VROOT_ARG}PAD_VID_RESUME=1 \
python3 '$RIG/padvidhost.py' '$VID_RING' >> '$VLOG' 2>&1 </dev/null &"
    if [ -n "$VID_USER" ] && [ "$VID_USER" != root ]; then
        runuser -u "$VID_USER" -- bash -c "$VCMD"
    else
        bash -c "$VCMD"
    fi
    echo "[restore] video host restarted in resume mode (game '$VGAME', log $VLOG)"
fi
