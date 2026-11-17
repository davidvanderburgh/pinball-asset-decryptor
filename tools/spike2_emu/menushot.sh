#!/bin/bash
# menushot.sh <card> <out png> <step>... - a picture of the game's own service menu, for the Service menu tab's
# "Show the real menu" (PAD-1382).
#
# Boots <card> in this rig (PAD_SLOT, the app's) hidden and muted, with whatever the caller's environment brings (the
# Emulate tab's override set and the runtime it installed: PAD_OVERRIDE_DIR, PAD_MODE_SO), waits for attract (a first
# boot's Guided Setup left by Save & Exit on the way), then walks the steps: a number is a switch pressed (25 select,
# 26 plus/down, 27 minus/up, 28 back), `w<s>` a wait of s game seconds. The frame then shown is written to <out png>
# (glshot.sh) and the run is stopped. PAD_MENUSHOT_GAME is the card's game directory (godzilla_le), for the
# title's switch list. Prints a VERDICT line; exit 0 with the picture written.
RIG=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$RIG/rigjob.sh"
CARD=${1:?menushot.sh <card> <out png> <step>...}
OUT=${2:?menushot.sh <card> <out png> <step>...}
shift 2
export JOB_OUT=${JOB_OUT:-/tmp/padmenushot_${PAD_SLOT:-0}}
job_begin "${PAD_MENUSHOT_GAME:-game}-menu" "$CARD"
job_boot 20
job_wait_attract "${PAD_BOOT_DEADLINE:-900}" || job_fail "$JOB_WHY"
job_sleep 6
for s in "$@"; do
    case "$s" in
        w*) job_sleep "${s#w}" ;;
        *[!0-9]*|'') job_fail "not a step: $s" ;;
        *) job_press "$s"; job_sleep 0.6 ;;
    esac
done
job_sleep 1.5
rm -f "$OUT"
for try in 1 2; do
    bash "$RIG/glshot.sh" "$OUT" > "$JOB_OUT/glshot.txt" 2>&1 < /dev/null
    [ -s "$OUT" ] && break
    job_sleep 2
done
[ -s "$OUT" ] || job_fail "the game's frame could not be read: $(tail -2 "$JOB_OUT/glshot.txt" | tr '\n' ' ')"
job_pass "the service menu's frame is in $OUT"
