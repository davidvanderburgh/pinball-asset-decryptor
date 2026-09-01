#!/bin/bash
# Load a Spike 1 save-state slot into the running rig. (item 87)
#
#   wsl -u root -e bash s1restorestate.sh [slot | <cache label>/<slot>]
#
# The rig must be UP (start.sh, with S1_PIVOT=1) and on the SAME TITLE the
# slot was saved from - the CUSE shims, node-bus responder and ball keeper are
# not part of the checkpoint and the restored guest reattaches to the live
# ones.  The current guest is replaced: the restart loop is PARKED on the
# holdoff flag (never pkill emu_root.sh - its EXIT trap kills the CUSE shims
# the restored guest must reopen), every live guest is killed, and criu
# restores the slot in its place.  Removing the holdoff flag later resumes
# the boot loop (a fresh boot) if the restored guest ever ends.
#
# Rebuild-proofing: the slot carries the two disk-mapped binaries (qemu copy,
# game ELF).  When the live tree's sha1 differs, the slot's own copy is
# REINSTALLED first - criu validates mapped files byte-for-byte and a rebuilt
# qemu or a re-patched game ELF would otherwise kill the restore halfway.
set -u
REF=${1:-quicksave}
HERE="$(cd "$(dirname "$0")" && pwd)"
S1_WORK=${S1_WORK:-/home/david/s1emu}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
PLUGDIR=${S1CRIU_PLUGIN_DIR:-$S1_WORK/criuplug}
[ "$(id -u)" = 0 ] || { echo "s1restore: needs root. Use: wsl -u root -e bash $0 ..."; exit 2; }
[ -x "$CRIU" ] || { echo "[s1restore] no criu at $CRIU"; exit 2; }

