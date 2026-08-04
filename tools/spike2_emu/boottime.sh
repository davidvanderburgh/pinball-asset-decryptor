#!/bin/bash
# boottime.sh [log] [maxsecs] - WHERE THE BOOT SPENDS ITS TIME.
#
#   wsl -e bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/boottime.sh /home/david/gzboot.log 120
#
# Start it at the same time as watch.sh. It polls the run log and prints the
# offset at which each phase of the boot first shows up, so "the boot takes ~15
# seconds" can be attributed to a phase instead of guessed at.
#
# WHY POLLING AND NOT TIMESTAMPS IN THE SHIM: logmsg() writes bare lines, and
# adding a clock to it means rebuilding hwshim.so and changing every log this
# rig has ever written. Polling from outside cannot perturb the run at all,
# which matters more here than sub-100ms resolution - the phases being measured
# are seconds long.
#
# t0 is the moment the log first has content, i.e. the game itself starting.
# watch.sh brings the renderer up before the game, and counting that as boot
# time would flatter the game by a second or two.
#
# START THIS FIRST AND watch.sh SECOND, from the SAME shell. Started afterwards
# it finds a log that is already full and reports every phase at t=0.00, which
# looks like a clean instant boot and is worth nothing. The first attempt at
# this measurement did exactly that.
set -u

LOG=${1:-/home/david/gzwatch.log}
MAX=${2:-180}

# marker|pattern  - printed the first time the pattern appears.
MARKERS=(
    "shim up                |^\[hwshim\]"
    "NVRAM opened           |^\[i2c\]"
    "GL bridge attached     |^\[bridge\]"
    "scenes: first          |^\[scenebytes\]"
    "node bus: first frame  |^\[nb\]"
    "node bus: schedule up  |^\[nbsched\]"
    "cabinet switches primed|^\[swprime\]"
    "playfield scan started |TX len=[0-9]* 8.0211"
    "audio device opened    |^\[alsa\]"
    "video pipeline built   |gst\] factory_make"
)

# Wait for the game to actually start writing, and take that as t0.
for i in $(seq 1 400); do
    [ -s "$LOG" ] && break
    sleep 0.25
done
[ -s "$LOG" ] || { echo "no log content after 100s - did the game start?"; exit 1; }

T0=$(date +%s.%N)
el() { echo "$T0 $(date +%s.%N)" | awk '{printf "%6.2f", $2 - $1}'; }

echo "t0 = first byte in $LOG"
printf '%8s  %s\n' "t(s)" "phase"

declare -a done_flag
for i in "${!MARKERS[@]}"; do done_flag[$i]=0; done

scenes_last_n=0
scenes_still=1
end=$(echo "$MAX" | awk '{print $1}')

while :; do
    now=$(el)
    over=$(echo "$now $end" | awk '{print ($1 >= $2) ? 1 : 0}')
    [ "$over" = 1 ] && { echo "  (stopped at ${MAX}s)"; break; }

    for i in "${!MARKERS[@]}"; do
        [ "${done_flag[$i]}" = 1 ] && continue
        name=${MARKERS[$i]%%|*}
        pat=${MARKERS[$i]#*|}
        if grep -aqE "$pat" "$LOG" 2>/dev/null; then
            printf '%8s  %s\n' "$now" "$name"
            done_flag[$i]=1
        fi
    done

    # Scene loading is the one phase with a natural END as well as a start, and
    # it is the one most likely to dominate: 157 scenes, mean ~2 MB, all
    # deserialized as emulated ARM. "No new [scenebytes] line for 2 s" is the
    # cheapest honest test for finished.
    if [ "$scenes_still" = 1 ]; then
        n=$(grep -ac '^\[scenebytes\]' "$LOG" 2>/dev/null)
        n=${n:-0}
        if [ "$n" -gt 0 ] && [ "$n" = "$scenes_last_n" ]; then
            printf '%8s  scenes: last of %s\n' "$now" "$n"
            scenes_still=0
        fi
        scenes_last_n=$n
    fi

    # Done when the game is past Tech Alerts, on the same test status.sh uses.
    g=$(grep -ac 'gst\] factory_make' "$LOG" 2>/dev/null)
    if [ "${g:-0}" -gt 10 ]; then
        printf '%8s  PAST TECH ALERTS (factory_make=%s)\n' "$now" "$g"
        break
    fi
    sleep 0.5
done
