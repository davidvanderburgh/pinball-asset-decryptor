"""KIRYU in blocks (PAD-658): the SDK's kiryu.c rebuilt, then (round 2) taken deeper: three stages and a pot.

Godzilla Against Mechagodzilla (2002): Kiryu, the Mechagodzilla built on the 1954 Godzilla's bones, carries the
Absolute Zero cannon. It has to charge, and it can run too hot; then it throws its whole arsenal at Godzilla, grabs
him, flies him out to sea and fires the cannon point blank. After Lyman Sheats: Metallica's Sparky (a meter that
costs more each start), stages with their own shots (EHoH), a multiplier carried up, Crank It Up's cash out or go
on, and failing still pays.

- LIGHT IT: 60 spins of the Shield ramp spinner (the Mechagodzilla spinner) start it at once; 120 the next time, then
  180 (a note every 10 spins says how many are left). A start that has to wait (a multiball, one of the game's
  modes) waits for the next spin.
- STAGE 1, ABSOLUTE ZERO (the C's rule): the ramps, the Building and the Big loop charge 15%, the Maser 10%, each
  Shield target 8%, every spin 1%; each charging shot pays 750,000 (a spin 10,000) and puts a clock under 15 s back
  to 15. From 100% the Godzilla target (the captive ball) or the Action button fires: 10M times the multiplier into
  the POT. PUSH IT: 200% x2, 300% x3, 400% x4; from 200% the reactor overheats: 12 s to fire (10 s the second time,
  8 s the third), again at each 100% more; run out and Kiryu VENTS (the charge back to 0). The multiplier it fired at
  is CARRIED UP into the next stages.
- STAGE 2, THE ARSENAL: three weapons, each its own shot and colour: the MASER CANNONS at the Maser target (red),
  the MISSILES at the Big loop (orange), the WRIST BLADE at the Building (white). Each fired pays more than the last
  (5M, 10M, 15M times the multiplier) into the pot.
- STAGE 3, THE GRAPPLE: the Mecha lane grabs Godzilla (8 s, 6 s, 4 s the more Kiryu has fought); the Big loop
  carries him out to sea: 8M, 16M, 24M times the multiplier into the pot. Three carries light POINT BLANK at the
  captive ball: the pot twice and 25M times the multiplier. KIRYU WINS.
- CASH OUT: after stage 1 or 2 the right scoop chases white: it pays the pot. The clock (40 s a stage, 35 s and 30 s
  the more Kiryu has fought) or a drain pays a quarter of it; a clock that runs out at 100% or more in stage 1 fires
  the cannon on its own (x1, 10M).
"""
from blk import (AND, OR, SECS_LEFT, a_show, add, award, beds, callout, change, clip, clips, div, end, eq, every, game_show,
                 ge, gt, hud, hud_counter, hud_line, hud_title, if_, light, lt, mul, music, ne, off, on_end, on_shot,
                 on_start, on_timer, score, secs_left, set_, set_time, shake, shake_game, shield, show, sound, sounds, start,
                 step, sub, timer_left, timer_start, timer_stop, var)
import pack

SLUG, NAME = "kiryu", "KIRYU"
ICE, STEEL, HOT, WHITE, ORANGE, RED = "#8cdcff", "#142846", "#ff2800", "#ffffff", "#ff8000", "#ff1010"
SPIN = "Shield ramp spinner"
LANE = "Mecha exit bottom"
FIRE_SHOTS = ("Godzilla target", "Action button")
CHARGE = (("Left ramp", 15), ("Right ramp", 15), ("Building", 15), ("Big loop", 15), ("Maser target", 10),
          ("Shield target left", 8), ("Shield target center", 8), ("Shield target right", 8))
#: stage 2's weapons: (its flag, its shot, its words, its colour)
WEAPONS = (("w1", "Maser target", "MASER CANNONS", RED), ("w2", "Big loop", "MISSILE VOLLEY", ORANGE),
           ("w3", "Building", "WRIST BLADE", WHITE))
SHOT_VALUE, SPIN_VALUE, FIRE_VALUE = 750000, 10000, 10000000
CHARGE_MAX, FLOOR = 400, 15
NEED = pack.need(60, "plays")             # 60 spins, then 120, then 180 (David: SUPER X2 starts at 60)
MAGNA = dict(x=89, y=260)                 # the MAGNA GRAB insert (the captive ball), the port's lamp place
LANE_XY = dict(x=282, y=393)              # the MECHA LANE insert: Kiryu's own lane (the Mechagodzilla at its top)
TIMERS = ("charge", "lamps", "heat", "fire", "next", "grab", "weapon")

