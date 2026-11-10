#!/bin/bash
# s3run.sh - boot a Stern Spike 3 card's own game program under qemu-aarch64,
# chroot'd into the card's own rootfs, straight out of the Spike 3 card store
# (s3store.py). PAD-1090, stage 1: the bring-up harness.
#
#   wsl -u root -e bash s3run.sh CARD.raw [--slot N] [--secs S] [--strace]
#
# THE STORE IS NEVER WRITTEN. The card's tree is the overlay's LOWER layer and
# each rig slot has its own upper layer (/var/tmp/pad-s3/slot<N>), so the game's
# settings, NVRAM and logs land in the slot. --fresh empties the slot first: the
# next boot is then the card's own first boot again.
#
#   /                overlay  lower = <tree>/rootfs        (Buildroot, aarch64)
#   /games           overlay  lower = <tree>/games         (the title; ro on a
#                                                           machine, the game
#                                                           writes nothing here)
#   /data            overlay  lower = <tree>/data          (settings: writable)
#   /connectivity    overlay  lower = <tree>/connectivity  (cache, dump, update)
#   /proc /dev/pts   real, in a private mount + pid namespace
#   /tmp /run /dev/shm /sys   tmpfs
#
# On the machine an initramfs unlocks the LUKS volumes and mounts them there;
# /etc/init.d/S95game then runs /games/game in game_monitor's restart loop. Here
# the game is exec'd directly (binfmt's qemu-aarch64 with the F flag, so nothing
# from the host is copied into the chroot), its exit code reported the way
# game_monitor reads it.
set -u
S=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CARD=""; SLOT=1; SECS=60; STRACE=0; FRESH=0; BRIDGE=0; BUS=0; PROG=/games/game; ARGS=()
B=${PAD_S3_BUILD:-/home/david/.pad-s3/build}
while [ $# -gt 0 ]; do
    case "$1" in
        --slot) SLOT=$2; shift ;;
        --secs) SECS=$2; shift ;;
        --strace) STRACE=1 ;;
        --fresh) FRESH=1 ;;
        --bridge) BRIDGE=1 ;;
        --bus) BUS=1 ;;
        --prog) PROG=$2; shift ;;
        --) shift; ARGS=("$@"); break ;;
        *) CARD=$1 ;;
    esac
    shift
done
[ -n "$CARD" ] || { echo "usage: s3run.sh CARD.raw [--slot N] [--secs S] [--strace] [--fresh] [--bridge] [--bus]" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "[s3run] needs root (overlay mounts): wsl -u root -e bash s3run.sh ..." >&2; exit 2; }

TREE=$(python3 "$S/s3store.py" path "$CARD") || {
    echo "[s3run] the card is not in the Spike 3 store yet: s3store.py build $CARD" >&2; exit 1; }
SD=/var/tmp/pad-s3/slot$SLOT
LOG=$SD/run.log
[ "$FRESH" = 1 ] && rm -rf "$SD"
mkdir -p "$SD"
echo "[s3run] card tree $TREE, slot $SLOT ($SD)"

# --bridge: the display (stage 2). s3build.sh's three guest libraries go into
# this slot's overlay - libGLESv2/libEGL over the card's Mesa ones, s3kms.so
# preloaded - and its own padglhost renders the ring headless (surfaceless EGL
# on the GPU) and dumps every 30th frame to $SD/frames as PNG.
HOSTPID=""
if [ "$BRIDGE" = 1 ]; then
    for f in libGLESv2.so.2 libEGL.so.1 s3kms.so padglhost; do
        [ -e "$B/$f" ] || { echo "[s3run] --bridge needs $B/$f: bash s3build.sh" >&2; exit 1; }
    done
    rm -rf "$SD/frames" "$SD/padgl.ring"; mkdir -p "$SD/frames"
    env -u DISPLAY -u WAYLAND_DISPLAY EGL_PLATFORM=surfaceless GALLIUM_DRIVER=${GALLIUM_DRIVER:-d3d12} \
        PAD_GL_W=${PAD_S3_W:-1920} PAD_GL_H=${PAD_S3_H:-1080} PAD_GL_DUMP="$SD/frames" \
        PAD_GL_FRAME_EVERY=${PAD_GL_FRAME_EVERY:-30} PAD_GL_MAX_FRAMES=${PAD_GL_MAX_FRAMES:-40} \
        setsid "$B/padglhost" "$SD/padgl.ring" > "$SD/padglhost.log" 2>&1 &
    HOSTPID=$!
    for i in $(seq 1 100); do [ -s "$SD/padgl.ring" ] && break; sleep 0.1; done
    [ -s "$SD/padgl.ring" ] || { echo "[s3run] padglhost made no ring:"; tail -5 "$SD/padglhost.log"; kill -9 $HOSTPID; exit 1; }
    echo "[s3run] renderer up: $(grep -a -m2 -E "GL_RENDERER|renderer|GL " "$SD/padglhost.log" | tr '\n' ' ')"
