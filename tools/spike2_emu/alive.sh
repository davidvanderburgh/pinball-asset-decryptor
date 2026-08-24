#!/bin/bash
# alive.sh - say what of the rig is actually still running, CORRECTLY.
#
# ** RUN THIS INSIDE WSL. `wsl -e bash .../alive.sh`, never from Git Bash. **
#
# 2026-08-06, and this one cost two hours and a whole measurement run. Git Bash
# on Windows has a `pgrep` that sees only WINDOWS processes, so every pattern
# below matches nothing and this script prints
#     TOTAL STILL RUNNING : 0  (clean)
# over a rig that is entirely live. killgame.sh run the same way fails outright
# ("pkill: command not found") - which is at least loud - but alive.sh was
# silently, confidently wrong, and on the strength of it a SECOND full run was
# started on top of the first: two guests, two padglhosts and two padvidhosts
# sharing one 96 MB ring. That is the "never run two measurement runs at once"
# rule broken by the very script that is supposed to enforce it.
#
# A wrong answer here is worse than no answer, because the whole rig treats
# this script as the definition of "clean". So it refuses to answer at all
# unless it can see /proc, which is the one thing that distinguishes a real
# WSL shell from Git Bash pretending to be one.
if [ ! -d /proc/1 ] || ! grep -qs . /proc/1/comm 2>/dev/null; then
    echo "alive.sh: this is not a Linux shell - /proc is not readable." >&2
    echo "  Run it inside WSL:  wsl -e bash \$0" >&2
    echo "  (Git Bash's pgrep sees only Windows processes and would report" >&2
    echo "   a confident 0 over a fully live rig. That has happened.)" >&2
    exit 2
fi
#
# THE RULE THIS SCRIPT EXISTS FOR: a process nothing counts is a process that
# leaks. It has been broken twice by the same mechanism - the rig grew a new
# part, nobody added it here, and this script then reported "clean" over a leak.
#
# 2026-08-05, the second time and the worst: it printed
#     TOTAL STILL RUNNING : 0  (clean)
# with SEVEN leaked Windows-interop stubs for playfield.py (oldest 2.5 h) and
# THREE orphaned fuse2fs card mounts live on the machine. Both classes were
# invisible because this script only ever counted the five shapes it knew.
# "alive.sh must print 0 after every run" is only as strong as what it counts,
# so the list below is now the FULL set of things a run starts, and killgame.sh
# no longer keeps its own copy of it - it asks this script (`--total`).
#
# WHEN YOU ADD A PROCESS TO THE RIG, ADD IT HERE FIRST. Not after it leaks.
#
# ---------------------------------------------------------------------------
# Why pgrep, and why these patterns:
#
# binfmt_misc is registered with the P flag, so the kernel builds argv as
#     [interpreter] [the path] [original argv0] ...
# A control run of an unrelated ARM binary invoked as './busybox' gives
#     /usr/libexec/qemu-binfmt/arm-binfmt-P ./busybox ./busybox sleep 3
# i.e. a RELATIVE path, which would indeed never contain 'godzilla_pro/game'.
# But the REAL game, measured while it was running, gives
#     /usr/libexec/qemu-binfmt/arm-binfmt-P /games/godzilla_pro/game ./game
# an ABSOLUTE one, which matches fine. The control test was not the real thing,
# and generalising from it produced a confident wrong conclusion.
#
#   - comm is the basename of the original binary, so `pgrep -x game` matches
#     exactly one thing and cannot be fooled by path shape at all.
#   - `pgrep -f godzilla_pro/game` also matches any SHELL whose command line
#     happens to contain the string - including the one running the check.
#     Measured live: `pgrep -cf godzilla_pro/game` said 2 with one game up.
#     That is why every -f pattern here is ANCHORED or comm-exact.
#   - pgrep is used rather than ps|grep because pgrep excludes itself; a `ps -eo
#     args | grep` pipeline matches its own shell's command line and reports
#     phantom hits.
set -u

# padpath.sh supplies $PAD_HOME for the feed/tail patterns below. It was
# referenced without being sourced (9d25782), so a BARE invocation - which is
# exactly how the non-negotiable says to run this script - died at the helpers
# row under set -u: the $(...) subshell aborted and the row printed a hollow 0.
# A counter that reads 0 because it crashed is the exact failure this script
# exists to not have (its own words, forty lines down). killgame.sh, the
# sibling, has sourced it at the top all along.
. "$(dirname "$0")/padpath.sh"

