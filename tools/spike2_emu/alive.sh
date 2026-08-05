#!/bin/bash
# alive.sh - say what of the rig is actually still running, CORRECTLY.
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
QEMU=$(n -f arm-binfmt)
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

# The two helpers a watch.sh run starts and kills: the Tech-Alerts advancer,
# and the `tail -F | awk` event feed. An orphaned `tail -F` never exits by
# itself, which is exactly the shape that hides here forever.
HELP=$(( $(n -f 'autoattract\.sh') + $(n -f '^tail -q -n 0 -F /home/david/padvid\.log') ))

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
STUB=$(n -f '^/init .*playfield\.py')

# The run scripts themselves. Four leaked watch.sh trees once sat on the
# playfield launch line before anyone noticed, because the symptom of a leaked
# run script is "it looks like it is still starting up".
#
# MINUS OUR OWN CALLER. watch.sh's teardown ends by running this script, so a
# naive count reports the very run that is tidying itself up and this can never
# print clean from the one place that matters most. $PPID is that caller.
SCRIPT=$(pgrep -f '^bash .*(watch|runbridge|nbrun)\.sh' 2>/dev/null \
         | grep -cvx "$PPID")
SCRIPT=${SCRIPT:-0}

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

PROCS=$((GAME + QEMU + HOST + BUS + AUD + VID + HELP + STUB + SCRIPT))
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
printf 'card mounts (fuse2fs)  : %s\n' "$CARD"
printf 'TOTAL STILL RUNNING    : %s%s\n' "$TOTAL" \
  "$( [ "$TOTAL" -eq 0 ] && echo '  (clean)' || echo '  <-- run killgame.sh' )"

if [ "$TOTAL" -ne 0 ]; then
  echo '--- what is still up ---'
  ps -eo pid,pcpu,etime,comm,args --sort=-pcpu \
    | grep -E 'arm-binfmt|padglhost|nodebus\.py|audio\.fifo|padrelay\.py|padplay\.py|padvidhost\.py|autoattract\.sh|playfield\.py|watch\.sh|fuse2fs' \
    | grep -v grep | head -12
  mountpoint -q /home/david/card 2>/dev/null
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