fi

# --bus: the node bus side of the CPU board (stage 4). Two host stand-ins, one
# per slot, bound over the chroot's device nodes:
#   /dev/spidev4.0  s3spid (CUSE char device; the game's spidev ioctls reach it
#                   through the qemu-spi-ioctls.patch translation) -> $SD/spi.log
#                   Its inputs (the cabinet switches) read 0xff at rest,
#                   PAD_S3_SPI_IDLE to change: at 0x00 every button reads HELD and
#                   the game boots straight into its service path (Tech Alerts).
#   /dev/ttyAMA5    s3bridge.py (a pty: the RP2040 netbridge board, answering
#                   its host UART as its own firmware does) -> $SD/bridge.log
# Needs cuse.ko loaded on the host (built from the same kernel tree as
# i2c-stub; see docs/plans/spike3_emulation.md stage 4).
BUSPIDS=""
DEVBINDS=""
if [ "$BUS" = 1 ]; then
    [ -e /dev/cuse ] || { echo "[s3run] --bus needs /dev/cuse (insmod cuse.ko)" >&2; exit 1; }
    [ -x "$B/s3spid" ] || { echo "[s3run] --bus needs $B/s3spid: bash s3build.sh" >&2; exit 1; }
    SPIDEV=pad-s3spi-slot$SLOT
    rm -f "$SD/spi.log" "$SD/bridge.log" "$SD/bridge.path"
    "$B/s3spid" -f --name=$SPIDEV --log="$SD/spi.log" --idle=${PAD_S3_SPI_IDLE:-0xff} > "$SD/s3spid.out" 2>&1 &
    BUSPIDS="$!"
    python3 "$S/s3bridge.py" "$SD" "$TREE/games/spike3/netbridge/netbridge.elf" "$TREE/games/game" > "$SD/s3bridge.out" 2>&1 &
    BUSPIDS="$BUSPIDS $!"
    for i in $(seq 1 50); do
        [ -e /dev/$SPIDEV ] && [ -s "$SD/bridge.path" ] && break; sleep 0.1
    done
    [ -e /dev/$SPIDEV ] || { echo "[s3run] s3spid made no /dev/$SPIDEV:"; tail -3 "$SD/s3spid.out"; kill $BUSPIDS; exit 1; }
    [ -s "$SD/bridge.path" ] || { echo "[s3run] s3bridge made no pty:"; tail -3 "$SD/s3bridge.out"; kill $BUSPIDS; exit 1; }
    DEVBINDS="spidev4.0=/dev/$SPIDEV ttyAMA5=$(cat "$SD/bridge.path")"
    echo "[s3run] node bus up: $DEVBINDS"
fi
export DEVBINDS

# NO NETWORK. The game runs in its own network namespace (-n) holding only a
# loopback interface: a Spike 3 title carries Stern's connectivity code
# (Insider Connected, conagent), and nothing it tries may leave this PC -
# without -n it shared WSL's own network and could have reached the internet
# (David, PAD-1090). Every attempt fails here with no route, and the --strace
# log shows what was attempted.
unshare -m -p -n -f --mount-proc=/proc bash -s "$TREE" "$SD" "$SECS" "$STRACE" "$BRIDGE" "$B" "$PROG" "${ARGS[@]}" <<'INNER'
set -u
TREE=$1; SD=$2; SECS=$3; STRACE=$4; BRIDGE=$5; B=$6; PROG=$7; shift 7
R=$SD/root
mount --make-rprivate /
ip link set lo up 2>/dev/null   # loopback only: no route off the PC
ov() {  # lower mountpoint name
    mkdir -p "$SD/$3.up" "$SD/$3.wk" "$2"
    mount -t overlay overlay -o "lowerdir=$1,upperdir=$SD/$3.up,workdir=$SD/$3.wk" "$2"
}
mkdir -p "$R"
ov "$TREE/rootfs" "$R" root || { echo "[s3run] overlay on the rootfs failed" >&2; exit 1; }
for d in games data connectivity; do
    [ -d "$TREE/$d" ] || continue
    mkdir -p "$R/$d" 2>/dev/null
    ov "$TREE/$d" "$R/$d" "$d" || { echo "[s3run] overlay on /$d failed" >&2; exit 1; }
