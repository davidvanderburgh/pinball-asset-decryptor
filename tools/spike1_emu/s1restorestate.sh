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
#
# Packed slots (PAD-1601, see s1savestate.sh): the checkpoint is unpacked
# into a staging dir under saves/ BEFORE the live guest is touched (a slot
# that will not unpack leaves the game playing), restored from there, and the
# staging dir goes once the guest is back.  The binaries come from the slot's
# own bin/ when it has one (older raw slots), else from the title's shared
# .bin/<sha1>.zst, checked against the sha1 before anything is replaced.
# Raw slots saved before packing restore in place, as they always did.
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
[ -f "$DDIR/restore.env" ] || { echo "[s1restore] no slot at $DDIR"; exit 1; }
SGAME=$(sed -n 's/^game //p' "$DDIR/restore.env" | head -1)
if [ -n "$SGAME" ] && [ "$SGAME" != "$CLABEL" ]; then
    echo "[s1restore] slot is for $SGAME but the rig is running $CLABEL -"
    echo "[s1restore] start the emulator on that title first"
    exit 1
fi
R=$(readlink -f "$S1_WORK/rootfs")
NEWPTY=$(cat "$S1_WORK/ttyS4.slave" 2>/dev/null)
ls /dev/s1i2c0 >/dev/null 2>&1 || { echo "[s1restore] the rig is not up (no CUSE devices) - start the emulator first"; exit 1; }

# --- a packed slot: unpack it first, while the live game still plays -------
# IDIR is where criu reads the checkpoint from: the slot itself when raw.
IDIR=$DDIR; LOADDIR=""
if [ -f "$DDIR/slot.tar.zst" ]; then
    command -v zstd >/dev/null 2>&1 || { echo "[s1restore] this slot is packed and there is no zstd here to unpack it"; exit 1; }
    LOADDIR="$S1_WORK/saves/.load.$$"
    trap 'rm -rf "$LOADDIR"' EXIT
    rm -rf "$LOADDIR"; mkdir -p "$LOADDIR"
    if ! zstd -d -q -c "$DDIR/slot.tar.zst" | tar -C "$LOADDIR" -xf -; then
        echo "[s1restore] the slot would not unpack (damaged?) - the game keeps playing"
        exit 1
    fi
    IDIR=$LOADDIR
fi
STORE="$(dirname "$DDIR")/.bin"

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
# bin lines record HOST-side canonical paths (the bind sources).  The copy
# is the slot's own bin/<name> (raw slots) or the title's shared store.
while read -r kind sum dest name; do
    [ "$kind" = bin ] || continue
    case "$dest" in /*) ;; *) continue ;; esac
    cur=$(sha1sum "$dest" 2>/dev/null | cut -d' ' -f1)
    [ "$cur" = "$sum" ] && continue
    if [ -f "$IDIR/bin/$name" ]; then
        cp -f "$IDIR/bin/$name" "$dest" \
            && echo "[s1restore] reinstalled the slot's $name (the live one was rebuilt)"
    elif [ -s "$STORE/$sum.zst" ]; then
        tmp="$dest.s1restore.$$"
        if zstd -d -q -f "$STORE/$sum.zst" -o "$tmp" \
                && [ "$(sha1sum "$tmp" | cut -d' ' -f1)" = "$sum" ] \
                && chmod 755 "$tmp" && cp -f "$tmp" "$dest"; then
            echo "[s1restore] reinstalled the slot's $name (the live one was rebuilt)"
        else
            echo "[s1restore] WARNING: the stored $name for this slot is damaged - the restore may fail"
        fi
        rm -f "$tmp"
    else
        echo "[s1restore] WARNING: the live $name was rebuilt and this slot's copy is gone - the restore may fail"
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
NSCLEAN=$IDIR/nsclean.sh
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
        "$CRIU" restore -D "$IDIR" -v4 -o restore.log -d \
            --pidfile "$IDIR/restored.pid" \
            --root "$R" -L "$PLUGDIR" \
            ${REST_EXT[@]+"${REST_EXT[@]}"} ${INHERIT[@]+"${INHERIT[@]}"}
}

# growing-output retry: a quicksaved guest kept appending to its logs after
# the dump, and a fresh boot rewrote them; truncate exactly the file criu
# names to exactly the size it wants, bounded attempts.
rm -f "$IDIR/restored.pid"
for attempt in 1 2 3 4 5 6 7 8; do
    if do_restore; then
        NEWPID=$(cat "$IDIR/restored.pid" 2>/dev/null)
        # hand the keeper the save-time ball picture (see s1savestate.sh)
        if [ -f "$IDIR/s1ball.state" ]; then
            printf 'state %s\n' "$(tr -d '\n' < "$IDIR/s1ball.state")" \
                >> "$S1_WORK/s1ball.cmd" 2>/dev/null || true
        fi
        echo "[s1restore] ok - guest pid ${NEWPID:-?} resumed from $SGAME/${DDIR##*/}"
        exit 0
    fi
    bad=$(grep -a 'has bad size' "$IDIR/restore.log" | tail -1)
    if [ -n "$bad" ]; then
        f=$(sed -n 's/.*File \(.*\) has bad size.*/\1/p' <<<"$bad")
        want=$(sed -n 's/.*expect \([0-9]*\).*/\1/p' <<<"$bad")
        if [ -n "$f" ] && [ -n "$want" ] && [ -e "$R/$f" ]; then
            truncate -s "$want" "$R/$f"
            rm -f "$IDIR/restored.pid"
            continue
        fi
    fi
    echo "[s1restore] FAILED:"
    grep -aE 'Error' "$IDIR/restore.log" | tail -10 | sed 's/^/    /'
    # the unpacked copy goes; criu's log (the diagnosis) is kept
    cp -f "$IDIR/restore.log" "$S1_WORK/s1restore.failed.log" 2>/dev/null \
        && echo "[s1restore] criu's full log: $S1_WORK/s1restore.failed.log"
    echo "[s1restore] the boot loop is parked - rm $S1_WORK/holdoff to boot fresh"
    exit 1
done
echo "[s1restore] gave up after size retries"
exit 1
