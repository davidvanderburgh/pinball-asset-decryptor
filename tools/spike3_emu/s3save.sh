#!/bin/bash
# s3save.sh - checkpoint a running Spike 3 game into a save-state directory,
# and keep it playing (PAD-1147: save states on Spike 3, Spike 2's parity).
#
#   wsl -u root -e bash s3save.sh SLOT DIR
#
# The game must be a checkpointable run (s3run.sh with PAD_S3_PIVOT=1: pid 1 of
# its namespace, its root pivoted). Spike 2's savestate.sh discovers the guest's
# mounts from the host's view of them; a Spike 3 run builds every mount inside
# its private namespace, so here the layout is the one s3run.sh made, named:
#
#   /games /data /connectivity   overlays: lower = the card store (never
#                                written), upper = the slot's <name>.up
#   /                            overlay, the same way (criu's --root at load)
#   /dev/null zero urandom random tty   the host's nodes, bound in
#   /dev/ttyAMA5                 the node bus: a pty of s3bridge.py's
#   /run/<name>                  files of the slot directory, bound in
#   /proc /sys /tmp /run /dev/shm /dev/pts   the namespace's own (criu's)
#
# What lands in DIR:
#   *.img, dump.log      criu's checkpoint of the game (frozen, then thawed)
#   up/<layer>/          the four overlay uppers at that instant - the game's
#                        settings, NVRAM and logs, so a load finds the disk the
#                        way the game's memory remembers it
#   glstate.bin          the renderer's GL world (padglhost's journal), so a
#                        load into a fresh renderer has every texture/shader
#   bridge.state         s3bridge.py's board model (node claims, coil rules)
#   restore.env          what s3load needs: the externals and the card
#   slot.meta            card=, title=, saved=, label= (written by the caller)
#
# The game is FROZEN for the dump plus the copies (a few seconds) so that every
# piece describes the same instant; then SIGCONT.
set -u
S=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SLOT=${1:?usage: s3save.sh SLOT DIR}
DDIR=${2:?usage: s3save.sh SLOT DIR}
SD=/var/tmp/pad-s3/slot$SLOT
. "$S/../spike2_emu/padpath.sh" 2>/dev/null
CRIU=${CRIU:-$(pad_criu 2>/dev/null)}

[ "$(id -u)" = 0 ] || { echo "[s3save] needs root: wsl -u root -e bash $0 ..."; exit 2; }
[ -x "${CRIU:-}" ] || {
    echo "[s3save] this machine has no criu; Set up emulator... builds it (getcriu.sh)"
    exit 2; }

# s3_game_pid SLOT: the slot's game - comm "game" whose root overlay's upper
# layer is this slot's. Empty when none runs.
s3_game_pid() {
    local p
    for p in $(pgrep -x game); do
        grep -q " / / .*upperdir=/var/tmp/pad-s3/slot$1/root.up," "/proc/$p/mountinfo" 2>/dev/null \
            && { echo "$p"; return 0; }
    done
    return 1
}
PID=$(s3_game_pid "$SLOT")
[ -n "$PID" ] || { echo "[s3save] no Spike 3 game is running in slot $SLOT"; exit 1; }
if [ "$(readlink "/proc/$PID/root")" != / ]; then
    echo "[s3save] this run cannot be saved: it was started without save states"
    echo "[s3save] (an ordinary chroot run). Start it again to use them."
    exit 1
fi
echo "[s3save] slot $SLOT, game pid $PID"
rm -rf "$DDIR"; mkdir -p "$DDIR"
: > "$DDIR/restore.env"

# --- externals: every mount whose backing is outside the checkpoint ---------
EXT=()
while read -r _id _par mm froot mp _rest; do
    fstype=$(awk '{for(i=7;i<=NF;i++) if($i=="-"){print $(i+1); exit}}' <<<"$_id $_par $mm $froot $mp $_rest")
    key="ext_$(echo "${mp#/}" | tr '/.' '__')"
    case "$mp" in
    /) continue ;;                                   # the root: --root at load
    /games|/data|/connectivity)
        echo "ovl $key $mp ${mp#/}" >> "$DDIR/restore.env" ;;
    /dev/ttyAMA5)
        echo "pty $key $mp" >> "$DDIR/restore.env" ;;
    /dev/null|/dev/zero|/dev/urandom|/dev/random|/dev/tty)
        echo "dev $key $mp $mp" >> "$DDIR/restore.env" ;;
    /run/*)
        case "$fstype" in tmpfs) continue ;; esac
        # a slot file bound in: at load, the same name in the new run's slot
        echo "file $key $mp ${froot##*/}" >> "$DDIR/restore.env" ;;
    *) continue ;;                                   # proc, tmpfs, devpts: criu's
    esac
    EXT+=(--external "mnt[$mp]:$key")
