"""DESTOROYAH in blocks (PAD-658): the SDK's destoroyah.c rebuilt, so David can open it in the block editor and change it.

Godzilla vs. Destoroyah (1995): the micro-oxygen of the Oxygen Destroyer woke something in Tokyo Bay; the crab-like
aggregates swarm into the city, then merge into Destoroyah's perfect form. After Lyman Sheats' Horde in The Walking
Dead: walkers advance on you, a kill is worth more the closer it is, a cleared wave pays a super worth the wave.

- LIGHT IT: 30 spins of the Top spinner (every spin counts) start it at once; 40 the next time, then 50.
- THE SWARM: aggregates come over the top at the POWERLINES (far, x1) and advance every few seconds to the RAMPS, the
  BUILDING or the BIG LOOP (near, x2), to the MASER, the SHIELDS or the CAPTIVE BALL (close, x4), and then into the
  city. Two at a time at most. A kill pays 1,000,000 (+250,000 a wave) times how close it was.
- WAVES: wave 1 needs 3 kills, wave 2 4, wave 3 5; they advance every 7, 6 and 5 s. A cleared wave pays the WAVE
  SUPER: every kill of the wave again.
- THE CITY: an aggregate past the close shots hits the city; three hits and Destoroyah wins.
- PERFECT FORM: after wave 3, 25 s at the BUILDING: three hits of 5,000,000, the third the SUPER JACKPOT (every kill
  of the mode again).

Built to be taken apart: RINGS says each ring's shots, multiplier and light, and every aggregate is a variable
holding the NUMBER of the shot it stands on (1-12 down the playfield, 0 = none), so a ring's shots are a range of
numbers. A new aggregate slot is one more variable, step timer and swarm_slot() call; another ring is one more row of
RINGS (the city comes after the last). The C picked each next shot at random; here pick() deals them out in turn
from a counter ("turn") that keeps running all game, skipping the shot the other aggregate stands on.
"""
from blk import (AND, OR, a_show, add, award, change, clip, clips, div, end, eq, every, game_show, ge, gt, hud,
                 hud_counter, hud_line, hud_title, if_, le, light, lt, mul, off, on_drain, on_end, on_shot, on_start,
                 on_timer, score, set_, shake_game, shield, show, sound, sounds, start, step, sub, timer_left,
                 timer_start, timer_stop, var)

SLUG, NAME = "destoroyah", "DESTOROYAH"
RED, DARK, GLOW = "#ff001e", "#28000a", "#ff7800"
SPIN, BOSS = "Top spinner", "Building"
SPINS_FIRST, SPINS_STEP = 30, 10
#: (name, multiplier, light colour, blink ms, its shots) from the top of the playfield down; a shot's number is its
#: place in this list, counted from 1 across the rings
RINGS = (
    ("FAR", 1, "#ffc800", 700, ("Powerline left", "Powerline center", "Powerline right")),
    ("NEAR", 2, "#ff5000", 400, ("Left ramp", "Right ramp", "Big loop", "Building")),
    ("CLOSE", 4, "#ff0000", 120, ("Maser target", "Shield target left", "Shield target center", "Shield target right",
                                  "Godzilla target")),
)
SHOTS = [s for r in RINGS for s in r[4]]
NUM = {s: i + 1 for i, s in enumerate(SHOTS)}                 # a shot's number
FIRST = []                                                    # each ring's first number
for _r in RINGS:
    FIRST.append(1 + sum(len(r[4]) for r in RINGS[:len(FIRST)]))
LAST = [f + len(r[4]) - 1 for f, r in zip(FIRST, RINGS)]
SLOTS = (("a", "step a"), ("b", "step b"))                    # the aggregates: where each stands, its step timer
WAVES, FIRST_NEED = 3, 3                                      # kills in wave 1; one more a wave
KILL_VALUE, KILL_WAVE_STEP = 1000000, 250000
ADVANCE_FIRST_MS = 7000                                       # one second faster a wave
SPAWN_AFTER_MS, WAVE_GAP_MS, INTRO_MS = 1200, 2500, 2500
CITY_HITS, BOSS_MS, BOSS_HITS, BOSS_HIT_VALUE = 3, 25000, 3, 5000000
BUILDING = dict(x=123, y=202)                                 # the BUILDING insert, the port's lamp place
TIMERS = ("step a", "step b", "spawn", "kill", "boss", "lamps")
NEED = add(FIRST_NEED - 1, var("wave"))                       # this wave's kills
LEFT = sub(NEED, var("kills"))
SPINS_NEED = add(SPINS_FIRST, mul(SPINS_STEP, var("plays")))