# --total  : the number only. Everything a run leaves behind, mounts included.
#            This is the "is the machine clean" answer; killgame.sh uses it.
# --procs  : the number only, WITHOUT card mounts. This is the "is a run up"
#            answer, which status.sh feeds to the app's Start/Stop button - and
#            an idle card mount must not make that button say Stop.
ONLY=""
case "${1:-}" in --total|--procs) ONLY=$1 ;; esac

# `pgrep -c` PRINTS 0 and ALSO exits non-zero when nothing matches, so the
# obvious `pgrep -c ... || echo 0` emits "0\n0" and every arithmetic use of it
# then dies with a syntax error. Take the printed value and only default it if
# pgrep produced nothing at all.
n() { local c; c=$(pgrep -c "$@" 2>/dev/null); echo "${c:-0}"; }

GAME=$(n -x game)
# arm-binfmt is WSL's interpreter name; qemu-arm covers a container whose
# binfmt rewrites argv with its own qemu path. On a platform where neither
# appears (the guest exec'd with no interpreter on its command line), GAME
# alone carries the count - comm=game holds everywhere measured.
QEMU=$(n -f 'arm-binfmt|qemu-arm')
HOST=$(n -x padglhost)
BUS=$(n -f nodebus.py)

# The audio player is the FIFTH thing a run starts, and there are three shapes
# of it because the rig has three sinks:
#
#   windows sink (the default on WSL): padrelay.py serving the fifo over TCP to
#                a NATIVE WINDOWS python running padplay.py.
#   native sink (macOS, Linux): padplay.py reading the fifo directly.
#   pulse sink (fallback): an ffmpeg draining the fifo into WSLg's PulseAudio.
#
# Matching only the old ffmpeg shape once made this print "audio player: 0"
# while the relay and a Windows player were both up. The ffmpeg pattern is
# ^-anchored and matched on the FIFO, not on '-f pulse': when playaudio.sh's
# command line was severed (the comment-inside-a-continuation bug), the broken
# player had no '-f pulse' in it at all, and two of them sat on the fifo for
# hours of CPU while this script reported 0. Match what the player cannot run
# without. playaudio.sh is counted too: it owns the fifo and the Windows child.
AUD=$(n -f '^ffmpeg .*audio\.fifo')
AUD=$((AUD + $(n -f 'padrelay\.py') + $(n -f 'padplay\.py') + $(n -f 'playaudio\.sh')))

# The video host: the guest has no H.264 decoder, so a host-side ffmpeg pump
# publishes I420 frames into a shared ring. watch.sh kills it in teardown and
# this script never counted it - a leaked one holds an ffmpeg per clip.
VID=$(n -f 'padvidhost\.py')

# The helpers a watch.sh run starts and kills: the Tech-Alerts advancer, and
# the `tail -F | awk` event feed. An orphaned `tail -F` never exits by itself,
# which is exactly the shape that hides here forever.
#
# longplay.sh is counted here too even though watch.sh does not start it. It is
# started BESIDE a run, it pokes switches on a timer, and a leaked one would go
# on pressing ramp optos into the NEXT run - a fault that would look like the
# game doing something by itself. It exits when the guest goes away, so a
# nonzero count here means that check failed.
#
# `^bash [^ ]*longplay\.sh` and NOT `longplay\.sh`, and this script's own header
# says why: the loose pattern matched the interactive shell that merely had the
# name on its command line, and alive.sh then reported 1 with the machine
# genuinely clean. A false positive is as corrosive as a false negative here -
# "alive.sh must print 0 after every run" is worthless if it cannot. The
# character class is what rejects a wrapper (`bash -lc '... bash longplay.sh'`)
# while still matching the real `bash /path/to/longplay.sh`.
# mktables.py is counted here too. watch.sh starts one in the BACKGROUND on a
# title that already has artwork - it opens the window immediately and lets the
# switch table finish behind it - and that builder sits in a poll loop waiting
# for the guest to publish. A run that ends first leaves it waiting for
# something that will never come, which is exactly the shape of every leak this
# script exists to catch.
# The PAD_PIVOT game-log tail is counted here too. A pivot run's guest logs to
# $ROOT/dump/game.out and watch.sh folds it into $LOG with `tail -F`; an
# orphaned one holds the file forever, the same shape as the event-feed tail.
# ballfeed.py (item 21b) is counted from the day it was written, which is this
# script's standing rule. It answers the game's trough eject by driving switch
# ids, so a leaked one would take balls out of the NEXT run's trough - the same
# shape as a leaked longplay.sh and just as hard to read from the game's side.
# It exits by itself when dump/padled goes away; a nonzero count here means
# that check failed.
# $PAD_HOME and not $HOME on the feed pattern - see padpath.sh. Run as root
# (which is how the app asks) $HOME is /root and this counted zero feeds however
# many were running. It mattered less here than in killgame.sh, which used the
# same wrong path to KILL, but a counter that reads 0 because it looked in the
# wrong place is the exact failure this script exists to not have.
# swexercise.sh / swexercise.py (item 59) are counted from the day they were
# written, which is this script's standing rule. The shell half sleeps in a
# poll loop waiting for the guest's switch table, so it outlives a run that
# ends first - the same shape as mktables.py; the python half then drives ~44
# switch ids, so a leaked one would be pressing switches into the NEXT run,
# which is the leaked-ballfeed shape and just as hard to read from the game's
# side. BOTH patterns, because the shell can be waiting with no python yet.
HELP=$(( $(n -f 'autoattract\.sh') + $(n -f "^tail -q -n 0 -F $PAD_HOME/padvid\.log") \
         + $(n -f '^tail -F .*dump/game\.out') + $(n -f 'ballfeed[.]py') \
         + $(n -f '^bash [^ ]*longplay\.sh') + $(n -f 'mktables[.]py') \
         + $(n -f 'swexercise\.sh') + $(n -f 'swexercise[.]py') ))

