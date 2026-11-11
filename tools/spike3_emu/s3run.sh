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
CARD=""; SLOT=1; SECS=60; STRACE=0; FRESH=0; BRIDGE=0; BUS=0; WINDOW=0; PROG=/games/game; ARGS=()
H=${PAD_S3_HOME:-/var/lib/pad-s3}       # the rig's own files (it runs as root)
B=${PAD_S3_BUILD:-$H/build}
while [ $# -gt 0 ]; do
    case "$1" in
        --slot) SLOT=$2; shift ;;
        --secs) SECS=$2; shift ;;
        --strace) STRACE=1 ;;
        --fresh) FRESH=1 ;;
        --bridge) BRIDGE=1 ;;
        --bus) BUS=1 ;;
        --window) WINDOW=1; BRIDGE=1; BUS=1 ;;
        --prog) PROG=$2; shift ;;
        --) shift; ARGS=("$@"); break ;;
        *) CARD=$1 ;;
    esac
    shift
done
[ -n "$CARD" ] || { echo "usage: s3run.sh CARD.raw [--slot N] [--secs S] [--strace] [--fresh] [--bridge] [--bus] [--window]" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "[s3run] needs root (overlay mounts): wsl -u root -e bash s3run.sh ..." >&2; exit 2; }

# THE HOST MODULES, LOADED HERE. Both are built from the same 6.6.87.2 tree as
# the self-built WSL kernel (docs/plans/spike3_emulation.md stages 3-4) and
# neither survives a WSL restart - which another rig's restart does at any
# time. So a run loads what it needs instead of failing on its absence.
#   cuse.ko      --bus: the CPU board's SPI chain is a CUSE device
#   i2c-stub.ko  PAD_S3_I2C: the amp/EEPROM bus. Chips: the TAS57xx amps and
#                EEPROMs (0x48 0x4c-0x4e 0x50-0x53) and the MAX9850 headphone
#                amp (0x10), whose register writes must read back.
KMOD=${PAD_S3_KMOD:-$H}
KTREE=$KMOD/kernel/WSL2-Linux-Kernel-linux-msft-wsl-6.6.87.2
# THE DEFAULT NEEDS NONE OF THIS (DEVMODE=preload): s3dev.so answers the SPI
# chain and the amp bus inside the game, so a stock WSL kernel and stock
# qemu-user run it. PAD_S3_DEV=0 (or no s3dev.so built) is the old path:
# s3spid over CUSE, i2c-stub, and the ioctl-patched qemu.
DEVMODE=preload
{ [ "${PAD_S3_DEV:-1}" = 0 ] || [ ! -e "$B/s3dev.so" ]; } && DEVMODE=kernel
export DEVMODE
if [ "$DEVMODE" = kernel ]; then
if [ "$BUS" = 1 ] && [ ! -e /dev/cuse ]; then
    insmod "$KTREE/fs/fuse/cuse.ko" 2>/dev/null && echo "[s3run] loaded cuse.ko"
    for i in $(seq 1 20); do [ -e /dev/cuse ] && break; sleep 0.1; done
fi
stub_bus() {          # the i2c-stub adapter's bus number, by NAME, not "0"
    local a
    for a in /sys/bus/i2c/devices/i2c-* /sys/class/i2c-adapter/i2c-*; do
        grep -q "SMBus stub driver" "$a/name" 2>/dev/null && { echo "${a##*-}"; return 0; }
    done
    return 1
}
if [ -n "${PAD_S3_I2C:-}" ] && [ ! -e "/dev/i2c-${PAD_S3_I2C}" ] || \
   { [ -z "${PAD_S3_I2C:-}" ] && ! stub_bus >/dev/null; }; then
    insmod "$KMOD/i2cstub/i2c-stub.ko" chip_addr=0x10,0x48,0x4c,0x4d,0x4e,0x50,0x51,0x52,0x53 2>/dev/null \
        && echo "[s3run] loaded i2c-stub.ko"
    [ -e /dev/i2c-0 ] || modprobe i2c-dev 2>/dev/null
    for i in $(seq 1 20); do stub_bus >/dev/null && break; sleep 0.1; done