SHOWS = [
    a_show("Wave",                                                                       # the swarm merges
           step("implode", 800, GLOW, DARK, "center", gi="flash"),
           step("fade", 400, GLOW, "#000000", "center")),
    a_show("City", step("strobe", 400, RED, "#000000", "center", rate=60, gi="flash")),
    a_show("Perfect form",
           step("bolts", 900, RED, DARK, "center", rate=130, gi="dark"),
           step("burst", 800, GLOW, RED, "xy", gi="dark", **BUILDING),                  # he stands up
           step("spin", 900, RED, DARK, "xy", rate=90, **BUILDING)),
]


def mod(x, n):
    return sub(x, mul(div(x, n), n))


def pick(ring, other):
    """The next shot of ``ring`` (0 = the first) into "pos", dealt in turn, never the one ``other`` stands on."""
    n, lo = len(RINGS[ring][4]), FIRST[ring]
    deal = [set_("pos", add(lo, mod(var("turn"), n))), change("turn", 1)]
    return deal + [if_(eq("pos", var(other)), deal)]


def ring_of(at):
    """The blocks that set "ring" (1, 2, 3...) from a shot's number in the variable ``at``."""
    return [set_("ring", 1)] + [if_(gt(at, LAST[i - 1]), [set_("ring", i + 1)]) for i in range(1, len(RINGS))]


def swarm_slot(me, other, timer):
    """An aggregate's step: on to the next ring, or (from the last) into the city."""
    return on_timer(timer, if_(AND(eq("phase", 1), gt(me, 0)), [
        if_(ge(me, FIRST[-1]), [
            set_(me, 0), change("city", 1),
            award("THE CITY IS HIT", sub="2 HITS LEFT", seconds=2),
            if_(eq("city", 2), [award("THE CITY IS HIT", sub="1 HIT LEFT", seconds=2)]),
            if_(ge("city", CITY_HITS), [award("THE CITY IS HIT", sub="0 HITS LEFT", seconds=2)]),
            show("City"), sound("escape"), clip("escape", "behind"),
            if_(ge("city", CITY_HITS), [end()], [timer_start("spawn", SPAWN_AFTER_MS)])],
            [*ring_of(var(me)),
             *[if_(eq("ring", i + 1), pick(i + 1, other)) for i in range(len(RINGS) - 1)],
             set_(me, var("pos")), timer_start(timer, var("advance ms"))]),
        timer_start("lamps", 1)]))


def lamps():
    """Each aggregate's shot in its ring's light; the perfect form: the Building red, faster as its 25 s run out.
    The HUD's words and counters follow."""
    out = []
    for i, r in enumerate(RINGS):
        for s in r[4]:
            k = NUM[s]
            here = OR(eq("a", k), eq("b", k))
            lit = [light(s, r[2], "blink", r[3])]
            if s == BOSS:
                out.append(if_(eq("phase", 3), [light(s, RED, "blink", var("rate"))],
                               [if_(here, lit, [off(s)])]))
            else:
                out.append(if_(here, lit, [off(s)]))
    tl = timer_left("boss")
    return [
        set_("rate", 100), if_(gt(tl, 3000), [set_("rate", 200)]), if_(gt(mul(tl, 3), BOSS_MS), [set_("rate", 400)]),
        if_(gt(mul(tl, 3), 2 * BOSS_MS), [set_("rate", 700)]),
        *out,
        hud_counter(3, sub(CITY_HITS, var("city")), "HITS TO TAKE"),
        if_(eq("phase", 3), [
            hud_title("PERFECT DESTOROYAH"), hud_line("SHOOT THE BUILDING: 3 HITS"),
            hud_counter(1, var("boss hits"), "PERFECT FORM", label="HITS"),
            hud_counter(2, var("kill total"), "EVERY KILL AGAIN", label="SUPER JACKPOT"),
            set_("gauge", var("boss hits"))], [
            hud_counter(1, var("wave"), "OF 3"),
            *[if_(eq("wave", w), [hud_counter(2, var("kills"), "OF %d" % (FIRST_NEED + w - 1)),
                                  if_(eq("phase", 2), [hud_line("WAVE %d IS COMING" % w)],
                                      [hud_line("WAVE %d: CLOSER PAYS MORE  -  TO GO" % w, value=LEFT)])])
              for w in range(1, WAVES + 1)],
            set_("gauge", var("kills"))]),
    ]


