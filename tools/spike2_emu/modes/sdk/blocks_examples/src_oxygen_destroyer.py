"""OXYGEN DESTROYER (PAD-658): the C example oxygen_destroyer.c rebuilt in blocks - a hurry-up with a super jackpot.

Dr. Serizawa's weapon (Godzilla, 1954). Its value drains away in real time: collect it before it is gone, then
deliver it for double.

- START: 25 Left spinner spins in one ball; up to 3 times a game per player, and not again for 15 s after it
  ends (25 fresh spins every time). It waits out a multiball: the next spin after it starts it.
- HURRY-UP: 20,000,000 falling 800,000 a second (0 at 25 s), kept by a 25 s timer. The LEFT RAMP collects it; the
  Godzilla target holds it off: each hit puts 2 s (1,600,000) back, up to 20,000,000, three times at most.
- SUPER: collecting lights the RIGHT RAMP for 12 s: double what was collected. Missed, it ends with what was
  collected; the value reaching 0 first is LOST (nothing).
- INSERTS: the Left ramp blinks green, yellow, then red as the value falls, faster as the clock runs down; the
  Godzilla target's insert pulses white while a hold-off is left; the super jackpot: the Right ramp flashes white
  (faster in its last 3 s).
"""
from blk import (AND, OR, SECS_LEFT, a_show, add, award, callout, change, clip, clips, div, end, eq, every,
                 game_show, ge, gt, hud, hud_counter, hud_line, hud_title, if_, light, lt, mul, off, on_end, on_shot, on_start,
                 on_timer, score, secs_left, set_, set_time, sound, sounds, start, step, sub, timer_left, timer_start,
                 timer_stop, var)

SLUG, NAME = "oxygen_destroyer", "OXYGEN DESTROYER"
GREEN, YELLOW, RED, WHITE = "#00ff3c", "#ffc800", "#ff0000", "#ffffff"    # the kit's colours
OXY_DEEP, OXY_AQUA = "#001446", "#3cdcff"
MAGNA_XY = (89, 260)                       # the port's lamp place: MAGNA GRAB (the Godzilla target's insert)
SPIN, HOLD, COLLECT, SUPER_SHOT = "Left spinner", "Godzilla target", "Left ramp", "Right ramp"
#: the value now: 800 points a millisecond left on the oxygen timer, in tens of thousands (as the C shows and pays it)
VALUE = mul(div(mul(timer_left("oxygen"), 2), 25), 10000)
TIMERS = ("oxygen", "cool")

SHOWS = [
    # the C's own shows, its fallback where the card has no "Playfield wave" / "Blue fade" (Godzilla has both)
    a_show("Oxygen start",
           step("sparkle", 900, OXY_AQUA, OXY_DEEP, "center", gi="dark"),                    # the sea bed
           step("sweep_up", 900, WHITE, OXY_DEEP, "center", gi="dark"),                      # bubbles rise
           step("sweep_up", 800, OXY_AQUA, OXY_DEEP, "center", gi="dark"),
           step("pulse", 900, OXY_AQUA, OXY_DEEP, "center", rate=220)),
    a_show("Oxygen won",
           step("strobe", 400, WHITE, "#000000", "center", rate=60, gi="flash"),             # the device fires
           step("burst", 900, WHITE, OXY_AQUA, "xy", gi="dark", x=MAGNA_XY[0], y=MAGNA_XY[1]),
           step("sparkle", 1200, WHITE, OXY_DEEP, "center", gi="dark"),                      # he dissolves
           step("fade", 900, OXY_AQUA, "#000000", "center")),
    a_show("Oxygen lost",
           step("sweep_down", 900, OXY_AQUA, OXY_DEEP, "center", gi="dark"),                 # the oxygen drains
           step("pulse", 900, RED, "#000000", "center", rate=300, gi="dark"),
           step("fade", 600, OXY_DEEP, "#000000", "center")),
]


def holds_left():
    """The HURRY-UP counter's words: the hold-offs left."""
    return [if_(eq("holds", 0), [hud_counter(2, VALUE, "3 HOLD-OFFS LEFT")], [
        if_(eq("holds", 1), [hud_counter(2, VALUE, "2 HOLD-OFFS LEFT")], [
            if_(eq("holds", 2), [hud_counter(2, VALUE, "1 HOLD-OFF LEFT")], [hud_counter(2, VALUE, "0 HOLD-OFFS LEFT")])])])]