fi
# UNSET = the stub bus, found by name: without an amp bus the TAS57xx init
# fails and the game aborts at xifo.cpp:72 a minute in (every proof run set
# PAD_S3_I2C=0 by hand; the Emulate tab's launcher sets nothing)
[ -n "${PAD_S3_I2C:-}" ] || PAD_S3_I2C=$(stub_bus) || PAD_S3_I2C=""
else
    PAD_S3_I2C=""                      # the amp bus is s3dev.so's
fi
export PAD_S3_I2C

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
HOSTPID=""; AS_USER=()
# a run killed from outside (its session ended) leaves its setsid helpers
# behind; an old padglhost kept dumping its own frames into this slot's
# fresh frames dir for hours, and the "newest" frame was then a stale one
for p in "padglhost $SD/padgl.ring" "s3bridge.py $SD( |\$)" "s3vidhost.py $SD( |\$)" "s3press.py autoguide $SLOT( |\$)" "s3keys.py $SLOT( |\$)"; do
    pkill -f "$p" 2>/dev/null && echo "[s3run] stopped a leftover: $p"
done
if [ "$BRIDGE" = 1 ]; then
    for f in libGLESv2.so.2 libEGL.so.1 s3kms.so padglhost; do
        [ -e "$B/$f" ] || { echo "[s3run] --bridge needs $B/$f: bash s3build.sh" >&2; exit 1; }
    done
    rm -rf "$SD/frames" "$SD/padgl.ring"; mkdir -p "$SD/frames"
    # 40 frames, or unbounded with --bus: s3press.py autoguide prunes them
    MAXFR=40; [ "$BUS" = 1 ] && MAXFR=1000000
    # --window: the game on screen, in Spike 2's renderer window, whose
    # keyboard (padsw.h) s3keys.py carries onto this rig's switches; the
    # window binds its keys by the title's own names from the
    # switch_list.txt s3bridge writes (PAD_TABLES/PAD_GAME). Without it the
    # renderer is headless (surfaceless EGL) and only dumps frames.
    if [ "$WINDOW" = 1 ]; then
        # dump/ is what the virtual playfield window reads and writes (padsw,
        # padled - Spike 2's padpath.dump()); its switch helper runs as the
        # WSL user, not root, so the block is everyone's to write
        rm -rf "$SD/dump"; mkdir -p "$SD/dump"; chmod 777 "$SD/dump"
        RENV=(PAD_GL_WINDOW=1 PAD_SW_SHM="$SD/dump/padsw" PAD_TABLES="$SD/tables" PAD_GAME=game)
        # AS THE DESKTOP'S USER, NOT ROOT (watch.sh learned it first): as
        # root, padglhost cannot attach to the WSLg X server's shared memory -
        # "MESA: error: Failed to attach to x11 shm" on repeat, 0.5 fps, a
        # black window. The X socket's owner is that user; the slot directory
        # becomes theirs so the renderer can make its ring (root still writes
        # anything in it).
        XU=$(stat -c %U "/tmp/.X11-unix/X${DISPLAY#*:}" 2>/dev/null | head -1)
        XU=${XU%%.*}
        if [ "$(id -u)" = 0 ] && [ -n "$XU" ] && [ "$XU" != root ] && id -u "$XU" >/dev/null 2>&1; then
            chown "$XU" "$SD" "$SD/frames"
            AS_USER=(runuser -u "$XU" --)
            echo "[s3run] the window, as $XU (the X display's owner)"
        fi
    else
        RENV=(-u DISPLAY -u WAYLAND_DISPLAY EGL_PLATFORM=surfaceless)
    fi
    "${AS_USER[@]}" env "${RENV[@]}" GALLIUM_DRIVER=${GALLIUM_DRIVER:-d3d12} \
        PAD_GL_W=${PAD_S3_W:-1920} PAD_GL_H=${PAD_S3_H:-1080} PAD_GL_DUMP="$SD/frames" \
        PAD_GL_FRAME_EVERY=${PAD_GL_FRAME_EVERY:-30} PAD_GL_MAX_FRAMES=${PAD_GL_MAX_FRAMES:-$MAXFR} \
        PAD_VID_SHM="$SD/padvid.shm" \
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
RUNBINDS=""
if [ "$BUS" = 1 ]; then
    rm -f "$SD/spi.log" "$SD/bridge.log" "$SD/bridge.path" "$SD/nodesw"
    # the cabinet inputs, live: 8 bytes, every one at rest; s3press.py
    # presses a button by clearing its bit (active low) while the game runs
    python3 -c "import sys; open(sys.argv[1],'wb').write(bytes([int(sys.argv[2],0)])*8)" \
        "$SD/spi.in" "${PAD_S3_SPI_IDLE:-0xff}"
    if [ "$DEVMODE" = kernel ]; then
        [ -e /dev/cuse ] || { echo "[s3run] --bus needs /dev/cuse (insmod cuse.ko)" >&2; exit 1; }
        [ -x "$B/s3spid" ] || { echo "[s3run] --bus needs $B/s3spid: bash s3build.sh" >&2; exit 1; }
        SPIDEV=pad-s3spi-slot$SLOT
        "$B/s3spid" -f --name=$SPIDEV --log="$SD/spi.log" --idle=${PAD_S3_SPI_IDLE:-0xff} --input="$SD/spi.in" > "$SD/s3spid.out" 2>&1 &
        BUSPIDS="$!"
    fi
    [ "$WINDOW" = 1 ] && export PAD_S3_PADLED="$SD/dump/padled"
    python3 "$S/s3bridge.py" "$SD" "$TREE/games/spike3/netbridge/netbridge.elf" "$TREE/games/game" > "$SD/s3bridge.out" 2>&1 &
    BUSPIDS="$BUSPIDS $!"
    # the video decoder (stage 5): s3vid.so hands the game's HEVC/H.264
    # packets to it and its I420 frames go to padglhost through padvid.shm
    rm -f "$SD/s3vid.feed" "$SD/padvid.shm" "$SD/s3vidhost.log"
    python3 "$S/s3vidhost.py" "$SD/s3vid.feed" "$SD/padvid.shm" "$SD/s3vidhost.log" > "$SD/s3vidhost.out" 2>&1 &
    BUSPIDS="$BUSPIDS $!"
    for i in $(seq 1 50); do
        { [ "$DEVMODE" != kernel ] || [ -e /dev/$SPIDEV ]; } && [ -s "$SD/bridge.path" ] && break; sleep 0.1
    done
    if [ "$DEVMODE" = kernel ]; then
        [ -e /dev/$SPIDEV ] || { echo "[s3run] s3spid made no /dev/$SPIDEV:"; tail -3 "$SD/s3spid.out"; kill $BUSPIDS; exit 1; }
    fi
    [ -s "$SD/bridge.path" ] || { echo "[s3run] s3bridge made no pty:"; tail -3 "$SD/s3bridge.out"; kill $BUSPIDS; exit 1; }
    if [ "$DEVMODE" = kernel ]; then
        DEVBINDS="spidev4.0=/dev/$SPIDEV ttyAMA5=$(cat "$SD/bridge.path")"
    else
        DEVBINDS="ttyAMA5=$(cat "$SD/bridge.path")"    # spidev4.0: s3dev.so
    fi
    for i in $(seq 1 50); do [ -s "$SD/padvid.shm" ] && [ -s "$SD/s3vid.feed" ] && break; sleep 0.1; done
    chmod 666 "$SD/padvid.shm" 2>/dev/null     # the renderer may be the desktop user
    if [ -s "$SD/padvid.shm" ] && [ -s "$SD/s3vid.feed" ]; then
        RUNBINDS="s3vid=$SD/s3vid.feed padvid=$SD/padvid.shm"
    else
        echo "[s3run] no video decoder: $(tail -2 "$SD/s3vidhost.out")"
    fi
    if [ "$DEVMODE" != kernel ]; then                  # s3dev.so reads it live
        RUNBINDS="${RUNBINDS:+$RUNBINDS }padspi=$SD/spi.in"
    fi
    echo "[s3run] node bus up: $DEVBINDS"
    # GUIDED SETUP, walked by the harness: the game holds a fresh machine (and
    # this one on every boot) on its operator screen until Save & Exit is
    # pressed. s3press.py watches the frame dumps and presses BACK + SELECT
    # (the coin-door buttons on the SPI chain) whenever it comes up, pruning
    # old dumps as it goes. PAD_S3_AUTOGUIDE=0 leaves the screen alone.
    if [ "$WINDOW" = 1 ]; then
        for i in $(seq 1 50); do [ -s "$SD/dump/padsw" ] && break; sleep 0.1; done
        chmod 666 "$SD/dump/padsw" 2>/dev/null
        python3 "$S/s3keys.py" "$SLOT" "$SD/dump/padsw" "$SD/tables/game/switch_list.txt" \
            > "$SD/s3keys.log" 2>&1 &
        BUSPIDS="$BUSPIDS $!"
        # the boot's progress for the Emulate tab's footer ([s3run] progress)
        python3 "$S/s3prog.py" "$SD" &
        BUSPIDS="$BUSPIDS $!"
        # THE VIRTUAL PLAYFIELD: Spike 2's window (playfield.py) on this run,
        # its layout and pictures from the card's own device records
        # (s3pf.py), its lamps from the node bus (s3leds.py via s3bridge). The
        # window is a Windows program the app opens on this line, as for a
        # Spike 2 run whose WSL cannot start one itself.
        if [ "${PAD_S3_PLAYFIELD:-1}" = 1 ]; then
            TITLE=$(basename "$(dirname "$(readlink "$TREE/games/game")")")
            for i in $(seq 1 50); do [ -s "$SD/tables/game/switch_list.txt" ] && break; sleep 0.1; done
            python3 "$S/s3pf.py" "$TREE/games/game" "$TREE" "$TITLE" "$SD/tables/$TITLE" \
                "$SD/tables/game/switch_list.txt" 2>&1 | sed 's/^/[s3run] /'
            chmod -R a+rX "$SD/tables" 2>/dev/null
            if [ -s "$SD/tables/$TITLE/device_xy.txt" ]; then
                echo "PAD_PLAYFIELD_WINDOWS_LAUNCH game=$TITLE savestates=0" \
                     "root=$(wslpath -w "$SD" 2>/dev/null)" \
                     "tables=$(wslpath -w "$SD/tables" 2>/dev/null)" \
                     "slot=$SLOT root_wsl=$SD"
            fi
        fi
    fi
    if [ "$BRIDGE" = 1 ] && [ "${PAD_S3_AUTOGUIDE:-1}" = 1 ]; then
        python3 "$S/s3press.py" autoguide "$SLOT" > "$SD/autoguide.log" 2>&1 &
        BUSPIDS="$BUSPIDS $!"
    fi