done
mount -t proc proc "$R/proc"
mount -t tmpfs tmpfs "$R/sys"
for d in tmp run dev/shm; do mkdir -p "$R/$d"; mount -t tmpfs tmpfs "$R/$d"; done
mkdir -p "$R/dev/pts"
mount -t devpts devpts "$R/dev/pts" -o newinstance,ptmxmode=0666
for f in null zero urandom random tty; do
    [ -e "$R/dev/$f" ] || touch "$R/dev/$f"
    mount --bind /dev/$f "$R/dev/$f"
done
ln -sf /proc/self/fd "$R/dev/fd" 2>/dev/null
# /dev/i2c-10: the TAS57XX audio amp + cabinet EEPROM bus. On the machine it is a
# real I2C controller; here the game only needs the bus to open and ACK, or its
# amp thread exits and the game aborts at xifo.cpp:72 (PAD-1090). PAD_S3_I2C=<n>
# names a host i2c-dev adapter (Linux's own i2c-stub, loaded on the host) to
# surface inside the chroot as /dev/i2c-10 - major 89, minor = the host number.
if [ -n "${PAD_S3_I2C:-}" ] && [ -e "/dev/i2c-${PAD_S3_I2C}" ]; then
    rm -f "$R/dev/i2c-10"
    mknod "$R/dev/i2c-10" c 89 "${PAD_S3_I2C}" 2>/dev/null \
        && echo "[s3run] /dev/i2c-10 -> host i2c-${PAD_S3_I2C} (stub bus)"
