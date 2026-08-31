#!/bin/bash
# item 87 PROTOTYPE: restore a pivoted Spike 1 guest from an s1savetest.sh slot.
#   wsl -u root -e bash s1restoretest.sh <dumpdir>
# Same-session quickload shape: the rig (CUSE shims, nodebus, s1ball) is still
# up; the restart loop and the live guest are killed and the checkpoint takes
# the guest's place.
set -u
DDIR=${1:?usage: s1restoretest.sh <dumpdir>}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
PLUGDIR=${S1CRIU_PLUGIN_DIR:-/home/david/s1emu/criuplug}
S1_WORK=${S1_WORK:-/home/david/s1emu}
HERE="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" = 0 ] || { echo "needs root"; exit 2; }
[ -d "$DDIR" ] || { echo "no slot at $DDIR"; exit 1; }

R="$S1_WORK/rootfs"; R=$(readlink -f "$R")
G=$(readlink -f "$S1_WORK/game")
GAME_NAME="$(tr -d '[:space:]' < "$G/.game_name" 2>/dev/null)"; : "${GAME_NAME:=GAME}"
NEWPTY=$(cat "$S1_WORK/ttyS4.slave" 2>/dev/null)
echo "[r] rootfs $R  game $G ($GAME_NAME)  pty ${NEWPTY:-none}"

# --- park the restart loop (holdoff), then kill the live guest -------------
# NEVER pkill emu_root.sh here: its EXIT trap kills the CUSE shims, and the
# restored guest must reopen those very devices.  The holdoff flag parks the
# loop with everything else alive.
touch "$S1_WORK/holdoff"
sleep 1.2
ls /dev/s1i2c0 >/dev/null 2>&1 || { echo "[r] CUSE devices are gone - is the rig up?"; exit 1; }
# kill EVERY live guest, not the busiest one — a survivor from an earlier
# restore (detached from emu_root's tree) plus the fresh boot makes two.
for OLD in $(ps -eo pid,comm | awk '$2=="game"{print $1}'); do
    kill -9 "$OLD" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do [ -d "/proc/$OLD" ] || break; sleep 0.2; done
    echo "[r] live guest $OLD killed"
done

# --- rebuild the restore externals from restore.env ------------------------
# Source per mountpoint is deterministic on this rig (emu_root.sh's own table).
src_for() {
    case "$1" in
    /proc/cpuinfo) echo "$R/.padqemu/cpuinfo" ;;
    /games/*)      echo "$G" ;;
    /dev/dmd)      echo /dev/s1dmd ;;
    /dev/i2s)      echo /dev/s1i2s ;;
    /dev/amp)      echo /dev/s1amp ;;
    /dev/adc)      echo /dev/s1adc ;;
    /dev/gpio)     echo /dev/s1gpio ;;
    /dev/spi0)     echo /dev/s1spi0 ;;
    /dev/spi1)     echo /dev/s1spi1 ;;
    /dev/i2c-0)    echo /dev/s1i2c0 ;;
    /dev/ttyS4)    echo "@PTY@" ;;
    /dev/null|/dev/zero|/dev/full|/dev/random|/dev/urandom|/dev/tty) echo "$1" ;;
    /dev/*)        echo /dev/null ;;      # the null stand-ins
    *)             echo "" ;;
    esac
}
REST_EXT=(); INHERIT=(); TTYFD=""
while read -r kind a b c; do
    case "$kind" in
    mnt)
        src=$(src_for "$b")
        [ "$src" = "@PTY@" ] && src=$NEWPTY
        if [ -z "$src" ]; then echo "[r] no source mapping for $b"; exit 1; fi
        REST_EXT+=(--external "mnt[$a]:$src")
        ;;
    tty)
        INHERIT+=(--inherit-fd "fd[9]:tty[$b]")
        TTYFD=$NEWPTY
        ;;
    esac
done < "$DDIR/restore.env"
echo "[r] ${#REST_EXT[@]} mnt args, ${#INHERIT[@]} inherit args"

# --- nsclean: the throwaway namespace the restore runs inside --------------
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

[ -n "$TTYFD" ] && { exec 9<>"$TTYFD" || { echo "[r] pty open failed"; exit 1; }; }
rm -f "$DDIR/restored.pid"

do_restore() {
    unshare -m bash "$NSCLEAN" \
        "$CRIU" restore -D "$DDIR" -v4 -o restore.log -d \
            --pidfile "$DDIR/restored.pid" \
            --root "$R" -L "$PLUGDIR" \
            ${REST_EXT[@]+"${REST_EXT[@]}"} ${INHERIT[@]+"${INHERIT[@]}"}
}

# growing-output retry: truncate exactly the files criu names, bounded.
for attempt in 1 2 3 4 5 6 7 8; do
    do_restore && { echo "[r] RESTORE OK (attempt $attempt) pid $(cat "$DDIR/restored.pid" 2>/dev/null)"; exit 0; }
    bad=$(grep -a 'has bad size' "$DDIR/restore.log" | tail -1)
    if [ -n "$bad" ]; then
        f=$(sed -n 's/.*File \(.*\) has bad size.*/\1/p' <<<"$bad")
        want=$(sed -n 's/.*expect \([0-9]*\).*/\1/p' <<<"$bad")
        if [ -n "$f" ] && [ -n "$want" ] && [ -f "$R/$f" ]; then
            echo "[r] truncating $f to $want and retrying"
            truncate -s "$want" "$R/$f"
            rm -f "$DDIR/restored.pid"
            continue
        fi
    fi
    echo "[r] RESTORE FAILED - errors:"
    grep -aE 'Error' "$DDIR/restore.log" | tail -15 | sed 's/^/    /'
    exit 1
done
echo "[r] gave up after truncate retries"
exit 1