fi
export DEVBINDS RUNBINDS
# SOUND, only when asked (PAD_S3_AUDIO=1): rig runs are muted. s3alsa.so
# writes the game's PCM, non-blocking, into $SD/audio/audio.fifo (bound at
# /run/padaudio inside) and its format into audio.fmt; Spike 2's
# playaudio.sh plays it - a Windows speaker on WSL, pulse/alsa elsewhere.
# Started HERE, outside the game's namespaces: inside them there is no
# network, and the WSL player reaches the Windows speaker over localhost.
# PAD_S3_AUDIO_PLAYER=0 makes only the fifo, for a caller that reads it.
AUDPID=""
pkill -f "playaudio.sh $SD/audio/" 2>/dev/null && echo "[s3run] stopped a leftover player"
if [ "${PAD_S3_AUDIO:-0}" = 1 ]; then
    rm -rf "$SD/audio"; mkdir -p "$SD/audio"
    # the player is the desktop's user too (its sound server's), as the window
    [ ${#AS_USER[@]} -gt 0 ] && chown "${AS_USER[2]}" "$SD/audio"
    if [ "${PAD_S3_AUDIO_PLAYER:-1}" = 1 ]; then
        # the player's TCP hop (WSL -> the Windows speaker, or a relay) gets
        # a port of this slot's own: Spike 2 rigs hold 45997+slot, so a
        # Spike 3 slot of the same number would take theirs
        PAD_AUDIO_PORT=${PAD_AUDIO_PORT:-$((46100 + SLOT))} \
        "${AS_USER[@]}" setsid bash "$S/../spike2_emu/playaudio.sh" "$SD/audio/audio.fifo" 44100 2 \
            "$SD/audio/audio.fmt" > "$SD/playaudio.log" 2>&1 &
        AUDPID=$!
        echo "[s3run] sound: playaudio.sh (log $SD/playaudio.log)"
    else
        mkfifo "$SD/audio/audio.fifo"
        echo "[s3run] sound: $SD/audio/audio.fifo, no player (PAD_S3_AUDIO_PLAYER=0)"
    fi
    export PAD_S3_AUDIO
fi

# NO NETWORK. The game runs in its own network namespace (-n) holding only a
# loopback interface: a Spike 3 title carries Stern's connectivity code
# (Insider Connected, conagent), and nothing it tries may leave this PC -
# without -n it shared WSL's own network and could have reached the internet
# (David, PAD-1090). Every attempt fails here with no route, and the --strace
# log shows what was attempted.
# --kill-child and a background wait: a TERM to this script (a caller's
# `kill`) now ends the game AND reaches the cleanup below. Run in the
# foreground, bash held the trap until the game itself ended, the caller
# gave up, and the setsid renderer lived on - three orphaned padglhosts
# slowed every later boot to a crawl (node bus at 169 s instead of 62).
unshare -m -p -n -f --kill-child --mount-proc=/proc bash -s "$TREE" "$SD" "$SECS" "$STRACE" "$BRIDGE" "$B" "$PROG" "${ARGS[@]}" <<'INNER' &
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
# ...and each NAME=FILE in RUNBINDS over /run/NAME (the video feed and ring)
for kv in ${RUNBINDS:-}; do
    n=${kv%%=*}; h=${kv#*=}
    touch "$R/run/$n" && mount --bind "$h" "$R/run/$n" && echo "[s3run] /run/$n -> $h"
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
# the SPI chain and the amp bus, inside the game (s3dev.so, DEVMODE=preload)
if [ "$DEVMODE" != kernel ]; then
    mkdir -p "$R/usr/lib/pad"; cp "$B/s3dev.so" "$R/usr/lib/pad/"
    PRELOAD="${PRELOAD:+$PRELOAD:}/usr/lib/pad/s3dev.so"
fi
# the video decoder (s3vid.so): takes the game's HEVC/H.264 decoding to the
# host when /run/s3vid is there (--bus), and leaves it alone when it is not
if [ -e "$B/s3vid.so" ]; then
    mkdir -p "$R/usr/lib/pad"; cp "$B/s3vid.so" "$R/usr/lib/pad/"
    PRELOAD="${PRELOAD:+$PRELOAD:}/usr/lib/pad/s3vid.so"
fi
[ -n "$PRELOAD" ] && PRELOAD="env LD_PRELOAD=$PRELOAD"
[ -n "$PRELOAD" ] && [ "$DEVMODE" != kernel ] && PRELOAD="$PRELOAD PAD_S3_SPI_IN=/run/padspi"
# SOUND, only when asked (PAD_S3_AUDIO=1): rig runs are muted. s3alsa.so
# writes the game's PCM, non-blocking, into $SD/audio/audio.fifo (bound at
# /run/padaudio) and the format into audio.fmt; Spike 2's playaudio.sh plays
# it (a Windows speaker on WSL, pulse/alsa/CoreAudio elsewhere).
# PAD_S3_AUDIO_PLAYER=0 makes only the fifo, for a caller that reads it.
if [ "${PAD_S3_AUDIO:-0}" = 1 ] && [ -n "$PRELOAD" ] && [ -d "$SD/audio" ]; then
    mkdir -p "$R/run/padaudio"
    mount --bind "$SD/audio" "$R/run/padaudio" && echo "[s3run] /run/padaudio -> $SD/audio"
    PRELOAD="$PRELOAD PAD_S3_AUDIO_PLAY=/run/padaudio/audio.fifo PAD_S3_AUDIO_FMT=/run/padaudio/audio.fmt"
fi
# The audio amp talks over /dev/i2c-10 with the Linux i2c-dev ioctls, which
# stock qemu-user does not translate (it answers ENOTTY and the amp thread dies
# -> xifo.cpp:72). A patched qemu-aarch64 that understands those ioctls lives at
# PAD_S3_QEMU (default ~/.pad-s3/qemu-aarch64); run the game through it
# explicitly, so the shared binfmt interpreter (Spike 2's qemu) stays stock.
# Absent -> fall back to binfmt. See docs/plans/spike3_emulation.md stage 3.
QEMU_INTERP=""
PQ="${PAD_S3_QEMU:-$(dirname "$B")/qemu-aarch64}"
if [ "$DEVMODE" != kernel ] && [ -z "${PAD_S3_QEMU:-}" ]; then
    echo "[s3run] game runs under the system's qemu-aarch64 (binfmt); buses in s3dev.so"
elif [ -x "$PQ" ]; then
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
echo "[s3run] exit $RC after $(python3 -c "import sys,time; print('%.1f' % (time.time() - float(sys.argv[1])))" "$T0") s"
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
INNERPID=$!
trap 'kill -KILL $INNERPID 2>/dev/null' TERM INT HUP   # unshare --fork ignores TERM; KILL + --kill-child ends the namespace
while :; do wait $INNERPID 2>/dev/null; RC=$?; kill -0 $INNERPID 2>/dev/null || break; done
trap - TERM INT HUP
if [ -n "$BUSPIDS" ]; then
    kill $BUSPIDS 2>/dev/null; sleep 0.5; kill -9 $BUSPIDS 2>/dev/null
    rm -f "$SD/dump/padled"      # gone = the run ended: the playfield window closes
    echo "[s3run] node bus: spi $(grep -c xfer "$SD/spi.log" 2>/dev/null) transfers; bridge: $(grep -c "^# \[node\].*claims" "$SD/bridge.log" 2>/dev/null) node boards identified ($SD/bridge.log)"
fi
if [ -n "$AUDPID" ]; then
    kill -TERM -"$AUDPID" 2>/dev/null; sleep 0.5; kill -9 -"$AUDPID" 2>/dev/null
    grep -a "\[s3alsa\] playing\|closed:" "$SD/game.err" | tail -2 | sed 's/^/[s3run]   sound: /'
fi
if [ -n "$HOSTPID" ]; then
    kill -INT -"$HOSTPID" 2>/dev/null; pkill -INT -f "padglhost $SD/padgl.ring" 2>/dev/null
    sleep 1; kill -9 -"$HOSTPID" 2>/dev/null; pkill -9 -f "padglhost $SD/padgl.ring" 2>/dev/null
    echo "[s3run] frames dumped: $(ls "$SD/frames" | wc -l) ($SD/frames)"
    grep -a -E "ops:|UNKNOWN|FAILED|PRESENTTEX|error" "$SD/padglhost.log" | tail -6 | sed 's/^/[s3run]   host: /'
fi
echo "[s3run] stdout: $(wc -l < "$SD/game.out") lines, stderr: $(wc -l < "$SD/game.err") lines ($SD)"
exit $RC
