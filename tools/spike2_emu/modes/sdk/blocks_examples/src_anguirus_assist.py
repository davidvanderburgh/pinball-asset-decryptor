"""ANGUIRUS (PAD-658): the SDK's C example anguirus_assist.c rebuilt in blocks - a mode that STACKS with the game's
own battle on purpose: Godzilla's oldest ally joins it, charges his spikes, then rolls.

- START: by itself, when one of the game's own modes is running and one ball is in play (the C: a kaiju battle),
  on the next shot; once per battle (a shot with none running gets it ready for the next one).
- CHARGE: each Shield target (left, center, right) charges one spike: 500,000. A charged spike does not charge again.
  The shields are the meter: a spike to charge blinks orange, a charged one is solid orange.
- ROLL: three spikes: the Big loop blinks cyan for a ROLLING ATTACK: 4,000,000; each Big loop within 6 s of the last
  doubles it (8M, then 16M, the most). 6 s without a loop: the roll is over, charge the spikes again.
- ENDS: when the game's mode is over (looked at every second), a drain, a tilt. The game's battle is never touched.
"""
from blk import (AND, BALLS, NOT, RUNNING, STOCK, a_show, start, add, award, change, clip, clips, end, eq, every, ge,
                 gt, hud, if_, le, light, lt, mul, off, on_any_shot, on_end, on_shot, on_start, on_timer,
                 score, set_, show, sound, sounds, step, timer_left, timer_start, timer_stop, var)

SLUG, NAME = "anguirus_assist", "ANGUIRUS"
AMBER, EMBER, ORANGE, CYAN, WHITE = "#ff6e00", "#501900", "#ff5000", "#00e6ff", "#ffffff"
ROLL_SHOT = "Big loop"
SPIKES = (("spike l", "Shield target left"), ("spike c", "Shield target center"), ("spike r", "Shield target right"))
SX, SY = 199, 346                     # the SHIELD CENTER insert's place: the C's KIT_AT_SHIELDS
TIMERS = ("enter", "roll", "charged")


def charged():
    return add(add(var("spike l"), var("spike c")), var("spike r"))


SHOWS = [
    a_show("He enters",
           step("burst", 700, WHITE, AMBER, "xy", gi="flash", x=SX, y=SY),
           step("spin", 1400, AMBER, EMBER, "xy", rate=90, x=SX, y=SY),
           step("fade", 400, AMBER, "#000000", "center")),
    a_show("Rolling attack",
           step("chase", 900, CYAN, "#000000", "center", rate=40),
           step("burst", 500, WHITE, CYAN, "top", gi="flash")),
    a_show("He rolled",
           step("burst", 800, WHITE, AMBER, "center", gi="flash"),
           step("rainbow", 1600, "#000000", "#000000", "xy", rate=60, x=SX, y=SY),
           step("fade", 500, AMBER, "#000000", "center")),
    a_show("Embers",
           step("sparkle", 900, AMBER, EMBER, "center", gi="dark"),
           step("fade", 800, EMBER, "#000000", "center")),
]


def shield_lights():
    """The charge meter: a spike to charge blinks orange, a charged one (or all while he rolls) is solid."""
    return [if_(eq(v, 1), [light(s, ORANGE, "solid")], [light(s, ORANGE, "blink", 400)]) for v, s in SPIKES]


SCRIPTS = [
    # ---- he joins the game's own mode ------------------------------------------------------------------------
    on_any_shot(if_(AND(STOCK, lt(BALLS, 2)), [
        if_(eq("joined", 0), [set_("joined", 1), start()])], [set_("joined", 0)]),
        when="idle"),
    on_start(set_("joined", 1), set_("rolling", 0), set_("rolls", 0), set_("entered", 0),
             *[set_(v, 0) for v, _s in SPIKES],
             *shield_lights(),
             timer_start("enter", 2000)),
    # his entrance, once the game's own start screen has had its moment
    on_timer("enter", if_(RUNNING, [
        set_("entered", 1), clip("intro", "full"), show("He enters"),
        award("ANGUIRUS JOINS", sub="SHIELDS CHARGE HIS SPIKES", seconds=3)])),

    # ---- charge the spikes --------------------------------------------------------------------------------------
    *[on_shot(s, if_(AND(eq("rolling", 0), eq(v, 0)), [
        set_(v, 1), score(500000), sound("spike"), light(s, ORANGE, "solid"), timer_start("charged", 1)]))
      for v, s in SPIKES],
    on_timer("charged",
             if_(ge(charged(), 3), [
                 set_("rolling", 1), set_("roll value", 4000000), timer_start("roll", 6000),
                 light(ROLL_SHOT, CYAN, "blink", 400), clip("spike", "full"),
                 award("ROLLING ATTACK LIT", sub="SHOOT THE BIG LOOP", seconds=3)], [
                 if_(eq("entered", 1), [award("SPIKE", value=charged(), sub="OF 3 CHARGED", seconds=2)])])),

    # ---- roll -----------------------------------------------------------------------------------------------------
    on_shot(ROLL_SHOT, if_(eq("rolling", 1), [
        score(var("roll value")), change("rolls", 1), sound("roll"), clip("roll", "full"), show("Rolling attack"),
        award("ROLLING ATTACK", value=var("roll value"), sub="AGAIN WITHIN 6 S TO DOUBLE", seconds=3),
        set_("roll value", mul(var("roll value"), 2)),
        if_(gt("roll value", 16000000), [set_("roll value", 16000000)]),
        timer_start("roll", 6000), light(ROLL_SHOT, CYAN, "blink", 400)])),
    on_timer("roll", if_(eq("rolling", 1), [
        set_("rolling", 0), *[set_(v, 0) for v, _s in SPIKES], off(ROLL_SHOT), *shield_lights(),
        award("CHARGE THE SPIKES", sub="HIT THE SHIELDS", seconds=2)])),

    # ---- every second: the roll's blink quickens; the game's mode over, he leaves with it ---------------------------
    every(1,
          if_(eq("rolling", 1), [
              if_(le(timer_left("roll"), 2000), [light(ROLL_SHOT, CYAN, "blink", 100)], [
                  if_(le(timer_left("roll"), 4000), [light(ROLL_SHOT, CYAN, "blink", 200)])])]),
          if_(NOT(STOCK), [end()])),

    on_end(*[timer_stop(t) for t in TIMERS], set_("rolling", 0),
           if_(gt("rolls", 0), [clip("won", "full"), sound("won"), show("He rolled")],
               [clip("lost", "full"), show("Embers")])),
]

PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "stack",
    "wait_multiball": False, "priority": 0,
    "vars": [{"name": "joined", "reset": "game"}] + [
        {"name": n, "reset": "mode"} for n in ("rolling", "roll value", "rolls", "entered")] + [
        {"name": v, "reset": "mode"} for v, _s in SPIKES],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud(" ", counters=[], timer=None,
               gauge={"label": "SPIKES", "kind": "spike", "count": 3, "color": "#ff7800", "value": charged()}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "spike", "roll", "won", "lost"),
    "sounds": sounds({"spike": 3, "roll": 3, "won": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 105, "titles": ["godzilla_le"], "based_on": "anguirus_assist.c",
    "about": ("The C example ANGUIRUS rebuilt in blocks: he joins the game's own battle and leaves with it; the "
              "three shields charge his spikes, then the Big loop is a rolling attack that doubles to 16M."),
    "lost": [
        "He joins on the first shot after one of the game's own modes begins (blocks only look at a shot), where "
        "the C looked twice a second; and blocks cannot tell a battle from the game's other modes: he joins any "
        "of its modes while one ball is in play (its multiballs are left out), where the C joined only kaiju "
        "battles.",
        "He leaves within a second of the game's mode ending (an Every second check) and his total shows at once "
        "for 3 s; the C waited for the battle's own total screen first, then kept his 4 s in view.",
        "As he leaves with the battle, ANGUIRUS TOTAL is the title over his total: the C put it under the total, "
        "with no title.",
        "Ended while the battle still runs (a stop, another of our modes), his total shows alone: the C put ANGUIRUS "
        "RETREATS under it. His HUD's title and line are the battle's while it runs, so a title block cannot say it.",
        "His screen is not shared in moments: with the HUD on he holds display priority 180 the whole time he runs, "
        "where the C held it only for each moment (entrance, a spike, the roll, a rolling attack) and gave the "
        "battle its own displays between them.",
        "His entrance (clip, music, words) comes a fixed 2 s after he joins; the C waited until the battle's start "
        "screen had gone (up to 12 s). His music starts as he joins, not with the entrance.",
        "The SPIKES gauge keeps its label: the C relabelled it ROLLING! while he rolls.",
        "The Big loop's blink quickens once a second (400, 200, 100 ms), where the C stepped it every tick.",
        "Godzilla LE only: the program names the center shield target; the C charged with two spikes on Godzilla "
        "Pro 1.15/1.16's two shields.",
        "The C's total gave way at once when another of our modes asked to start; the blocks' runtime TOTAL runs "
        "its 3 s.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


_JOIN = ["battle", 1, "secs", 1, "shot", "Slingshot", "secs", 3]
_CHARGE = ["shot", "Shield target left", "ms", 400, "shot", "Shield target center", "ms", 400,
           "shot", "Shield target right", "secs", 1]
DESK = [
    ("joins the battle charges rolls and leaves", _JOIN + _CHARGE + ["shot", "Big loop", "secs", 2, "shot", "Big loop",
                                                                     "secs", 2, "shot", "Big loop", "secs", 2,
                                                                     "shot", "Big loop", "secs", 2,
                                                                     "battle", 0, "secs", 6],
     ["[ANGUIRUS] START", "Hud_Award: ANGUIRUS JOINS", "LAMP SHIELD LEFT ff5000 blink 400",
      "LAMP SHIELD LEFT ff5000 solid", "Hud_Award: ROLLING ATTACK LIT", "SCORE +500000", "SCORE +4000000",
      "SCORE +8000000", "SCORE +16000000", "LAMP BIG LOOP 00e6ff blink 400", "own sound won", "END (a block)",
      "Hud_Title: ANGUIRUS TOTAL", "lamps held 0"]),
    ("the roll runs out", _JOIN + _CHARGE + ["secs", 4, "lamps", "secs", 3, "lamps"],
     ["LAMP BIG LOOP 00e6ff blink 200", "Hud_Award: CHARGE THE SPIKES", "LAMP OFF BIG LOOP"]),
    ("no battle no join", ["shot", "Slingshot", "secs", 2, "battle", 1, "secs", 1, "shot", "Slingshot", "secs", 1],
     ["[ANGUIRUS] START"]),
    ("a drain mid battle", _JOIN + ["shot", "Shield target left", "secs", 1, "ball_end", "secs", 7,
                                    "shot", "Slingshot", "secs", 1],
     ["END (ball ended)", "own clip lost", "lamps held 0"]),
]
