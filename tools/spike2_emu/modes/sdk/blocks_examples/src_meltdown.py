"""MELTDOWN (PAD-658): the SDK's C example meltdown.c rebuilt in blocks - a push-your-luck multiball of our own.

Burning Godzilla (Godzilla vs. Destoroyah, 1995): his heart is a nuclear reactor running away.

- LIGHT IT: 10 hits of the MAGNA-GRAB captive ball (the Godzilla target) in a game; then it pulses red and the next
  hit starts it (not beside the game's own battle or multiball: it waits, still ready).
- START: a 3-ball multiball with a 15 s ball save; the shields turn toward the player.
- THE CORE starts at 25% and rises 1% a second (2% from 70%); a jackpot heats it 4% (the HEART 8%). STABLE under
  40% x1, HOT x2, CRITICAL (70%) x3, MELTDOWN IMMINENT (90%) x5.
- JACKPOTS: the Left ramp, Right ramp, Building and Big loop: 2,000,000 x the heat (+500,000 on the base for each
  meltdown survived). One of them is the HEART (double): it moves every 8 s and when hit (in turn here).
- CADMIUM: each Shield target cools the core 12%.
- MELTDOWN at 100%: for 20 s the Building is the SUPER JACKPOT, twice the jackpots paid since the last one. Hit it:
  the core back to 25% and the base up 500,000. Miss it: the core blows, back to 50%, the base back to 2,000,000.
- ADD-A-BALL: after 4 jackpots the captive ball adds a ball, once.
- ENDS: one ball left after the ball save and 3 s more (for 2 s), the last drain, a tilt.
"""
from blk import (AND, BALLS, LIT, NOT, a_show, add, award, change, clip, clips, div, end, eq, every, game_show, ge, gt,
                 hud, hud_counter, hud_line, hud_title, if_, le, light, light_mode, lt, mul, multiball, off,
                 on_any_shot, on_end, on_shot, on_start, on_timer, score, set_, shield, show, sound, sounds, step, sub,
                 timer_left, timer_start, timer_stop, var)

SLUG, NAME = "meltdown", "MELTDOWN"
RED, ORANGE, EMBER, ICE, WHITE, GREEN = "#ff1400", "#ff5a00", "#460800", "#78d2ff", "#ffffff", "#00ff3c"
HEAT = ("#ffd200", "#ff6e00", "#ff1400", "#ffffff")              # STABLE, HOT, CRITICAL, IMMINENT
LEVELS = ("STABLE", "HOT", "CRITICAL", "IMMINENT")
MULT = (1, 2, 3, 5)
LIGHT_SHOT = "Godzilla target"                                    # the MAGNA-GRAB captive ball
JP = ("Left ramp", "Right ramp", "Building", "Big loop")
SHIELDS = ("Shield target left", "Shield target center", "Shield target right")
BX, BY = 123, 202                                                  # the BUILDING insert: the C's KIT_AT_BUILDING
SX, SY = 199, 346                                                  # SHIELD CENTER: the C's KIT_AT_SHIELDS
TIMERS = ("core", "jackpot", "melt", "lights")

SHOWS = [
    a_show("Meltdown",
           step("strobe", 700, WHITE, RED, "center", rate=45, gi="flash"),
           step("implode", 900, WHITE, RED, "xy", gi="dark", x=BX, y=BY),
           step("fire", 1000, WHITE, RED, "center", gi="dark")),
    a_show("Junior",
           step("burst", 800, WHITE, ICE, "xy", gi="flash", x=BX, y=BY),
           step("sparkle", 1000, ICE, "#001e50", "center"),
           step("fade", 500, ICE, "#000000", "center")),
    a_show("Cadmium",
           step("sweep_rl", 500, ICE, "#00143c", "xy", x=SX, y=SY)),
]