GAMEDIR=$(readlink -f "$S1_WORK/game" 2>/dev/null)
CLABEL=$(basename "$(dirname "$GAMEDIR")" 2>/dev/null)
case "$REF" in
*/*) DDIR="$S1_WORK/saves/$REF" ;;
*)   DDIR="$S1_WORK/saves/$CLABEL/$REF" ;;
esac
[ -d "$DDIR" ] || { echo "[s1restore] no slot at $DDIR"; exit 1; }
SGAME=$(sed -n 's/^game //p' "$DDIR/restore.env" | head -1)
if [ -n "$SGAME" ] && [ "$SGAME" != "$CLABEL" ]; then
    echo "[s1restore] slot is for $SGAME but the rig is running $CLABEL -"
    echo "[s1restore] start the emulator on that title first"
    exit 1
fi
R=$(readlink -f "$S1_WORK/rootfs")
NEWPTY=$(cat "$S1_WORK/ttyS4.slave" 2>/dev/null)
ls /dev/s1i2c0 >/dev/null 2>&1 || { echo "[s1restore] the rig is not up (no CUSE devices) - start the emulator first"; exit 1; }

# --- park the restart loop, then clear every live guest --------------------
touch "$S1_WORK/holdoff"
sleep 1.2
# OUR guests only (s1own.sh): comm=game is also what the Spike 2 rig calls
# its guest, and "replace the live guest" must not reach into its run.
for OLD in $(S1_WORK="$S1_WORK" bash "$HERE/s1own.sh" game 2>/dev/null); do
    kill -9 "$OLD" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do [ -d "/proc/$OLD" ] || break; sleep 0.2; done
    echo "[s1restore] live guest $OLD replaced"
done

# --- reinstall the slot's binaries when the live tree differs --------------
# bin lines record HOST-side canonical paths (the bind sources).
while read -r kind sum dest name; do
    [ "$kind" = bin ] || continue
    case "$dest" in /*) ;; *) continue ;; esac
    cur=$(sha1sum "$dest" 2>/dev/null | cut -d' ' -f1)
    if [ "$cur" != "$sum" ] && [ -f "$DDIR/bin/$name" ]; then
        cp -f "$DDIR/bin/$name" "$dest" \
            && echo "[s1restore] reinstalled the slot's $name (the live one was rebuilt)"
    fi
done < "$DDIR/restore.env"

# --- externals -------------------------------------------------------------
REST_EXT=(); INHERIT=(); TTYFD=""
while read -r kind a b c; do
    case "$kind" in
    mnt)
        src=$c
        [ "$src" = '@PTY@' ] && src=$NEWPTY
        [ -n "$src" ] || { echo "[s1restore] empty source for $b"; exit 1; }
        REST_EXT+=(--external "mnt[$a]:$src")
        ;;
    tty)
        INHERIT+=(--inherit-fd "fd[9]:tty[$b]")
        TTYFD=$NEWPTY
        ;;
    esac
done < "$DDIR/restore.env"

# --- the throwaway namespace the restore runs inside -----------------------
# WSL's init-namespace mounts refuse a plain umount, so strip a copy of the
# namespace down to /, /proc, /dev, /dev/pts + a rootfs re-bind for --root.
NSCLEAN=$DDIR/nsclean.sh
cat > "$NSCLEAN" <<EOF
mount --make-rprivate /
awk '\$5 != "/" && \$5 != "/proc" && \$5 != "/dev" && \$5 != "/dev/pts" { print \$5 }' \
    /proc/self/mountinfo | sort -r | while IFS= read -r mp; do
    mp=\$(printf '%b' "\$mp")
    umount -l "\$mp" 2>/dev/null
done
umount -l /proc 2>/dev/null
mount -t proc proc /proc
mount --bind "$R" "$R"
exec "\$@"
EOF

[ -n "$TTYFD" ] && { exec 9<>"$TTYFD" || { echo "[s1restore] could not open the pty $TTYFD"; exit 1; }; }

do_restore() {
    unshare -m bash "$NSCLEAN" \
        "$CRIU" restore -D "$DDIR" -v4 -o restore.log -d \
            --pidfile "$DDIR/restored.pid" \
            --root "$R" -L "$PLUGDIR" \
            ${REST_EXT[@]+"${REST_EXT[@]}"} ${INHERIT[@]+"${INHERIT[@]}"}
}

# growing-output retry: a quicksaved guest kept appending to its logs after
# the dump, and a fresh boot rewrote them; truncate exactly the file criu
# names to exactly the size it wants, bounded attempts.
rm -f "$DDIR/restored.pid"
for attempt in 1 2 3 4 5 6 7 8; do
    if do_restore; then
        NEWPID=$(cat "$DDIR/restored.pid" 2>/dev/null)
        # hand the keeper the save-time ball picture (see s1savestate.sh)
        if [ -f "$DDIR/s1ball.state" ]; then
            printf 'state %s\n' "$(tr -d '\n' < "$DDIR/s1ball.state")" \
                >> "$S1_WORK/s1ball.cmd" 2>/dev/null || true
        fi
        echo "[s1restore] ok - guest pid ${NEWPID:-?} resumed from $SGAME/${DDIR##*/}"
        exit 0
    fi
    bad=$(grep -a 'has bad size' "$DDIR/restore.log" | tail -1)
    if [ -n "$bad" ]; then
        f=$(sed -n 's/.*File \(.*\) has bad size.*/\1/p' <<<"$bad")
        want=$(sed -n 's/.*expect \([0-9]*\).*/\1/p' <<<"$bad")
        if [ -n "$f" ] && [ -n "$want" ] && [ -e "$R/$f" ]; then
            truncate -s "$want" "$R/$f"
            rm -f "$DDIR/restored.pid"
            continue
        fi
    fi
    echo "[s1restore] FAILED:"
    grep -aE 'Error' "$DDIR/restore.log" | tail -10 | sed 's/^/    /'
    echo "[s1restore] the boot loop is parked - rm $S1_WORK/holdoff to boot fresh"
    exit 1
done
echo "[s1restore] gave up after size retries"
exit 1