SHOWS = [
    a_show("Online",                                                    # Kiryu's eyes light up
           step("fade_in", 700, ICE, "#000000", "xy", gi="dark", **LANE_XY),
           step("strobe", 300, WHITE, ICE, "xy", rate=60, gi="dark", **LANE_XY),
           step("sweep_up", 900, ICE, STEEL, "flippers", gi="dark"),
           step("spiral_out", 1100, WHITE, ICE, "xy", gi="dark", **LANE_XY),
           step("fade", 500, ICE, "#000000", "center", blend=200)),
    a_show("Charge", step("implode", 600, WHITE, ICE, "xy", **MAGNA),               # each 100%
           step("pulse", 400, ICE, STEEL, "xy", rate=200, **MAGNA)),
    a_show("Absolute zero",
           step("strobe", 400, WHITE, ICE, "center", rate=40, gi="flash"),
           step("burst", 900, WHITE, ICE, "xy", gi="flash", **MAGNA),
           step("sparkle", 1500, WHITE, ICE, "center"),                                  # frost
           step("fade", 700, ICE, "#000000", "center")),
    a_show("Vent",
           step("strobe", 500, HOT, "#000000", "center", rate=70, gi="flash"),
           step("fire", 800, "#ffc000", HOT, "xy", gi="dark", **MAGNA),
           step("fade", 500, HOT, "#000000", "center")),
    a_show("Stage up",
           step("bounce", 900, WHITE, STEEL, "center", rate=300, gi="dark"),
           step("spin", 900, ICE, STEEL, "center", rate=80, gi="dark"),
           step("fade", 400, ICE, "#000000", "center", blend=150)),
    a_show("Volley",                                                    # the arsenal fires
           step("sweep_down", 350, ORANGE, "#000000", "top", gi="dark"),
           step("burst", 500, "#ffc000", RED, "center", gi="flash"),
           step("fade", 300, ORANGE, "#000000", "center")),
    a_show("Grapple",
           step("implode", 700, WHITE, STEEL, "xy", gi="dark", **LANE_XY),
           step("chase", 900, ICE, STEEL, "center", rate=70, gi="dark"),
           step("fade", 300, ICE, "#000000", "center")),
    a_show("Carry",                                                     # out to sea on its thrusters
           step("sweep_rl", 500, "#ffc000", "#000000", "center", gi="dark"),
           step("ripple", 800, ICE, STEEL, "right", rate=300, gi="keep"),
           step("fade", 300, ICE, "#000000", "center")),
    a_show("Point blank",
           step("strobe", 600, WHITE, ICE, "center", rate=45, gi="flash"),
           step("implode", 800, WHITE, ICE, "xy", gi="flash", **MAGNA),
           step("burst", 900, WHITE, ICE, "xy", gi="flash", **MAGNA),
           step("sparkle", 2000, WHITE, ICE, "center", gi="dark"),
           step("rainbow", 1500, "#000000", "#000000", "center", rate=60),
           step("fade", 900, ICE, "#000000", "center", blend=300)),
    a_show("Home",                                                      # back to base
           step("solid", 500, WHITE, "#000000", "center", gi="dark"),
           step("spiral_in", 1200, ICE, "#000000", "xy", gi="dark", **LANE_XY),
           step("fade", 900, ICE, "#000000", "xy", blend=400, **LANE_XY)),
    a_show("Down",
           step("sparkle", 700, HOT, STEEL, "center", gi="dark"),
           step("fade", 1200, STEEL, "#000000", "xy", gi="dark", **LANE_XY)),
]


def pot_up(points):
    return [change("pot", points), hud_counter(2, var("pot"), "CASH AT SCOOP")]


