#!/bin/bash
# guidedsetup.sh [backs] [--confirm] - leave a first boot's GUIDED SETUP by its Save & Exit row.
#
#   PAD_GAME=jaws_le wsl -e bash $RIG/guidedsetup.sh 0 --confirm
#
# Exit 0 = Save & Exit was pressed; 1 = the screen is not that menu (or there is no switch list yet).
#
# A title's first boot in a fresh NVRAM (Jaws, Jurassic Park, King Kong, Avengers, Stranger Things...)
# opens Guided Setup - language, country, Free Play, pricing, volume, date - and waits there for an
# operator; nothing else leaves it. On the Emulate tab a person can walk it with the service keys, but
# a Visual Pinball table has no service keys at all, so a table opened on such a title sat on the menu
# with every button dead (PAD-882). menurow.py reads a glshot.sh frame: walk the selected row down with
# SERVICE PLUS until the last row (Save & Exit) is the selected one, then SERVICE SELECT. Every setting
# keeps the game's own default. Measured on Avengers LE 1.09 (2026-09-24) and Jaws LE 1.02 (PAD-882).
#
# backs: a row's EDITOR (Start or Select opened it: the language list, its title previewing each
# language as PLUS walks it) is not the menu; up to <backs> SERVICE BACKs close it first, leaving the
# setting as it was. --confirm: the menu must be read twice before anything is pressed, for a caller
# that looks on spec (autoattract.sh): a PLUS pressed into attract is a volume step.
#
# LIST (the title's switch_list.txt) is taken from the environment when the caller has it (rigjob.sh),
# else from PAD_TABLES/PAD_GAME the way autoattract.sh finds it. The presses carry the caller's
# PAD_SW_SRC (autoattract.sh: a, the rig's own). GS_KEEP=<png>: where the frame judged "not the menu"
# is copied, for a person (modes/gamecheck.sh).
#
# ONE WALKER AT A TIME. autoattract.sh looks for the menu on every run, and a rig job or the mode
# check walks it too: two walks at once press PLUS twice past Save & Exit and SELECT into attract. The
# second waits on the first (flock on the slot's dump directory, which root's jobs and the user's
# helper can both open) and then looks again - at a menu that is gone.
. "$(dirname "$0")/padpath.sh"
set -u
RIG=$(cd "$(dirname "$0")" && pwd)
BACKS=${1:-0}
CONFIRM=0
[ "${2:-}" = --confirm ] && CONFIRM=1
LIST=${LIST:-${PAD_TABLES:-$ROOT/dump/tables}/${PAD_GAME:-}/switch_list.txt}
[ -s "$LIST" ] || exit 1

plus=$(awk '!/^#/ && toupper($0) ~ /SERVICE PLUS/ {print $1; exit}' "$LIST")
sel=$(awk '!/^#/ && toupper($0) ~ /SERVICE SELECT/ {print $1; exit}' "$LIST")
back=$(awk '!/^#/ && toupper($0) ~ /SERVICE BACK/ {print $1; exit}' "$LIST")
[ -n "$plus" ] && [ -n "$sel" ] || exit 1

exec 9< "$ROOT/dump" && flock -w 120 9 || exit 1

shot=$(mktemp "${TMPDIR:-/tmp}/guidedsetup.XXXXXX.png")
trap 'rm -f "$shot"' EXIT
# a frame that does not come is asked for once more: glshot.sh has one request file per slot, so a
# grab by anyone else at the same moment (a rig job's job_shot) takes this one's picture away, and a
# boot that loads the CPU (Jurassic Park LE) can keep the renderer from answering in time
look() {
    state=none
    (cd "$RIG" && bash glshot.sh "$shot" > /dev/null 2>&1) \
        || { sleep 1; (cd "$RIG" && bash glshot.sh "$shot" > /dev/null 2>&1); } || return 1
    state=$(python3 "$RIG/menurow.py" "$shot" 2>/dev/null)
}
poke() { python3 "$RIG/swpoke.py" "$1" 300 > /dev/null 2>&1 < /dev/null; }

state=
if [ "$CONFIRM" = 1 ]; then
    seen=0
    for again in 1 2 3 4 5 6 7 8; do
        look
        [ "${state#menu}" != "$state" ] && seen=$((seen + 1))
        [ "$seen" -ge 2 ] && break
        sleep 0.5
    done
    [ "$seen" -ge 2 ] || exit 1
fi

for k in $(seq 1 16); do
    look || break
    # a cursor that PULSES (Jaws Pro: bright, then a dim teal menurow does not read) - look again a few
    # times, half a second apart, before calling it no menu
    for again in 1 2 3 4 5; do
        [ "${state#menu}" != "$state" ] && break
        sleep 0.5; look || break
    done
    case "$state" in
        "menu last=yes")
            poke "$sel"
            pad_gsleep 4; exit 0 ;;
        "menu last=no")
            poke "$plus"
            pad_gsleep 1.2 ;;
        *)
            if [ "$BACKS" -gt 0 ] && [ -n "$back" ]; then
                BACKS=$((BACKS - 1))
                poke "$back"
                pad_gsleep 1.5; continue
            fi
            [ -n "${GS_KEEP:-}" ] && cp "$shot" "$GS_KEEP" 2>/dev/null
            break ;;
    esac
done
exit 1
