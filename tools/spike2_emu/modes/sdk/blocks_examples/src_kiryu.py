"""KIRYU in blocks (PAD-658): the SDK's kiryu.c rebuilt, so David can open it in the block editor and change it.

Godzilla Against Mechagodzilla (2002): Kiryu, the Mechagodzilla built on the 1954 Godzilla's bones, carries the
Absolute Zero cannon. It has to charge, and it can run too hot. After Lyman Sheats: Metallica's Sparky (a meter the
shots fill, each start costing more) and Crank It Up's cash out or carry on.

- LIGHT IT: 30 spins of the Shield ramp spinner (the Mechagodzilla spinner) start it at once; 40 the next time, then
  50. A start that has to wait (a multiball, one of the game's modes) waits for the next spin.
- CHARGE: a 40 s clock. The ramps, the Building and the Big loop charge 15%, the Maser 10%, each Shield target 8%,
  every spin 1%; each charging shot pays 750,000 (a spin 10,000) and puts a clock under 15 s back to 15.
- FIRE: from 100% the Godzilla target (the captive ball) or the Action button fires: 10M times the multiplier plus a
  quarter of the mode's points, then KIRYU WINS 4 s later.
- PUSH IT: 200% x2, 300% x3, 400% x4 (the most). From 200% the reactor overheats: 12 s to fire, again at each 100%
  more; run out and Kiryu VENTS (the charge back to 0, the clock still running).
- ENDS: fired; the clock (at 100% or more it fires on its own at x1 with no bonus); a drain; one of the game's modes.
"""
from blk import (AND, SECS_LEFT, TOTAL, a_show, add, award, change, clip, clips, div, end, eq, every, game_show,
                 ge, gt, hud, hud_counter, hud_line, hud_title, if_, light, lt, mul, ne, off, on_drain, on_end, on_shot,
                 on_start, on_timer, score, set_, set_time, shield, show, sound, sounds, start, step, sub,
                 timer_left, timer_start, timer_stop, var)

SLUG, NAME = "kiryu", "KIRYU"
ICE, STEEL, HOT, WHITE = "#8cdcff", "#142846", "#ff2800", "#ffffff"
SPIN = "Shield ramp spinner"
FIRE_SHOTS = ("Godzilla target", "Action button")
CHARGE = (("Left ramp", 15), ("Right ramp", 15), ("Building", 15), ("Big loop", 15), ("Maser target", 10),
          ("Shield target left", 8), ("Shield target center", 8), ("Shield target right", 8))
SPINS_FIRST, SPINS_STEP = 30, 10
SHOT_VALUE, SPIN_VALUE, FIRE_VALUE = 750000, 10000, 10000000
CHARGE_MAX, HEAT_MS, FIRED_MS, FLOOR = 400, 12000, 4000, 15
MAGNA = dict(x=89, y=260)                 # the MAGNA GRAB insert (the captive ball), the port's lamp place
TIMERS = ("charge", "lamps", "heat", "fire", "fired")
NEED = add(SPINS_FIRST, mul(SPINS_STEP, var("plays")))

SHOWS = [
    a_show("Charge", step("implode", 600, WHITE, ICE, "xy", **MAGNA)),                 # each 100%
    a_show("Absolute zero",
           step("strobe", 400, WHITE, ICE, "center", rate=40, gi="flash"),
           step("burst", 900, WHITE, ICE, "xy", gi="flash", **MAGNA),
           step("sparkle", 1500, WHITE, ICE, "center"),                                  # frost
           step("fade", 700, ICE, "#000000", "center")),
    a_show("Vent",
           step("strobe", 500, HOT, "#000000", "center", rate=70, gi="flash"),
           step("fade", 500, HOT, "#000000", "center")),
]