SCRIPTS = [
    # ---- the start: 25 spins of the Left spinner ----------------------------------------------------------
    on_shot(SPIN, if_(AND(lt("ran game", 3), eq("cooling", 0)), [
        if_(lt("spins", 25), [change("spins", 1)]),
        if_(ge("spins", 25), [start()], [
            if_(eq("spins", 24), [award("1 SPIN TO GO", sub=NAME, seconds=2)],
                [award("SPINS TO GO", value=sub(25, var("spins")), sub=NAME, seconds=2)])]),
    ]), when="idle"),
    on_start(set_("spins", 0), change("ran game", 1), set_("oxygen played", 1),
             timer_start("oxygen", 25000),
             clip("intro", "full"), clip("loop", "loop"), game_show("Playfield wave"),
             award(NAME, sub="COLLECT IT BEFORE IT IS GONE", seconds=3),
             hud_line("LEFT RAMP COLLECTS - CAPTIVE BALL HOLDS"), *holds_left(),
             light(COLLECT, GREEN, "hurry"), light(HOLD, WHITE, "pulse", 1000)),

    # ---- the hurry-up ----------------------------------------------------------------------------------------
    # the Left ramp's colour by the value left: green over two thirds, yellow over one, then red
    every(1, if_(eq("phase", 0), [
        if_(gt(mul(VALUE, 3), 40000000), [light(COLLECT, GREEN, "hurry")], [
            if_(gt(mul(VALUE, 3), 20000000), [light(COLLECT, YELLOW, "hurry")], [light(COLLECT, RED, "hurry")])])])),
    on_shot(HOLD, if_(AND(eq("phase", 0), lt("holds", 3)), [
        change("holds", 1),
        set_("t", add(timer_left("oxygen"), 2000)), if_(gt("t", 25000), [set_("t", 25000)]),
        timer_start("oxygen", var("t")), set_time(div(add(var("t"), 999), 1000)),
        award("HELD OFF", sub="+2 SECONDS", seconds=1), *holds_left(),
        if_(ge("holds", 3), [off(HOLD), hud_line("SHOOT THE LEFT RAMP")]),
    ])),
    on_shot(COLLECT, if_(AND(eq("phase", 0), gt(VALUE, 0)), [
        set_("collected", VALUE), score(var("collected")),
        set_("phase", 1), timer_stop("oxygen"), set_time(12),
        off(COLLECT), off(HOLD), light(SUPER_SHOT, WHITE, "blink", 150),
        hud_line("SUPER JACKPOT: SHOOT THE RIGHT RAMP"),
        {"op": "hud_counter", "counter": 2, "value": mul(var("collected"), 2), "sub": "RIGHT RAMP",
         "label": "SUPER JACKPOT"},
        award("COLLECTED", value=var("collected"), sub="DOUBLE IT AT THE RIGHT RAMP", seconds=3),
        sound("collect"), clip("collect", "behind"),
    ])),
    on_timer("oxygen", if_(eq("phase", 0), [set_("gone", 1), end()])),

    # ---- the super jackpot -----------------------------------------------------------------------------------
    on_shot(SUPER_SHOT, if_(eq("phase", 1), [
        score(mul(var("collected"), 2)), set_("won", 1), set_("oxygen won", 1), sound("won"), end()])),
    secs_left(3, if_(eq("phase", 1), [light(SUPER_SHOT, WHITE, "blink", 80)])),
    secs_left(10, callout("ten_seconds")),

    # ---- the end, and 15 s before the spins count again ------------------------------------------------------
    on_end(*[timer_stop(t) for t in TIMERS],
           if_(AND(eq("won", 0), OR(eq("gone", 1), eq(SECS_LEFT, 0))), [sound("lost", fallback="time_up")]),
           if_(eq("won", 1), [clip("won", "full"), hud_title("GODZILLA IS GONE")], [
               clip("lost", "full"),
               if_(gt("collected", 0), [hud_title("OXYGEN DESTROYER")], [hud_title("THE OXYGEN IS GONE")])]),
           game_show("Blue fade"),
           set_("cooling", 1), timer_start("cool", 15000)),
    on_timer("cool", set_("cooling", 0)),
]