def lamps():
    """The inserts and the HUD's words for where it is (the C's show_lamps and show, then each stage's shots)."""
    tl = timer_left("heat")
    return [
        if_(AND(eq("stage", 1), lt("charge", CHARGE_MAX)),
            [light(s, ICE, "blink", 500) for s, _p in CHARGE], [off(s) for s, _p in CHARGE]),
        if_(eq("stage", 1), [
            set_("heat ms", 100), if_(gt(tl, 3000), [set_("heat ms", 200)]), if_(gt(tl, 4000), [set_("heat ms", 400)]),
            if_(gt(tl, 8000), [set_("heat ms", 700)]),
            if_(gt("mult", 0), [
                if_(gt(tl, 0), [light(s, HOT, "blink", var("heat ms")) for s in FIRE_SHOTS],
                    [light(s, WHITE, "chase", 120) for s in FIRE_SHOTS])],
                [off(s) for s in FIRE_SHOTS]),
            if_(gt(tl, 0), [hud_line("OVERHEATING! FIRE NOW", value=div(add(tl, 999), 1000))], [
                if_(gt("mult", 0), [hud_line("FIRE: THE CAPTIVE BALL  -  OR CHARGE ON")],
                    [hud_line("CHARGE THE ABSOLUTE ZERO: LIT SHOTS")])]),
            hud_counter(1, var("charge"), "PERCENT"),
            if_(ge("charge", CHARGE_MAX), [set_("pips", 10)],
                [set_("pips", div(sub(var("charge"), mul(var("mult"), 100)), 10))]),
        ]),
        if_(eq("stage", 2), [if_(eq(f, 0), [light(s, c, "chase", 110)], [off(s)]) for f, s, _w, c in WEAPONS]),
        if_(eq("stage", 3), [
            if_(ge("carries", 3), [off(LANE), off("Big loop"), light("Godzilla target", WHITE, "chase", 60)], [
                if_(gt(timer_left("grab"), 0), [off(LANE), light("Big loop", "#ffc000", "chase", 80)],
                    [light(LANE, ICE, "chase", 120), off("Big loop")])])]),
    ]


def charged():
    """A charging hit's percent ("pct") into the charge, and what passing each 100% does (the C's charge_by)."""
    words = [if_(eq("mult", m), [award("X%d  -  %d%%" % (m, m * 100), sub="THE REACTOR OVERHEATS")])
             for m in (2, 3, 4)]
    return [
        if_(lt("charge", CHARGE_MAX), [
            change("charge", var("pct")), if_(gt("charge", CHARGE_MAX), [set_("charge", CHARGE_MAX)]),
            set_("mult", div(var("charge"), 100)),
            if_(ne("mult", var("was")), [
                set_("was", var("mult")), set_("x", var("mult")), hud_counter(3, var("x"), "CARRIED UP"),
                if_(eq("mult", 1), [award("ABSOLUTE ZERO", sub="READY: THE CAPTIVE BALL", seconds=3),
                                    sound("ready"), clip("ready", "behind")],
                    words + [sound("charge"), clip("charge", "behind")]),
                show("Charge"), shake(300, "soft"),
                if_(ge("charge", 200), [timer_start("heat", var("heat max")),
                                        if_(eq("mult", 2), [sound("overheat"), clip("overheat", "behind")])]),
            ]),
        ]),
        timer_start("lamps", 1),
    ]


def setup_stage():
    """What each stage lights and says as it begins (run by the "next" timer once the stage before is done)."""
    return [
        if_(eq("stage", 2), [
            hud_line("THE ARSENAL: FIRE EVERY WEAPON"), hud_counter(1, 0, "OF 3", "WEAPONS"),
            award("THE ARSENAL", sub="MASERS, MISSILES, THE BLADE", seconds=3),
            clip("arsenal", "behind"), sound("volley")]),
        if_(eq("stage", 3), [
            hud_line("THE GRAPPLE: THE MECHA LANE"), hud_counter(1, 0, "OF 3", "CARRIES"),
            award("THE GRAPPLE", sub="GRAB HIM AT THE MECHA LANE", seconds=3),
            clip("grapple", "behind"), sound("grapple"), music("grapple")]),
    ]


