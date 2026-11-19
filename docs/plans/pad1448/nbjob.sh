#!/bin/bash
# PAD-1448: census of node-bus frames per node in attract (does node 2 get LED frames with no lamps on it?)
RIGDIR=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1448/tools/spike2_emu
. "$RIGDIR/rigjob.sh"
JOB_OUT=/mnt/c/tmp/PAD-1448/res/$1.${TAG:-x}
job_begin "$1" "$2"
export JOB_KEEP=1
export PAD_NB_LOG=400000 PAD_LOG_TIME=1
[ -n "${SPK:-}" ] && { cp /mnt/c/tmp/PAD-1448/probe/spkprobe.so "$DUMP/spkprobe.so"; export PAD_TRACE_SO=/dump/spkprobe.so; }
job_boot 20
job_wait_attract || job_fail "$JOB_WHY"
job_sleep 40
job_shot "$JOB_OUT/attract.png"
L="$PAD_LOGDIR/gzwatch.log"
job_say "logs with TX: $L"
cp "$L" "$JOB_OUT/game.log"; cp "$DUMP/padled" "$JOB_OUT/padled" 2>/dev/null
for f in $L; do python3 "$RIGDIR/ledframes.py" "$f" > "$JOB_OUT/census.$(basename $f).txt" 2>&1; done
cp "$DUMP/spkprobe.log" "$JOB_OUT/" 2>/dev/null; rm -f "$DUMP/spkprobe.so" "$DUMP/spkprobe.log"
job_pass "census written"
