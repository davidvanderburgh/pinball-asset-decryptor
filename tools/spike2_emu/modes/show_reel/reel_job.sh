#!/bin/bash
# PAD-1476 show reel, one build (a rigbatch job: <key> <card>; env WT, KIT, REEL_OUT, NUMS).
# The build's own port and the runtime from the worktree, a plain game, then /dump/showreel with NUMS (the shows the
# game's own modes start, clip_shows) - each plays 3 s by its number, 3 s apart (pad_mode_runtime.c reel_tick) -
# while ledsample.py records the LED view (both banks) and the reel's lines into $REEL_OUT/<key>/led.txt.
# reel_verdict.py reads it. Rig runs are muted (no PAD_AUDIO).
WT=${WT:?}
RIG=$WT/tools/spike2_emu
. "$RIG/rigjob.sh"
OUTD=${REEL_OUT:?}/$1
export JOB_OUT=/tmp/padreel_out_${PAD_SLOT:?}
[ -n "$PAD_SLOT" ] && [ "$PAD_SLOT" != 0 ] || { echo "VERDICT ${1:-?} fail refusing slot '$PAD_SLOT'"; exit 1; }
job_begin "$1" "$2"
rm -rf "$OUTD"; mkdir -p "$OUTD"
[ -e "$DUMP/ballfeed.off" ] && job_fail "ballfeed.off in $DUMP: no balls on this slot"
( while kill -0 $$ 2>/dev/null; do bash "$RIG/riglock.sh" note "$PAD_SLOT" "show reel $1" > /dev/null 2>&1; sleep 30; done ) &
BEAT=$!
ST=/tmp/padreel_stage_${PAD_SLOT}
rm -rf "$ST"; mkdir -p "$ST"
cp "$REEL_OUT/stage/pad_mode.so" "$ST/"
tr -d '\r' < "$WT/tools/spike2_emu/modes/sdk/ports/$1.port" > "$ST/game.port"
bash "$RIG/modes/tryit.sh" install "$ST" > "$OUTD/install.txt" 2>&1 || job_fail "install: $(tail -1 "$OUTD/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
LOG=$DUMP/mode.log
fin() { kill "$SAMP" "$BEAT" 2>/dev/null; cp "$LOG" "$OUTD/mode.log" 2>/dev/null; cp "$JOB_OUT/timeline.txt" "$OUTD/" 2>/dev/null; }
fail() { fin; job_fail "$*"; }
job_boot
job_wait_attract || fail "$JOB_WHY"
job_wait_log "$LOG" 'armed:' 120 || fail "$JOB_WHY"
grep -aq "game shows by number" "$LOG" || fail "no 'game shows by number' line: $(grep -a 'game shows' "$LOG" | tail -1)"
n=$(echo "$NUMS" | tr ',' '\n' | grep -c .)
python3 "${KIT:?}/ledsample.py" "$DUMP/padled" "$LOG" "$OUTD/led.txt" $((n * 6 + 200)) < /dev/null &
SAMP=$!
job_start_game || fail "$JOB_WHY"
job_sleep 8
echo "$NUMS" > "$DUMP/showreel"
job_wait_log "$LOG" "show reel: [0-9]* of the game's shows" 20 || fail "the reel did not start: $(tail -2 "$LOG" | cut -c1-160 | tr '\n' '|')"
end=$(( $(date +%s) + n * 6 + 40 ))
while [ "$(date +%s)" -lt "$end" ]; do
    grep -aq "show reel: done" "$LOG" && break
    python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null    # keep a ball in play
    job_sleep 4
done
fin
grep -aq "show reel: done" "$OUTD/mode.log" || job_fail "the reel did not finish: $(grep -ac 'show reel: #.* on' "$OUTD/mode.log") on"
job_pass "$1: $(grep -ac 'show reel: #.* on' "$OUTD/mode.log") shows, $(grep -ac 'REFUSED' "$OUTD/mode.log") refused"
