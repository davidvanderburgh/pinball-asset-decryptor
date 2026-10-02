#!/bin/bash
# sppath.sh - sourced by every script of the Spooky P-ROC rig (Rick and
# Morty, Alice Cooper's Nightmare Castle).  Owns every path the rig uses;
# nothing else may hard-code one.
#
#   SPP_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   SPP_ROOT     /var/tmp/pad_spkproc         everything the rig writes
#   SPP_CACHE    $SPP_ROOT/cache/<build>      unpacked .pkg builds (prepare.py)
#   SPP_RIG      $SPP_ROOT/rig<slot>          this run: /game, logs, pids
#   SPP_PY       the Python 2.7 the games run on: tools/ap_emu's env
#                (/var/tmp/pad_ap/py27, its setup.sh builds it) - the same
#                pySDL2 / SDL2_mixer / PyYAML / numpy / PIL / OpenCV stack
#                SkeletonGame wants, so it is shared, not built twice
#   SPP_PY3      a Python 3 with PyYAML for the board (prochw.py reads the
#                machine yaml; PAD-Runtime's python3 has no yaml): tools/
#                ap_emu's py3 env, built by the same setup.sh
#   SPP_PROC     tools/proc_emu: the emulated P3-ROC and its pure-Python
#                pinproc (PAD-262)
#   SPP_USER     the account the game runs as (never root: the games call
#                unlock-root, killall, reboot)
#   SPP_DISPLAY  hidden Xvfb display for this slot (:200 + slot; BoF uses :90+,
#                Dutch Pinball :120+, AP :140+, AP apiav and the Spooky Warden
#                rig :160+)
#
# Alice Cooper's screen is a Unity player the game drives over TCP
# 127.0.0.1:9999 (fixed in both), so every slot runs in a network namespace
# of its own (run_game.sh), as the AP apiav rig does.
SPP_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SPP_PROC=$(cd "$SPP_TOOLS/../../proc_emu" && pwd)
SPP_SLOT=${PAD_SLOT:-0}
SPP_ROOT=${SPP_ROOT:-/var/tmp/pad_spkproc}
SPP_CACHE=$SPP_ROOT/cache
SPP_RIG=$SPP_ROOT/rig$SPP_SLOT
SPP_PY=${SPP_PY:-/var/tmp/pad_ap/py27}
SPP_PY3=${SPP_PY3:-/var/tmp/pad_ap/py3}
SPP_DISPLAY=${SPP_DISPLAY:-:$((200 + SPP_SLOT))}

# The rig board (PAD-296): tools/rigboard.sh, shared by every emulator, posts
# this rig's runs where the triage dashboard and the app can see them.
if [ -f "$SPP_TOOLS/../../rigboard.sh" ]; then
    . "$SPP_TOOLS/../../rigboard.sh"
else
    rigboard_post() { :; }; rigboard_clear() { :; }; rigboard_audio() { echo "${2:-0}"; }
    rigboard_visible() { echo "${PAD_VISIBLE:-1}"; }
fi

if [ -z "${SPP_USER:-}" ]; then
    SPP_USER=$(getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $1; exit}')
fi

spp_pid() { cat "$SPP_RIG/$1.pid" 2>/dev/null; }
spp_alive() {
    local p; p=$(spp_pid "$1")
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
# Every process of this slot's game, found by the marker netns.sh puts in
# their environment (SPK_MARK): what the game forked lives on after it, as
# an orphan of WSL's init, and holds no pid file.
spp_mark_pids() {
    local p
    for p in $(pgrep -u "$SPP_USER" . 2>/dev/null); do
        tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -qx "SPK_MARK=$SPP_RIG" && echo "$p"
    done
}
