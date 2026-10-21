"""MASER BARRAGE (PAD-658): the C example maser_barrage.c rebuilt in blocks - a combo chain with a window.

The Maser cannons fire in sequence (the Maser tanks of the Showa and Heisei films): make the shots in order, each
one quickly after the last, and the multiplier climbs. Wait too long and the chain breaks.

- START: the Maser target 3 times in one ball (PAD-371: never the skill shot); once a ball per player. It waits out
  a multiball: the next Maser hit after it starts it.
- SEQUENCE: LEFT RAMP, then RIGHT RAMP, then the BUILDING; only the next shot counts: 1,000,000 x the multiplier.
- WINDOW: after a step the next must come within 7 s, or the CHAIN BREAKS: back to x1, the window back to 7 s, from
  the Left ramp again.
- BARRAGE: the third step is a JACKPOT of 5,000,000 x the multiplier; then the multiplier +1 (up to x5), the clock
  +5 s, the window 1 s shorter (down to 4 s).
- CLOCK: 40 s; a step that counts with under 10 s left puts it back to 10 s (PAD-371). It is WON with a barrage.
- INSERTS: the next shot bright Maser blue (steady with no window running, faster as the window closes); the other
  two pulse a dim blue.
"""
from blk import (AND, SECS_LEFT, a_show, add, add_time, award, callout, change, clip, clips, div, end, eq, every,
                 game_show, ge, gt, hud, hud_counter, hud_line, if_, le, light, lt, mul, on_end, on_shot, on_start,
                 on_timer, score, secs_left, set_, set_time, sound, sounds, start, step, timer_left, timer_start,
                 timer_stop, var, hits)

SLUG, NAME = "maser_barrage", "MASER BARRAGE"
BLUE, DIM, WHITE, RED = "#005aff", "#001e5a", "#ffffff", "#ff0000"   # the kit's KIT_BLUE, KIT_BLUE_DIM
MASER_BLUE, MASER_ICE = "#0078ff", "#8cdcff"
MASER_XY = (51, 417)                       # the port's lamp place: MASER
START_SHOT = "Maser target"
STEPS = (("Left ramp", "LEFT RAMP"), ("Right ramp", "RIGHT RAMP"), ("Building", "BUILDING"))
TIMERS = ("window", "lights")
WINDOW_LEFT = timer_left("window")

SHOWS = [
    # the C's own shows, its fallback where the card has no "Insert chase" / "Colour fade" (Godzilla has both)
    a_show("Maser start",
           step("strobe", 450, WHITE, MASER_BLUE, "xy", rate=55, gi="flash", x=MASER_XY[0], y=MASER_XY[1]),
           step("spin", 1600, MASER_ICE, "#000000", "xy", rate=110, gi="dark", x=MASER_XY[0], y=MASER_XY[1]),
           step("sweep_lr", 500, WHITE, MASER_BLUE, "center", gi="dark"),
           step("sweep_rl", 500, WHITE, MASER_BLUE, "center", gi="dark"),
           step("fade", 400, MASER_BLUE, "#000000", "center")),
    a_show("Maser won",
           step("implode", 800, WHITE, MASER_BLUE, "center", gi="dark"),                  # every beam on one spot
           step("strobe", 600, WHITE, "#000000", "center", rate=50, gi="flash"),
           step("chase", 1400, MASER_ICE, MASER_BLUE, "center", rate=45),
           step("fade", 500, MASER_BLUE, "#000000", "center")),
    a_show("Maser lost",
           step("sparkle", 700, RED, MASER_BLUE, "center", gi="dark"),                    # the tanks burning
           step("sweep_down", 900, MASER_BLUE, "#000000", "center", gi="dark"),
           step("fade", 500, MASER_BLUE, "#000000", "center")),
]


def jackpot_sub():
    """The MULTIPLIER counter's words: what a barrage pays now."""
    out = [hud_counter(1, var("mult"), "JACKPOT 25M")]
    for m in (4, 3, 2, 1):
        out = [if_(eq("mult", m), [hud_counter(1, var("mult"), "JACKPOT %dM" % (5 * m))], out)]
    return out