PROGRAM = {
    "name": NAME, "seconds": 25, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "ball"} for n in ("spins", "cooling")] +
            [{"name": "ran game", "reset": "game"}] +
            [{"name": n, "reset": "game", "shared": True} for n in ("oxygen played", "oxygen won")] +
            [{"name": n, "reset": "mode"} for n in ("phase", "holds", "collected", "won", "gone", "t")],
    "timers": [{"name": n} for n in TIMERS],
    # the big counter follows the value while it falls (the oxygen timer stopped reads 0), then the super jackpot
    "hud": hud("SHOOT THE LEFT RAMP",
               counters=[("", "", None), ("HURRY-UP", "LEFT RAMP", add(VALUE, mul(var("collected"), 2))),
                         ("", "", None)],
               timer=("OXYGEN", "oxygen"),
               gauge={"label": "OXYGEN", "kind": "segment", "count": 10, "color": "#00aaff",
                      "value": add(div(add(timer_left("oxygen"), 2499), 2500), mul(var("phase"), 10))}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "collect", "won", "lost"),
    "sounds": sounds({"collect": 3, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
    "scripts": None,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 102, "titles": ["godzilla_le"],
    "based_on": "oxygen_destroyer.c",
    "about": ("The C example OXYGEN DESTROYER rebuilt in blocks: a hurry-up with a super jackpot. 25 Left spinner "
              "spins start it; 20,000,000 drains away over 25 s, the Left ramp collects it, the Godzilla target holds "
              "it off, and the Right ramp delivers it for double."),
    "lost": [
        "The value falls on a timer the blocks keep in milliseconds, but the clock the HUD badge shows is whole "
        "seconds: a hold-off puts the clock to the next whole second above the value's time (the C counted both "
        "from one drain, and a stalled frame drained at most 100 ms).",
        "The Godzilla target has no 250 ms debounce: a ball rattling on the captive ball can use up two hold-offs "
        "(the C counted one hit a quarter second).",
        "The Left ramp blinks faster as the mode's clock runs down (the blocks' Hurry pattern) and changes colour "
        "once a second; the C's blink followed the value itself, every tick, with a flicker in the last 3 s.",
        "The HUD keeps one counter: HURRY-UP, then SUPER JACKPOT; the C showed a COLLECTED counter beside it in "
        "the super jackpot (a counter the HUD does not have from the start cannot appear later). Its gauge is one blue, where the "
        "C's ten segments went from deep to pale blue, and a note says SPINS TO GO 24 where the C said 24 SPINS "
        "TO GO.",
        "The ending title (GODZILLA IS GONE, OXYGEN DESTROYER or THE OXYGEN IS GONE) and its total stay up 3 s, "
        "the runtime's: the C kept them 10 s.",
        "The ending has no OXYGEN DESTROYER TOTAL under the total: the C put those words there.",
        "The cooldown is 15 s on a timer that a new ball clears (the C kept each player's own across balls), and "
        "a start from the tab's Start mode now counts toward the 3 a game.",
        "The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).",
        "For Godzilla Premium/LE only: the C also ran on Godzilla Pro, playing its own shows where the game has no "
        "Playfield wave or Blue fade (a Pro 1.15 has none of the game's shows, a Pro 1.16 no Playfield wave); a "
        "blocks program cannot ask whether the game has a show. Its own three shows are kept under Light shows "
        "(Oxygen start, Oxygen won, Oxygen lost), not run, to swap in.",
        "The blocks pack keeps its own FINAL WARS ledger in shared variables ('oxygen played', 'oxygen won'), "
        "which the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not "
        "read the C's ledger.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _spins(n):
    out = []
    for _i in range(n):
        out += ["shot", SPIN, "ms", 60]
    return out


_START = ["trigger", "oxygen_destroyer.start", "secs", 1]
_GT = ["shot", HOLD, "ms", 300]
#: the desk scenarios (make_examples.py --desk): what, the harness's commands, lines its output must hold
DESK = [
    ("25 spins start it", _GT * 3 + ["secs", 3] + _spins(24) + ["secs", 1] + _spins(1) + ["secs", 2],
     ["Hud_Award: SPINS TO GO 24", "Hud_Award: 1 SPIN TO GO", "Hud_AwardSub: OXYGEN DESTROYER",
      "[OXYGEN DESTROYER] START (a block)", "Hud_Line: LEFT RAMP COLLECTS - CAPTIVE BALL HOLDS",
      "Hud_C2_Value: 20.0M", "LAMP LEFT RAMP 00ff3c blink", "LAMP MAGNA GRAB ffffff pulse 1000"]),
    ("held off, collected, delivered double", _START + ["secs", 4] + _GT + ["secs", 2, "shot", COLLECT, "secs", 3,
                                                                         "shot", SUPER_SHOT, "secs", 11],
     ["Hud_Award: HELD OFF", "Hud_C2_Sub: 2 HOLD-OFFS LEFT", "Hud_Award: COLLECTED", "SCORE +15640000",
      "Hud_Line: SUPER JACKPOT: SHOOT THE RIGHT RAMP", "Hud_C2_Label: SUPER JACKPOT", "Hud_C2_Value: 31.2M", "LAMP RIGHT RAMP ffffff blink 150", "SCORE +31280000",
      "END (a block): 2 scores, total 46920000", "Hud_Title: GODZILLA IS GONE", "lamps held 0"]),
    ("the value runs out", _START + ["secs", 27] + _spins(4) + ["secs", 1],
     ["LAMP LEFT RAMP ffc800 blink", "LAMP LEFT RAMP ff0000 blink", "CALLOUT 1291", "CALLOUT 1295",
      "0 scores, total 0", "Hud_Title: THE OXYGEN IS GONE", "lamps held 0"]),
    ("the super jackpot missed", _START + ["shot", COLLECT, "secs", 13],
     ["Hud_Award: COLLECTED", "LAMP RIGHT RAMP ffffff blink 80", "END (time ran out): 1 scores",
      "Hud_Title: OXYGEN DESTROYER", "lamps held 0"]),
    ("a drain ends it", _START + ["secs", 2, "ball_end", "secs", 8],
     ["END (ball ended): 0 scores", "lamps held 0"]),
]
