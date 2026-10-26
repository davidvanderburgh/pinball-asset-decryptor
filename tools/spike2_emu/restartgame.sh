#!/bin/bash
# restartgame.sh - Restart game (PAD-738): boot the running game again, as
# switching the machine off and on does, inside the run that is up.
#
#   wsl -u root -e env HOME=<desktop home> bash restartgame.sh
#
# The game window and the virtual playfield STAY OPEN: watch.sh's own poll loop
# does the reboot (reboot_game there, which says what it puts back and why).
# This script only asks it, through dump/reboot.req, and says whether a session
# took the request - watch.sh removes the file the moment it sees it.
#
# Exit 0: taken, the game is booting again. 1: no run is up on this rig (or the
# rig is another session's). 3: a run is up but no session took the request in
# 10 s - the app then falls back to Stop and Start.
. "$(dirname "$0")/padpath.sh"
if [ ! -d /proc/1 ] || ! grep -qs . /proc/1/comm 2>/dev/null; then
    echo "restartgame.sh: this is not a Linux shell - nothing here can see the rig." >&2
    exit 2
fi
# THE LEASE (riglock.sh): restarting a game another session is using is
# ending its run as surely as a Stop would - refused, as killgame.sh refuses.
pad_slot_use restart || exit 1
if [ -z "$(pad_pids -x padglhost)" ]; then
    echo "restartgame: no emulator is running on this rig"
    exit 1
fi
REQ=$ROOT/dump/reboot.req
: > "$REQ" || { echo "restartgame: cannot write $REQ"; exit 1; }
for _ in $(seq 1 40); do
    if [ ! -e "$REQ" ]; then
        echo "[restartgame] the run took it: the game is booting again"
        exit 0
    fi
    sleep 0.25
done
rm -f "$REQ"
echo "restartgame: the run did not take the request in 10 s"
exit 3