def chain_step(i):
    """Step ``i`` of the sequence, made in turn: its points, the window, the clock topped up."""
    shot, says = STEPS[i]
    body = [score(mul(1000000, var("mult"))),
            if_(lt(SECS_LEFT, 10), [set_time(10)])]                  # PAD-371
    if i < 2:
        body += [set_("step", i + 1), timer_start("window", var("window")),
                 award("%s X" % says, value=var("mult"), sub="NOW THE %s" % STEPS[i + 1][1], seconds=1),
                 hud_counter(3, div(add(WINDOW_LEFT, 999), 1000), "SECONDS")]
    else:
        nxt = [award("BARRAGE JACKPOT", value=mul(5000000, var("mult")), sub="NOW X5", seconds=3)]
        for m in (3, 2, 1):
            nxt = [if_(eq("mult", m), [award("BARRAGE JACKPOT", value=mul(5000000, var("mult")),
                                             sub="NOW X%d" % (m + 1), seconds=3)], nxt)]
        body += [score(mul(5000000, var("mult"))), change("barrages", 1), set_("maser won", 1), *nxt,
                 if_(lt("mult", 5), [change("mult", 1)]), if_(gt("mult", var("best")), [set_("best", var("mult"))]),
                 if_(gt("window", 4000), [change("window", -1000)]),
                 add_time(5), set_("step", 0), timer_stop("window"),
                 sound("barrage"), clip("barrage", "behind"),
                 *jackpot_sub(), hud_counter(3, 0, "NO CLOCK YET")]
    return on_shot(shot, if_(eq("step", i), body + [timer_start("lights", 1)]))


SCRIPTS = [
    # ---- the start: the Maser target three times in one ball --------------------------------------------------
    on_shot(START_SHOT, if_(eq("ran ball", 0), [
        if_(ge(hits(START_SHOT), 3), [start()], [
            if_(eq(hits(START_SHOT), 2), [award("MASER 2 OF 3", sub=NAME, seconds=2)],
                [award("MASER 1 OF 3", sub=NAME, seconds=2)])]),
    ]), when="idle"),
    on_start(set_("ran ball", 1), set_("maser played", 1),
             set_("mult", 1), set_("best", 1), set_("window", 7000),
             clip("intro", "full"), clip("loop", "loop"), game_show("Insert chase"),
             award(NAME, sub="LEFT RAMP  >  RIGHT RAMP  >  BUILDING", seconds=3),
             hud_counter(1, 1, "JACKPOT 5M"), hud_counter(3, 0, "NO CLOCK YET"),
             timer_start("lights", 1)),

    # ---- the chain ---------------------------------------------------------------------------------------------
    chain_step(0), chain_step(1), chain_step(2),
    on_timer("window",
             change("breaks", 1), set_("step", 0), set_("mult", 1), set_("window", 7000),
             award("CHAIN BROKEN", sub="BACK TO X1 - START AT THE LEFT RAMP", seconds=2),
             sound("broken"), clip("broken", "behind"),
             hud_counter(1, 1, "JACKPOT 5M"), hud_counter(2, var("barrages"), "CHAIN BROKEN"),
             hud_counter(3, 0, "NO CLOCK YET"), timer_start("lights", 1)),
    every(1, timer_start("lights", 1)),
    # the chain on the playfield: the next shot bright, blinking faster as its window closes; the rest dim
    on_timer("lights",
             set_("pace", 500),
             if_(gt("step", 0), [
                 if_(le(mul(WINDOW_LEFT, 10), mul(var("window"), 6)), [set_("pace", 250)]),
                 if_(le(mul(WINDOW_LEFT, 10), mul(var("window"), 3)), [set_("pace", 100)])]),
             *[if_(eq("step", i), [light(shot, BLUE, "blink", var("pace")), hud_line("SHOOT THE %s" % says)],
                   [light(shot, DIM, "pulse", 1600)]) for i, (shot, says) in enumerate(STEPS)]),
    secs_left(10, callout("ten_seconds")),

    # ---- the end: won with a barrage --------------------------------------------------------------------------
    on_end(*[timer_stop(t) for t in TIMERS],
           if_(eq(SECS_LEFT, 0), [callout("time_up")]),
           if_(gt("barrages", 0), [clip("won", "full")], [clip("lost", "full")]),
           # under MASER BARRAGE TOTAL: the barrages and the best multiplier (the number can only come last)
           *[if_(eq("best", m), [hud_line("BEST X%d  -  BARRAGES" % m, value=var("barrages"))]) for m in range(1, 6)],
           game_show("Colour fade")),
]