# ★ WINDOWS-INTEROP STUBS - the class that leaked seven deep unseen.
#
# The virtual playfield is a WINDOWS program (this WSL has no GUI toolkit), so
# watch.sh launches it through interop. Inside the VM that appears as a process
# whose comm is the Windows image name and whose argv[0] is /init:
#     /init /mnt/c/Python314//pythonw.exe pythonw.exe C:\...\playfield.py <game>
# It is the WSL-side representative of the Windows process, and it is supposed
# to exit when that process does. MEASURED: it does not always. Seven were
# found sitting in poll() with no Windows process behind them at all - their
# session's interop Relay had already died, so the notification that would end
# the poll can never arrive. They are ordinary processes and SIGKILL clears
# them; nothing was killing them because nothing was looking.
#
# Anchored on '^/init ' so this matches the STUB and not a shell whose command
# line merely mentions the script (the documented pgrep trap, one line up).
# ...and on a LINUX desktop there is no stub, because there is no boundary: the
# playfield is an ordinary local python3 process. Counting only the interop
# shape would have printed a confident 0 over a live playfield window on every
# Linux machine, which is the exact failure this script exists to prevent.
# Both patterns are counted always; only one of them can match on any machine.
STUB=$(n -f '^/init .*playfield\.py')
STUB=$((STUB + $(n -f '^python3? .*playfield\.py')))

# The run scripts themselves. Four leaked watch.sh trees once sat on the
# playfield launch line before anyone noticed, because the symptom of a leaked
# run script is "it looks like it is still starting up".
#
# MINUS OUR OWN CALL CHAIN - the WHOLE chain, not just $PPID. watch.sh's
# teardown and ensurebuild.sh's "is a run live?" both ask this script about
# the very run they belong to, and the second one asks through a command
# substitution: `$( )` interposes a subshell, so alive.sh's $PPID was that
# subshell and the exclusion missed. watch.sh then COUNTED ITSELF, every
# fresh machine answered "a run is still up" at the exact moment
# ensurebuild.sh asked, and the guest GL bridge was never built - which on
# macOS meant Stern's own libGLESv2 stayed in the rootfs and the game drew
# nothing, run after run, with killgame.sh unable to clear it because the
# next start self-matched the same way. Walking every ancestor is right in
# both directions: a watch.sh that is ASKING cannot be evidence of a second
# run, and a watch.sh that is not an ancestor still counts - that is how the
# app's status poll sees a live run. The walk must reach PID 1: in the macOS
# container watch.sh IS PID 1.
ANC=$PPID
_p=$PPID
while :; do
    _p=$(ps -o ppid= -p "$_p" 2>/dev/null | tr -d ' ')
    case "$_p" in ''|0) break ;; esac
    ANC="$ANC
$_p"
done
SCRIPT=$(pgrep -f '^bash .*(watch|runbridge|nbrun|run_game|cardmount)\.sh' 2>/dev/null \
         | grep -cvxF "$ANC")
SCRIPT=${SCRIPT:-0}

