"""DESTOROYAH in blocks (PAD-658): the SDK's destoroyah.c rebuilt, then (round 2) taken deeper in three stages.

Godzilla vs. Destoroyah (1995): the micro-oxygen of the Oxygen Destroyer woke something in Tokyo Bay; the crab-like
aggregates swarm into the city, merge, take wing as the flying form, and stand up as Destoroyah's perfect form. After
Lyman Sheats' Horde in The Walking Dead (walkers advance on you, a kill is worth more the closer it is, a cleared wave
pays a super worth the wave), his stages with their own shots (EHoH's House), a pot to cash out or put at risk
(Metallica's Crank It Up) and supers worth your history.

- LIGHT IT: 30 spins of the Top spinner (every spin counts) start it at once; 60 the second time, 90 the third.
- STAGE 1, THE SWARM: aggregates come over the top at the POWERLINES (far, x1) and advance every few seconds to the
  RAMPS, the BUILDING or the BIG LOOP (near, x2), to the MASER, the SHIELDS or the CAPTIVE BALL (close, x4), and then
  into the city. Two at a time at most. A kill pays 1,000,000 (+250,000 a wave) times how close it was. Waves of 3,
  4 and 5 kills; they advance every 7, 6 and 5 s (a second faster each time he comes back). A cleared wave pays the
  WAVE SUPER (every kill of the wave again) and puts it in the POT. Three city hits and Destoroyah wins.
- STAGE 2, FLYING FORM: he takes wing (his own battle music): he flies over the Left ramp, the Big loop and the Right
  ramp in turn (chasing violet), moving on every 3 s (2.5, 2 the more he has been fought) and when hit. Four hits in
  30 s bring him down: 5M, 10M, 15M, 20M into the pot.
- STAGE 3, PERFECT FORM: 25 s at the BUILDING: three hits of 5,000,000, the third the SUPER JACKPOT: every kill of the
  mode again and the pot twice over.
- CASH OUT at the right scoop once the swarm is beaten (it chases white): the pot, and he withdraws. The flying or
  the perfect form's clock, three city hits or a drain pay a quarter of the pot.

Built to be taken apart: RINGS says each ring's shots, multiplier and light, and every aggregate is a variable
holding the NUMBER of the shot it stands on (1-12 down the playfield, 0 = none), so a ring's shots are a range of
numbers. The C picked each next shot at random; here pick() deals them out in turn from a counter ("turn") that keeps
running all game, skipping the shot the other aggregate stands on.
"""
from blk import (AND, OR, a_show, add, award, beds, change, clip, clips, div, end, eq, every, game_show, ge, gt, hud,
                 hud_counter, hud_line, hud_title, if_, light, light_insert, lt, mul, music, off, off_insert, on_end,
                 on_shot, on_start, on_timer, score, set_, shake, shake_game, shield, show, sound, sounds, start, step,
                 sub, timer_left, timer_start, timer_stop, var)
import pack

SLUG, NAME = "destoroyah", "DESTOROYAH"
RED, DARK, GLOW, VIOLET, WHITE, ICE = "#ff001e", "#28000a", "#ff7800", "#b428ff", "#ffffff", "#78c8ff"
SPIN, BOSS = "Top spinner", "Building"
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
SKY = ("Left ramp", "Big loop", "Right ramp")                 # where the flying form flies, in turn
WAVES, FIRST_NEED = 3, 3                                      # kills in wave 1; one more a wave
KILL_VALUE, KILL_WAVE_STEP = 1000000, 250000
SPAWN_AFTER_MS, WAVE_GAP_MS, INTRO_MS = 1200, 2500, 2500
CITY_HITS, BOSS_HITS, BOSS_HIT_VALUE, WING_HITS = 3, 3, 5000000, 4
FLY_CLOCK_MS, BOSS_MS = 30000, 25000
CITY = 99                                                     # "killed" for an aggregate that reached the city
BUILDING = dict(x=123, y=202)                                 # the port's lamp places on the playfield picture
SKY_XY = dict(x=150, y=240)
TIMERS = ("step a", "step b", "spawn", "kill", "boss", "lamps", "next", "fly")
NEED = add(FIRST_NEED - 1, var("wave"))                       # this wave's kills
LEFT = sub(NEED, var("kills"))
SPINS_NEED = pack.need(30, "plays")                           # 30 spins, then 60, then 90
#: he flies on every 3 s, half a second faster each time he has come back (2 s at the fastest)
FLY_MS = sub(3500, mul(500, var("plays")))
SUPER = add(var("kill total"), mul(var("pot"), 2))