PROGRAM = {
    "name": NAME, "seconds": 40, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": "ran ball", "reset": "ball"}] +
            [{"name": n, "reset": "game", "shared": True} for n in ("maser played", "maser won")] +
            [{"name": n, "reset": "mode"} for n in ("step", "mult", "best", "window", "barrages", "breaks", "pace")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("LEFT RAMP  >  RIGHT RAMP  >  BUILDING",
               counters=[("MULTIPLIER", "MAX X5", var("mult")), ("BARRAGES", " ", var("barrages")),
                         ("WINDOW", "SECONDS", div(add(WINDOW_LEFT, 999), 1000))],
               timer=("MASER", "maser"),
               gauge={"label": "CHAIN", "kind": "diamond", "count": 3, "color": "#008cff", "value": var("step")}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "barrage", "broken", "won", "lost"),
    "sounds": sounds({"barrage": 4, "broken": 3}),
    "music": "music.wav",
    "shows": SHOWS,
    "scripts": None,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 103, "titles": ["godzilla_le"],
    "based_on": "maser_barrage.c",
    "about": ("The C example MASER BARRAGE rebuilt in blocks: a combo chain. Three Maser target hits start it; the "
              "Left ramp, Right ramp and Building in order, each within the window, pay more as the multiplier "
              "climbs to x5, and a broken chain starts again at x1."),
    "lost": [
        "The start counts every Maser target hit this ball, with no 250 ms debounce, and the chain's shots have none "
        "either: a ball rattling in the Left ramp's entrance can count twice (the C counted one a quarter second).",
        "The next shot's blink quickens once a second as its window closes (the C every tick), and the HUD shows the "
        "multiplier as 2 where the C showed X2, and the window as 0 with NO CLOCK YET where it showed -.",
        "Awards say their numbers after the words: LEFT RAMP X 2 / NOW THE RIGHT RAMP and BARRAGE JACKPOT 10,000,000 "
        "/ NOW X3, where the C said LEFT RAMP X2 over 2,000,000 and 10,000,000   NOW X3 under BARRAGE JACKPOT.",
        "The ending's line under MASER BARRAGE TOTAL puts the count last (BEST X3  -  BARRAGES 2) where the C said "
        "2 BARRAGES  -  BEST X3, and says BARRAGES for one too.",
        "The ending stays up 3 s, the runtime's: the C kept it 10 s.",
        "The counters are in the film recipe's order (MULTIPLIER, BARRAGES, WINDOW); the C drew MULTIPLIER, WINDOW, "
        "BARRAGES.",
        "The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).",
        "For Godzilla Premium/LE only: the C also ran on Godzilla Pro, playing its own shows where the game has no "
        "Insert chase or Colour fade (a Pro 1.15 has none of the game's shows, a Pro 1.16 no Insert chase); a "
        "blocks program cannot ask whether the game has a show. Its own three shows are kept under Light shows "
        "(Maser start, Maser won, Maser lost), not run, to swap in.",
        "The blocks pack keeps its own FINAL WARS ledger in shared variables ('maser played', 'maser won'), which "
        "the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not read "
        "the C's ledger.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


MASER3 = ["shot", START_SHOT, "ms", 300] * 3 + ["secs", 1]
_START = ["trigger", "maser_barrage.start", "secs", 1]
#: the desk scenarios (make_examples.py --desk): what, the harness's commands, lines its output must hold
DESK = [
    ("three Maser hits start it", ["shot", START_SHOT, "ms", 300, "shot", START_SHOT, "ms", 300, "shot", START_SHOT,
                                   "secs", 2],
     ["Hud_Award: MASER 1 OF 3", "Hud_Award: MASER 2 OF 3", "Hud_AwardSub: MASER BARRAGE",
      "[MASER BARRAGE] START (a block)", "Hud_Line: SHOOT THE LEFT RAMP", "LAMP LEFT RAMP 005aff blink 500",
      "LAMP RIGHT RAMP 001e5a pulse 1600", "Hud_C1_Sub: JACKPOT 5M"]),
    ("a barrage, then the chain breaks", MASER3 +
     ["shot", "Right ramp", "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building",
      "secs", 1, "shot", "Left ramp", "secs", 7,
      "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building", "secs", 50],
     ["SCORE +1000000", "Hud_Award: BARRAGE JACKPOT 5,000,000", "Hud_AwardSub: NOW X2", "Hud_C1_Sub: JACKPOT 10M",
      "SCORE +2000000", "Hud_Award: CHAIN BROKEN", "Hud_C2_Sub: CHAIN BROKEN", "Hud_Line: SHOOT THE BUILDING",
      "CALLOUT 1291", "CALLOUT 1295", "END (time ran out): 9 scores, total 18000000",
      "Hud_Title: MASER BARRAGE TOTAL", "Hud_Line: BEST X2  -  BARRAGES 2", "lamps held 0"]),
    ("the multiplier climbs and the clock tops up", _START +
     ["shot", "Left ramp", "ms", 400, "shot", "Right ramp", "ms", 400, "shot", "Building", "ms", 400] * 5 +
     ["secs", 2, "trigger", "maser_barrage.stop", "secs", 4],
     ["Hud_AwardSub: NOW X5", "Hud_C1_Sub: JACKPOT 25M", "SCORE +25000000", "Hud_C1_Value: 5",
      "END (trigger file): 20 scores, total 120000000", "Hud_Line: BEST X5  -  BARRAGES 5", "lamps held 0"]),
    # 5 s left, a step: the clock goes back to 10 s, so its window (7 s) can run out and break the chain first
    ("a step tops the clock up to 10 s", _START + ["secs", 35, "shot", "Left ramp", "secs", 12],
     ["SCORE +1000000", "Hud_Award: CHAIN BROKEN", "END (time ran out)", "lamps held 0"]),
    ("a drain ends it", _START + ["shot", "Left ramp", "secs", 1, "ball_end", "secs", 8],
     ["SCORE +1000000", "END (ball ended): 1 scores, total 1000000", "lamps held 0"]),
]
