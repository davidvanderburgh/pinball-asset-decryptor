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
# WHEN, AND THIS IS THE PART THAT WAS WRONG FIRST TIME. The first version fired
# as soon as the guest's switch table had been read, plus 5 s - boot+8 s - on
# the theory that clearing the rows before autoattract walked past that screen
# meant nobody ever saw them. It works on godzilla_pro, whose audit is already
# populated by boot+14 s, and it DOES NOT WORK on turtles_pro: David's run had
# all 50 switches exercised at boot+8 s (padswx.log, 99 tagged edges in the
# guest log) and the screen still listed twelve CHECK SWITCH rows a minute
# later. Running the identical exercise by hand at boot+4 min cleared every one
# of them. So the edges were landing BEFORE the game had built the audit, and
# an exercise before there is anything to clear is wasted.
#
# So it now waits for the game to be PAST Tech Alerts, which is the one moment
# the audit is provably built - the game has just rendered it. `autoattract.sh`
# exits exactly then, so waiting for that process to go is the whole test, and
# it deliberately does NOT re-implement that script's bus-quiet predicate: two
# copies of one fact is how this rig has been bitten before. With auto-advance
# off there is no such signal and it falls back to a plain longer wait.
#
# The cost of the change is that the rows ARE on the screen during the boot
# that clears them. That is the honest trade: the audit persists (measured
# godzilla run 3 -> run 4, active=0 on all 16 dumps of a boot with the
# exerciser off), autoattract walks past the screen in ~20 s anyway, and the
# window's own "Clear alerts" button is there for the impatient case.
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

echo "[swx] switch table seen after ${waited}s"

# PAST TECH ALERTS, which is when the audit is provably built - see the header.
# autoattract.sh exits the moment it gets there, so its absence IS the signal
# and this script never has to know how it decided. Waiting on the process
# rather than grepping padauto.log for a phrase, because that phrase is that
# script's to change.
if [ "${PAD_AUTO_ATTRACT:-1}" != 0 ]; then
    echo "[swx] waiting for autoattract.sh to get the game past Tech Alerts"
    waited=0
    while [ "$waited" -lt "$WAIT_MAX" ]; do
        up || { echo "[swx] the game is not running; nothing to do"; exit 0; }
        pgrep -f 'autoattract\.sh' >/dev/null 2>&1 || break
        sleep 1
        waited=$((waited + 1))
    done
    echo "[swx] auto-advance finished after ${waited}s"
else
    # No auto-advance means no signal, so this is a plain wait rather than a
    # measurement. Longer than the old 5 s on purpose: boot+8 s is the exact
    # value that was measured NOT to work on turtles_pro.
    echo "[swx] auto-advance is off; waiting ${PAD_SW_EXERCISE_BLIND:-60}s blind"
    sleep "${PAD_SW_EXERCISE_BLIND:-60}"
fi

up || { echo "[swx] the game exited while waiting"; exit 0; }
echo "[swx] settling ${SETTLE}s"
sleep "$SETTLE"
up || { echo "[swx] the game exited during the settle"; exit 0; }

exec python3 "$S/swexercise.py"
