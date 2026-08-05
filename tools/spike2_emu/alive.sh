#!/bin/bash
# alive.sh - say what of the rig is actually still running, CORRECTLY.
#
# The rig's historic check, `grep -c 'godzilla_pro/game'`, DOES work. That was
# worth establishing properly, because a control test says otherwise and it is
# easy to convince yourself the check is broken.
#
# binfmt_misc is registered with the P flag, so the kernel builds argv as
#     [interpreter] [the path] [original argv0] ...
# A control run of an unrelated ARM binary invoked as './busybox' gives
#     /usr/libexec/qemu-binfmt/arm-binfmt-P ./busybox ./busybox sleep 3
# i.e. a RELATIVE path, which would indeed never contain 'godzilla_pro/game'.
# But the REAL game, measured while it was running, gives
#     /usr/libexec/qemu-binfmt/arm-binfmt-P /games/godzilla_pro/game ./game
# an ABSOLUTE path, which matches fine. The control test was not the real
# thing, and generalising from it produced a confident wrong conclusion.
#
# This script still exists, and is still better, for three reasons:
#   - comm is the basename of the original binary, so `pgrep -x game` matches
#     exactly one thing and cannot be fooled by path shape at all.
#   - `pgrep -f godzilla_pro/game` also matches any SHELL whose command line
#     happens to contain the string - including the one running the check.
#     Measured live: `pgrep -cf godzilla_pro/game` said 2 with one game up.
#   - the rig's checks only ever looked for the guest. An orphaned padglhost or
#     nodebus.py was invisible, and killgame.sh still does not touch either.
#
# pgrep is used rather than ps|grep because pgrep excludes itself; a `ps -eo
# args | grep` pipeline matches its own shell's command line and reports
# phantom hits (that is why the control test above appeared to find three
# 'godzilla_pro/game' processes when there were none).
set -u

# `pgrep -c` PRINTS 0 and ALSO exits non-zero when nothing matches, so the
# obvious `pgrep -c ... || echo 0` emits "0\n0" and every arithmetic use of it
# then dies with a syntax error. Take the printed value and only default it if
# pgrep produced nothing at all.
n() { local c; c=$(pgrep -c "$@" 2>/dev/null); echo "${c:-0}"; }

GAME=$(n -x game)
QEMU=$(n -f arm-binfmt)
HOST=$(n -x padglhost)
BUS=$(n -f nodebus.py)
# The audio player is the FIFTH thing a run starts, and the whole point of this
# script is that a process nothing counts is a process that leaks.
#
# Matched on the PulseAudio stream name, not on the fifo path: PAD itself runs
# ffmpeg constantly so `-x ffmpeg` would catch unrelated work, and `-f audio.fifo`
# also matches any shell whose command line happens to contain it - including the
# shell running this check, which is the exact trap documented above.
AUD=$(n -f 'ffmpeg.*-f pulse')
TOTAL=$((GAME + QEMU + HOST + BUS + AUD))

printf 'guest (comm=game)      : %s\n' "$GAME"
printf 'qemu  (arm-binfmt)     : %s\n' "$QEMU"
printf 'host  (padglhost)      : %s\n' "$HOST"
printf 'node bus (nodebus.py)  : %s\n' "$BUS"
printf 'audio player (ffmpeg)  : %s\n' "$AUD"
printf 'TOTAL STILL RUNNING    : %s%s\n' "$TOTAL" \
  "$( [ "$TOTAL" -eq 0 ] && echo '  (clean)' || echo '  <-- run killgame.sh' )"

if [ "$TOTAL" -ne 0 ]; then
  echo '--- what is still up ---'
  ps -eo pid,pcpu,etime,comm,args --sort=-pcpu \
    | grep -E 'arm-binfmt|padglhost|nodebus\.py|audio\.fifo' | grep -v grep | head -10
fi
exit 0
