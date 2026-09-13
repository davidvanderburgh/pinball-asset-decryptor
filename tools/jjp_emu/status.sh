#!/bin/bash
# One fact per line, key=value.  Machine-readable for the GUI panel; the GUI
# must never have to parse prose.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

if [ ! -r /proc/1/stat ]; then echo "wsl=0"; exit 2; fi
echo "wsl=1"
echo "image_mounted=$(mountpoint -q "$JJP_ROOT" && echo 1 || echo 0)"
echo "jail_mounted=$(mountpoint -q "$JJP_JAIL" && echo 1 || echo 0)"
# NOTE: `pgrep -c` PRINTS 0 and EXITS 1 when nothing matches, so the obvious
# `$(pgrep -c ... || echo 0)` emits TWO lines and corrupts key=value parsing.
echo "game_procs=$(jjp_game_count)"
HLMD=$(pgrep -c -x hasplmd_x86_64 2>/dev/null); echo "hasplmd=${HLMD:-0}"
AKSD=$(pgrep -c -x aksusbd_x86_64 2>/dev/null); echo "aksusbd=${AKSD:-0}"

KEY=0
for d in /sys/bus/usb/devices/*; do
    [ -f "$d/idVendor" ] || continue
    [ "$(cat "$d/idVendor")" = "${JJP_HASP_VIDPID%%:*}" ] || continue
    [ "$(cat "$d/idProduct")" = "${JJP_HASP_VIDPID##*:}" ] || continue
    KEY=1; break
done
echo "dongle_present=$KEY"
echo "hasp_port_1947=$(bash -c 'echo > /dev/tcp/127.0.0.1/1947' 2>/dev/null && echo 1 || echo 0)"

RSS=$(ps -o rss= -C game 2>/dev/null | sort -rn | head -1 | tr -d ' ')
echo "game_rss_kb=${RSS:-0}"
ET=$(ps -o etimes= -C game 2>/dev/null | sort -rn | head -1 | tr -d ' ')
echo "game_uptime_s=${ET:-0}"
echo "display=$JJP_DISPLAY"

# Nested X server (display.sh).  Its presence is what keeps the game off a 4K
# desktop and out of software rendering.
NEST=$(pgrep -fc "Xephyr ${JJP_NESTED:-:1}" 2>/dev/null); echo "nested_display=${NEST:-0}"

# CUSE boards.  Without these the game opens nothing and sees no switches.
CUSE=$(pgrep -fc "${JJP_CUSE_BIN:-/var/tmp/jjpcuse}" 2>/dev/null); echo "cuse_daemons=${CUSE:-0}"
NODES=0
for n in jjpio100 jjpled100 jjpacc100 jjpcab100 jjptop100; do
    [ -e "/dev/$n" ] && NODES=$((NODES+1))
done
echo "board_nodes=$NODES"

# Frame counters out of the shared block, so the panel can say whether the
# game is actually TALKING to the boards rather than merely having opened them.
SHM=/dev/shm${JJP_SHM_NAME:-/jjp_switches}
if [ -r "$SHM" ]; then
    python3 - "$SHM" <<'PYEOF'
import struct, sys
# Layout mirrors jjpshm.h: magic,version,game_pid, switches[16], cabinet[16],
# out[8][64], out_changes[8], read_count, write_count.
OFF_OUT_CHANGES = 12 + 16 + 16 + 8*64
try:
    d = open(sys.argv[1], 'rb').read(OFF_OUT_CHANGES + 8*4 + 8)
    rd, wr = struct.unpack_from('<II', d, OFF_OUT_CHANGES + 8*4)
    led = struct.unpack_from('<I', d, OFF_OUT_CHANGES + 1*4)[0]
    print("frames_in=%d" % rd)
    print("frames_out=%d" % wr)
    print("led_writes=%d" % led)
except Exception:
    print("frames_in=0"); print("frames_out=0"); print("led_writes=0")
PYEOF
else
    echo "frames_in=0"; echo "frames_out=0"; echo "led_writes=0"
fi

# Which title is mounted, asked of the image rather than assumed.
TITLE=""
if mountpoint -q "$JJP_ROOT"; then
    for d in "$JJP_ROOT"/jjpe/gen1/*/; do
        [ -x "$d/game" ] && TITLE=$(basename "$d") && break
    done
fi
echo "game=${TITLE:-${JJP_GAME}}"

# PAD multi-boot (item 117): does root A carry the menu, is root B in the jail,
# what did the menu choose, and which tree does the RUNNING game see.  The
# hook's bind lives in the run's own mount namespace, so it is asked from inside
# that namespace (nsenter on the leader's pid); empty = no run, or no bind =
# image 0's own tree.
echo "multiboot=$(jjp_multiboot && echo 1 || echo 0)"
echo "rootb_mounted=$(mountpoint -q "$JJP_JAIL$JJP_MULTI_B" 2>/dev/null && echo 1 || echo 0)"
echo "selector_procs=$(jjp_select_count)"
CH=""
[ -r "$JJP_JAIL/jjpe/temp/padselect.choice" ] && CH=$(head -c 8 "$JJP_JAIL/jjpe/temp/padselect.choice" 2>/dev/null | tr -cd '0-9')
echo "choice=$CH"
BOUND=""; LOWER=""
if [ -n "$TITLE" ] && [ -r "$JJP_PID_FILE" ]; then
    L=$(cat "$JJP_PID_FILE" 2>/dev/null)
    if [ -n "$L" ] && [ -d "/proc/$L" ]; then
        BOUND=$(nsenter -t "$L" -m findmnt -n -o SOURCE "$JJP_JAIL/jjpe/gen1/$TITLE" 2>/dev/null | head -1)
        # both roots are overlays here, so the SOURCE alone reads the same for
        # either; the lower directory names which one (…/rootb = image 1)
        LOWER=$(nsenter -t "$L" -m findmnt -n -o OPTIONS "$JJP_JAIL/jjpe/gen1/$TITLE" 2>/dev/null | head -1 \
                | tr ',' '\n' | sed -n 's/^lowerdir=//p' | head -1)
    fi
fi
echo "bound=$BOUND"
echo "bound_lower=$LOWER"
