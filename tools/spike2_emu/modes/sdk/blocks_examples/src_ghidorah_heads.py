"""KING GHIDORAH (PAD-658): the C example ghidorah_heads.c rebuilt in blocks - a boss battle with health.

Ghidorah (1964). Each head is two shots with 3 health; only the LIT head takes damage, the lit head turns every
8 s, and a wounded head left alone grows back. Sever all three and the Maser gets one shot at the body.

- START: the three powerline targets (any order) in one ball; once a ball, twice a game per player. It waits out
  one of the game's battles or a multiball: the next powerline hit after it starts it.
- HEADS: LEFT = Left ramp (2) or Powerline left (1); MIDDLE = Building (2) or Powerline center (1); RIGHT = Right
  ramp (2) or Powerline right (1). The lit head: 1M a point of damage; another head: a glancing blow, 250K.
- REGROW: a wounded head that takes no damage for 10 s grows 1 back (and again every 10 s).
- SEVER: 5M x heads severed so far, +10 s on the clock; the lit head moves on at once.
- CLOCK: 50 s (+10 s a head). FINAL BLOW: all three severed, the Maser target is lit for 15 s: 20M + 1M a second
  left. The clock or the final blow running out: GHIDORAH ESCAPES.
- INSERTS: the lit head's two shots blink gold (slow at 3, faster at 2, fast at 1); a wounded head that is not lit
  pulses green; MASER and MASER READY flash white in the final blow (faster in its last 5 s).
"""
from blk import (AND, OR, SECS_LEFT, a_show, add, add_time, award, callout, change, clip, clips, end, eq,
                 game_show, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_insert, lt, mul, off,
                 off_insert, on_end, on_shot, on_start, on_timer, score, secs_left, set_, set_time, show, sound,
                 sounds, start, step, timer_start, timer_stop, var)

SLUG, NAME = "ghidorah_heads", "KING GHIDORAH"
GOLD, GREEN, WHITE = "#ffaa00", "#00ff3c", "#ffffff"           # the kit's KIT_GOLD, KIT_GREEN, KIT_WHITE
GHID_GOLD, GHID_EMBER = "#ffaf00", "#5a1e00"
#: each head: its name, its big shot (2 damage), its powerline (1), its health, its regrowth timer, its start light
HEADS = (("LEFT HEAD", "Left ramp", "Powerline left", "hp l", "regrow l", "pl left"),
         ("MIDDLE HEAD", "Building", "Powerline center", "hp m", "regrow m", "pl center"),
         ("RIGHT HEAD", "Right ramp", "Powerline right", "hp r", "regrow r", "pl right"))
FINAL_SHOT, FINAL_INSERT = "Maser target", "MASER READY"
TIMERS = ("turn", "regrow l", "regrow m", "regrow r", "sever", "glance", "next", "lights")
POWERLINES = add(add(var("pl left"), var("pl center")), var("pl right"))
SUPER = add(20000000, mul(1000000, SECS_LEFT))
BUILDING_XY, MASER_XY = (123, 202), (51, 417)       # the port's lamp places: BUILDING, MASER

SHOWS = [
    # the C's own shows, its fallback where the card has no "Strobe burst" / "Colour fade" (Godzilla has both)
    a_show("Ghidorah start",
           step("bolts", 1500, GHID_GOLD, "#000000", "center", rate=190, gi="dark"),        # gravity beams strike
           step("strobe", 500, WHITE, GHID_GOLD, "center", rate=60, gi="flash"),
           step("burst", 800, GHID_GOLD, GHID_EMBER, "xy", gi="dark", x=BUILDING_XY[0], y=BUILDING_XY[1]),
           step("fade", 400, GHID_EMBER, "#000000", "center")),
    a_show("Ghidorah won",
           step("strobe", 400, WHITE, "#000000", "center", rate=50, gi="flash"),
           step("burst", 700, WHITE, GHID_GOLD, "xy", gi="dark", x=MASER_XY[0], y=MASER_XY[1]),   # the final blow
           step("rainbow", 1800, "#000000", "#000000", "center", rate=60),
           step("fade", 500, GHID_GOLD, "#000000", "center")),
    a_show("Ghidorah lost",
           step("sweep_up", 900, GHID_GOLD, GHID_EMBER, "center", gi="dark"),               # Ghidorah flies off
           step("sweep_up", 900, GHID_GOLD, "#000000", "center", gi="dark"),
           step("sparkle", 700, GHID_GOLD, "#000000", "center", gi="dark"),
           step("fade", 400, GHID_EMBER, "#000000", "center")),
]


