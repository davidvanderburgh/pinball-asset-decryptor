#!/bin/bash
# autoattract.sh [log] - carry the game from Tech Alerts to attract mode by
# itself, so a human does not have to sit through the boot and press Escape.
#
#   wsl -e bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/autoattract.sh /home/david/gzwatch.log
#
# watch.sh starts this automatically unless PAD_AUTO_ATTRACT=0.
#
# WHY THIS IS A PRESS AND NOT A SAVED STATE. The obvious idea is to remember
# "the alerts were already dismissed" in NVRAM. The NVRAM already persists -
# /data/nvram.bin is loaded and saved by the shim and survives restarts, the
# game formatted it itself - and the game STILL shows Tech Alerts on every boot,
# because that screen is not an acknowledgement flag. It is the boot-time
# readout of a live scan, and then it waits for an operator exactly as the
# machine on a location does. There is nothing to persist; the only thing to
# skip is the waiting, and the honest way to skip it is to be the operator.
#
# ONE PRESS, WHEN THE GAME IS ACTUALLY READY. The first version of this script
# pressed on a fixed 3 s timer until the game moved, which took four to eleven
# presses. That was wrong three ways and all three were audible or visible:
#
#   - every press plays the machine's switch sound, so a boot sounded like
#     somebody hammering the service button.
#   - a press that lands AFTER the game has already left Tech Alerts is not
#     inert. It walks INTO the boot/service menu, and the game then sits on
#     `GODZILLA PRO / SERVICE MENU` instead of going to attract mode. The
#     "we sit on the next screen for a while" symptom was this script's own
#     doing, not a fault in the boot.
#   - hammering hides the thing worth knowing, which is WHEN the game becomes
#     willing. One press at the right moment goes straight to attract mode -
#     verified by holding once and then touching nothing: PLAYER 1, then the
#     high score reel.
#
# So: wait for the readiness signal, press ONCE, verify, and only retry - with a
# long gap - if it genuinely did not take.
#
# THE READINESS SIGNAL is the node bus timeout storm going quiet. Bring-up
# probes node 2, which a Godzilla Pro does not have, ~250 times; while that is
# running the game will not leave Tech Alerts, and every press is swallowed.
# The storm ends on its own (measured: it ends with nothing pressed at all), and
# the game accepts a press within a second of it stopping. `ExchangeData: read
# failed` is the game's own stderr, one line per probe, so "no new line for
# QUIET seconds" is a direct read of that state and needs no extra plumbing.
#
# THE SWITCH is Service Back (id 28, the one Esc is bound to). Service Select
# would be wrong - on Tech Alerts it starts the Node Bus Test.
#
# HOW LONG TO PRESS IT, measured one press per boot with presstest.sh:
#
#     60 ms  no      300 ms  1 of 2      600 ms  yes
#    150 ms  no      400 ms  yes        1600 ms  yes
#                    500 ms  2 of 2  <- default
#
# 1600 ms was the old default and it is why a boot sounded like
# "................": the game auto-repeats its menu tick for as long as a
# service button is down, so ONE long hold is a burst of ticks and reads as a
# frozen UI. 500 ms is comfortably clear of the 150 ms floor, marginal only at
# 300, and short enough not to repeat.
#
# THE OLD COMMENT HERE SAID "a tap does nothing, it must be HELD". THAT WAS
# WRONG and it is worth knowing why, because the measurement was real. The tap
# that "did nothing" was tried on a run with PAD_NB_LOG raised, where the
# bring-up storm ran for 125 s instead of ~19 s; it landed just before the game
# was ready and the hold that followed landed just after. Press LENGTH was
# confounded with READINESS, and the conclusion drawn was about the wrong
# variable. Once readiness is detected properly, 300-500 ms is plenty.
set -u

LOG=${1:-/home/david/gzwatch.log}
S=$(dirname "$0")
SW=/home/david/spike2root/dump/padsw

BACK=28                              # Service Back == Esc in the legend window
HOLD=${PAD_AUTO_HOLD:-500}           # ms to press; see the table above
QUIET=${PAD_AUTO_QUIET:-2}           # s of bus silence that means "ready"
TRIES=${PAD_AUTO_TRIES:-5}           # presses before giving up and saying so
GAP=${PAD_AUTO_GAP:-6}               # s between presses if one does not take
WAIT_MAX=${PAD_AUTO_WAIT:-240}       # s to wait for the game to boot

