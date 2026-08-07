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
. "$(dirname "$0")/padpath.sh"
set -u
LOG=${1:-$HOME/gzwatch.log}
S=$RIG
# shellcheck source=gamestate.sh
. "$S/gamestate.sh"

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

# WHERE THE GAME IS. Asked of gamestate.sh, which is also what autoattract.sh
# asks, because these two used to disagree: with the game sitting in attract
# mode on its high-score screen, autoattract.sh said "past Tech Alerts after 3
# presses" while this script reported state=techalerts to the app, and the app
# is the one David reads. The rule that did it counted `gst] factory_make` and
# wanted more than ten; that count only ever exceeded ten because the video bug
# was rebuilding the pipeline 25 times a second, and a whole run now makes
# eight. See gamestate.sh for the full story - do not reinvent the count here.
echo "state=$(gs_state "$LOG")"

# Whether the auto-advance helper is still working on it. The tab uses this to
# say "advancing on its own" rather than "press a switch yourself", which is
# the difference between a wait and a job for the human.
echo "auto=$(n -f autoattract.sh)"

# ...AND HOW IT ENDED, which nothing reported until now. autoattract.sh exits
# after a fixed number of presses whether or not they worked, and it says so
# clearly in its own log - a log nobody reads while the app quietly shows the
# same state word forever. `auto=0` alone cannot tell "finished the job" from
# "gave up", and those need opposite things from the human. The last line of
# its log is the answer, so publish it.
#   ok      - it reached attract, or found the game already past
#   gaveup  - the presses did not clear it (the game may be on the service menu)
#   working - still going
#   none    - it was never started (Skip to attract mode unticked)
AUTOLOG=$HOME/padauto.log
if [ "$(n -f autoattract.sh)" != 0 ]; then
    echo "auto_result=working"
elif [ ! -r "$AUTOLOG" ]; then
    echo "auto_result=none"
elif grep -aq 'past Tech Alerts\|already past\|nothing to do' "$AUTOLOG"; then
    echo "auto_result=ok"
elif grep -aq 'presses did not clear it\|gave up' "$AUTOLOG"; then
    echo "auto_result=gaveup"
else
    echo "auto_result=none"
fi

# The renderer prints its rate every 2 s; take the most recent.
f=$(grep -ao '[0-9.]* fps' $HOME/padglhost.log 2>/dev/null | tail -1)
[ -n "$f" ] && echo "fps=${f% fps}"

# Audio comes from the PAD_AUDIO_DUMP line, which watch.sh only emits when
# PAD_AUDIO_DUMP is set; blank is "not being sampled", not "no audio".
a=$(grep -a '\[aud\] ---' "$LOG" 2>/dev/null | tail -1)
if [ -n "$a" ]; then
    echo "pcm=$(sed -n 's/.*played=\([0-9]*\).*/\1/p' <<<"$a")"
    echo "drop=$(sed -n 's/.*dropped=\([0-9]*\).*/\1/p' <<<"$a")"
fi
exit 0