# The guest's unshare wrapper - run_game.sh's `unshare $USERNS -m -p -f`, the
# process that owns the guest's namespaces and is supposed to reap it and
# exit. 2026-08-09, the third instance of this script's founding rule: TWO of
# these sat uncounted for half an hour, each holding a dead guest as a
# zombie, and their -m namespaces were what kept the card mounts alive
# through killgame.sh's unmount pass. run_game.sh joined the SCRIPT pattern
# above the same day. The `(-r )?` is because a root PAD_PIVOT run drops the
# user namespace; restorestate.sh's `unshare -m bash` has no -p and is not
# this.
UNSH=$(n -f '^unshare (-r )?-m -p -f')

# ★ CARD MOUNTS - the other class that leaked. cardmount.sh setsid's fuse2fs on
# purpose (a run's process-group kill used to take the mount out from under the
# game it had just started, and the game then hung at "Startup In Progress"
# forever with no error anywhere), so nothing in a teardown ever reached it.
# A mount is cheap to remake - the expensive part, the local image cache, is a
# FILE and survives - so an idle one after a run is a leak, not a cache.
CARD=$(n -x fuse2fs)

# Zombies are NOT added to the total: a defunct process is already gone, it
# just has not been reaped, and counting them once made runbridge.sh report
# survivors that did not exist. They are reported because of what they mean -
# see the note printed below.
#
# Filtered to RIG comms on purpose: WSL leaves a `[SessionLeader] <defunct>`
# under /init after ordinary session exits, and a check that shouts about that
# is a check people learn to ignore.
ZOMB=$(ps -eo stat,comm --no-headers 2>/dev/null \
       | awk '$1 ~ /^Z/ && $2 ~ /^(game|padglhost|fuse2fs|ffmpeg|pythonw\.exe|python3?)$/' | wc -l)

PROCS=$((GAME + QEMU + HOST + BUS + AUD + VID + HELP + STUB + SCRIPT + UNSH))
TOTAL=$((PROCS + CARD))

case "$ONLY" in
    --total) echo "$TOTAL"; exit 0 ;;
    --procs) echo "$PROCS"; exit 0 ;;
esac

printf 'guest (comm=game)      : %s\n' "$GAME"
printf 'qemu  (arm-binfmt)     : %s\n' "$QEMU"
printf 'host  (padglhost)      : %s\n' "$HOST"
printf 'node bus (nodebus.py)  : %s\n' "$BUS"
printf 'audio player           : %s\n' "$AUD"
printf 'video host (padvidhost): %s\n' "$VID"
printf 'helpers (attract/feed) : %s\n' "$HELP"
printf 'playfield (win stub)   : %s\n' "$STUB"
printf 'run scripts (watch.sh) : %s\n' "$SCRIPT"
printf 'guest wrapper (unshare): %s\n' "$UNSH"
printf 'card mounts (fuse2fs)  : %s\n' "$CARD"
printf 'TOTAL STILL RUNNING    : %s%s\n' "$TOTAL" \
  "$( [ "$TOTAL" -eq 0 ] && echo '  (clean)' || echo '  <-- run killgame.sh' )"

if [ "$TOTAL" -ne 0 ]; then
  echo '--- what is still up ---'
  ps -eo pid,pcpu,etime,comm,args --sort=-pcpu \
    | grep -E 'arm-binfmt|qemu-arm-static|padglhost|nodebus\.py|audio\.fifo|padrelay\.py|padplay\.py|padvidhost\.py|autoattract\.sh|longplay\.sh|playfield\.py|mktables\.py|watch\.sh|run_game\.sh|unshare -|fuse2fs|game\.out' \
    | grep -v grep | head -12
  mountpoint -q "$PAD_HOME/card" 2>/dev/null
  mount 2>/dev/null | grep 'fuse.ext4' | sed 's/^/  mount: /'
fi

# A zombie cannot be killed - only reaped - and when its parent is a WSL
# interop Relay (/init), the parent ignores SIGKILL from inside the VM too.
# killgame.sh reported "killed 0; still running: 1" against exactly this and
# gave up without saying that no signal could ever fix it. Say it here.
if [ "${ZOMB:-0}" -ne 0 ]; then
  echo "zombies (cannot be killed, only reaped): $ZOMB"
  ps -eo pid,ppid,stat,comm --no-headers 2>/dev/null \
    | awk '$3 ~ /^Z/ && $4 ~ /^(game|padglhost|fuse2fs|ffmpeg|pythonw\.exe|python3?)$/ {print "  " $0}'
  echo "  A zombie held by a WSL interop Relay(/init) will NOT clear: the relay"
  echo "  ignores SIGKILL from inside the VM. The only cure is, from Windows:"
  echo "      wsl --shutdown"
fi
exit 0