def kill():
    """The aggregate on shot "killed" is blown apart: the kill value times its ring's multiplier."""
    return [if_(OR(eq("a", var("killed")), eq("b", var("killed"))), [
        if_(eq("a", var("killed")), [set_("a", 0), timer_stop("step a")], [set_("b", 0), timer_stop("step b")]),
        *ring_of(var("killed")),
        set_("kill value", add(KILL_VALUE, mul(KILL_WAVE_STEP, sub(var("wave"), 1)))),
        *[if_(eq("ring", i + 1), [set_("kill value", mul(var("kill value"), r[1])),
                                  award("%s KILL X%d" % (r[0], r[1]), value=var("kill value"), seconds=2)])
          for i, r in enumerate(RINGS)],
        score(var("kill value")), change("wave total", var("kill value")), change("kill total", var("kill value")),
        change("kills", 1), change("all kills", 1),
        sound("kill"), if_(eq("clip ok", 1), [clip("kill", "behind"), set_("clip ok", 0)]),
        if_(ge("kills", NEED), wave_cleared(), [timer_start("spawn", SPAWN_AFTER_MS)]),
        timer_start("lamps", 1)])]


def wave_cleared():
    """The WAVE SUPER (every kill of the wave again); then the next wave after a gap, or the perfect form."""
    return [
        score(var("wave total")),
        *[if_(eq("wave", w), [award("WAVE %d CLEARED" % w, value=var("wave total"), seconds=3)])
          for w in range(1, WAVES + 1)],
        show("Wave"), sound("wave"), clip("wave", "behind"),
        set_("a", 0), set_("b", 0), timer_stop("step a"), timer_stop("step b"),
        if_(ge("wave", WAVES), [
            set_("phase", 3), set_("boss hits", 0), timer_start("boss", BOSS_MS),
            award("PERFECT FORM", sub="THE BUILDING: THREE HITS", seconds=3),
            show("Perfect form"), sound("boss"), clip("boss", "full")],
            [set_("phase", 2), change("wave", 1), timer_start("spawn", WAVE_GAP_MS)]),
    ]


def spawn():
    """A wave begins after its gap; then, every so often, an aggregate comes over the top into an empty slot while
    the wave still needs more kills than there are aggregates."""
    return [
        if_(eq("phase", 2), [set_("phase", 1), set_("kills", 0), set_("wave total", 0),
                             set_("advance ms", sub(ADVANCE_FIRST_MS + 1000, mul(1000, var("wave"))))]),
        if_(eq("phase", 1), [
            if_(AND(eq("a", 0), OR(eq("b", 0), ge(LEFT, 2))),
                pick(0, "b") + [set_("a", var("pos")), timer_start("step a", var("advance ms"))],
                [if_(AND(eq("b", 0), ge(LEFT, 2)),
                     pick(0, "a") + [set_("b", var("pos")), timer_start("step b", var("advance ms"))])]),
            timer_start("spawn", SPAWN_AFTER_MS)]),
        timer_start("lamps", 1),
    ]