def by_lit(make):
    """``make(i)`` for the lit head: an if-chain over the three."""
    return [if_(eq("lit", 1), make(0), [if_(eq("lit", 2), make(1), make(2))])]


def head_hit(i, damage):
    """A hit on head ``i`` worth ``damage``: the lit head is hurt (or severed), another one is a glancing blow."""
    name, _big, _small, hp, regrow, _pl = HEADS[i]
    return [if_(AND(eq("phase", 0), gt(hp, 0)), [
        if_(eq("lit", i + 1), [
            if_(le(hp, damage), [
                score(mul(1000000, var(hp))), set_(hp, 0), set_("cut", i + 1), timer_start("sever", 1)],
                [change(hp, -damage), score(1000000 * damage),
                 award("%s -%d" % (name, damage), sub="{:,}".format(1000000 * damage), seconds=1),
                 timer_start(regrow, 10000), timer_start("lights", 1)]),
        ], [score(250000), timer_start("glance", 1)]),
    ])]


def head_lights(i):
    """Head ``i``'s two shots and its counter, as the battle stands."""
    name, big, small, hp, _regrow, _pl = HEADS[i]
    return [if_(eq(hp, 0), [off(big), off(small), hud_counter(i + 1, 0, "SEVERED")], [
        if_(eq("lit", i + 1), [
            set_("pace", 180), if_(ge(hp, 2), [set_("pace", 400)]), if_(ge(hp, 3), [set_("pace", 700)]),
            light(big, GOLD, "blink", var("pace")), light(small, GOLD, "blink", var("pace")),
            hud_counter(i + 1, var(hp), ">> LIT <<"),
        ], [
            if_(lt(hp, 3), [light(big, GREEN, "pulse", 1200), light(small, GREEN, "pulse", 1200)],
                [off(big), off(small)]),
            hud_counter(i + 1, var(hp), "HEALTH"),
        ]),
    ])]


def qualify(i):
    """A powerline while the battle is not on: one of the three this ball; the third starts it."""
    pl = HEADS[i][5]
    return on_shot(HEADS[i][2], if_(AND(eq("ran ball", 0), lt("ran game", 2)), [
        set_(pl, 1),
        if_(ge(POWERLINES, 3), [start()], [
            if_(eq(POWERLINES, 2), [award("POWERLINES 2 OF 3", sub=NAME, seconds=2)],
                [award("POWERLINES 1 OF 3", sub=NAME, seconds=2)])]),
    ]), when="idle")


def regrowth(i):
    name, _big, _small, hp, regrow, _pl = HEADS[i]
    return on_timer(regrow, if_(AND(eq("phase", 0), gt(hp, 0), lt(hp, 3)), [
        change(hp, 1), award("%s REGROWS" % name, sub="FINISH IT BEFORE IT TURNS", seconds=2),
        sound("regrow"), clip("regrow", "behind"), timer_start(regrow, 10000), timer_start("lights", 1)]))