SHOWS = [
    a_show("Swarm",                                                                      # they crawl out of the bay
           step("fade_in", 700, GLOW, "#000000", "flippers", gi="dark"),
           step("sweep_down", 900, GLOW, DARK, "top", gi="dark"),
           step("sparkle", 900, RED, DARK, "center", gi="dark"),
           step("fade", 400, GLOW, "#000000", "center", blend=150)),
    a_show("Kill",
           step("burst", 450, ICE, GLOW, "center", gi="keep"),
           step("fade", 250, GLOW, "#000000", "center")),
    a_show("Wave",                                                                       # the swarm merges
           step("implode", 800, GLOW, DARK, "center", gi="flash"),
           step("fade", 400, GLOW, "#000000", "center")),
    a_show("City", step("strobe", 400, RED, "#000000", "center", rate=60, gi="flash")),
    a_show("Takes wing",                                                                 # the flying form rises
           step("sweep_up", 700, VIOLET, "#000000", "flippers", gi="dark"),
           step("bounce", 1200, VIOLET, DARK, "xy", rate=350, gi="dark", **SKY_XY),
           step("spiral_out", 900, RED, VIOLET, "xy", gi="dark", **SKY_XY),
           step("fade", 400, VIOLET, "#000000", "center", blend=200)),
    a_show("Wing hit",
           step("ripple", 600, WHITE, VIOLET, "xy", rate=200, gi="flash", **SKY_XY),
           step("sweep_rl", 400, VIOLET, "#000000", "top", gi="dark"),
           step("fade", 250, VIOLET, "#000000", "center")),
    a_show("Perfect form",
           step("bolts", 900, RED, DARK, "center", rate=130, gi="dark"),
           step("burst", 800, GLOW, RED, "xy", gi="dark", **BUILDING),                  # he stands up
           step("spin", 900, RED, DARK, "xy", rate=90, **BUILDING)),
    a_show("Super jackpot",
           step("strobe", 500, WHITE, RED, "center", rate=45, gi="flash"),
           step("fire", 1300, GLOW, RED, "top", gi="dark"),
           step("rainbow", 1800, "#000000", "#000000", "center", rate=50),
           step("fade", 700, GLOW, "#000000", "center", blend=300)),
    a_show("Withdraws",                                                                  # the cash-out
           step("solid", 500, ICE, "#000000", "center", gi="dark"),
           step("spiral_in", 1200, ICE, "#001020", "xy", gi="dark", **BUILDING),
           step("fade", 900, ICE, "#000000", "center", blend=400)),
    a_show("He wins",
           step("pulse", 900, RED, DARK, "center", rate=450, gi="dark"),
           step("sweep_lr", 700, RED, "#000000", "center", gi="dark"),
           step("fade", 800, RED, "#000000", "center", blend=300)),
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
        if_(ge(me, FIRST[-1]), [set_(me, 0), set_("killed", CITY), timer_start("kill", 1)],
            [*ring_of(var(me)),
             *[if_(eq("ring", i + 1), pick(i + 1, other)) for i in range(len(RINGS) - 1)],
             set_(me, var("pos")), timer_start(timer, var("advance ms"))]),
        timer_start("lamps", 1)]))


def city():
    """An aggregate past the close shots hits the city (the "kill" timer with "killed" set to CITY)."""
    return [
        change("city", 1),
        award("THE CITY IS HIT", value=sub(CITY_HITS, var("city")), sub="HITS LEFT", seconds=2),
        show("City"), sound("escape"), clip("escape", "behind"), shake(400, "strong"),
        if_(ge("city", CITY_HITS), [end()], [timer_start("spawn", SPAWN_AFTER_MS)])]


