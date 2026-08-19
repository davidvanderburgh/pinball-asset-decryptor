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
GAMES=$(pgrep -c -x game 2>/dev/null); echo "game_procs=${GAMES:-0}"
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
echo "game=${JJP_GAME}"