SCRIPTS = [
    # ---- the start: three powerlines in one ball ----------------------------------------------------------
    qualify(0), qualify(1), qualify(2),
    on_start(set_("ran ball", 1), change("ran game", 1), set_("ghidorah played", 1),
             set_("pl left", 0), set_("pl center", 0), set_("pl right", 0),
             set_("hp l", 3), set_("hp m", 3), set_("hp r", 3), set_("lit", 1),
             clip("intro", "full"), clip("loop", "loop"), game_show("Strobe burst"),
             hud_line("SHOOT THE LEFT HEAD"),
             award("GHIDORAH ATTACKS", sub="SEVER ALL THREE HEADS", seconds=3),
             timer_start("turn", 8000), timer_start("lights", 1)),

    # ---- the heads -------------------------------------------------------------------------------------------
    *[on_shot(HEADS[i][1], *head_hit(i, 2)) for i in range(3)],
    *[on_shot(HEADS[i][2], *head_hit(i, 1)) for i in range(3)],
    on_timer("glance", *by_lit(lambda i: [award("GLANCING BLOW", sub="HIT THE %s" % HEADS[i][0], seconds=1)])),
    *[regrowth(i) for i in range(3)],
    on_timer("turn", if_(eq("phase", 0), [timer_start("next", 1), timer_start("turn", 8000)])),
    # the lit head moves on to the next living one (left, middle, right, round again)
    on_timer("next",
             if_(eq("lit", 1), [if_(gt("hp m", 0), [set_("lit", 2)], [if_(gt("hp r", 0), [set_("lit", 3)])])], [
                 if_(eq("lit", 2), [if_(gt("hp r", 0), [set_("lit", 3)], [if_(gt("hp l", 0), [set_("lit", 1)])])],
                     [if_(gt("hp l", 0), [set_("lit", 1)], [if_(gt("hp m", 0), [set_("lit", 2)])])])]),
             timer_start("lights", 1)),
    on_timer("lights",
             if_(eq("phase", 0), by_lit(lambda i: [hud_line("SHOOT THE %s" % HEADS[i][0])])),
             *[b for i in range(3) for b in head_lights(i)]),

    # ---- a head severed --------------------------------------------------------------------------------------
    on_timer("sever",
             change("severed", 1), score(mul(5000000, var("severed"))),
             sound("sever"), clip("sever", "behind"),
             if_(ge("severed", 3), [
                 set_("phase", 1), set_time(15), timer_stop("turn"),
                 award("ALL HEADS SEVERED", sub="FINAL BLOW: THE MASER", seconds=3),
                 hud_line("FINAL BLOW: SHOOT THE MASER"),
                 {"op": "hud_counter", "counter": 2, "value": SUPER, "sub": "MASER TARGET", "label": "SUPER JACKPOT"},
                 light(FINAL_SHOT, WHITE, "blink", 150), light_insert(FINAL_INSERT, WHITE, "blink", 150),
             ], [
                 add_time(10), timer_start("turn", 8000),
                 *[if_(eq("cut", i + 1), [award("%s SEVERED" % HEADS[i][0], value=mul(5000000, var("severed")),
                                                sub="+10 SECONDS", seconds=3)]) for i in range(3)],
                 timer_start("next", 1),
             ]),
             timer_start("lights", 1)),

    # ---- the final blow --------------------------------------------------------------------------------------
    secs_left(5, if_(eq("phase", 1), [light(FINAL_SHOT, WHITE, "blink", 80),
                                      light_insert(FINAL_INSERT, WHITE, "blink", 80)])),
    on_shot(FINAL_SHOT, if_(eq("phase", 1), [
        score(SUPER), set_("won", 1), set_("ghidorah won", 1), sound("won"), end()])),
    secs_left(10, callout("ten_seconds")),

    # ---- the end ---------------------------------------------------------------------------------------------
    on_end(*[timer_stop(t) for t in TIMERS],
           off_insert(FINAL_INSERT),
           if_(AND(eq("won", 0), eq(SECS_LEFT, 0)), [sound("lost", fallback="time_up")]),
           if_(eq("won", 1), [clip("won", "full"), hud_title("GHIDORAH DEFEATED")],
               [clip("lost", "full"), hud_title("GHIDORAH ESCAPES")]),
           game_show("Colour fade")),
]