def lamps():
    """The inserts and the HUD's words for where the charge is (the C's show_lamps and show)."""
    tl = timer_left("heat")
    return [
        if_(AND(eq("phase", 1), lt("charge", CHARGE_MAX)),
            [light(s, ICE, "blink", 500) for s, _p in CHARGE], [off(s) for s, _p in CHARGE]),
        set_("heat ms", 100), if_(gt(tl, 3000), [set_("heat ms", 200)]), if_(gt(tl, 4000), [set_("heat ms", 400)]),
        if_(gt(tl, 8000), [set_("heat ms", 700)]),
        if_(AND(eq("phase", 1), gt("mult", 0)), [
            if_(gt(tl, 0), [light(s, HOT, "blink", var("heat ms")) for s in FIRE_SHOTS],
                [light(s, WHITE, "blink", 300) for s in FIRE_SHOTS])],
            [off(s) for s in FIRE_SHOTS]),
        if_(eq("phase", 1), [
            if_(gt(tl, 0), [hud_line("OVERHEATING! FIRE NOW", value=div(add(tl, 999), 1000))], [
                if_(gt("mult", 0), [hud_line("FIRE: THE CAPTIVE BALL  -  OR CHARGE ON"),
                                    hud_counter(1, var("charge"), "READY")],
                    [hud_line("CHARGE THE ABSOLUTE ZERO: LIT SHOTS"), hud_counter(1, var("charge"), "CHARGING")])]),
            if_(ge("charge", CHARGE_MAX), [set_("pips", 10), hud_counter(3, var("x"), "THE MOST")],
                [set_("pips", div(sub(var("charge"), mul(var("mult"), 100)), 10))] +
                [if_(eq("mult", m), [hud_counter(3, var("x"), "X%d AT %d%%" % (m + 1, (m + 1) * 100))])
                 for m in range(4)]),
        ]),
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
                set_("was", var("mult")), set_("x", var("mult")),
                if_(eq("mult", 1), [award("ABSOLUTE ZERO READY", sub="FIRE: THE CAPTIVE BALL OR THE BUTTON", seconds=3),
                                    sound("ready"), clip("ready", "behind")],
                    words + [sound("charge"), clip("charge", "behind")]),
                show("Charge"),
                if_(ge("charge", 200), [timer_start("heat", HEAT_MS),
                                        if_(eq("mult", 2), [sound("overheat"), clip("overheat", "behind")])]),
            ]),
        ]),
        timer_start("lamps", 1),
    ]


def fire():
    """ABSOLUTE ZERO: the multiplier's 10M and a quarter of the mode's points, then KIRYU WINS after the moment."""
    return [
        set_("paid", add(mul(FIRE_VALUE, var("mult")), div(TOTAL, 4))), score(var("paid")),
        set_("fired", 1), set_("phase", 2), timer_stop("heat"), set_("pips", 10),
        *[if_(eq("mult", m), [award("ABSOLUTE ZERO X%d" % m, value=var("paid"), sub="KIRYU FIRES", seconds=4)])
          for m in (1, 2, 3, 4)],
        show("Absolute zero"), sound("fire"), clip("fire", "full"),
        if_(lt(SECS_LEFT, 5), [set_time(5)]),          # the C's clock stands still for the shot's moment
        timer_start("fired", FIRED_MS), timer_start("lamps", 1),
    ]


