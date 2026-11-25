#!/bin/bash
# coiljob.sh <key> <card> - every held coil the port names, held by a mode on a new build (PAD-1555; PAD-420's coil_job,
# re-made).
#
#   COILS="<name> ..."  which (default: the port's `text held_coils`)
#   PORT=<port>         the port (default: modes/sdk/ports/<key>.port)
#
# In one game, for each coil a mode file `coil_hold <name> 2000` (once, as it starts) is written and the mode started.
# Pass per coil: the runtime's `<name>: HOLD for <ms>` and, after it, a command on the coil's own board address
# (`text <name>_drive <node> <coil> ...`) in the shim's [coildrive] lines (PAD_COIL_PROBE=1, the slot's gzwatch.log).
# Writes $JOB_OUT/coils.txt: `<name> pass|fail <evidence>`; the job passes when every coil does.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: coiljob.sh <key> <card>}" "${2:?usage: coiljob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
COILS=${COILS:-$(awk '$1 == "text" && $2 == "held_coils" {$1 = $2 = ""; print; exit}' "$PORT")}
[ -n "${COILS// /}" ] || job_fail "the port names no held coils"
cfg() { printf 'name COIL TEST\ngame_modes stack\nseconds 6\ntrigger 0x1 99\nshots 0x1\naward 100\ncoil_hold %s 2000\n' "$1"; }
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
set -- $COILS
cfg "$1" > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so PAD_COIL_PROBE=1
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
GZ=${LOG:-$PAD_LOGDIR/gzwatch.log}
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 5
: > "$JOB_OUT/coils.txt"
bad=0
for c in $COILS; do
    read -r node out _ < <(awk -v n="${c}_drive" '$1 == "text" && $2 == n {print $3, $4; exit}' "$PORT")
    cfg "$c" > "$DUMP/mode.cfg"
    job_sleep 1.5
    mark=$(grep -c "" "$GZ")
    lines=$(grep -c "" "$log")
    bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
    job_wait_log "$log" "$c: (HOLD for|no hold|not held|refused)" 10 || true
    job_sleep 3
    said=$(tail -n +"$lines" "$log" | grep -a -m1 -Eo "$c: (HOLD for [0-9]+ ms \(asked [0-9]+\)|no hold.*|not held.*|refused.*)" | cut -c1-120)
    tail -n +"$mark" "$GZ" | grep -a '\[coildrive\]' > "$JOB_OUT/coil_$c.txt"
    if [ -n "$node" ]; then
        drive=$(grep -a -m1 -Eo "\[coildrive\] [0-9]+ ms node $node coil $out: (pulse|fired)[^,]*" "$JOB_OUT/coil_$c.txt")
    else
        # no `text <name>_drive` (King Kong's ControlCoil route): the coil's own command, by the earlier build's proof -
        # EXPECT="<name>=<pulse power>,<pulse ms>,<hold power>+..."
        want=$(tr '+' '\n' <<<"${EXPECT:-}" | awk -F= -v n="$c" '$1 == n {print $2}')
        IFS=, read -r pp pm hp <<<"$want"
        drive=$([ -n "$want" ] && grep -a -m1 -Eo "\[coildrive\] [0-9]+ ms node [0-9]+ coil [0-9]+: pulse $pp/255 for $pm ms, hold $hp/255 for [0-9]+ ms" "$JOB_OUT/coil_$c.txt")
    fi
    if echo "$said" | grep -q "HOLD for" && [ -n "$drive" ]; then
        echo "$c pass $said | $drive" >> "$JOB_OUT/coils.txt"
    else
        echo "$c fail ${said:-no hold line} | ${drive:-node $node coil $out not driven}" >> "$JOB_OUT/coils.txt"; bad=$((bad + 1))
    fi
    job_sleep 4
done
cp "$log" "$JOB_OUT/mode.log"
[ "$bad" = 0 ] || job_fail "$bad coil(s) not proven: $(grep ' fail ' "$JOB_OUT/coils.txt" | tr '\n' ';' | cut -c1-300)"
job_pass "attract=${JOB_ATTRACT_S}s $(awk '{print $1}' "$JOB_OUT/coils.txt" | tr '\n' ' ')held: $(cut -c1-90 "$JOB_OUT/coils.txt" | tr '\n' ';' | cut -c1-400)"