SCRIPTS = [
    # ---- light it: every spin of the Mechagodzilla spinner, a note every 10 ------------------------------------
    on_shot(SPIN,
            if_(lt("spins", NEED), [change("spins", 1)]),
            if_(ge("spins", NEED), [start()], [
                if_(ge("spins", "note at"), [
                    award("SPINS TO KIRYU", value=sub(NEED, var("spins")), sub="KIRYU IS BEING BUILT"),
                    set_("note at", add(var("spins"), 10))])]),
            when="idle"),

    # ---- Kiryu online --------------------------------------------------------------------------------------------
    on_start(set_("spins", 0), set_("note at", 0), change("plays", 1),
             set_("stage", 1), set_("charge", 0), set_("mult", 0), set_("was", 0), set_("x", 1), set_("pips", 0),
             set_("pot", 0), set_("won", 0), set_("cashed", 0), set_("volleys", 0), set_("carries", 0),
             set_("w1", 0), set_("w2", 0), set_("w3", 0),
             # each time harder: a shorter overheat, a shorter clock, a shorter grab
             set_("heat max", sub(14000, mul(2000, var("plays")))),
             set_("clock", sub(45, mul(5, var("plays")))), if_(lt("clock", 30), [set_("clock", 30)]),
             set_time(var("clock")),
             shield("toward"), game_show("Strobe burst"), clip("intro", "full"), clip("loop", "loop"),
             show("Online"), shake(800, "strong"),
             award("KIRYU ONLINE", sub="CHARGE THE ABSOLUTE ZERO", seconds=3),
             hud_counter(1, 0, "PERCENT", "CHARGE"), hud_counter(2, 0, "CASH AT SCOOP"), hud_counter(3, 1, "CARRIED UP"),
             timer_start("lamps", 1)),

    # ---- stage 1: charge ------------------------------------------------------------------------------------------
    *[on_shot(s, if_(eq("stage", 1), [score(SHOT_VALUE), if_(lt(SECS_LEFT, FLOOR), [set_time(FLOOR)]),
                                       set_("pct", p), timer_start("charge", 1)]))
      for s, p in CHARGE if s not in ("Big loop", "Building", "Maser target")],
    on_shot(SPIN, if_(eq("stage", 1), [score(SPIN_VALUE), set_("pct", 1), timer_start("charge", 1)])),
    on_timer("charge", *charged()),
    on_timer("lamps", *lamps()),
    every(1, if_(gt(timer_left("heat"), 0), [timer_start("lamps", 1)])),     # the overheat's seconds and pace

    # ---- the reactor ran too hot: it vents ------------------------------------------------------------------------
    on_timer("heat", if_(eq("stage", 1), [
        set_("charge", 0), set_("mult", 0), set_("was", 0), set_("x", 1), hud_counter(3, 1, "CARRIED UP"),
        award("KIRYU VENTS", sub="THE CHARGE IS LOST", seconds=3), show("Vent"), sound("overheat"),
        shake(500, "medium"), clip("overheat", "behind"), timer_start("lamps", 1)])),

    # ---- fire: the captive ball or the action button ----------------------------------------------------------------
    on_shot("Action button", if_(AND(eq("stage", 1), gt("mult", 0)), [timer_start("fire", 1)])),
    on_shot("Godzilla target",
            if_(AND(eq("stage", 1), gt("mult", 0)), [timer_start("fire", 1)]),
            if_(AND(eq("stage", 3), ge("carries", 3), eq("won", 0)), [
                set_("won", 1), score(add(mul(var("pot"), 2), mul(25000000, var("x")))),
                clip("won", "full"), sound("won"), show("Point blank"), shake_game("multiball_start"), end()])),
    on_timer("fire",
             score(2000000), *pot_up(mul(FIRE_VALUE, var("mult"))), set_("x", var("mult")),
             set_("pips", 10), timer_stop("heat"),
             *[if_(eq("mult", m), [award("ABSOLUTE ZERO X%d" % m, value=mul(FIRE_VALUE, m), sub="INTO THE POT",
                                         seconds=4)]) for m in (1, 2, 3, 4)],
             show("Absolute zero"), sound("fire"), clip("fire", "full"), shake(600, "hard"),
             timer_start("next", 700)),

    # ---- stage 2: the arsenal (the Big loop, the Building and the Maser charge in stage 1) ----------------------------
    *[on_shot(s,
              if_(eq("stage", 1), [score(SHOT_VALUE), if_(lt(SECS_LEFT, FLOOR), [set_time(FLOOR)]),
                                   set_("pct", dict(CHARGE)[s]), timer_start("charge", 1)]),
              if_(AND(eq("stage", 2), eq(f, 0)), [set_(f, 1), set_("pct", i), timer_start("weapon", 1)]),
              *([if_(AND(eq("stage", 3), gt(timer_left("grab"), 0)), [timer_stop("grab"), timer_start("weapon", 1)])]
                if s == "Big loop" else []))
      for i, (f, s, _w, _c) in enumerate(WEAPONS, 1)],
    on_timer("weapon",
             if_(eq("stage", 2), [
                 change("volleys", 1), score(1000000), *pot_up(mul(mul(5000000, var("x")), var("volleys"))),
                 hud_counter(1, var("volleys"), "OF 3"),
                 *[if_(eq("pct", i), [award(w, value=mul(mul(5000000, var("x")), var("volleys")), sub="INTO THE POT")])
                   for i, (_f, _s, w, _c) in enumerate(WEAPONS, 1)],
                 clip("volley", "behind"), sound("volley"), show("Volley"), shake(300, "medium"),
                 if_(ge("volleys", 3), [timer_start("next", 700)])]),
             # stage 3: a carry out to sea
             if_(eq("stage", 3), [
                 change("carries", 1), score(2000000), *pot_up(mul(mul(8000000, var("x")), var("carries"))),
                 hud_counter(1, var("carries"), "OF 3"),
                 award("OUT TO SEA", value=mul(mul(8000000, var("x")), var("carries")), sub="INTO THE POT"),
                 clip("charge", "behind"), sound("fire"), show("Carry"), shake(400, "hard"),
                 if_(ge("carries", 3), [hud_line("POINT BLANK: THE CAPTIVE BALL")])]),
             timer_start("lamps", 1)),

    # ---- stage 3: the grapple ---------------------------------------------------------------------------------------
    on_shot(LANE, if_(AND(eq("stage", 3), lt("carries", 3), eq(timer_left("grab"), 0)), [
        timer_start("grab", sub(10000, mul(2000, var("plays")))),
        award("KIRYU GRABS HIM", sub="CARRY HIM: THE BIG LOOP"),
        clip("grapple", "behind"), sound("grapple"), show("Grapple"), shake(500, "strong"),
        timer_start("lamps", 1)])),
    on_timer("grab", if_(eq("stage", 3), [award("HE BREAKS FREE", sub="GRAB HIM AGAIN"), sound("overheat"),
                                          timer_start("lamps", 1)])),

    # ---- a stage done: on to the next, or cash out --------------------------------------------------------------------
    on_timer("next",
             if_(eq("cashed", 1), [end()], [
                 change("stage", 1), set_time(var("clock")), show("Stage up"), shake_game("jackpot"),
                 *pack.cash_out_lit(), *setup_stage(), timer_start("lamps", 1)])),
    on_shot(pack.CASH_SHOT,
            if_(AND(ge("stage", 2), eq("won", 0), eq("cashed", 0)), [
                set_("cashed", 1), score(var("pot")),
                award("CASHED OUT", value=var("pot"), sub="BACK TO BASE", seconds=4),
                clip("cashout", "full"), sound("cashout"), show("Home"), shake_game("big_hit"),
                timer_start("next", 1500)])),

    # the stage's last 10 s: the cash-out shot hurries (blinking faster as the clock runs down)
    secs_left(10, callout("ten_seconds"),
              if_(AND(ge("stage", 2), eq("cashed", 0)), [light(pack.CASH_SHOT, WHITE, "hurry")])),

    # ---- the end ----------------------------------------------------------------------------------------------------
    on_end(*[timer_stop(t) for t in TIMERS],
           # the clock ran out at 100% or more in stage 1: Kiryu fires on its own, x1, into nothing but its 10M
           if_(AND(eq("stage", 1), eq(SECS_LEFT, 0), gt("mult", 0)), [
               set_("won", 2), score(FIRE_VALUE), clip("fire", "full"), sound("fire"), show("Absolute zero")]),
           if_(eq("won", 1), [hud_title("KIRYU WINS"), hud_line("ABSOLUTE ZERO POINT BLANK")]),
           if_(eq("won", 2), [hud_title("KIRYU FIRES ON ITS OWN"), hud_line("ABSOLUTE ZERO X1")]),
           if_(eq("cashed", 1), [hud_title("KIRYU RETURNS TO BASE"), hud_line("THE POT IS CASHED OUT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               hud_title("KIRYU IS DOWN"), hud_line("A QUARTER OF THE POT"), score(div(var("pot"), 4)),
               clip("lost", "full"), sound("lost", fallback="time_up"), show("Down"), shake_game("rumble")]),
           set_("stage", 0), game_show("Blue fade")),
]

PROGRAM = {
    "name": NAME, "seconds": 40, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "game"} for n in ("spins", "plays", "note at")] + [
        {"name": n, "reset": "mode"} for n in ("stage", "charge", "pct", "mult", "was", "x", "heat ms", "heat max",
                                                "pips", "pot", "clock", "won", "cashed", "volleys", "carries",
                                                "w1", "w2", "w3")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("CHARGE THE ABSOLUTE ZERO: LIT SHOTS",
               counters=[("CHARGE", "PERCENT", None),            # set by the blocks: each stage counts its own
                         ("POT", "CASH AT SCOOP", var("pot")),
                         ("MULTIPLIER", "CARRIED UP", var("x"))],
               timer=("KIRYU", "snowflake"),
               gauge={"label": "CHARGE", "kind": "segment", "count": 10, "color": ICE, "value": var("pips")}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "charge", "ready", "fire", "overheat", "won", "lost", "arsenal", "volley",
                   "grapple", "cashout"),
    "sounds": sounds({"charge": 3, "ready": 4, "fire": 4, "overheat": 3, "won": 4, "lost": 4, "volley": 3,
                      "grapple": 4, "cashout": 3}),
    "music": "music.wav",
    "beds": beds("grapple"),
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 108, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "kiryu.c",
    "title_alt": {"godzilla_pro": {"shots": {"Shield ramp spinner": "Right spinner", "Shield target center": None}}},
    "about": ("The C example KIRYU rebuilt in blocks and taken deeper (PAD-658): 60 spins of the Mechagodzilla "
              "spinner start it (120 the second time, 180 the third); stage 1 charges the Absolute Zero and fires it "
              "at the captive ball, x1 to x4 as the reactor overheats, the multiplier carried up; stage 2 fires the "
              "arsenal (masers, missiles, the wrist blade); stage 3 grabs Godzilla at the Mecha lane, carries him out "
              "to sea at the Big loop and fires point blank. The pot cashes out at the right scoop after stage 1 or "
              "2. On a Pro the spinner is the Right spinner."),
    "lost": [
        "The badge always counts the stage's clock: while the reactor overheats the C counted the overheat's "
        "12 s there instead. The overheat's seconds now ride on the line (OVERHEATING! FIRE NOW 9).",
        "The counters show bare numbers: CHARGE 109 where the C showed 109%, MULTIPLIER 2 where it showed X2.",
        "The gauge stays one ice blue labelled CHARGE: the C shaded its ten pips from blue to white and relabelled "
        "it OVERHEAT while overheating and FIRED after the shot.",
        "The spin count note reads SPINS TO KIRYU with the number under it, every 10 spins, where the C said "
        "29 SPINS TO KIRYU at every spin.",
        "When the clock runs out at 100% or more in stage 1 Kiryu still fires on its own (x1, 10M), but at the end "
        "itself: the C played the shot's 4-second moment before KIRYU WINS. The C's quarter of the mode's points "
        "on top of the shot is now the pot (10M times the multiplier) cashed or carried on.",
        "The ending (its title, its line and the total) stays up 3 s, the runtime's: the C kept it 10 s.",
        "No debounce: the C counted the same target once in 250 ms (a bouncing standup pays once); the blocks "
        "count every report.",
        "A hit no longer answers by itself: the C flashed every charging shot's inserts white and played the "
        "game's climbing orchestra hit (PAD-415).",
        "Its ending call plays after a drain or one of the game's own modes ends it too (the C kept quiet then).",
        "Its own start and end light shows the C kept for a game without the game's Strobe burst and Blue fade are "
        "the mode's own shows here, played beside the game's.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _shots(name, n, gap=60):
    out = []
    for _i in range(n):
        out += ["shot", name, "ms", gap]
    return out


#: one of each charging shot: 94%
_SET = [x for s, _p in CHARGE for x in ("shot", s, "ms", 300)]
_START = ["trigger", "kiryu.start", "secs", 1]
_FIRE = _SET + ["shot", "Left ramp", "secs", 1, "shot", "Godzilla target", "secs", 2]
_ARSENAL = ["shot", "Maser target", "ms", 400, "shot", "Big loop", "ms", 400, "shot", "Building", "secs", 2]
_GRAPPLE = ["shot", LANE, "ms", 500, "shot", "Big loop", "ms", 600] * 3 + ["secs", 1]
DESK = [
    ("sixty spins the first time, a hundred and twenty the second",
     _shots(SPIN, 60) + ["secs", 1, "trigger", "kiryu.stop", "secs", 4] + _shots(SPIN, 119) + ["secs", 2] +
     _shots(SPIN, 1) + ["secs", 2],
     ["Hud_Title: SPINS TO KIRYU", "Hud_Line: 59  -  KIRYU IS BEING BUILT", "[KIRYU] START (a block)",
      "Hud_Line: 119  -  KIRYU IS BEING BUILT", "Hud_Line: 9  -  KIRYU IS BEING BUILT", "SHIELD toward"]),
    ("charge and fire: into the pot, the arsenal is next", _START + _FIRE + ["secs", 5],
     ["Hud_Award: ABSOLUTE ZERO", "Hud_Line: FIRE: THE CAPTIVE BALL  -  OR CHARGE ON", "SCORE +750000",
      "SCORE +2000000", "Hud_Award: ABSOLUTE ZERO X1", "Hud_AwardSub: 10,000,000  -  INTO THE POT",
      "Hud_Line: THE ARSENAL: FIRE EVERY WEAPON", "LAMP SELECT CITY ffffff chase", "LAMP MASER ff1010 chase"]),
    ("cash out after the cannon", _START + _FIRE + ["shot", "Right scoop", "secs", 5],
     ["Hud_Title: KIRYU RETURNS TO BASE", "SCORE +10000000", "END (a block)", "lamps held 0"]),
    ("overheat vents the charge", _START + _SET * 2 + ["shot", "Left ramp", "secs", 42],
     ["Hud_Award: X2  -  200%", "Hud_AwardSub: THE REACTOR OVERHEATS", "Hud_Line: OVERHEATING! FIRE NOW",
      "Hud_Award: KIRYU VENTS", "Hud_Line: CHARGE THE ABSOLUTE ZERO: LIT SHOTS", "END (time ran out)",
      "Hud_Title: KIRYU IS DOWN"]),
    ("push to x3, the arsenal, the grapple, point blank",
     _START + _SET * 3 + ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "secs", 1,
                          "shot", "Action button", "secs", 2] + _ARSENAL + _GRAPPLE +
     ["shot", "Godzilla target", "secs", 6],
     ["Hud_Award: X3  -  300%", "Hud_Award: ABSOLUTE ZERO X3", "Hud_Award: MASER CANNONS",
      "Hud_AwardSub: 30,000,000  -  INTO THE POT", "Hud_Award: WRIST BLADE", "Hud_Line: THE GRAPPLE: THE MECHA LANE",
      "Hud_Award: KIRYU GRABS HIM", "Hud_Award: OUT TO SEA", "Hud_Line: POINT BLANK: THE CAPTIVE BALL",
      "LAMP MAGNA GRAB ffffff chase 60", "END (a block)", "Hud_Title: KIRYU WINS", "lamps held 0"]),
    ("the grab runs out", _START + _FIRE + _ARSENAL + ["shot", LANE, "secs", 10],
     ["Hud_Award: KIRYU GRABS HIM", "Hud_Award: HE BREAKS FREE"]),
    ("the clock fires it at x1", _START + _SET + ["shot", "Left ramp", "secs", 45],
     ["Hud_Award: ABSOLUTE ZERO", "SCORE +10000000", "END (time ran out)", "Hud_Title: KIRYU FIRES ON ITS OWN",
      "lamps held 0"]),
    ("a short clock back to fifteen", _START + ["secs", 30, "shot", "Left ramp", "secs", 12],
     ["SCORE +750000", "Hud_Timer_Num: 09", "END lamps held"]),       # still running at 44 s: back to 15
    ("a drain pays a quarter of the pot", _START + _FIRE + ["ms", 500, "ball_end", "secs", 8],
     ["END (ball ended)", "SCORE +2500000", "lamps held 0"]),
]

#: PAD-658: as a Pro gets it - the Mechagodzilla spinner is the Pro's Right spinner, no centre shield to charge
DESK_PRO = [
    ("sixty spins of the Right spinner start it", _shots("Right spinner", 60) + ["secs", 2],
     ["[KIRYU] START (a block)", "Hud_Award: KIRYU ONLINE"]),
    ("charge without the centre shield and fire",
     _START + [x for s, _p in CHARGE if s != "Shield target center" for x in ("shot", s, "ms", 300)] +
     ["shot", "Left ramp", "ms", 300, "shot", "Right spinner", "secs", 1, "shot", "Godzilla target", "secs", 2],
     ["Hud_Award: ABSOLUTE ZERO X1", "Hud_Line: THE ARSENAL: FIRE EVERY WEAPON"]),
]
