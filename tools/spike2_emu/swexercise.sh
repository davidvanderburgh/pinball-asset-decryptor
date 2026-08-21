#!/bin/bash
# swexercise.sh <log> - run swexercise.py ONCE per boot, at the right moment.
#
# Item 59. The Tech Alerts `CHECK SWITCH #n` rows are the game's own no-usage
# audit, and MEASURED 2026-08-21 they are rebuilt from nothing on every boot:
# godzilla_pro read `active=37` on the switch-alert provider, an exercise took
# it to 0 and the glass said "No Technician Alerts", and the very next boot read
# 37 again. So this is a per-boot job, not a one-time repair - which is exactly
# what David said it would be.
#
# WHEN. As soon as the game's own switch table has been read, which is the
# precondition for the audit existing at all, plus a settle. That is EARLY, at
# Tech Alerts, and deliberately so: the alerts are then already gone by the time
# autoattract.sh walks past that screen, so nobody ever sees them.
#
# WHY IT CANNOT DISTURB autoattract.sh, checked rather than assumed - all three
# of that script's predicates are blind to this:
#   probes()   counts 'ExchangeData: read failed', a node-bus bring-up line
#   past()     keys on the attract light show
#   operator() matches source letters f/k/p only - the playfield window, the
#              game window's keyboard, its buttons. This tags its edges `x`,
#              which is not in that set, so an unattended boot does not stand
#              down. That alphabet is exactly what it is for.
#
# ITS OWN LOG, like autoattract's and the ball feeder's, and NOT $LOG: $LOG is
# the guest's, watch.sh truncates it and several readers grep it.
. "$(dirname "$0")/padpath.sh"
set -u

LOG=${1:-$HOME/gzwatch.log}
S="$RIG"
WAIT_MAX=${PAD_SW_EXERCISE_WAIT:-180}
SETTLE=${PAD_SW_EXERCISE_SETTLE:-5}

up()     { pgrep -x game >/dev/null 2>&1; }
# The shim prints these when it reads (or finds) the game's switch table, which
# is what swtable.py is built on. The audit is per-switch, so the table being
# known is the honest "the game has switches now" signal - and it arrives about
# a quarter of the way into the boot, long before the first alert is countable.
table() { grep -aq '\[sw\] id=' "$LOG" 2>/dev/null; }

echo "[swx] waiting for the game's switch table"
waited=0
while [ "$waited" -lt "$WAIT_MAX" ]; do
    up || { echo "[swx] the game is not running; nothing to do"; exit 0; }
    table && break
    sleep 1
    waited=$((waited + 1))
done
table || { echo "[swx] gave up after ${WAIT_MAX}s: no switch table in $LOG"; exit 1; }

echo "[swx] switch table seen after ${waited}s; settling ${SETTLE}s"
sleep "$SETTLE"
up || { echo "[swx] the game exited during the settle"; exit 0; }

exec python3 "$S/swexercise.py"
