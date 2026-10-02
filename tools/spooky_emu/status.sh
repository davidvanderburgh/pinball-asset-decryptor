#!/bin/bash
# status.sh - one key=value per line about this slot's rig, for the app (and
# for you).  Never prose: the app parses it (webui/rig.parse_status).  The
# same keys as tools/ap_emu's, so the Emulate tabs read alike:
#   wsl=1                 always (the app's "WSL answered")
#   running=0|1
#   title=<spktitles key> title_name= build= version= pid= rss_kb= uptime_s= display= visible=0|1
#   window=WxH  switches=<count>  slot=  attract=0|1               (while running)
#   gl=d3d12|llvmpipe  fps=<frames a second, last sample>         (while running)
#   switches_json=<the virtual playfield's table, Linux path>      (once written)
# While the slot runs a P-ROC game, proc/status.sh answers (the same keys).
. "$(dirname "$0")/spkpath.sh"
spk_proc_alive && exec bash "$SPK_PROC/status.sh"
echo "wsl=1"
if spk_game_alive; then
    P=$(spk_game_pid)
    B=$(cat "$SPK_RIG/build" 2>/dev/null)
    T=$(cat "$SPK_RIG/title" 2>/dev/null || echo bj)
    echo "running=1"
    echo "title=$T"
    echo "title_name=$(python3 "$SPK_TOOLS/spktitles.py" get "$T" name)"
    echo "build=$(basename "$B")"
    # Halloween and Ultraman have no version.txt: the build's name has it
    V=$(head -1 "$B/version.txt" 2>/dev/null | tr -d '')
    echo "version=${V:-$(basename "$B" | sed 's/^[^_]*_//')}"
    echo "pid=$P"
    echo "rss_kb=$(awk '/^VmRSS/ {print $2}' "/proc/$P/status" 2>/dev/null)"
    echo "uptime_s=$(ps -o etimes= -p "$P" 2>/dev/null | tr -d ' ')"
    echo "display=$(cat "$SPK_RIG/display" 2>/dev/null)"
    echo "visible=$(cat "$SPK_RIG/visible" 2>/dev/null)"
    echo "window=$(cat "$SPK_RIG/window" 2>/dev/null)"
    # the renderer (d3d12 = the GPU through WSL, llvmpipe = the CPU) and the
    # frame rate Mesa's HUD last sampled (run_game.sh)
    echo "gl=$(cat "$SPK_RIG/gl" 2>/dev/null)"
    echo "fps=$(tail -1 "$SPK_RIG/hud/fps" 2>/dev/null | cut -d. -f1)"
    echo "switches=$(grep -c '"n":' "$SPK_RIG/switches.json" 2>/dev/null)"
    [ -f "$SPK_RIG/switches.json" ] && echo "switches_json=$SPK_RIG/switches.json"
    echo "slot=$SPK_SLOT"
    spk_attract && echo "attract=1" || echo "attract=0"
else
    echo "running=0"
fi
