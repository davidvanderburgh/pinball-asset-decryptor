#!/usr/bin/env python3
"""plunge.py [start|plunge|reset] - move a virtual ball the way the machine does.

There is no ball, so "plunging" means telling the game the switch story a real
plunge tells:

  the ball leaves the trough      one held trough switch OPENS   (66..71)
  it arrives in the shooter lane  Shooter Lane CLOSES            (62)
  the player plunges              Shooter Lane OPENS             (62)

  coin    drop a coin in the left chute (39). A machine with no credits
          IGNORES the Start button, silently - see do_coin().
  game    coin, start, plunge, in the order that actually works. Use this.
  start   pulse the Start button (36). The game then fires the trough eject
          itself, so run `plunge` a moment later to give it the ball. On its
          own this does NOT start a game unless there are credits.
  plunge  the three steps above, on the lowest-numbered trough ball still held.
  reset   put six balls back in the trough and shut the coin door - the
          machine-at-rest set, same as swinit.py.

TROUGH SWITCHES ARE LATCHED, NOT PULSED, which is the whole reason this is a
script and not three swpoke calls: a ball sitting in the trough holds its switch
closed for as long as it is there. swpoke.py pulses and would put the ball back.

The order matters and is not arbitrary: open the trough switch BEFORE closing
the shooter lane. A real ball cannot be in both places, and the game's ball
accounting notices.

WHY THERE IS A `take` CALL IN HERE. The trough is the one place the keyboard and
the scripts genuinely both hold state: padglhost latches all six balls on when
its window opens (B toggles them), and this script wants to take one out. The
guest merges the two arrays by LAST EDGE WINS, so writing a 0 into a script byte
that is already 0 would move nothing - `padsw.take` first copies the merged value
across, silently, so the write after it is a real edge. Before the arrays were
split this script "worked" by writing the keyboard's own array, and every key
press put the ball straight back in the trough.
"""
import sys
import time

import padsw

PATH = padsw.PATH
MAGIC = padsw.MAGIC
#: Reads answer "where is the ball as far as the GAME is concerned", so they
#: come from the merged array; writes go to the script array. Kept as
#: module-level names because coilact.py uses them.
OFF_GEN, OFF_HELD, OFF_MRG = padsw.OFF_SCR_GEN, padsw.OFF_SCR_HELD, padsw.OFF_MRG

START, SHOOTER, TROUGH_JAM = 36, 62, 72
COIN = 39                                # Left Coin, the "5" key in the legend
TROUGH = (71, 70, 69, 68, 67, 66)        # Trough 1..6; 1 is nearest the eject
REST = (33,) + TROUGH                    # coin door shut, six balls loaded

#: Long enough for the game's own ball-search and switch debounce to see each
#: step as a separate event rather than one glitch.
STEP_S = 0.45
LANE_S = 1.2


def _open():
    return padsw.open_block()


def _set(m, sw, val):
    padsw.set_held(m, sw, val)


def _held(m, sw):
    """What the GAME sees for `sw` - the merge, not either input."""
    return padsw.merged(m, sw)


def do_coin(m, n=1):
    """Drop `n` coins in the left chute.

    THIS IS THE STEP THAT WAS MISSING, AND IT COST ITEM 6 FIVE RUNS. Pressing
    Start on a machine with no credits does exactly nothing, and it does it
    SILENTLY: the switch reaches the game (the shim logs `+36` and `-36` at the
    asked-for duration), the game simply declines to start. Every instrument
    the rig had said the press was delivered, so "the press worked" and "a game
    started" looked like the same claim - and a whole run of scripted switch
    pokes then lands on ATTRACT MODE, scoring nothing and reaching no scene,
    while the log fills with switch events that all look correct.

    Measured 2026-08-05: three Start presses over ten minutes left the game in
    attract (screenshot-confirmed, and only video channel 0 ever streamed).
    Coins in, and a game came up shortly after - 4 players, a real score, and
    the TV-inset scene fired three times in the next fifteen minutes after
    about twenty-five scripted attempts had produced one sighting in total.
    """
    padsw.take(m, (COIN,))
    for _ in range(n):
        _set(m, COIN, 1)
        time.sleep(0.12)
        _set(m, COIN, 0)
        time.sleep(0.7)
    print("%d coin(s) in the left chute" % n)


def do_start(m):
    padsw.take(m, (START,))
    _set(m, START, 1)
    time.sleep(0.15)
    _set(m, START, 0)
    print("Start pressed")
    if not _held(m, COIN):
        print("  NOTE: a game needs CREDITS. If the game stays in attract, run"
              " `plunge.py coin` first - see do_coin().")


def do_plunge(m):
    padsw.take(m, TROUGH + (SHOOTER,))
    ball = next((s for s in TROUGH if _held(m, s)), None)
    if ball is None:
        print("no ball in the trough - run `plunge.py reset` first")
        return 1
    _set(m, ball, 0)
    print("trough switch %d opened (ball out)" % ball)
    time.sleep(STEP_S)
    _set(m, SHOOTER, 1)
    print("shooter lane closed (ball waiting)")
    time.sleep(LANE_S)
    _set(m, SHOOTER, 0)
    print("shooter lane opened (ball launched)")
    return 0


def do_reset(m):
    """The machine at rest, stated from the script side.

    This clears the SCRIPT array only. It cannot clear what the keyboard holds,
    and must not try: padglhost owns that half, and the merge would hand the
    keyboard's value straight back on its next publish. What it can do - and
    does - is assert the rest set as a genuine edge on every id in it, which is
    what makes the merge adopt it.

    ONE bump, after the whole array is staged. Clearing everything and then
    setting the rest set, with a publish between, would show the guest an empty
    trough for however long its next poll took - and its poll is sub-millisecond,
    so it would land there sooner or later and report a ball drain nobody caused.
    """
    padsw.take(m, REST)
    for s in range(1, padsw.MAX_ID):
        m[OFF_HELD + s] = 1 if s in REST else 0
    padsw.bump(m)
    print("six balls in the trough, coin door shut")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "plunge"
    m = _open()
    if m is None:
        return 1
    rc = 0
    if what == "start":
        do_start(m)
    elif what == "coin":
        do_coin(m, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    elif what == "game":
        # The whole "put a ball into play" story, in the order that works.
        do_coin(m)
        time.sleep(1.5)
        do_start(m)
        time.sleep(5)
        rc = do_plunge(m)
    elif what == "reset":
        do_reset(m)
    else:
        rc = do_plunge(m)
    m.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