def lamps():
    """Each aggregate's shot in its ring's light; the flying form's shot chasing violet; the perfect form: the
    Building red, faster as its 25 s run out. The swarm's line and counters follow."""
    out = []
    for r in RINGS:
        for s in r[4]:
            k = NUM[s]
            here = AND(eq("phase", 1), OR(eq("a", k), eq("b", k)))
            lit = [light(s, r[2], "blink", r[3])]
            if s == BOSS:
                out.append(if_(eq("phase", 4), [light(s, RED, "blink", add(80, div(timer_left("boss"), 40)))],
                               [if_(here, lit, [off(s)])]))
            elif s in SKY:
                out.append(if_(here, lit, [if_(AND(eq("phase", 3), eq("pos", SKY.index(s) + 1)),
                                               [light(s, VIOLET, "chase", 60)], [off(s)])]))
            else:
                out.append(if_(here, lit, [off(s)]))
    return [
        *out,
        if_(lt("phase", 3), [
            hud_counter(3, sub(CITY_HITS, var("city")), "HITS TO TAKE"),
            hud_counter(1, var("wave"), "OF 3"),
            if_(eq("phase", 2), [hud_line("THE NEXT WAVE IS COMING")],
                [hud_line("CLOSER PAYS MORE  -  KILLS TO GO", value=LEFT)]),
        ]),
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
        change("kills", 1), change("all kills", 1), sound("kill"), show("Kill"),
        if_(eq("clip ok", 1), [clip("kill", "behind"), set_("clip ok", 0)]),
        if_(ge("kills", NEED), wave_cleared(), [shake(200, "soft"), timer_start("spawn", SPAWN_AFTER_MS)])])]


def wave_cleared():
    """The WAVE SUPER (every kill of the wave again) into the pot; then the next wave after a gap, or (after the
    third) the flying form 0.7 s later."""
    return [
        score(var("wave total")), change("pot", var("wave total")),
        award("WAVE CLEARED", value=var("wave total"), sub="INTO THE POT", seconds=3),
        show("Wave"), sound("wave"), clip("wave", "behind"),
        set_("a", 0), set_("b", 0), timer_stop("step a"), timer_stop("step b"), set_("phase", 2),
        if_(ge("wave", WAVES), [timer_stop("spawn"), timer_start("next", 700)],
            [shake(500, "medium"), change("wave", 1), timer_start("spawn", WAVE_GAP_MS)]),
    ]


def spawn():
    """A wave begins after its gap; then, every so often, an aggregate comes over the top into an empty slot while
    the wave still needs more kills than there are aggregates."""
    return [
        if_(eq("phase", 2), [set_("phase", 1), set_("kills", 0), set_("wave total", 0),
                             set_("advance ms", sub(9000, mul(1000, add(var("wave"), var("plays"))))),
                             if_(lt("advance ms", 2000), [set_("advance ms", 2000)])]),
        if_(eq("phase", 1), [
            if_(AND(eq("a", 0), OR(eq("b", 0), ge(LEFT, 2))),
                pick(0, "b") + [set_("a", var("pos")), timer_start("step a", var("advance ms"))],
                [if_(AND(eq("b", 0), ge(LEFT, 2)),
                     pick(0, "a") + [set_("b", var("pos")), timer_start("step b", var("advance ms"))])]),
            timer_start("spawn", SPAWN_AFTER_MS)]),
        timer_start("lamps", 1),
    ]


def next_stage():
    """A stage done: the flying form after the swarm, the perfect form after the flying form."""
    return [
        if_(eq("phase", 3), [
            set_("phase", 4), set_("hits", 0), timer_stop("fly"), timer_start("boss", BOSS_MS),
            hud_title("PERFECT DESTOROYAH"), hud_line("PERFECT FORM: THE BUILDING, 3 HITS"),
            hud_counter(1, 3, "PERFECT FORM", "STAGE"),
            award("PERFECT FORM", sub="THE BUILDING: THREE HITS", seconds=3),
            light_insert("BUILDING SPOT", RED, "blink", 100),
            show("Perfect form"), sound("boss"), clip("boss", "full"), shake_game("rumble")],
            [set_("phase", 3), set_("hits", 0), set_("pos", 1), timer_start("fly", FLY_MS),
             timer_start("boss", FLY_CLOCK_MS), music("fly"),
             hud_title("FLYING DESTOROYAH"), hud_line("FLYING FORM: HIT HIM WHERE HE FLIES"),
             hud_counter(1, 2, "FLYING FORM", "STAGE"), hud_counter(3, 30, "TO DOWN HIM", "SECONDS"),
             award("HE TAKES WING", sub="HIT HIM WHERE HE FLIES", seconds=3),
             *pack.cash_out_lit(),
             show("Takes wing"), sound("fly"), clip("fly", "behind"), shake_game("jackpot")]),
        timer_start("lamps", 1),
    ]