fi
# --bus: each NAME=HOSTDEV in DEVBINDS bound over the chroot's /dev/NAME
for kv in ${DEVBINDS:-}; do
    n=${kv%%=*}; h=${kv#*=}
    rm -f "$R/dev/$n"; touch "$R/dev/$n"
    mount --bind "$h" "$R/dev/$n" && echo "[s3run] /dev/$n -> $h"
done
# /dump -> /connectivity/dump on the machine (S95game makes it)
mkdir -p "$R/connectivity/dump/log"
PRELOAD=""
if [ "$BRIDGE" = 1 ]; then
    rm -f "$R/usr/lib/libEGL.so.1" "$R/usr/lib/libGLESv2.so.2"
    cp "$B/libEGL.so.1" "$B/libGLESv2.so.2" "$R/usr/lib/"
    mkdir -p "$R/usr/lib/pad"; cp "$B/s3kms.so" "$R/usr/lib/pad/"
    touch "$R/run/padgl"; mount --bind "$SD/padgl.ring" "$R/run/padgl"
    # LD_PRELOAD only INSIDE the chroot (the card's own env sets it): exported
    # here, script/timeout/chroot - host binaries - each said it could not open
    # the aarch64 .so at a host path
    export PAD_GL_BRIDGE=/run/padgl
    PRELOAD="/usr/lib/pad/s3kms.so"
fi
# the sound cards (s3alsa.so): without them the game asserts in
# snd_pcm_prepare a few seconds in, once the node bus lets it get that far
if [ -e "$B/s3alsa.so" ]; then
    mkdir -p "$R/usr/lib/pad"; cp "$B/s3alsa.so" "$R/usr/lib/pad/"
    PRELOAD="${PRELOAD:+$PRELOAD:}/usr/lib/pad/s3alsa.so"
fi
[ -n "$PRELOAD" ] && PRELOAD="env LD_PRELOAD=$PRELOAD"
# The audio amp talks over /dev/i2c-10 with the Linux i2c-dev ioctls, which
# stock qemu-user does not translate (it answers ENOTTY and the amp thread dies
# -> xifo.cpp:72). A patched qemu-aarch64 that understands those ioctls lives at
# PAD_S3_QEMU (default ~/.pad-s3/qemu-aarch64); run the game through it
# explicitly, so the shared binfmt interpreter (Spike 2's qemu) stays stock.
# Absent -> fall back to binfmt. See docs/plans/spike3_emulation.md stage 3.
QEMU_INTERP=""
PQ="${PAD_S3_QEMU:-$(dirname "$B")/qemu-aarch64}"
if [ -x "$PQ" ]; then
    cp "$PQ" "$R/.pad-qemu" && chmod +x "$R/.pad-qemu" && QEMU_INTERP="/.pad-qemu"
    echo "[s3run] game runs under the I2C-patched qemu ($PQ)"
fi
echo "[s3run] exec $PROG $* (${SECS}s cap)"
[ "$STRACE" = 1 ] && export QEMU_STRACE=1
export HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin
T0=$(date +%s.%N)
# STDOUT ON A PTY. To a plain file the game's stdout is block-buffered, and
# neither a SIGKILL at the cap nor its own TERM handler (which exits without a
# flush) ever wrote it: a 30 s boot left game.out EMPTY (PAD-1090, second
# sweep). `script` gives it a terminal, so it is line-buffered as on the
# machine's console. stderr stays its own file. TERM at the cap, KILL 5 s on.
printf '%q ' "$PROG" "$@" > "$SD/.argv"
script -q -f -e -c "timeout -s TERM -k 5 $SECS chroot $R $PRELOAD $QEMU_INTERP $(cat "$SD/.argv") 2> $SD/game.err < /dev/null" "$SD/game.out" > /dev/null < /dev/null   # script reads stdin - which is THIS script (bash -s)
RC=$?
# script's own exit is the child's (-e); a dumped core reads 128+signal
grep -q 'COMMAND_EXIT_CODE="134"' "$SD/game.out" && RC=134
echo "[s3run] exit $RC after $(echo "$(date +%s.%N) - $T0" | bc | cut -c1-6) s"
case $RC in
    0) echo "[s3run]   0 = RESTART REQUESTED" ;; 1) echo "[s3run]   1 = REBOOT REQUESTED" ;;
    2) echo "[s3run]   2 = EXIT REQUESTED" ;; 3) echo "[s3run]   3 = POWER LOSS" ;;
    4) echo "[s3run]   4 = FATAL ERROR" ;; 5) echo "[s3run]   5 = DISPATCH TIMEOUT" ;;
    124|143) echo "[s3run]   $RC = still running at the ${SECS}s cap (stopped with TERM)" ;;
    137) echo "[s3run]   137 = still running at the cap and ignored TERM (killed)" ;;
    *) [ "$RC" -ge 128 ] && echo "[s3run]   uncaught signal $((RC-128))"
       grep -h -m3 -E "Assertion|uncaught target signal" "$SD/game.err" | sed 's/^/[s3run]   /' ;;
esac
INNER
RC=$?
if [ -n "$BUSPIDS" ]; then
    kill $BUSPIDS 2>/dev/null; sleep 0.5; kill -9 $BUSPIDS 2>/dev/null
    echo "[s3run] node bus: spi $(grep -c xfer "$SD/spi.log" 2>/dev/null) transfers; bridge: $(grep -c "^# \[node\].*claims" "$SD/bridge.log" 2>/dev/null) node boards identified ($SD/bridge.log)"
fi
if [ -n "$HOSTPID" ]; then
    kill -INT -"$HOSTPID" 2>/dev/null; sleep 1; kill -9 -"$HOSTPID" 2>/dev/null
    echo "[s3run] frames dumped: $(ls "$SD/frames" | wc -l) ($SD/frames)"
    grep -a -E "ops:|UNKNOWN|FAILED|PRESENTTEX|error" "$SD/padglhost.log" | tail -6 | sed 's/^/[s3run]   host: /'
fi
echo "[s3run] stdout: $(wc -l < "$SD/game.out") lines, stderr: $(wc -l < "$SD/game.err") lines ($SD)"
exit $RC