SCRIPTS = [
    # ---- light it: every spin of the Mechagodzilla spinner ---------------------------------------------------
    on_shot(SPIN,
            if_(lt("spins", NEED), [change("spins", 1)]),
            if_(ge("spins", NEED), [start()],
                [award("SPINS TO KIRYU", value=sub(NEED, var("spins")), sub="MECHAGODZILLA IS BEING BUILT")]),
            when="idle"),

    # ---- Kiryu online ------------------------------------------------------------------------------------------
    on_start(set_("spins", 0), change("plays", 1),
             set_("phase", 1), set_("charge", 0), set_("mult", 0), set_("was", 0), set_("x", 1), set_("fired", 0),
             set_("drained", 0), set_("pips", 0),
             shield("toward"), game_show("Strobe burst"), clip("intro", "full"), clip("loop", "loop"),
             award("KIRYU ONLINE", sub="CHARGE THE ABSOLUTE ZERO", seconds=3),
             timer_start("lamps", 1)),

    # ---- charge -------------------------------------------------------------------------------------------------
    *[on_shot(s, if_(eq("phase", 1), [score(SHOT_VALUE), if_(lt(SECS_LEFT, FLOOR), [set_time(FLOOR)]),
                                       set_("pct", p), timer_start("charge", 1)]))
      for s, p in CHARGE],
    on_shot(SPIN, if_(eq("phase", 1), [score(SPIN_VALUE), set_("pct", 1), timer_start("charge", 1)])),
    on_timer("charge", *charged()),
    on_timer("lamps", *lamps()),
    every(1, if_(gt(timer_left("heat"), 0), [timer_start("lamps", 1)])),     # the overheat's seconds and pace

    # ---- the reactor ran too hot: it vents ------------------------------------------------------------------------
    on_timer("heat", if_(eq("phase", 1), [
        set_("charge", 0), set_("mult", 0), set_("was", 0), set_("x", 1),
        award("KIRYU VENTS", sub="THE CHARGE IS LOST", seconds=3), show("Vent"), sound("overheat"),
        clip("overheat", "behind"), timer_start("lamps", 1)])),

    # ---- fire: the captive ball or the action button ---------------------------------------------------------------
    *[on_shot(s, if_(AND(eq("phase", 1), gt("mult", 0)), [timer_start("fire", 1)])) for s in FIRE_SHOTS],
    on_timer("fire", *fire()),
    on_timer("fired", end()),

    # ---- the end ----------------------------------------------------------------------------------------------------
    on_drain(set_("drained", 1)),
    on_end(*[timer_stop(t) for t in TIMERS],
           # the clock ran out at 100% or more: Kiryu fires on its own, x1, no bonus
           if_(AND(eq("fired", 0), eq(SECS_LEFT, 0), gt("mult", 0)), [
               set_("fired", 1), set_("mult", 1), set_("paid", FIRE_VALUE), score(FIRE_VALUE),
               award("ABSOLUTE ZERO X1", value=FIRE_VALUE, sub="KIRYU FIRES ON ITS OWN", seconds=4)]),
           set_("phase", 0),
           if_(eq("drained", 0), [if_(eq("fired", 1), [sound("won")], [sound("lost", fallback="time_up")])]),
           if_(eq("fired", 1), [clip("won", "full"), hud_title("KIRYU WINS")] +
               [if_(eq("mult", m), [hud_line("ABSOLUTE ZERO X%d  -" % m, value=var("paid"))]) for m in (1, 2, 3, 4)],
               [clip("lost", "full"), hud_title("KIRYU IS DOWN"), hud_line("THE CANNON NEVER FIRED")]),
           game_show("Blue fade")),
]