# `grep -c` PRINTS 0 and ALSO exits non-zero when it finds nothing, so the
# obvious `$(grep -c ... || echo 0)` yields "0\n0" and every arithmetic use of
# it then dies with "integer expression expected". Take grep's own printed
# count and only default it if grep produced nothing at all. Same trap alive.sh
# documents for pgrep.
count() {
    local c=""
    [ -r "$LOG" ] && c=$(grep -ac "$1" "$LOG" 2>/dev/null)
    echo "${c:-0}"
}
booted()  { [ "$(count 'gst\] factory_make')" -ge 3 ]; }
past()    { [ "$(count 'gst\] factory_make')" -gt 10 ]; }
probes()  { count 'ExchangeData: read failed'; }
up()      { pgrep -x game >/dev/null 2>&1; }
press()   { python3 "$S/swpoke.py" "$BACK" "$1" >/dev/null 2>&1; }

echo "[auto] waiting for the game to reach its boot screen"

waited=0
while [ "$waited" -lt "$WAIT_MAX" ]; do
    up || { echo "[auto] the game is not running; nothing to do"; exit 0; }
    booted && break
    sleep 1
    waited=$((waited + 1))
done
booted || { echo "[auto] gave up after ${WAIT_MAX}s: no boot screen"; exit 1; }

# Wait for the bus to go quiet. Sampled once a second; QUIET consecutive
# samples with no new probe means bring-up has stopped retrying.
#
# THE STORM HAS TO HAVE STARTED FIRST. The game reaches its boot screen at ~1 s
# and bring-up does not begin probing until ~7 s, so a naive "no new probes for
# 2 s" is TRUE before there is anything to be quiet about - it reported "bus
# quiet after 3s (0 probes)", pressed into the void, and needed a second press
# anyway. Which is the same bug as the fixed timer, just better disguised.
#
# NO_PROBE_MAX is the escape hatch: if the storm never appears at all (a future
# fix, or another title), stop waiting for something that is not coming and
# fall through to pressing.
echo "[auto] booted; waiting for node bus bring-up to stop retrying"
still=0
seen=0
last=$(probes)
[ "$last" -gt 0 ] && seen=1
nop=0
while [ "$waited" -lt "$WAIT_MAX" ]; do
    up || { echo "[auto] the game exited"; exit 0; }
    past && { echo "[auto] already past Tech Alerts; nothing to do"; exit 0; }
    sleep 1
    waited=$((waited + 1))
    now=$(probes)
    if [ "$now" != "$last" ]; then
        seen=1
        still=0
        last=$now
        continue
    fi
    if [ "$seen" = 0 ]; then
        nop=$((nop + 1))
        if [ "$nop" -ge "${PAD_AUTO_NO_PROBE_MAX:-25}" ]; then
            echo "[auto] no bring-up probes at all after ${nop}s; going anyway"
            break
        fi
        continue
    fi
    still=$((still + 1))
    [ "$still" -ge "$QUIET" ] && break
done

echo "[auto] bus quiet after ${waited}s ($last probes); pressing Service Back once (${HOLD}ms)"

for i in $(seq 1 "$TRIES"); do
    up || { echo "[auto] the game exited"; exit 0; }
    past && { echo "[auto] past Tech Alerts after $((i - 1)) presses"; exit 0; }
    [ -e "$SW" ] || { sleep 1; continue; }
    [ "$i" -gt 1 ] && echo "[auto] press $i (the last one did not take)"
    press "$HOLD"
    # Poll FAST after the press, so that the moment it works we stop. Checking
    # on the retry timer instead is what let an extra press land on the screen
    # after Tech Alerts and walk the game into the service menu.
    n=0
    while [ "$n" -lt "$GAP" ]; do
        sleep 0.5; sleep 0.5
        n=$((n + 1))
        past && { echo "[auto] past Tech Alerts after $i press(es)"; exit 0; }
    done
done

echo "[auto] $TRIES presses did not clear it - press Esc in the game window."
exit 1