PROGRAM = {
    "name": NAME, "seconds": 50, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "ball"} for n in ("pl left", "pl center", "pl right", "ran ball")] +
            [{"name": "ran game", "reset": "game"}] +
            [{"name": n, "reset": "game", "shared": True} for n in ("ghidorah played", "ghidorah won")] +
            [{"name": n, "reset": "mode"} for n in ("hp l", "hp m", "hp r", "lit", "severed", "phase", "won", "cut",
                                                    "pace")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("SHOOT THE LIT HEAD",
               counters=[("LEFT HEAD", "HEALTH", var("hp l")),
                         # the middle one is the super jackpot in the final blow (its health is 0 by then)
                         ("MIDDLE HEAD", "HEALTH", add(var("hp m"), mul(var("phase"), SUPER))),
                         ("RIGHT HEAD", "HEALTH", var("hp r"))],
               timer=("GHIDORAH", "bolt"),
               gauge={"label": "SEVERED", "kind": "diamond", "count": 3, "color": "#ffaa00",
                      "value": var("severed")}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "sever", "regrow", "won", "lost"),
    "sounds": sounds({"sever": 3, "regrow": 3, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
    "scripts": None,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 101, "titles": ["godzilla_le"],
    "based_on": "ghidorah_heads.c",
    "about": ("The C example KING GHIDORAH rebuilt in blocks: a boss battle with health. The three powerlines in one "
              "ball start it; only the lit head (two shots each) takes damage, the lit head turns every 8 s, a wounded "
              "head left alone grows back; sever all three and the Maser lands the super jackpot."),
    "lost": [
        "The heads' shots have no 250 ms debounce: a ball rattling on a target is several hits (the C counted one "
        "hit a quarter second per shot).",
        "A start from the tab's Start mode now counts as the ball's and the game's start too (the C counted only "
        "the three powerlines).",
        "When a run will not count (it already ran this ball, or twice this game) the powerlines say nothing; the C "
        "logged why once.",
        "The HUD shows a severed head's health as 0, where the C showed X; and in the final blow the left and "
        "right counters stay up (0, SEVERED) beside the SUPER JACKPOT counter, where the C hid them.",
        "Awards say their numbers after the words: LEFT HEAD SEVERED 5,000,000 / +10 SECONDS, where the C put "
        "5,000,000   +10 SECONDS under LEFT HEAD SEVERED.",
        "The ending title (GHIDORAH DEFEATED or GHIDORAH ESCAPES) and its total stay up 3 s, the runtime's: the "
        "C kept them 10 s.",
        "The ending has no KING GHIDORAH TOTAL under the total: the C put those words there.",
        "The lit head moves on its own 8 s timer, and moves a tick after a sever (the C moved it in the same tick); "
        "its inserts change a tick after a hit too.",
        "The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).",
        "For Godzilla Premium/LE only: the C also ran on Godzilla Pro, playing its own shows where the game has no "
        "Strobe burst or Colour fade (a Pro 1.15 has none of the game's shows, nor a MASER READY insert); a blocks "
        "program cannot ask whether the game has a show. Its own three shows are kept under Light shows (Ghidorah "
        "start, Ghidorah won, Ghidorah lost), not run, to swap in.",
        "The blocks pack keeps its own FINAL WARS ledger in shared variables ('ghidorah played', 'ghidorah won'), "
        "which the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not "
        "read the C's ledger.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


POWER3 = ["shot", "Powerline left", "ms", 300, "shot", "Powerline center", "ms", 300, "shot", "Powerline right",
          "secs", 1]
_START = ["trigger", "ghidorah_heads.start", "secs", 1]
_SEVER_ALL = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Powerline left", "secs", 1,
              "shot", "Building", "ms", 300, "shot", "Powerline center", "secs", 1,
              "shot", "Right ramp", "ms", 300, "shot", "Powerline right", "secs", 2]
#: the desk scenarios (make_examples.py --desk): what, the harness's commands, lines its output must hold
DESK = [
    ("the powerlines start it", ["shot", "Powerline left", "secs", 1] + POWER3 + ["secs", 2],
     ["Hud_Award: POWERLINES 1 OF 3", "Hud_AwardSub: KING GHIDORAH", "[KING GHIDORAH] START (a block)",
      "Hud_Award: GHIDORAH ATTACKS", "Hud_Line: SHOOT THE LEFT HEAD", "Hud_C1_Sub: >> LIT <<"]),
    ("head by head and the super jackpot", POWER3 + _SEVER_ALL + ["shot", "Maser target", "secs", 12],
     ["SCORE +2000000", "SCORE +250000", "Hud_Award: GLANCING BLOW", "Hud_AwardSub: HIT THE LEFT HEAD",
      "Hud_Award: LEFT HEAD SEVERED 5,000,000", "Hud_Line: SHOOT THE MIDDLE HEAD",
      "SCORE +10000000", "SCORE +15000000", "Hud_Award: ALL HEADS SEVERED", "Hud_Line: FINAL BLOW: SHOOT THE MASER", "Hud_C2_Label: SUPER JACKPOT", "Hud_C2_Value: 35.0M",
      "Hud_C1_Sub: SEVERED", "SCORE +33000000", "END (a block): 11 scores, total 72250000", "Hud_Title: GHIDORAH DEFEATED",
      "lamps held 0"]),
    ("a head regrows, turns, and Ghidorah escapes", _START + ["shot", "Left ramp", "secs", 12, "secs", 60],
     ["Hud_Award: LEFT HEAD -2", "Hud_Line: SHOOT THE MIDDLE HEAD", "Hud_Award: LEFT HEAD REGROWS",
      "LAMP LEFT RAMP 00ff3c pulse 1200", "CALLOUT 1295", "END (time ran out): 1 scores, total 2000000", "Hud_Title: GHIDORAH ESCAPES",
      "lamps held 0"]),
    ("the final blow missed", _START + _SEVER_ALL + ["secs", 17],
     ["Hud_Award: ALL HEADS SEVERED", "END (time ran out)", "lamps held 0"]),
    ("a drain ends it", _START + ["shot", "Building", "secs", 1, "ball_end", "secs", 8],
     ["SCORE +250000", "Hud_Award: GLANCING BLOW", "END (ball ended)", "lamps held 0"]),
]