PROGRAM = {
    "name": NAME, "seconds": 40, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "game"} for n in ("spins", "plays")] + [
        {"name": n, "reset": "mode"} for n in ("phase", "charge", "pct", "mult", "was", "x", "heat ms", "pips",
                                                "paid", "fired", "drained")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("CHARGE THE ABSOLUTE ZERO: LIT SHOTS",
               counters=[("CHARGE", "CHARGING", var("charge")),
                         ("ABSOLUTE ZERO", "THE CAPTIVE BALL", add(mul(FIRE_VALUE, var("x")), div(TOTAL, 4))),
                         ("MULTIPLIER", "X1 AT 100%", var("x"))],
               timer=("KIRYU", "snowflake"),
               gauge={"label": "CHARGE", "kind": "segment", "count": 10, "color": ICE, "value": var("pips")}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "charge", "ready", "fire", "overheat", "won", "lost"),
    "sounds": sounds({"charge": 3, "ready": 4, "fire": 4, "overheat": 3, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 108, "titles": ["godzilla_le"], "based_on": "kiryu.c",
    "about": ("The C example KIRYU rebuilt in blocks: 30 spins of the Mechagodzilla spinner start it, the lit shots "
              "charge the Absolute Zero, and from 100% the captive ball or the Action button fires it - or push on to "
              "x2, x3, x4 while the reactor overheats and may vent."),
    "lost": [
        "The badge always counts the mode's 40 s clock: while the reactor overheats the C counted the overheat's "
        "12 s there instead. The overheat's seconds now ride on the line (OVERHEATING! FIRE NOW 9).",
        "The counters show bare numbers: CHARGE 109 where the C showed 109%, MULTIPLIER 2 where it showed X2.",
        "The gauge stays one ice blue labelled CHARGE: the C shaded its ten pips from blue to white and relabelled "
        "it OVERHEAT while overheating and FIRED after the shot.",
        "The spin count note reads SPINS TO KIRYU 29 (the number after the words) where the C said 29 SPINS TO "
        "KIRYU.",
        "When the clock runs out at 100% or more Kiryu still fires on its own (x1, 10M, no bonus), but at the end "
        "itself: the C played the shot's 4-second moment (its clip and frost light show) before KIRYU WINS.",
        "After firing, the badge keeps counting (the clock is only held at 5 s or more) where the C stopped and hid "
        "it for the shot's moment.",
        "The ending (KIRYU WINS or KIRYU IS DOWN, its line and the total) stays up 3 s, the runtime's: the C kept "
        "it 10 s.",
        "No debounce: the C counted the same target once in 250 ms (a bouncing standup pays once); the blocks "
        "count every report.",
        "A hit no longer answers by itself: the C flashed every charging shot's inserts white and played the "
        "game's climbing orchestra hit (PAD-415).",
        "Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does "
        "for a drain or a tilt).",
        "Its own start and end light shows are gone: the C used them only on a game without the game's Strobe "
        "burst and Blue fade, which Godzilla Premium/LE has.",
        "For Godzilla Premium/LE only: the C also ran on Godzilla Pro (its Right spinner, no Shield target "
        "center), and a blocks program names one spinner.",
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
DESK = [
    ("thirty spins then forty", _shots(SPIN, 30) + ["secs", 1, "trigger", "kiryu.stop", "secs", 4] +
     _shots(SPIN, 39) + ["secs", 2] + _shots(SPIN, 1) + ["secs", 2],
     ["Hud_Award: SPINS TO KIRYU 29", "Hud_Award: SPINS TO KIRYU 1", "[KIRYU] START (a block)",
      "Hud_Award: SPINS TO KIRYU 39", "SHIELD toward"]),
    ("charge and fire at the captive ball", _START + _SET + ["shot", "Left ramp", "secs", 1,
                                                             "shot", "Godzilla target", "secs", 6],
     ["Hud_Award: ABSOLUTE ZERO READY", "Hud_Line: FIRE: THE CAPTIVE BALL  -  OR CHARGE ON",
      "SCORE +750000", "SCORE +11687500", "Hud_Award: ABSOLUTE ZERO X1 11,687,500", "END (a block)",
      "Hud_Title: KIRYU WINS", "Hud_Line: ABSOLUTE ZERO X1  - 11,687,500", "lamps held 0"]),
    ("overheat vents the charge", _START + _SET * 2 + ["shot", "Left ramp", "secs", 42],
     ["Hud_Award: X2  -  200%", "Hud_AwardSub: THE REACTOR OVERHEATS", "Hud_Line: OVERHEATING! FIRE NOW",
      "Hud_Award: KIRYU VENTS", "Hud_Line: CHARGE THE ABSOLUTE ZERO: LIT SHOTS", "END (time ran out)",
      "Hud_Title: KIRYU IS DOWN", "Hud_Line: THE CANNON NEVER FIRED"]),
    ("push to x3 and fire the button", _START + _SET * 3 + ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "secs", 1,
                                                             "shot", "Action button", "secs", 6],
     ["Hud_Award: X3  -  300%", "Hud_Award: ABSOLUTE ZERO X3 34,875,000", "SCORE +34875000", "END (a block)", "lamps held 0"]),
    ("the clock fires it at x1", _START + _SET + ["shot", "Left ramp", "secs", 45],
     ["Hud_Award: ABSOLUTE ZERO READY", "SCORE +10000000", "END (time ran out)", "Hud_Title: KIRYU WINS",
      "Hud_Line: ABSOLUTE ZERO X1  - 10,000,000", "lamps held 0"]),
    ("a short clock back to fifteen", _START + ["secs", 30, "shot", "Left ramp", "secs", 12],
     ["SCORE +750000", "Hud_Timer_Num: 09", "END lamps held 8"]),       # still running at 44 s: the clock went back to 15
    ("a drain ends it", _START + _SET + ["ms", 500, "ball_end", "secs", 8],
     ["END (ball ended)", "lamps held 0"]),
]