SCRIPTS = [
    # ---- light it: every spin of the Top spinner -----------------------------------------------------------------
    on_shot(SPIN,
            if_(lt("spins", SPINS_NEED), [change("spins", 1)]),
            if_(ge("spins", SPINS_NEED), [start()],
                [if_(eq(mod(var("spins"), 2), 0),
                     [award("SPINS TO DESTOROYAH", value=sub(SPINS_NEED, var("spins")), sub="THE OXYGEN SPREADS")])]),
            when="idle"),

    # ---- the aggregates are coming --------------------------------------------------------------------------------
    on_start(*pack.begin(SLUG),
             set_("spins", 0), change("plays", 1),
             set_("phase", 2), set_("wave", 1), set_("kills", 0), set_("city", 0), set_("hits", 0), set_("pot", 0),
             set_("kill total", 0), set_("wave total", 0), set_("all kills", 0), set_("won", 0), set_("cashed", 0),
             set_("a", 0), set_("b", 0), set_("clip ok", 1),
             shield("toward"), game_show("Strobe burst"), clip("intro", "full"), clip("loop", "loop"),
             show("Swarm"), shake(800, "strong"),
             award("DESTOROYAH", sub="THE AGGREGATES ARE COMING", seconds=3),
             hud_counter(2, 0, "CASH AT SCOOP"),
             timer_start("spawn", INTRO_MS), timer_start("lamps", 1)),

    # ---- stage 1: the swarm -----------------------------------------------------------------------------------------
    *[swarm_slot(me, other, timer) for (me, timer), (other, _t) in zip(SLOTS, reversed(SLOTS))],
    on_timer("spawn", *spawn()),
    *[on_shot(s, if_(AND(eq("phase", 1), OR(eq("a", NUM[s]), eq("b", NUM[s]))),
                     [set_("killed", NUM[s]), timer_start("kill", 1)]),
              if_(AND(eq("phase", 3), eq("pos", SKY.index(s) + 1)), [set_("killed", 0), timer_start("kill", 1)]))
      for s in SKY],
    *[on_shot(s, if_(AND(eq("phase", 1), OR(eq("a", NUM[s]), eq("b", NUM[s]))),
                     [set_("killed", NUM[s]), timer_start("kill", 1)]))
      for s in SHOTS if s != BOSS and s not in SKY],
    on_timer("kill",
             if_(AND(eq("phase", 1), eq("killed", CITY)), city()),
             if_(AND(eq("phase", 1), lt("killed", CITY)), kill()),
             # ---- stage 2: a hit on the flying form (killed 0) ----
             if_(AND(eq("phase", 3), eq("killed", 0), lt("hits", WING_HITS)), [
                 change("hits", 1), change("pos", 1), if_(gt("pos", 3), [set_("pos", 1)]),
                 timer_start("fly", FLY_MS), score(1000000),
                 change("pot", mul(5000000, var("hits"))), clip("wing", "behind"), sound("fly"), show("Wing hit"),
                 if_(ge("hits", WING_HITS), [
                     timer_stop("fly"), timer_stop("boss"), shake(600, "hard"),
                     award("SHOT DOWN", value=var("pot"), sub="POT", seconds=3), timer_start("next", 700)],
                     [shake(350, "medium"),
                      award("WING HIT", value=mul(5000000, var("hits")), sub="INTO THE POT")])]),
             timer_start("lamps", 1)),
    on_timer("fly", if_(eq("phase", 3), [change("pos", 1), if_(gt("pos", 3), [set_("pos", 1)]),
                                         timer_start("fly", FLY_MS), timer_start("lamps", 1)])),
    every(4, set_("clip ok", 1)),                       # a kill's clip every few seconds at most

    # ---- stage 3: the perfect form at the Building --------------------------------------------------------------------
    on_shot(BOSS,
            if_(AND(eq("phase", 1), OR(eq("a", NUM[BOSS]), eq("b", NUM[BOSS]))),
                [set_("killed", NUM[BOSS]), timer_start("kill", 1)]),
            if_(AND(eq("phase", 4), eq("won", 0)), [
                change("hits", 1), score(BOSS_HIT_VALUE), timer_start("lamps", 1),
                if_(lt("hits", BOSS_HITS), [
                    award("DESTOROYAH IS HIT", value=sub(BOSS_HITS, var("hits")), sub="MORE"),
                    sound("kill"), clip("wing", "behind"), shake(350, "hard")],
                    [set_("won", 1), timer_stop("boss"), score(SUPER),
                     award("SUPER JACKPOT", value=SUPER, sub="KILLS AND THE POT X2", seconds=4),
                     clip("won", "full"), sound("won"), show("Super jackpot"), shake_game("jackpot"),
                     timer_start("next", 1500)])])),
    on_timer("boss", if_(AND(ge("phase", 3), eq("won", 0), eq("cashed", 0)), [end()])),
    every(1, if_(ge("phase", 3), [hud_counter(3, div(add(timer_left("boss"), 999), 1000), "TO STOP HIM"),
                                  timer_start("lamps", 1)])),
    on_timer("lamps", *lamps()),

    # ---- a stage done: on to the next, or cash out --------------------------------------------------------------
    on_timer("next", if_(OR(eq("cashed", 1), eq("won", 1)), [end()], next_stage())),
    on_shot(pack.CASH_SHOT,
            if_(AND(ge("phase", 3), eq("won", 0), eq("cashed", 0)), [
                set_("cashed", 1), timer_stop("boss"), timer_stop("fly"), score(var("pot")),
                award("CASHED OUT", value=var("pot"), sub="DESTOROYAH WITHDRAWS", seconds=4),
                clip("cashout", "full"), sound("cashout"), show("Withdraws"), shake(600, "medium"),
                timer_start("next", 1500)])),

    # ---- the end ------------------------------------------------------------------------------------------------------
    on_end(*pack.finish(), *[timer_stop(t) for t in TIMERS], set_("phase", 0),
           if_(eq("won", 1), [hud_title("DESTOROYAH DEFEATED"), hud_line("KILLS", value=var("all kills"))]),
           if_(eq("cashed", 1), [hud_title("DESTOROYAH WITHDRAWS"), hud_line("THE POT IS CASHED OUT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               hud_title("DESTOROYAH WINS"), hud_line("A QUARTER OF THE POT"), score(div(var("pot"), 4)),
               sound("lost", fallback="time_up"), clip("lost", "full"), show("He wins")]),
           game_show("Ember fade")),
]

PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": pack.pack_vars() + [{"name": n, "reset": "game"} for n in ("spins", "plays", "turn")] + [
        {"name": n, "reset": "mode"} for n in ("phase", "wave", "kills", "city", "hits", "kill total", "wave total",
                                                "won", "cashed", "a", "b", "pos", "ring", "killed", "kill value",
                                                "advance ms", "clip ok", "all kills", "pot")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": dict(hud("THE NEXT WAVE IS COMING",
                    counters=[("WAVE", "OF 3", None), ("POT", "CASH AT SCOOP", var("pot")),
                              ("CITY", "HITS TO TAKE", None)])),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "kill", "escape", "wave", "fly", "wing", "boss", "won", "lost", "cashout"),
    "sounds": sounds({"kill": 3, "escape": 3, "wave": 4, "fly": 3, "boss": 4, "won": 4, "lost": 4, "cashout": 4}),
    "music": "music.wav",
    "beds": beds("fly"),
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 110, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "destoroyah.c",
    #: the Pro (two fixed shields): the close ring's middle shield is the Mecha lane (Mecha exit bottom), as close
    #: to the flippers, so the close ring keeps five shots
    "title_alt": {"godzilla_pro": {"shots": {"Shield target center": "Mecha exit bottom"}}},
    "about": ("The C example DESTOROYAH rebuilt in blocks and taken deeper (PAD-658): 30 Top spinner spins start it "
              "(60 the second time, 90 the third). Three stages: THE SWARM (three waves of aggregates advance from "
              "the Powerlines to the ramps and loop to the close targets, a kill paying more the closer it is, each "
              "cleared wave into the pot), his FLYING FORM (four hits where he flies over the ramps and the Big loop "
              "in 30 s), then his PERFECT FORM (three Building hits in 25 s, the super jackpot every kill and the pot "
              "twice over). Cash the pot out at the right scoop once the swarm is beaten."),
    "lost": [
        "No randomness in blocks: each aggregate's next shot is dealt in turn from a counter that runs all game "
        "(the far ring left, center, right, the near ring and the close ring likewise, skipping the shot the other "
        "aggregate stands on), where the C picked one at random; the flying form flies over the Left ramp, the Big "
        "loop and the Right ramp in that order. A player who learns the order can wait for it.",
        "Aggregates come to the shield targets at once: the C sent none there until the shield platform had turned "
        "to face the player (or ever, with the shields fixed away).",
        "The flying and perfect forms' seconds are a counter (SECONDS, TO STOP HIM), not the badge (the blocks' "
        "badge counts the mode's clock, and this mode has none): the Building's blink still quickens as they run "
        "out.",
        "The counters show bare numbers: STAGE 1 over WAVE 2 OF 3 where the C showed the wave as 2/3 and the "
        "kills as 1/4 (the kills to go are on the line), and no counter says what the wave has paid so far.",
        "The line puts the kills to go last (WAVE 2: CLOSER PAYS MORE  -  TO GO 3) where the C said WAVE 2: 3 "
        "MORE  -  CLOSER PAYS MORE.",
        "No KILLS gauge: on the glass its pips sat over the game's own POWER widget at the right edge (the C showed "
        "as many pips as the wave needs, shaded yellow to red); the kills to go are on the line.",
        "A kill's clip plays at most once in each 4 s window of the mode's own (a block's every 4 seconds): the C "
        "waited 4 s from the last one it played.",
        "An aggregate that would advance onto the other's shot takes the next one in turn: the C waited half a "
        "second and tried again.",
        "The ending (DESTOROYAH DEFEATED, DESTOROYAH WITHDRAWS or DESTOROYAH WINS, its line and the total) stays "
        "up 3 s, the runtime's: the C kept it 10 s, with the kills and the wave in its line.",
        "No debounce: the C counted the same target once in 250 ms; the blocks count every report.",
        "A hit no longer answers by itself: the C flashed every kill's inserts white and played the game's "
        "climbing orchestra hit (PAD-415).",
        "Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does "
        "for a drain or a tilt).",
        "On Godzilla Pro the close ring's middle shield is the Mecha lane (the Pro has two fixed shields): the C "
        "dealt aggregates to the Pro's two shields only.",
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
_WAVES = _START + ["secs", 3] + _SWEEP + ["secs", 1]
#: the flying form starts over the Left ramp and moves on with every hit
_FLY = _shots(["Left ramp", "Big loop", "Right ramp"] * 2, 300) + ["secs", 2]
DESK = [
    ("thirty spins the first time, sixty the second",
     ["shot", SPIN, "ms", 60] * 30 + ["secs", 4, "trigger", "destoroyah.stop", "secs", 4] +
     ["shot", SPIN, "ms", 60] * 58 + ["secs", 3] + ["shot", SPIN, "ms", 60] * 2 + ["secs", 4],
     ["Hud_Line: 28  -  THE OXYGEN SPREADS", "[DESTOROYAH] START (a block)", "Hud_Line: 58  -  THE OXYGEN SPREADS",
      "Hud_Line: 2  -  THE OXYGEN SPREADS", "LAMP POWERLINE LEFT ffc800 blink 700", "SHIELD toward"]),
    ("far near close then the city", _START + ["secs", 27],
     ["LAMP POWERLINE LEFT ffc800 blink 700", "ff5000 blink 400 DESTOROYAH", "LAMP MASER ff0000 blink 120",
      "Hud_Award: THE CITY IS HIT", "Hud_AwardSub: 2  -  HITS LEFT"]),
    ("three city hits and he wins", _START + ["secs", 60],
     ["Hud_AwardSub: 1  -  HITS LEFT", "END (a block)", "Hud_Title: DESTOROYAH WINS", "lamps held 0"]),
    ("a kill pays more the closer it is", _START + ["secs", 3.5] + _FAR + ["secs", 8] + _NEAR + ["secs", 8] +
     _CLOSE + ["secs", 1],
     ["Hud_Award: FAR KILL X1", "Hud_AwardSub: 1,000,000", "Hud_Award: NEAR KILL X2", "Hud_AwardSub: 2,000,000",
      "SCORE +4000000", "Hud_Award: WAVE CLEARED", "Hud_AwardSub: 7,000,000  -  INTO THE POT"]),
    ("the swarm, the flying form and the perfect form", _WAVES + _FLY + ["secs", 2] + _shots([BOSS] * 3, 400) + ["secs", 6],
     ["Hud_AwardSub: 3,000,000  -  INTO THE POT", "Hud_Line: THE NEXT WAVE IS COMING", "Hud_C1_Value: 3",
      "Hud_Title: FLYING DESTOROYAH", "Hud_Award: HE TAKES WING", "LAMP SELECT CITY ffffff chase",
      "Hud_Award: WING HIT", "Hud_AwardSub: 15,000,000  -  INTO THE POT", "Hud_Award: SHOT DOWN",
      "Hud_AwardSub: 65,500,000  -  POT", "Hud_Title: PERFECT DESTOROYAH", "Hud_Award: SUPER JACKPOT",
      "SCORE +146500000", "END (a block)", "Hud_Title: DESTOROYAH DEFEATED", "Hud_Line: KILLS 12", "lamps held 0"]),
    ("cash out after the swarm", _WAVES + ["secs", 1, "shot", "Right scoop", "secs", 5],
     ["Hud_Award: CASHED OUT", "Hud_AwardSub: 15,500,000  -  DESTOROYAH WITHDRAWS", "SCORE +15500000",
      "Hud_Title: DESTOROYAH WITHDRAWS", "lamps held 0"]),
    ("the flying form gets away", _WAVES + ["secs", 32],
     ["Hud_Title: FLYING DESTOROYAH", "Hud_C3_Label: SECONDS", "END (a block)", "Hud_Title: DESTOROYAH WINS",
      "SCORE +3875000", "lamps held 0"]),
    ("the perfect form's clock runs out", _WAVES + _FLY + ["secs", 26],
     ["Hud_Award: PERFECT FORM", "LAMP BUILDING ff001e blink", "END (a block)", "lamps held 0"]),
    ("a drain ends it", _START + ["secs", 3.5] + _FAR + ["ball_end", "secs", 8],
     ["END (ball ended)", "lamps held 0"]),
]
#: the same mode as a Pro gets it (title_alt): the Mecha lane is a close shot
DESK_PRO = [
    ("the Pro: spins, the swarm, the flying form and the perfect form",
     ["shot", SPIN, "ms", 60] * 30 + ["secs", 3] + _SWEEP + ["secs", 1] + _FLY + ["secs", 2] +
     _shots([BOSS] * 3, 400) + ["secs", 6],
     ["[DESTOROYAH] START (a block)", "Hud_Award: WAVE CLEARED", "Hud_Title: FLYING DESTOROYAH",
      "Hud_Award: SHOT DOWN", "Hud_Award: SUPER JACKPOT", "Hud_Title: DESTOROYAH DEFEATED", "lamps held 0"]),
    ("the Pro's close ring takes the Mecha lane", _START + (["shot", "Mecha exit bottom", "secs", 1] * 2 + ["shot", "Powerline left", "secs", 1]) * 30,
     ["Hud_Award: CLOSE KILL X4", "Hud_AwardSub: 4,000,000"]),
]