done < "/proc/$PID/mountinfo"

# --- the node-bus pty the game holds (criu's tty[] key: rdev:dev, hex) ------
for fd in /proc/$PID/fd/*; do
    t=$(readlink "$fd" 2>/dev/null) || continue
    case "$t" in
    /dev/ttyAMA5)
        k=$(python3 -c 'import os,sys;s=os.stat(sys.argv[1]);print("%x:%x"%(s.st_rdev,s.st_dev))' "$fd") || continue
        EXT+=(--external "tty[$k]")
        echo "tty ${fd##*/} $k" >> "$DDIR/restore.env" ;;
    esac
done
# THE NETWORK NAMESPACE (loopback only, PAD-1090) is not criu's to dump: a
# tree with a namespace of its own is network-LOCKED with iptables-restore
# and dumped with iptables-save, packages a user's WSL need not have, for a
# namespace that holds nothing. So criu runs INSIDE the game's namespace
# (nsenter --net): it is then criu's own, neither locked nor dumped, and the
# load restores the game into a fresh loopback-only namespace the same way.
TREE=$(awk '$5 == "/games" {print}' "/proc/$PID/mountinfo" | tr ',' '\n' | sed -n 's/^lowerdir=//p' | head -1)
echo "tree ${TREE%/games}" >> "$DDIR/restore.env"
echo "[s3save] externals: ${EXT[*]}"

# --- dump, LEFT FROZEN -------------------------------------------------------
T0=$(date +%s%3N)
nsenter --net="/proc/$PID/ns/net" -- "$CRIU" dump -t "$PID" -D "$DDIR" -v4 -o dump.log --leave-stopped "${EXT[@]}"
RC=$?
thaw() {
    kill -CONT "$PID" 2>/dev/null
    for _ in 1 2 3 4 5; do
        [ "$(awk '{print $3}' "/proc/$PID/stat" 2>/dev/null)" != T ] && return 0
        kill -CONT "$PID" 2>/dev/null; sleep 0.2
    done
}
if [ "$RC" != 0 ] || grep -aq 'Dumping FAILED' "$DDIR/dump.log"; then
    grep -a 'Error' "$DDIR/dump.log" | tail -8 | sed 's/^/    /'
    why=$(grep -a 'Error' "$DDIR/dump.log" | grep -av 'Dumping FAILED' | head -1 \
          | sed 's/^([^)]*) *//; s/^Error ([^)]*): *//')
    thaw
    echo "[s3save] could not save: ${why:-criu stopped without saying why (exit $RC)}"
    exit 1
fi

# --- while frozen: the disk, the renderer, the boards ----------------------
mkdir -p "$DDIR/up"
for l in root games data connectivity; do
    [ -d "$SD/$l.up" ] && cp -a "$SD/$l.up" "$DDIR/up/$l"
done
rm -f "$SD/glstate.bin"
if [ -e "$SD/padgl.ring" ] && pgrep -f "padglhost $SD/padgl.ring" >/dev/null; then
    : > "$SD/glstate.req"
    for _ in $(seq 1 100); do [ -e "$SD/glstate.req" ] || break; sleep 0.1; done
    if [ -s "$SD/glstate.bin" ]; then
        mv -f "$SD/glstate.bin" "$DDIR/glstate.bin"
    else
        rm -f "$SD/glstate.req"
        echo "[s3save] NOTE: the renderer gave no GL journal; a load rebuilds pictures as the game redraws"
    fi
fi
thaw
echo "[s3save] frozen $(( $(date +%s%3N) - T0 )) ms; $(du -sh "$DDIR" | cut -f1) raw"
echo "[s3save] ok"