SCRIPTS = [
    # ---- light it: every spin of the Top spinner -----------------------------------------------------------------
    on_shot(SPIN,
            if_(lt("spins", SPINS_NEED), [change("spins", 1)]),
            if_(ge("spins", SPINS_NEED), [start()],
                [if_(eq(mod(var("spins"), 2), 0),
                     [award("SPINS TO DESTOROYAH", value=sub(SPINS_NEED, var("spins")),
                            sub="THE MICRO-OXYGEN SPREADS")])]),
            when="idle"),

    # ---- the aggregates are coming --------------------------------------------------------------------------------
    on_start(set_("spins", 0), change("plays", 1),
             set_("phase", 1), set_("wave", 1), set_("kills", 0), set_("city", 0), set_("boss hits", 0),
             set_("kill total", 0), set_("wave total", 0), set_("all kills", 0), set_("won", 0), set_("drained", 0), set_("a", 0),
             set_("b", 0), set_("clip ok", 1), set_("advance ms", ADVANCE_FIRST_MS),
             shield("toward"), game_show("Strobe burst"), clip("intro", "full"), clip("loop", "loop"),
             award("DESTOROYAH", sub="THE AGGREGATES ARE COMING", seconds=3),
             timer_start("spawn", INTRO_MS), timer_start("lamps", 1)),

    # ---- the swarm ----------------------------------------------------------------------------------------------------
    *[swarm_slot(me, other, timer) for (me, timer), (other, _t) in zip(SLOTS, reversed(SLOTS))],
    on_timer("spawn", *spawn()),
    *[on_shot(s, if_(AND(eq("phase", 1), OR(eq("a", NUM[s]), eq("b", NUM[s]))),
                     [set_("killed", NUM[s]), timer_start("kill", 1)]))
      for s in SHOTS if s != BOSS],
    on_timer("kill", *kill()),
    every(4, set_("clip ok", 1)),                       # a kill's clip every few seconds at most

    # ---- the perfect form at the Building --------------------------------------------------------------------------
    on_shot(BOSS,
            if_(AND(eq("phase", 1), OR(eq("a", NUM[BOSS]), eq("b", NUM[BOSS]))),
                [set_("killed", NUM[BOSS]), timer_start("kill", 1)]),
            if_(eq("phase", 3), [
                change("boss hits", 1), score(BOSS_HIT_VALUE),
                if_(lt("boss hits", BOSS_HITS), [
                    award("DESTOROYAH IS HIT", sub="2 MORE", seconds=2),
                    if_(eq("boss hits", 2), [award("DESTOROYAH IS HIT", sub="1 MORE", seconds=2)]),
                    sound("kill"), timer_start("lamps", 1)],
                    [set_("won", 1), score(var("kill total")),
                     award("SUPER JACKPOT", value=var("kill total"), seconds=3), shake_game("jackpot"), end()])])),
    on_timer("boss", if_(eq("phase", 3), [end()])),
    on_timer("lamps", *lamps()),
    every(1, if_(eq("phase", 3), [timer_start("lamps", 1)])),       # the Building's blink hurries

    # ---- the end ------------------------------------------------------------------------------------------------------
    on_drain(set_("drained", 1)),
    on_end(*[timer_stop(t) for t in TIMERS], set_("phase", 0),
           if_(eq("drained", 0), [if_(eq("won", 1), [sound("won")], [sound("lost", fallback="time_up")])]),
           if_(eq("won", 1), [clip("won", "full"), hud_title("DESTOROYAH DEFEATED")],
               [clip("lost", "full"), hud_title("DESTOROYAH WINS")]),
           # the wave reached and the kills under it (a number can only come last)
           *[if_(eq("wave", w), [hud_line("WAVE %d  -  KILLS" % w, value=var("all kills"))])
             for w in range(1, WAVES + 1)],
           game_show("Ember fade")),
]

PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "game"} for n in ("spins", "plays", "turn")] + [
        {"name": n, "reset": "mode"} for n in ("phase", "wave", "kills", "city", "boss hits", "kill total",
                                                "wave total", "won", "drained", "a", "b", "pos", "ring", "killed",
                                                "kill value", "advance ms", "clip ok", "gauge", "rate", "all kills")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": dict(hud("WAVE 1: CLOSER PAYS MORE  -  TO GO 3",
                    counters=[("WAVE", "OF 3", None), ("KILLS", "OF 3", None), ("CITY", "HITS TO TAKE", None)],
                    gauge={"label": "KILLS", "kind": "segment", "count": 5, "color": GLOW, "value": var("gauge")})),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "kill", "escape", "wave", "boss", "won", "lost"),
    "sounds": sounds({"kill": 3, "escape": 3, "wave": 4, "boss": 4, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 110, "titles": ["godzilla_le"], "based_on": "destoroyah.c",
    "about": ("The C example DESTOROYAH rebuilt in blocks: 30 Top spinner spins start it; three waves of aggregates "
              "advance from the Powerlines to the ramps and loop to the close targets, a kill paying more the closer "
              "it is, then his perfect form takes three Building hits in 25 s."),
    "lost": [
        "No randomness in blocks: each aggregate's next shot is dealt in turn from a counter that runs all game "
        "(the far ring left, center, right, the near ring and the close ring likewise, skipping the shot the other "
        "aggregate stands on), where the C picked one at random. A player who learns the order can wait for it.",
        "Aggregates come to the shield targets at once: the C sent none there until the shield platform had turned "
        "to face the player (or ever, with the shields fixed away).",
        "The perfect form's 25 s are not on the badge (the blocks' badge counts the mode's clock, and this mode has "
        "none): the Building's blink still quickens as they run out.",
        "The counters show bare numbers: WAVE 2 OF 3 and KILLS 1 OF 4 where the C showed 2/3 and 1/4, and the "
        "KILLS counter no longer says what the wave has paid so far (WAVE 2.25M).",
        "The line puts the kills to go last (WAVE 2: CLOSER PAYS MORE  -  TO GO 3) where the C said WAVE 2: 3 "
        "MORE  -  CLOSER PAYS MORE.",
        "The gauge has five pips all along, one colour: the C showed as many pips as the wave needs (3, 4, 5, then "
        "the perfect form's 3), shaded yellow to red.",
        "A kill's award puts its value after the words (FAR KILL X1 1,000,000) where the C put it under them.",
        "A kill's clip plays at most once in each 4 s window of the mode's own (a block's every 4 seconds): the C "
        "waited 4 s from the last one it played.",
        "An aggregate that would advance onto the other's shot takes the next one in turn: the C waited half a "
        "second and tried again.",
        "The ending's line puts the kills last (WAVE 3  -  KILLS 12) where the C said 12 KILLS  -  WAVE 3.",
        "The ending (DESTOROYAH DEFEATED or DESTOROYAH WINS, its line and the total) stays up 3 s, the runtime's: "
        "the C kept it 10 s.",
        "No debounce: the C counted the same target once in 250 ms; the blocks count every report.",
        "A hit no longer answers by itself: the C flashed every kill's inserts white and played the game's "
        "climbing orchestra hit (PAD-415).",
        "Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does "
        "for a drain or a tilt).",
        "The super jackpot's shake is cut short at the end: the C let the game's jackpot shake run out past it.",
        "Its own start, win and end light shows are gone: the C used them only on a game without the game's Strobe "
        "burst and Ember fade, which Godzilla Premium/LE has.",
        "For Godzilla Premium/LE only: the C also ran on Godzilla Pro, with two shield targets.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _shots(names, gap=150):
    out = []
    for n in names:
        out += ["shot", n, "ms", gap]
    return out


_START = ["trigger", "destoroyah.start"]
_FAR, _NEAR, _CLOSE = (_shots(r[4]) for r in RINGS)
#: sweep the far ring every 1.3 s: every aggregate dies as it comes over the top (x1)
_SWEEP = (["secs", 1] + _FAR) * 16
_WAVES = _START + ["secs", 3] + _SWEEP
DESK = [
    ("thirty spins start it", ["shot", SPIN, "ms", 60] * 30 + ["secs", 4],
     ["Hud_Award: SPINS TO DESTOROYAH 28", "Hud_Award: SPINS TO DESTOROYAH 2", "[DESTOROYAH] START (a block)",
      "LAMP POWERLINE LEFT ffc800 blink 700", "SHIELD toward"]),
    ("far near close then the city", _START + ["secs", 27],
     ["LAMP POWERLINE LEFT ffc800 blink 700", "ff5000 blink 400 DESTOROYAH", "LAMP MASER ff0000 blink 120",
      "Hud_Award: THE CITY IS HIT", "Hud_AwardSub: 2 HITS LEFT"]),
    ("three city hits and he wins", _START + ["secs", 60],
     ["Hud_AwardSub: 1 HIT LEFT", "END (a block)", "Hud_Title: DESTOROYAH WINS", "Hud_Line: WAVE 1  -  KILLS 0",
      "lamps held 0"]),
    ("a kill pays more the closer it is", _START + ["secs", 3.5] + _FAR + ["secs", 8] + _NEAR + ["secs", 8] +
     _CLOSE + ["secs", 1],
     ["Hud_Award: FAR KILL X1 1,000,000", "Hud_Award: NEAR KILL X2 2,000,000", "SCORE +4000000", "Hud_Award: WAVE 1 CLEARED 7,000,000"]),
    ("three waves and the perfect form", _WAVES + _shots([BOSS] * 3, 400) + ["secs", 6],
     ["Hud_Award: WAVE 1 CLEARED 3,000,000", "Hud_Line: WAVE 2 IS COMING", "Hud_Award: WAVE 2 CLEARED 5,000,000",
      "SCORE +7500000", "Hud_Title: PERFECT DESTOROYAH", "Hud_C1_Label: HITS",
      "Hud_C2_Label: SUPER JACKPOT", "SCORE +15500000", "SHAKE", "END (a block)", "Hud_Title: DESTOROYAH DEFEATED",
      "Hud_Line: WAVE 3  -  KILLS 12", "lamps held 0"]),
    ("the perfect form's clock runs out", _WAVES + ["secs", 26],
     ["Hud_Award: PERFECT FORM", "LAMP BUILDING ff001e blink 100", "END (a block)", "lamps held 0"]),
    ("a drain ends it", _START + ["secs", 3.5] + _FAR + ["ball_end", "secs", 8],
     ["END (ball ended)", "lamps held 0"]),
]