def lights():
    """The C's show_lamps and show: the four jackpots in the heat's colour (the heart faster), the shields ice blue
    from 40%, the captive ball green while the add-a-ball is lit; in MELTDOWN only the Building, white."""
    burn = []
    for lv in range(4):
        rest, fast = (150 if lv == 3 else 500), (100 if lv >= 2 else 250)
        burn.append(if_(eq("level", lv), [
            if_(eq("heart", i), [light(s, HEAT[lv], "blink", fast)], [light(s, HEAT[lv], "blink", rest)])
            for i, s in enumerate(JP, 1)]))
    return [
        if_(eq("phase", 1), burn + [
            if_(ge("core", 40), [light(s, ICE, "pulse", 900) for s in SHIELDS], [off(s) for s in SHIELDS]),
            if_(AND(eq("add used", 0), ge("jackpots", 4)), [light(LIGHT_SHOT, GREEN, "blink", 300)],
                [off(LIGHT_SHOT)]),
            if_(ge("level", 2), [hud_line("SHIELDS COOL THE CORE - OR RIDE THE HEAT")],
                [hud_line("SHOOT RED SHOTS - THE HEART PAYS DOUBLE")]),
            hud_counter(2, mul(var("base"), var("mult")), None),
        ], [
            *[off(s) for s in JP if s != "Building"], *[off(s) for s in SHIELDS], off(LIGHT_SHOT),
            light("Building", WHITE, "blink", 120),
            hud_counter(2, mul(var("paid"), 2), "SUPER JACKPOT"),
        ]),
    ]


def core_sub():
    """The core moved: clamp it, MELTDOWN at 100%, else its level (a hotter one says so)."""
    return [
        if_(gt("core", 100), [set_("core", 100)]), if_(lt("core", 0), [set_("core", 0)]),
        if_(AND(eq("phase", 1), ge("core", 100)), [
            set_("phase", 2), set_("level", 3), set_("was level", 3), set_("mult", 5), timer_start("melt", 20000),
            award("MELTDOWN!", sub="20 SECONDS: SHOOT THE BUILDING", seconds=3), show("Meltdown"),
            sound("meltdown"), clip("meltdown", "full"),
            hud_title("MELTDOWN!"), hud_line("SHOOT THE BUILDING: SUPER JACKPOT"), hud_counter(1, 100, "MELTDOWN"),
        ], [
            set_("level", 0), if_(ge("core", 40), [set_("level", 1)]), if_(ge("core", 70), [set_("level", 2)]),
            if_(ge("core", 90), [set_("level", 3)]),
            *[if_(eq("level", lv), [set_("mult", MULT[lv]), hud_counter(1, var("core"), LEVELS[lv]),
                                    hud_counter(2, mul(var("base"), MULT[lv]), "X%d HEAT" % MULT[lv])])
              for lv in range(4)],
            if_(gt("level", "was level"), [
                if_(eq("level", 1), [award("HOT", sub="JACKPOTS ARE WORTH MORE"), sound("heat")]),
                if_(eq("level", 2), [award("CRITICAL", sub="JACKPOTS ARE WORTH MORE"), sound("critical"),
                                     clip("critical", "behind")]),
                if_(eq("level", 3), [award("MELTDOWN IMMINENT", sub="SHOOT THE SHIELDS TO COOL HIM"),
                                     sound("heat")]),
            ]),
            set_("was level", var("level")),
        ]),
        timer_start("lights", 1),
    ]


def heart_moves():
    return [change("heart", 1), if_(gt("heart", 4), [set_("heart", 1)]), set_("heart secs", 0)]


def back_to_burn(core):
    return [set_("phase", 1), set_("paid", 0), set_("core", core), set_("heart secs", 0), timer_stop("melt"),
            hud_title("BURNING GODZILLA"), timer_start("core", 1)]


