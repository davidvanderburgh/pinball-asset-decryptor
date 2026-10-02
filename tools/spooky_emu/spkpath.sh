#!/bin/bash
# spkpath.sh - sourced by every Spooky rig script.  Owns every path the rig
# uses; nothing else may hard-code one.
#
#   SPK_SLOT     rig slot (PAD_SLOT, default 0) - several rigs can run at once
#   SPK_ROOT     /var/tmp/pad_spooky          everything the rig writes
#   SPK_CACHE    $SPK_ROOT/cache/<build>      unpacked updates (prepare.sh)
#   SPK_RIG      $SPK_ROOT/rig<slot>          this run: the /game tree the
#                                             game sees, logs, pids, FIFO
#   SPK_USER     the account the game runs as (NEVER root: the game shells
#                out to bash for its housekeeping)
#   SPK_DISPLAY  hidden Xvfb display for this slot (:160 + slot; BoF uses
#                :90+, Dutch Pinball :120+, American Pinball :140+)
#   SPK_SHIM     the LD_PRELOAD shim that maps /dev/WARDEN onto the rig's
#                board (build.sh)
#   SPK_PROC     proc/: the P-ROC games' rig (Rick and Morty, Alice Cooper;
#                its own paths in proc/sppath.sh).  watch.sh hands their
#                files there, and status / stop / cancel / cache / ctl
#                answer for whichever of the two runs on the slot
#   SPK_PROC_RIG that rig's folder for this slot (SPP_RIG there)
SPK_TOOLS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SPK_SLOT=${PAD_SLOT:-0}
SPK_ROOT=${SPK_ROOT:-/var/tmp/pad_spooky}
SPK_CACHE=$SPK_ROOT/cache
SPK_RIG=$SPK_ROOT/rig$SPK_SLOT
SPK_DISPLAY=${SPK_DISPLAY:-:$((160 + SPK_SLOT))}
SPK_SHIM=$SPK_TOOLS/spkshim.so
SPK_PROC=$SPK_TOOLS/proc
SPK_PROC_ROOT=${SPP_ROOT:-/var/tmp/pad_spkproc}
SPK_PROC_RIG=$SPK_PROC_ROOT/rig$SPK_SLOT

# The rig board (PAD-296): tools/rigboard.sh, shared by every emulator, posts
# this rig's runs where the triage dashboard and the app can see them.
if [ -f "$SPK_TOOLS/../rigboard.sh" ]; then
    . "$SPK_TOOLS/../rigboard.sh"
else
    rigboard_post() { :; }; rigboard_clear() { :; }; rigboard_audio() { echo "${2:-0}"; }
    rigboard_visible() { echo "${PAD_VISIBLE:-1}"; }
fi

# The first ordinary account (uid 1000..59999): "pad" in PAD-Runtime.
if [ -z "${SPK_USER:-}" ]; then
    SPK_USER=$(getent passwd | awk -F: '$3>=1000 && $3<60000 {print $1; exit}')
fi

spk_game_pid() { cat "$SPK_RIG/game.pid" 2>/dev/null; }
spk_game_alive() {
    local p; p=$(spk_game_pid)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
# Every process of this slot: the game, its board and anything they started,
# found by this rig's marker in their environment (the game's cwd is in its
# own mount namespace, so it does not show which rig it is).
spk_slot_pids() {
    local p
    for p in $(pgrep -f 'main\.x86_64|spkwarden\.py'); do
        tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -qx "SPK_MARK=$SPK_RIG" && echo "$p"
    done
}

# A P-ROC game's update file (proc/prepare.py tells them apart the same way;
# Total Nuclear Annihilation goes there too, to be refused by name).
spk_proc_file() {
    case "$(basename "$1" | tr 'A-Z' 'a-z')" in
        rm-gamecode*|ac-gamecode*|tna-gamecode*) return 0 ;;
    esac
    return 1
}
# Is this slot's P-ROC game up / anything of it left (a pid file)?
spk_proc_alive() {
    local p; p=$(cat "$SPK_PROC_RIG/game.pid" 2>/dev/null)
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
spk_proc_present() {
    local f
    for f in game unity ns xvfb; do [ -f "$SPK_PROC_RIG/$f.pid" ] && return 0; done
    return 1
}

# Has this slot's game reached attract mode?  Each title says how it shows
# (spktitles.py: attract, attract_in); the caller may have them already in
# SPK_ATTRACT / SPK_ATTRACT_IN.
spk_attract() {
    local t=${SPK_TITLE_KEY:-$(cat "$SPK_RIG/title" 2>/dev/null || echo bj)}
    local a=${SPK_ATTRACT:-$(python3 "$SPK_TOOLS/spktitles.py" get "$t" attract)}
    local f=${SPK_ATTRACT_IN-$(python3 "$SPK_TOOLS/spktitles.py" get "$t" attract_in)}
    grep -qE "$a" "$SPK_RIG/${f:-player.log}" 2>/dev/null
}
