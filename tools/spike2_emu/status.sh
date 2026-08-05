#!/bin/bash
# status.sh - ONE machine-readable snapshot of the rig, for the PAD Emulate tab.
#
# Emits key=value lines and nothing else, so the GUI never has to parse prose:
#
#   running=0|1        the guest is up
#   procs=<n>          all five rig processes (see alive.sh)
#   cpu=<pct>          guest CPU, percent of one core
#   rss=<mb>           guest resident memory
#   host_cpu=<pct>     renderer CPU
#   state=<word>       off | booting | techalerts | running
#   fps=<n>            renderer frames per second, blank if not reported yet
#   pcm=<frames>       PCM frames actually played out to the speakers
#   drop=<frames>      PCM frames dropped (should stay 0)
#   log=<path>
#
# state=techalerts vs running is the `[gst] factory_make` count: the game sits on
# Tech Alerts waiting for an operator to press something, and 3 means it is still
# waiting rather than stuck. That distinction cost this project a whole pass, so
# it is computed here once rather than re-derived by every caller.
set -u
LOG=${1:-/home/david/gzwatch.log}
S=/mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu

pid=$(pgrep -x game 2>/dev/null | head -1)
hpid=$(pgrep -x padglhost 2>/dev/null | head -1)

# ASK alive.sh, do not keep a second list here. This used to count four things
# plus a pattern ('Godzilla Pro emulator') that had not matched anything for
# months, so the app's idea of "a run is up" was built on a list that had
# already drifted - the same drift that let seven leaked processes hide behind
# "TOTAL STILL RUNNING : 0". --procs is deliberately the count WITHOUT card
# mounts: an idle mount is worth reporting as unclean, but it must not make the
# app's button say "Stop emulator".
procs=$(bash "$S/alive.sh" --procs)
# `pgrep -c` PRINTS 0 and ALSO exits non-zero on no match, so `|| echo 0` emits
# "0\n0" and breaks every arithmetic use downstream. Take the value, default it.
n() { local c; c=$(pgrep -c "$@" 2>/dev/null); echo "${c:-0}"; }

echo "procs=$procs"
echo "log=$LOG"

if [ -z "$pid" ]; then
    echo "running=0"
    echo "state=off"
    exit 0
fi
echo "running=1"

read -r cpu rss <<<"$(ps -o pcpu=,rss= -p "$pid" 2>/dev/null)"
echo "cpu=${cpu:-0}"
echo "rss=$(( ${rss:-0} / 1024 ))"
if [ -n "$hpid" ]; then
    echo "host_cpu=$(ps -o pcpu= -p "$hpid" 2>/dev/null | tr -d ' ')"
fi

# `grep -c` PRINTS 0 and ALSO exits non-zero when it finds nothing, so the old
# `$(grep -ac ... || echo 0)` here yielded "0\n0" and every [ -gt ] below then
# failed with "integer expression expected". It happened to fall through to
# `booting`, which is the right answer for a count of 0, so it never showed -
# but it is the same trap alive.sh documents for pgrep and it is fixed now.
gst=""
[ -r "$LOG" ] && gst=$(grep -ac 'gst\] factory_make' "$LOG" 2>/dev/null)
gst=${gst:-0}
if [ "$gst" -gt 10 ]; then echo "state=running"
elif [ "$gst" -ge 3 ]; then echo "state=techalerts"
else echo "state=booting"; fi

# Whether the auto-advance helper is still working on it. The tab uses this to
# say "advancing on its own" rather than "press a switch yourself", which is
# the difference between a wait and a job for the human.
echo "auto=$(n -f autoattract.sh)"

# The renderer prints its rate every 2 s; take the most recent.
f=$(grep -ao '[0-9.]* fps' /home/david/padglhost.log 2>/dev/null | tail -1)
[ -n "$f" ] && echo "fps=${f% fps}"

# Audio comes from the PAD_AUDIO_DUMP line, which watch.sh only emits when
# PAD_AUDIO_DUMP is set; blank is "not being sampled", not "no audio".
a=$(grep -a '\[aud\] ---' "$LOG" 2>/dev/null | tail -1)
if [ -n "$a" ]; then
    echo "pcm=$(sed -n 's/.*played=\([0-9]*\).*/\1/p' <<<"$a")"
    echo "drop=$(sed -n 's/.*dropped=\([0-9]*\).*/\1/p' <<<"$a")"
fi
exit 0