SCRIPTS = [
    # ---- light it: ten captive ball hits ------------------------------------------------------------------------
    on_shot(LIGHT_SHOT, if_(eq("ready", 0), [
        change("hits", 1),
        if_(ge("hits", 10), [
            set_("ready", 1), light_mode(LIGHT_SHOT, RED, "pulse"), sound("lit"),
            award("MELTDOWN IS READY", sub="HIT THE CAPTIVE BALL", seconds=3)], [
            award("CAPTIVE BALL", value=sub(10, var("hits")), sub="MORE FOR MELTDOWN", seconds=2)])]), when="idle"),
    on_any_shot(if_(AND(eq("ready", 1), NOT(LIT)), [light_mode(LIGHT_SHOT, RED, "pulse")]), when="idle"),

    # ---- the multiball -------------------------------------------------------------------------------------------
    on_start(set_("ready", 0), set_("hits", 0), multiball(3, 15), shield("toward"),
             set_("phase", 1), set_("core", 25), set_("level", 0), set_("was level", 0), set_("mult", 1),
             set_("base", 2000000), set_("heart", 1), set_("heart secs", 0), set_("jackpots", 0), set_("paid", 0),
             set_("meltdowns", 0), set_("add used", 0), set_("secs", 0), set_("one ball", 0),
             game_show("Strobe storm"), clip("intro", "full"), clip("loop", "loop"),
             hud_title("BURNING GODZILLA"),
             award("MELTDOWN MULTIBALL", sub="HIS HEART IS A NUCLEAR REACTOR", seconds=3),
             timer_start("core", 1)),
    on_timer("core", *core_sub()),
    on_timer("lights", *lights()),

    # ---- every second: the core rises, the heart moves, MELTDOWN counts down, one ball left ends it ----------------
    every(1,
          change("secs", 1),
          if_(eq("phase", 1), [
              if_(ge("core", 70), [change("core", 2)], [change("core", 1)]),
              change("heart secs", 1), if_(ge("heart secs", 8), heart_moves()),
              timer_start("core", 1)], [
              hud_line("SUPER JACKPOT AT THE BUILDING:", value=div(timer_left("melt"), 1000)),
              if_(le(timer_left("melt"), 5000), [light("Building", WHITE, "blink", 60)])]),
          if_(gt("secs", 18), [
              if_(lt(BALLS, 2), [change("one ball", 1), if_(ge("one ball", 2), [end()])], [set_("one ball", 0)])])),

    # ---- jackpots ---------------------------------------------------------------------------------------------------
    *[on_shot(s, if_(eq("phase", 1), [set_("jp", i), timer_start("jackpot", 1)]))
      for i, s in enumerate(JP, 1) if s != "Building"],
    on_shot("Building",
            if_(eq("phase", 1), [set_("jp", 3), timer_start("jackpot", 1)], [
                # MELTDOWN: the super jackpot, twice the jackpots paid (five jackpots at x5 when none were)
                set_("got", mul(var("paid"), 2)), if_(eq("paid", 0), [set_("got", mul(var("base"), 25))]),
                score(var("got")), change("meltdowns", 1), change("base", 500000),
                award("MELTDOWN SUPER JACKPOT", value=var("got"), sub="THE CORE BACK TO 25%", seconds=4),
                show("Junior"), sound("won"), clip("won", "full"), *back_to_burn(25)])),
    on_timer("jackpot",
             set_("got", var("base")), set_("got", mul(var("got"), var("mult"))),
             if_(eq("jp", "heart"), [set_("got", mul(var("got"), 2))]),
             score(var("got")), change("paid", var("got")), change("jackpots", 1),
             hud_counter(3, var("jackpots"), " "),
             sound("jackpot"), clip("jackpot", "behind"),
             if_(eq("jp", "heart"), [award("HEART JACKPOT", value=var("got"), seconds=2), change("core", 8),
                                     *heart_moves()],
                 [award("JACKPOT", value=var("got"), seconds=2), change("core", 4)]),
             timer_start("core", 1)),

    # ---- cadmium at the shields ---------------------------------------------------------------------------------------
    *[on_shot(s, if_(eq("phase", 1), [
        change("core", -12), award("CADMIUM MISSILE", sub="THE CORE COOLS", seconds=2), show("Cadmium"),
        sound("cool"), clip("cool", "behind"), timer_start("core", 1)])) for s in SHIELDS],

    # ---- add-a-ball at the captive ball -----------------------------------------------------------------------------
    on_shot(LIGHT_SHOT, if_(AND(eq("phase", 1), eq("add used", 0), ge("jackpots", 4)), [
        set_("add used", 1),
        if_(eq(BALLS, 1), [multiball(2, 10)], [if_(eq(BALLS, 2), [multiball(3, 10)], [
            if_(eq(BALLS, 3), [multiball(4, 10)], [if_(eq(BALLS, 4), [multiball(5, 10)])])])]),
        award("ADD-A-BALL", sub="ANOTHER BALL IN PLAY", seconds=2), sound("add"), timer_start("lights", 1)])),

    # ---- MELTDOWN missed: the core blows -----------------------------------------------------------------------------
    on_timer("melt", if_(eq("phase", 2), [
        award("THE CORE BLOWS", sub="THE JACKPOTS START AGAIN", seconds=3), sound("lost", fallback="time_up"),
        set_("base", 2000000), *back_to_burn(50)])),

    on_end(*[timer_stop(t) for t in TIMERS], set_("phase", 0), game_show("Ember fade"),
           if_(gt("meltdowns", 0), [clip("won", "full")], [clip("lost", "full")]),
           # under MELTDOWN TOTAL: the jackpots and the meltdowns survived (a number can only come last)
           *[if_(eq("meltdowns", m), [hud_line("%d MELTDOWN%s SURVIVED  -  JACKPOTS" % (m, "" if m == 1 else "S"),
                                               value=var("jackpots"))]) for m in range(4)],
           if_(gt("meltdowns", 3), [hud_line("JACKPOTS", value=var("jackpots"))]),),
]

PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 190,
    "vars": [{"name": n, "reset": "game"} for n in ("hits", "ready")] + [
        {"name": n, "reset": "mode"} for n in ("phase", "core", "level", "was level", "mult", "base", "heart",
                                                "heart secs", "jp", "got", "jackpots", "paid", "meltdowns",
                                                "add used", "secs", "one ball")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("SHOOT RED SHOTS - SHIELDS COOL THE CORE",
               counters=[("CORE", "STABLE", None), ("JACKPOT", "X1 HEAT", None), ("JACKPOTS", " ", None)],
               timer=None,
               gauge={"label": "CORE", "kind": "segment", "count": 10, "color": ORANGE,
                      "value": div(add(var("core"), 9), 10)}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "jackpot", "cool", "critical", "meltdown", "won", "lost"),
    "sounds": sounds({"lit": 4, "jackpot": 3, "cool": 4, "critical": 4, "meltdown": 4, "won": 4, "add": 3,
                      "heat": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 106, "titles": ["godzilla_le"], "based_on": "meltdown.c",
    "about": ("The C example MELTDOWN rebuilt in blocks: ten captive ball hits light a 3-ball multiball where the "
              "core heats by itself and with every jackpot (x1 to x5), the shields cool it, and at 100% the "
              "Building is a super jackpot worth twice the jackpots paid."),
    "lost": [
        "No randomness in blocks: the HEART starts at the Left ramp and moves in turn (Left ramp, Right ramp, "
        "Building, Big loop) every 8 s and when hit, where the C picked another shot at random.",
        "The core is looked at once a second (an Every second script), so it rises a whole 1% or 2% each second "
        "and the MELTDOWN blink quickens on the second, where the C stepped them every tick.",
        "No timer badge: the MELTDOWN 20 s is a timer the line counts (SUPER JACKPOT AT THE BUILDING: 17), where "
        "the C counted it on the MELTDOWN badge (a blocks badge counts only the mode's own clock, and this mode "
        "has none).",
        "The HUD shows the core as a number (25), not 25%; the JACKPOTS counter has no SUPER value under it; the "
        "CORE gauge is one colour (the C's ran yellow to white-hot); the lines lost their double spaces to fit "
        "the 40 letters a blocks HUD line holds.",
        "The ending's line under MELTDOWN TOTAL puts the jackpots last (1 MELTDOWN SURVIVED  -  JACKPOTS 6) where "
        "the C said 6 JACKPOTS  -  1 MELTDOWN SURVIVED, says JACKPOTS for one too, and past 3 meltdowns says only "
        "the jackpots.",
        "The ending stays up 3 s, the runtime's: the C kept it 10 s.",
        "The captive ball counts toward lighting it while another of our modes runs, where the C left the shot "
        "to that mode.",
        "The ready light is the runtime's lit mode (held ball after ball), where the C pulsed MAGNA GRAB only while "
        "nothing else owned the playfield.",
        "One ball left is checked once a second after 18 s (two looks in a row), the C's 2 s after the 15 s ball "
        "save and 3 s grace; and the C noted whether a second ball was ever served.",
        "Godzilla LE only: the program names the center shield target (Godzilla Pro has two shields).",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _shots(name, n, gap=200):
    out = []
    for _i in range(n):
        out += ["shot", name, "ms", gap]
    return out


_START = ["trigger", "meltdown.start", "secs", 1]
#: the heart in turn: each shot here is the heart (Left ramp first), 8% a time
_HEARTS = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Building", "ms", 300,
           "shot", "Big loop", "ms", 300]
#: nine hearts in a row (8% each, the core rising too) take the core from 25% to 100%: MELTDOWN
_TO_MELTDOWN = _HEARTS * 2 + ["shot", "Left ramp", "secs", 3]
DESK = [
    ("ten hits light it and the next starts it", _shots(LIGHT_SHOT, 10, 300) + ["secs", 1, "lamps"] +
     ["shot", LIGHT_SHOT, "secs", 2],
     ["Hud_Award: CAPTIVE BALL 9", "Hud_Award: MELTDOWN IS READY", "LAMP MAGNA GRAB ff1400 pulse",
      "[MELTDOWN] START (its lit shot)", "MULTIBALL 3 balls, save 15 s", "SHIELD toward",
      "Hud_Award: MELTDOWN MULTIBALL"]),
    ("jackpots heat the core and cadmium cools it", _START + _HEARTS + ["shot", "Left ramp", "ms", 300] +
     ["secs", 1, "shot", "Shield target left", "secs", 1, "lamps"],
     ["SCORE +4000000", "Hud_Award: HEART JACKPOT 4,000,000", "Hud_Award: HOT", "SCORE +8000000",
      "LAMP BUILDING ff6e00 blink 250", "LAMP SHIELD LEFT 78d2ff pulse 900", "LAMP MAGNA GRAB 00ff3c blink 300",
      "Hud_Award: CADMIUM MISSILE"]),
    ("meltdown and the super jackpot", _START + _TO_MELTDOWN + ["shot", "Building", "secs", 2,
                                                                "shot", "Godzilla target", "secs", 2,
                                                                "trigger", "meltdown.stop", "secs", 2],
     ["Hud_Award: CRITICAL", "Hud_Award: MELTDOWN IMMINENT", "Hud_Award: MELTDOWN!",
      "LAMP BUILDING ffffff blink 120", "SCORE +168000000", "Hud_Award: MELTDOWN SUPER JACKPOT 168,000,000",
      "MULTIBALL 4 balls, save 10 s", "END (trigger file)", "Hud_Line: 1 MELTDOWN SURVIVED  -  JACKPOTS"]),
    ("meltdown missed the core blows", _START + _TO_MELTDOWN + ["secs", 15, "lamps", "secs", 5],
     ["Hud_Award: MELTDOWN!", "Hud_Line: SUPER JACKPOT AT THE BUILDING: 5", "LAMP BUILDING ffffff blink 60",
      "Hud_Award: THE CORE BLOWS", "own sound lost", "WORDS PadMode_meltdown_Hud_C1_Value: 50"]),
    ("one ball left ends it", _START + ["secs", 5, "balls", 1, "secs", 18],
     ["END (a block)", "own clip lost", "Hud_Title: MELTDOWN TOTAL",
      "Hud_Line: 0 MELTDOWNS SURVIVED  -  JACKPOTS 0", "lamps held 0"]),
    ("the last drain", _START + ["shot", "Left ramp", "secs", 2, "balls", 1, "ball_end", "secs", 8],
     ["END (ball ended)", "lamps held 0"]),
]
