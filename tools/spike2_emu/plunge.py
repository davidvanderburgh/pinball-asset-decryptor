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
  plunge  the three steps above. The switch it OPENS is the one at the FAR end
          of the trough, not the eject end - ballmodel.py has the ramp rule,
          and what opening the wrong end did to the game (item 20).
  drain   a ball in play comes home: the lowest-numbered OPEN trough position
          closes. The other half of a plunge, and the only way a multiball
          can end, because nothing here simulates a playfield.
  reset   put six balls back in the trough and shut the coin door - the
          machine-at-rest set, same as swinit.py.

ballfeed.py NOW DOES THE FIRST OF THESE BY ITSELF when a run is up: it watches
the game's own trough eject coil and answers it, which is what makes multiball
possible. This script stays the hand-driven way to move a ball, and both go
through ballmodel.py so they cannot disagree about which switch moves.

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

import ballmodel
import gameinfo
import padsw

padsw.set_source('l')   # who the [sw] log says moved a switch;
                        # PAD_SW_SRC overrides. See padsw.h.

PATH = padsw.PATH
MAGIC = padsw.MAGIC
#: Reads answer "where is the ball as far as the GAME is concerned", so they
#: come from the merged array; writes go to the script array. Kept as
#: module-level names because coilact.py uses them.
OFF_GEN, OFF_HELD, OFF_MRG = padsw.OFF_SCR_GEN, padsw.OFF_SCR_HELD, padsw.OFF_MRG

#: GODZILLA PRO'S IDS, AND FOR A LONG TIME EVERY TITLE'S, WHICH IS WHY NO OTHER
#: TITLE COULD START A GAME. These ids are per title: Jaws's trough is 60..65
#: where Godzilla's is 66..71. Writing them down meant `reset` cheerfully
#: reported "six balls in the trough" while closing six switches Jaws does not
#: watch, and the game ball-searched for ever on LOCATING PINBALLS. They stay
#: here as the FALLBACK for a title whose switch list cannot be read at all.
_GZ = dict(start=36, shooter=62, jam=72, coin=39, door=33,
           trough=(71, 70, 69, 68, 67, 66))

#: What each one is CALLED. The name is the portable identifier - the id is not -
#: and swnames.py now fills these in even on a title whose own dump says `?`.
_WANT = dict(start="START BUTTON", shooter="SHOOTER LANE", jam="TROUGH JAM",
             coin="LEFT COIN", door="COIN DOOR POWER INTERLOCK")
#: Trough 1 is nearest the eject; see do_plunge() for why the END matters.
_TROUGH_NAMES = ["TROUGH %d" % n for n in range(1, 7)]


def _resolve():
    """Look the ids up in THIS title's switch list, falling back to Godzilla's.

    Silent on failure on purpose: a missing table must not stop a Godzilla run
    working the way it always has, and every caller here prints what it did.
    """
    ids = dict(_GZ)
    try:
        path = gameinfo.table("switch_list.txt")
        by_name = {}
        for line in open(path):
            if line.startswith("#"):
                continue
            f = line.split(None, 4)
            if len(f) >= 5:
                by_name[f[4].strip().upper()] = int(f[0])
    except (OSError, TypeError):
        return ids
    for key, name in _WANT.items():
        if name in by_name:
            ids[key] = by_name[name]
    got = [by_name[n] for n in _TROUGH_NAMES if n in by_name]
    if len(got) == 6:
        ids["trough"] = tuple(got)
    return ids


_IDS = _resolve()
START, SHOOTER, TROUGH_JAM = _IDS["start"], _IDS["shooter"], _IDS["jam"]
COIN = _IDS["coin"]                      # Left Coin, the "5" key in the legend
TROUGH = _IDS["trough"]                  # Trough 1..6; 1 is nearest the eject
REST = (_IDS["door"],) + TROUGH          # coin door shut, six balls loaded

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


def _model():
    """This title's trough as ballmodel sees it - positions in trough order.

    WHICH END A BALL LEAVES FROM IS NOW STATED IN ONE PLACE, and it used to be
    stated here, in a comment, in a `reversed()`. That is the fact item 20 was
    a bug in, ballfeed.py needs the same answer forty times a second, and the
    rig's standing rule is that a fact with two homes drifts rather than
    breaks. ballmodel.Trough carries the ramp rule; the long form of WHY the
    far end is the one that opens is in its docstring.
    """
    return ballmodel.Trough([dict(pos=i + 1, id=s, name="TROUGH %d" % (i + 1))
                             for i, s in enumerate(TROUGH)])


def _mrg(m):
    return m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID]


def do_plunge(m):
    padsw.take(m, TROUGH + (SHOOTER,))
    plan = ballmodel.plan_eject(_model(), _mrg(m), SHOOTER, _held(m, SHOOTER),
                                STEP_S)
    if plan.refused:
        print("%s - run `plunge.py reset` first" % plan.refused)
        return 1
    for step in plan.steps:
        if step[0] == "wait":
            time.sleep(step[1])
            continue
        _set(m, step[1], step[2])
        print(step[3])
    # The ball then WAITS in the lane, and the launch is its own step: on a
    # real machine the player decides when, and now that ballfeed.py answers
    # the game's auto plunger there are two other things that may do it first.
    time.sleep(LANE_S)
    _set(m, SHOOTER, 0)
    print("shooter lane opened (ball launched)")
    return 0


def do_drain(m):
    """A ball in play drains home. The other half of a plunge, and new.

    NOTHING SIMULATES THE PLAYFIELD, so a ball that has left the shooter lane
    is in play until something says otherwise - and until this existed nothing
    could say otherwise, so a multiball could start and never end and the
    game's ball counter would walk away from the trough's. The switch that
    closes is the LOWEST-numbered OPEN position: a returning ball rolls to the
    back of the stack, which is the same ramp rule as the eject read the other
    way round.
    """
    padsw.take(m, TROUGH)
    plan = ballmodel.plan_drain(_model(), _mrg(m))
    if plan.refused:
        print(plan.refused)
        return 1
    for step in plan.steps:
        _set(m, step[1], step[2])
        print(step[3])
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
    elif what == "drain":
        rc = do_drain(m)
    else:
        rc = do_plunge(m)
    m.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
