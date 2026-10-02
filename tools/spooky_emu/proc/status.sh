#!/bin/bash
# status.sh - one key=value per line about this slot's rig.  Never prose:
# callers parse it.  The Emulate Spooky tab reads it through
# tools/spooky_emu/status.sh, so the keys a Warden game's status has are here
# too, alike:
#   wsl=1 slot=
#   running=0|1                 the game is up (and, for Alice Cooper, its
#                               Unity player)
#   build= title=               the prepared build it runs (rm | ac)
#   title_name= version=        the game's name, the build's version
#   attract=0|1                 it has reached attract
#   pid= rss_kb= uptime_s=      the game, while it runs
#   display= visible=0|1 window=WxH
#   switches=<count> switches_json=<the virtual playfield's table>
#   board=... hw=...            tools/proc_emu's status lines
. "$(dirname "$0")/sppath.sh"
echo "wsl=1"
echo "slot=$SPP_SLOT"
T=$(cat "$SPP_RIG/title" 2>/dev/null)
if spp_alive game && { [ "$T" != ac ] || spp_alive unity; }; then echo "running=1"; else echo "running=0"; fi
B=$(basename "$(cat "$SPP_RIG/build" 2>/dev/null)")
echo "build=$B"
echo "title=$T"
echo "title_name=$(cat "$SPP_RIG/name" 2>/dev/null)"
echo "version=${B#*_}"
if [ -f "$SPP_RIG/attract" ]; then echo "attract=1"; else echo "attract=0"; fi
if spp_alive game; then
    P=$(spp_pid game)
    echo "pid=$P"
    echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
    echo "display=$(cat "$SPP_RIG/display" 2>/dev/null)"
    echo "visible=$(cat "$SPP_RIG/visible" 2>/dev/null)"
    echo "window=$(cat "$SPP_RIG/window" 2>/dev/null)"
    echo "switches=$(grep -c '"n":' "$SPP_RIG/switches.json" 2>/dev/null)"
    [ -f "$SPP_RIG/switches.json" ] && echo "switches_json=$SPP_RIG/switches.json"
fi
PATH=$SPP_PY3/bin:$PATH PAD_SLOT=$SPP_SLOT bash "$SPP_PROC/status.sh" | grep -E '^(board|hw)='
