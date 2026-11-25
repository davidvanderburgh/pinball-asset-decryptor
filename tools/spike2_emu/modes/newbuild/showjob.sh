#!/bin/bash
# showjob.sh <key> <card> - every light show of the game's the port names, played by a mode on a new build (PAD-1555:
# the shows re-placed from the earlier build, some by newbuild/showmatch.py).
#
#   PORT=<port>    the port (default: modes/sdk/ports/<key>.port)
#
# In one game, for each `text show_name_<N>` a mode file with `show_start <name>` is written to /dump/mode.cfg (the
# runtime reads it twice a second) and started; each runs 4 s. Pass: every show says `show N (<name>): the game's own
# light show, started by its own call`, and the game lives to the end.
. "$(cd "$(dirname "$0")/../.." && pwd)/rigjob.sh"
job_begin "${1:?usage: showjob.sh <key> <card>}" "${2:?usage: showjob.sh <key> <card>}"
MODES=$RIG/modes
PORT=${PORT:-$MODES/sdk/ports/$KEY.port}
[ -f "$PORT" ] || job_fail "no port $PORT"
mapfile -t shows < <(awk '$1 == "text" && $2 ~ /^show_name_[0-9]+$/ {n = substr($2, 11); $1 = $2 = ""; sub(/^ +/, ""); print n "\t" $0}' "$PORT" | sort -n)
[ "${#shows[@]}" -gt 0 ] || job_fail "the port names no shows"
cfg() { printf 'name SHOW TEST\ngame_modes stack\nseconds 4\ntrigger 0x1 99\nshots 0x1\naward 100\nshow_start %s\n' "$1"; }
S=$JOB_OUT/stage
mkdir -p "$S"
cp "$MODES/sdk/prebuilt/mode.so" "$S/pad_mode.so" && cp "$PORT" "$S/game.port" || job_fail "could not stage"
cfg "${shows[0]#*$'\t'}" > "$S/mode.cfg"
bash "$MODES/tryit.sh" install "$S" > "$JOB_OUT/install.txt" 2>&1 < /dev/null || job_fail "tryit.sh install: $(tail -1 "$JOB_OUT/install.txt")"
export PAD_MODE_SO=/lib/pad_mode.so
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || { cp "$DUMP/mode.log" "$JOB_OUT/mode.log" 2>/dev/null; job_fail "$JOB_WHY"; }
log=$DUMP/mode.log
job_start_game || job_fail "$JOB_WHY"
job_sleep 3
python3 "$RIG/plunge.py" plunge > /dev/null 2>&1 < /dev/null
job_sleep 2
ok=0; bad=""
for s in "${shows[@]}"; do
    n=${s%%$'\t'*}; name=${s#*$'\t'}
    cfg "$name" > "$DUMP/mode.cfg"
    job_sleep 1.5
    bash "$MODES/tryit.sh" start 0 > /dev/null 2>&1 < /dev/null
    if job_wait_log "$log" "show $n (\\(|: not)" 12 && grep -aEq "show $n (.*): the game's own light show, (playing|started)" "$log"; then
        ok=$((ok + 1))
    else
        bad="$bad $n:$(grep -a "show $n[ :(]" "$log" | tail -1 | cut -c1-90)"
        job_dead && break
    fi
    job_sleep 6
done
cp "$log" "$JOB_OUT/mode.log"
job_dead && job_fail "the game died after $ok show(s): $(job_died_why)"
[ "$ok" -eq "${#shows[@]}" ] || job_fail "$ok of ${#shows[@]} shows played;$bad"
job_pass "attract=${JOB_ATTRACT_S}s all ${#shows[@]} of the game's shows played by a mode"
