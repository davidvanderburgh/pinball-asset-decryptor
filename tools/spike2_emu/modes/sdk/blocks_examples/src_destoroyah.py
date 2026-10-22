"""DESTOROYAH in blocks (PAD-658): the SDK's destoroyah.c rebuilt, then (round 2) taken deeper in three stages.

Godzilla vs. Destoroyah (1995): the micro-oxygen of the Oxygen Destroyer woke something in Tokyo Bay; the crab-like
aggregates swarm into the city, merge, take wing as the flying form, and stand up as Destoroyah's perfect form. After
Lyman Sheats' Horde in The Walking Dead (walkers advance on you, a kill is worth more the closer it is, a cleared wave
pays a super worth the wave), his stages with their own shots (EHoH's House), a pot to cash out or put at risk
(Metallica's Crank It Up) and supers worth your history.

- LIGHT IT: 50 spins of the Top spinner (none in a multiball, PAD-669) start it at once; 100 the second time, 150 the third. A note
  every 5 spins says how many are left (SPIN THE TOP SPINNER / 20 - SPINS TO DESTOROYAH).
- STAGE 1, THE SWARM: aggregates come over the top at the POWERLINES (far, x1) and advance every 10 s to the RAMPS,
  the BUILDING or the BIG LOOP (near, x2), to the MASER, the SHIELDS or the CAPTIVE BALL (close, x4), and then into
  the city. Two at a time at most. A kill pays 1,000,000 (+250,000 a wave) times how close it was. Waves of 3, 4 and
  5 kills. A cleared wave pays the WAVE SUPER (every kill of the wave again) and puts it in the POT. Three city hits
  and Destoroyah wins.
- STAGE 2, FLYING FORM: he takes wing (his own battle music): he flies over the Left ramp, the Big loop and the Right
  ramp in turn (chasing violet), moving on every 10 s and when hit. Four hits in 40 s bring him down: 5M, 10M, 15M,
  20M into the pot.
- STAGE 3, PERFECT FORM: 40 s at the BUILDING: three hits of 5,000,000, the third the SUPER JACKPOT: every kill of the
  mode again and the pot twice over.
- CASH OUT at the right scoop once the swarm is beaten (it chases white): the pot, and he withdraws. The flying or
  the perfect form's clock, three city hits or a drain pay a quarter of the pot.

SAY THE SHOT (PAD-658 round 3, David: "the shots are not explicit enough... some of the information only flashes on
the screen very briefly"; "you can't really accomplish much in 10 seconds. 40 seconds is better"):
- the swarm: the TITLE names the first aggregate's shot (SHOOT THE MASER TARGET) and the LINE the second's (OR THE
  LEFT POWERLINE); with one on the playfield the line says THE CLOSER IT IS, THE MORE IT PAYS. Each one blinks in
  its ring's colour, the close ring fastest; a killed one goes off at once. The WAVE counter says the kills to go
  (WAVE 2 / 3 / KILLS TO GO); a new wave is announced (HERE THEY COME / 4 - KILLS IN THIS WAVE);
- the flying form: the line follows him (SHOOT THE BIG LOOP), HITS 1 OF 4, and a hit's note names where he flew;
- the perfect form: SHOOT THE BUILDING 3 TIMES, then SHOOT THE BUILDING AGAIN, then SUPER JACKPOT: SHOOT THE
  BUILDING, HITS 2 OF 3;
- every note stays 3 s at least (pack.NOTE_S), and a stage change waits out the note before it;
- the clocks: an aggregate stands 10 s at each shot (was 7, 6, 5 s, faster each time), the flying form moves on
  every 10 s (was 3, 2.5, 2 s), the flying and perfect forms' clocks are pack.STAGE_S (were 30 and 25 s), and a
  wing or Building hit keeps at least pack.CLOCK_FLOOR seconds on them.

Built to be taken apart: RINGS says each ring's shots, multiplier and light, and every aggregate is a variable
holding the NUMBER of the shot it stands on (1-12 down the playfield, 0 = none), so a ring's shots are a range of
numbers. The C picked each next shot at random; here pick() deals them out in turn from a counter ("turn") that keeps
running all game, skipping the shot the other aggregate stands on. Aggregate "a" is always the first on the
playfield: when it goes and "b" is still there, "b" moves into "a" (with its step timer), so the title follows the
one that came first.
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
NOTE_MS = pack.NOTE_S * 1000                                  # a note's time on the glass: a stage change waits it out
SPAWN_AFTER_MS, WAVE_GAP_MS, INTRO_MS = 1200, NOTE_MS + 500, NOTE_MS
CITY_HITS, BOSS_HITS, BOSS_HIT_VALUE, WING_HITS = 3, 3, 5000000, 4
#: PAD-658 round 3: a moving target stays 10 s at least before it moves on its own (an aggregate at its shot, the
#: flying form over a ramp or the loop); the flying and the perfect forms' clocks are a stage's
MOVE_MS = 10000
STAGE_MS = pack.STAGE_S * 1000
FLOOR_MS = pack.CLOCK_FLOOR * 1000
CITY = 99                                                     # "killed" for an aggregate that reached the city
BUILDING = dict(x=123, y=202)                                 # the port's lamp places on the playfield picture
SKY_XY = dict(x=150, y=240)
TIMERS = ("step a", "step b", "spawn", "kill", "boss", "lamps", "next", "fly")
NEED = add(FIRST_NEED - 1, var("wave"))                       # this wave's kills
LEFT = sub(NEED, var("kills"))
SPINS_NEED = pack.need(50, "plays")                           # 50 spins, then 100, then 150 (PAD-675: was 30)
SPIN_NOTE_EVERY = 5                                           # the qualifying note: every 5 spins
SUPER = add(var("kill total"), mul(var("pot"), 2))
CLOSER = "THE CLOSER IT IS, THE MORE IT PAYS"
W = pack.SHOT_WORDS

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


def floor_clock():
    """pack.clock_floor() for this mode's stage clock: the mode has no clock of its own (three city hits end the
    swarm), so the flying and perfect forms' clock is the "boss" timer; a good shot keeps CLOCK_FLOOR s on it."""
    return if_(lt(timer_left("boss"), FLOOR_MS), [timer_start("boss", FLOOR_MS)])


def swarm_slot(me, other, timer):
    """An aggregate's step: on to the next ring, or (from the last) into the city."""
    return on_timer(timer, if_(AND(eq("phase", 1), gt(me, 0)), [
        if_(ge(me, FIRST[-1]), [set_(me, 0), set_("killed", CITY), timer_start("kill", 1)],
            [*ring_of(var(me)),
             *[if_(eq("ring", i + 1), pick(i + 1, other)) for i in range(len(RINGS) - 1)],
             set_(me, var("pos")), timer_start(timer, MOVE_MS)]),
        timer_start("lamps", 1)]))


def city():
    """An aggregate past the close shots hits the city (the "kill" timer with "killed" set to CITY)."""
    return [
        change("city", 1),
        award("THE CITY IS HIT", value=sub(CITY_HITS, var("city")), sub="HITS LEFT", seconds=pack.NOTE_S),
        show("City"), sound("escape"), clip("escape", "behind"), shake(400, "strong"),
        if_(ge("city", CITY_HITS), [end()], [timer_start("spawn", SPAWN_AFTER_MS)])]


def promote():
    """"a" is the first on the playfield: when it is gone and "b" is not, "b" (and its step timer) moves into it, so
    the title names the one nearest the city (both advance at the same pace)."""
    return if_(AND(eq("a", 0), gt("b", 0)), [set_("a", var("b")), set_("b", 0),
                                            timer_start("step a", add(timer_left("step b"), 1)), timer_stop("step b")])


def swarm_words():
    """The swarm's title and line: the first aggregate's shot in the title, the second's in the line."""
    first = [if_(eq("a", NUM[s]), [hud_title("SHOOT THE %s" % W[s])]) for s in SHOTS]
    second = [if_(eq("b", NUM[s]), [hud_line("OR THE %s" % W[s])]) for s in SHOTS]
    return [
        if_(eq("phase", 1), [
            hud_counter(1, LEFT),
            if_(gt("a", 0), first, [hud_title(NAME)]),
            if_(gt("b", 0), second, [if_(gt("a", 0), [hud_line(CLOSER)], [hud_line("THE NEXT ONE IS COMING")])])]),
        if_(eq("phase", 2), [
            if_(ge("kills", NEED), [hud_title("THE SWARM IS BEATEN"), hud_line("NOW HE TAKES WING")],
                [hud_title(NAME), hud_line("THE NEXT WAVE IS COMING")])]),
    ]


def lamps():
    """Each aggregate's shot in its ring's light; the flying form's shot chasing violet; the perfect form: the
    Building red, faster as its clock runs out. The title, line and counters follow."""
    out = []
    for r in RINGS:
        for s in r[4]:
            k = NUM[s]
            here = AND(eq("phase", 1), OR(eq("a", k), eq("b", k)))
            lit = [light(s, r[2], "blink", r[3])]
            if s == BOSS:
                out.append(if_(AND(eq("phase", 4), eq("won", 0), eq("cashed", 0)),
                               [light(s, RED, "blink", add(80, div(timer_left("boss"), 60)))],
                               [if_(here, lit, [off(s)])]))
            elif s in SKY:
                out.append(if_(here, lit, [if_(AND(eq("phase", 3), eq("pos", SKY.index(s) + 1)),
                                               [light(s, VIOLET, "chase", 60)], [off(s)])]))
            else:
                out.append(if_(here, lit, [off(s)]))
    return [
        promote(),
        *out,
        if_(lt("phase", 3), [hud_counter(3, sub(CITY_HITS, var("city")), "HITS TO TAKE"), *swarm_words()]),
        if_(eq("phase", 3), pack.line_follows("pos", SKY)),
    ]


def kill():
    """The aggregate on shot "killed" is blown apart: the kill value times its ring's multiplier."""
    return [if_(OR(eq("a", var("killed")), eq("b", var("killed"))), [
        if_(eq("a", var("killed")), [set_("a", 0), timer_stop("step a")], [set_("b", 0), timer_stop("step b")]),
        *ring_of(var("killed")),
        set_("kill value", add(KILL_VALUE, mul(KILL_WAVE_STEP, sub(var("wave"), 1)))),
        *[if_(eq("ring", i + 1), [set_("kill value", mul(var("kill value"), r[1])),
                                  award("%s KILL X%d" % (r[0], r[1]), value=var("kill value"), seconds=pack.NOTE_S)])
          for i, r in enumerate(RINGS)],
        score(var("kill value")), change("wave total", var("kill value")), change("kill total", var("kill value")),
        change("kills", 1), change("all kills", 1), sound("kill"), show("Kill"),
        if_(eq("clip ok", 1), [clip("kill", "behind"), set_("clip ok", 0)]),
        if_(ge("kills", NEED), wave_cleared(), [shake(200, "soft"), timer_start("spawn", SPAWN_AFTER_MS)])])]


def wave_cleared():
    """The WAVE SUPER (every kill of the wave again) into the pot; then the next wave after a gap, or (after the
    third) the flying form once the note has had its time."""
    return [
        score(var("wave total")), change("pot", var("wave total")),
        award("WAVE CLEARED", value=var("wave total"), sub="INTO THE POT", seconds=pack.NOTE_S),
        hud_counter(1, 0), show("Wave"), sound("wave"), clip("wave", "behind"),
        set_("a", 0), set_("b", 0), timer_stop("step a"), timer_stop("step b"), set_("phase", 2),
        if_(ge("wave", WAVES), [timer_stop("spawn"), timer_start("next", NOTE_MS)],
            [shake(500, "medium"), change("wave", 1), timer_start("spawn", WAVE_GAP_MS)]),
    ]


def spawn():
    """A wave begins after its gap (said by a note from the second on); then, every so often, an aggregate comes
    over the top into an empty slot while the wave still needs more kills than there are aggregates."""
    return [
        if_(eq("phase", 2), [set_("phase", 1), set_("kills", 0), set_("wave total", 0),
                             *[if_(eq("wave", w), [hud_counter(1, NEED, label="WAVE %d" % w)])
                               for w in range(1, WAVES + 1)],
                             if_(gt("wave", 1), [award("HERE THEY COME", value=NEED, sub="KILLS IN THIS WAVE",
                                                       seconds=pack.NOTE_S)])]),
        if_(eq("phase", 1), [
            promote(),                                  # (a step into the city in the same tick left "a" empty)
            if_(AND(eq("a", 0), OR(eq("b", 0), ge(LEFT, 2))),
                pick(0, "b") + [set_("a", var("pos")), timer_start("step a", MOVE_MS)],
                [if_(AND(eq("b", 0), ge(LEFT, 2)),
                     pick(0, "a") + [set_("b", var("pos")), timer_start("step b", MOVE_MS)])]),
            timer_start("spawn", SPAWN_AFTER_MS)]),
        timer_start("lamps", 1),
    ]


def wing_hit():
    """A hit on the flying form (the "kill" timer with "killed" 0): he moves on to the next place, and the note
    names it."""
    return [
        change("hits", 1), change("pos", 1), if_(gt("pos", len(SKY)), [set_("pos", 1)]),
        timer_start("fly", MOVE_MS), score(1000000), floor_clock(), hud_counter(1, var("hits")),
        change("pot", mul(5000000, var("hits"))), clip("wing", "behind"), sound("fly"), show("Wing hit"),
        if_(ge("hits", WING_HITS), [
            set_("pos", 0), timer_stop("fly"), timer_stop("boss"), shake(600, "hard"),
            hud_line("HIS PERFECT FORM IS NEXT"),
            award("SHOT DOWN", value=var("pot"), sub="IN THE POT", seconds=pack.NOTE_S), timer_start("next", NOTE_MS)],
            [shake(350, "medium"),
             *[if_(eq("pos", i), [award("WING HIT", value=mul(5000000, var("hits")), sub="NOW THE %s" % W[s],
                                        seconds=pack.NOTE_S)])
               for i, s in enumerate(SKY, 1)]])]


def next_stage():
    """A stage done: the flying form after the swarm, the perfect form after the flying form."""
    return [
        if_(eq("phase", 3), [
            set_("phase", 4), set_("hits", 0), timer_stop("fly"), timer_start("boss", STAGE_MS),
            hud_title("PERFECT DESTOROYAH"), hud_line("SHOOT THE BUILDING %d TIMES" % BOSS_HITS),
            hud_counter(1, 0, "OF %d" % BOSS_HITS, "HITS"), hud_counter(3, pack.STAGE_S, "TO STOP HIM", "SECONDS"),
            award("PERFECT FORM", sub="SHOOT THE BUILDING %d TIMES" % BOSS_HITS, seconds=pack.NOTE_S),
            light_insert("BUILDING SPOT", RED, "blink", 100),
            show("Perfect form"), sound("boss"), clip("boss", "full"), shake_game("rumble")],
            [set_("phase", 3), set_("hits", 0), set_("pos", 1), timer_start("fly", MOVE_MS),
             timer_start("boss", STAGE_MS), music("fly"),
             hud_title("FLYING DESTOROYAH"), hud_line(pack.shoot(SKY[0])),
             hud_counter(1, 0, "OF %d" % WING_HITS, "HITS"), hud_counter(3, pack.STAGE_S, "TO DOWN HIM", "SECONDS"),
             award("HE TAKES WING", sub=pack.shoot(SKY[0]), seconds=pack.NOTE_S),
             *pack.cash_out_lit(),
             show("Takes wing"), sound("fly"), clip("fly", "behind"), shake_game("jackpot")]),
        timer_start("lamps", 1),
    ]


SCRIPTS = [
    # ---- light it: every spin of the Top spinner -----------------------------------------------------------------
    # (PAD-669: no spin counts in a multiball; one counted out but held off starts it on the next spin)
    on_shot(SPIN,
            if_(ge("spins", SPINS_NEED), [start()], [if_(pack.ONE_BALL, [
                change("spins", 1),
                if_(ge("spins", SPINS_NEED), [start()],
                    [if_(eq(mod(var("spins"), SPIN_NOTE_EVERY), 0),
                         [award("SPIN THE TOP SPINNER", value=sub(SPINS_NEED, var("spins")),
                                sub="SPINS TO DESTOROYAH", seconds=pack.NOTE_S)])])])]),
            when="idle"),

    # ---- the aggregates are coming --------------------------------------------------------------------------------
    on_start(*pack.begin(SLUG),
             set_("spins", 0), change("plays", 1),
             set_("phase", 2), set_("wave", 1), set_("kills", 0), set_("city", 0), set_("hits", 0), set_("pot", 0),
             set_("kill total", 0), set_("wave total", 0), set_("all kills", 0), set_("won", 0), set_("cashed", 0),
             set_("a", 0), set_("b", 0), set_("clip ok", 1),
             shield("toward"), game_show("Strobe burst"), clip("intro", "full"), clip("loop", "loop"),
             show("Swarm"), shake(800, "strong"),
             award("DESTOROYAH", sub="THE AGGREGATES ARE COMING", seconds=pack.NOTE_S),
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
             if_(AND(eq("phase", 3), eq("killed", 0), lt("hits", WING_HITS)), wing_hit()),
             timer_start("lamps", 1)),
    on_timer("fly", if_(eq("phase", 3), [change("pos", 1), if_(gt("pos", len(SKY)), [set_("pos", 1)]),
                                         timer_start("fly", MOVE_MS), timer_start("lamps", 1)])),
    every(4, set_("clip ok", 1)),                       # a kill's clip every few seconds at most

    # ---- stage 3: the perfect form at the Building --------------------------------------------------------------------
    on_shot(BOSS,
            if_(AND(eq("phase", 1), OR(eq("a", NUM[BOSS]), eq("b", NUM[BOSS]))),
                [set_("killed", NUM[BOSS]), timer_start("kill", 1)]),
            if_(AND(eq("phase", 4), eq("won", 0)), [
                change("hits", 1), score(BOSS_HIT_VALUE), floor_clock(), hud_counter(1, var("hits")),
                timer_start("lamps", 1),
                if_(lt("hits", BOSS_HITS), [
                    if_(eq("hits", BOSS_HITS - 1), [hud_line("SUPER JACKPOT: SHOOT THE BUILDING")],
                        [hud_line("SHOOT THE BUILDING AGAIN")]),
                    award("DESTOROYAH IS HIT", value=sub(BOSS_HITS, var("hits")), sub="MORE AT THE BUILDING",
                          seconds=pack.NOTE_S),
                    sound("kill"), clip("wing", "behind"), shake(350, "hard")],
                    [set_("won", 1), timer_stop("boss"), score(SUPER), *pack.cash_out_off(),
                     off_insert("BUILDING SPOT"),
                     award("SUPER JACKPOT", value=SUPER, sub="KILLS AND THE POT X2", seconds=4),
                     clip("won", "full"), sound("won"), show("Super jackpot"), shake_game("jackpot"),
                     timer_start("next", NOTE_MS)])])),
    on_timer("boss", if_(AND(ge("phase", 3), eq("won", 0), eq("cashed", 0)), [end()])),
    every(1, if_(AND(ge("phase", 3), gt(timer_left("boss"), 0)), [
        hud_counter(3, div(add(timer_left("boss"), 999), 1000)), timer_start("lamps", 1)])),
    on_timer("lamps", *lamps()),

    # ---- a stage done: on to the next, or cash out --------------------------------------------------------------
    on_timer("next", if_(OR(eq("cashed", 1), eq("won", 1)), [end()], next_stage())),
    on_shot(pack.CASH_SHOT,
            if_(AND(ge("phase", 3), eq("won", 0), eq("cashed", 0)), [
                set_("cashed", 1), timer_stop("boss"), timer_stop("fly"), score(var("pot")), *pack.cash_out_off(),
                off_insert("BUILDING SPOT"), set_("pos", 0), timer_start("lamps", 1),
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
                                                "clip ok", "all kills", "pot")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": dict(hud("THE NEXT ONE IS COMING",
                    counters=[("WAVE 1", "KILLS TO GO", None), ("POT", "CASH AT SCOOP", var("pot")),
                              ("CITY", "HITS TO TAKE", None)])),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "kill", "escape", "wave", "fly", "wing", "boss", "won", "lost", "cashout"),
    "sounds": sounds({"kill": 3, "escape": 3, "wave": 4, "fly": 3, "boss": 4, "won": 4, "lost": 4, "cashout": 4}),
    "music": "music.wav",
    "beds": beds("fly"),
    "shows": SHOWS,
}

#: the Pro's close ring takes the Mecha lane where the Premium/LE has its centre shield: the words that name that
#: shot, as the Pro letters them (BM.adapt rewords whole strings with title_alt's "words")
_PRO_SHOT = {"Shield target center": "Mecha exit bottom"}
_PRO_WORDS = {}
for _from, _to in _PRO_SHOT.items():
    for _fmt in ("SHOOT THE %s", "OR THE %s"):
        _PRO_WORDS[_fmt % W[_from]] = _fmt % W[_to]

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 110, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "destoroyah.c",
    #: the Pro (two fixed shields): the close ring's middle shield is the Mecha lane (Mecha exit bottom), as close
    #: to the flippers, so the close ring keeps five shots
    "title_alt": {"godzilla_pro": {"shots": dict(_PRO_SHOT), "words": _PRO_WORDS}},
    "about": ("The C example DESTOROYAH rebuilt in blocks and taken deeper (PAD-658): 50 Top spinner spins start it "
              "(100 the second time, 150 the third). Three stages: THE SWARM (three waves of aggregates advance from "
              "the Powerlines to the ramps and loop to the close targets, 10 s at each, a kill paying more the closer "
              "it is, each cleared wave into the pot; the title and line name where they are), his FLYING FORM (four "
              "hits in 40 s where he flies over the ramps and the Big loop, moving on every 10 s), then his PERFECT "
              "FORM (three Building hits in 40 s, the super jackpot every kill and the pot twice over). Cash the pot "
              "out at the right scoop once the swarm is beaten."),
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
        "The counters show bare numbers: WAVE 2 over the kills to go where the C showed the wave as 2/3 and the "
        "kills as 1/4, and no counter says what the wave has paid so far.",
        "The line does not say the wave or the kills (the WAVE counter does): in the swarm the title names the first "
        "aggregate's shot and the line the second's (SHOOT THE MASER TARGET / OR THE LEFT POWERLINE), where the C's "
        "line said WAVE 2: 3 MORE  -  CLOSER PAYS MORE and its lit shots alone said where they were.",
        "An aggregate stands 10 s at each shot and the flying form moves on every 10 s, the same each time he comes "
        "back (PAD-658: a moving target stays 10 s at least), where the C's advanced every 7, 6 and 5 s, faster each "
        "time, and its flying form moved on every 3 s; its flying and perfect forms' clocks were 30 and 25 s.",
        "No KILLS gauge: on the glass its pips sat over the game's own POWER widget at the right edge (the C showed "
        "as many pips as the wave needs, shaded yellow to red); the kills to go are on the WAVE counter.",
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
_SWEEP = (["secs", 1] + _FAR) * 20
_WAVES = _START + ["secs", 4] + _SWEEP + ["secs", 1]
#: the flying form starts over the Left ramp and moves on with every hit
_FLY = _shots(["Left ramp", "Big loop", "Right ramp"] * 2, 300) + ["secs", 2]
DESK = [
    # PAD-669: a multiball's spins count for nothing: back to one ball, 49 more do not start him (one of the 50 in
    # the multiball counted would). No note line asked: on a card with KAMACURAS too, her note has the glass
    ("no spin counts in a multiball", ["balls", 2] + ["shot", SPIN, "ms", 60] * 50 + ["balls", 1, "secs", 1] + ["shot", SPIN, "ms", 60] * 49 + ["secs", 2],
     ["![DESTOROYAH] START (a block)"]),
    ("fifty spins the first time, a hundred the second",
     ["shot", SPIN, "ms", 60] * 50 + ["secs", 4, "trigger", "destoroyah.stop", "secs", 4] +
     ["shot", SPIN, "ms", 60] * 95 + ["secs", 4] + ["shot", SPIN, "ms", 60] * 5 + ["secs", 4],
     # his early notes are KAMACURAS's glass on a full card (the same spinner): the last 5 are his once she is lit
     ["Hud_Award: SPIN THE TOP SPINNER", "[DESTOROYAH] START (a block)", "Hud_AwardSub: 5  -  SPINS TO DESTOROYAH", "LAMP POWERLINE LEFT ffc800 blink 700",
      "SHIELD toward"]),
    ("the title and the line name the aggregates", _START + ["secs", 5],
     ["Hud_Title: SHOOT THE LEFT POWERLINE", "Hud_Line: OR THE CENTER POWERLINE",
      "LAMP POWERLINE LEFT ffc800 blink 700", "LAMP POWERLINE CENTER ffc800 blink 700", "Hud_C1_Label: WAVE 1",
      "Hud_C1_Value: 3"]),
    ("far near close then the city", _START + ["secs", 36],
     ["LAMP POWERLINE LEFT ffc800 blink 700", "LAMP BIG LOOP ff5000 blink 400", "Hud_Title: SHOOT THE BIG LOOP",
      "Hud_Line: OR THE BUILDING", "Hud_Title: SHOOT THE GODZILLA TARGET", "Hud_Line: OR THE MASER TARGET",
      "LAMP MASER ff0000 blink 120", "Hud_Award: THE CITY IS HIT", "Hud_AwardSub: 2  -  HITS LEFT"]),
    ("three city hits and he wins", _START + ["secs", 70],
     ["Hud_AwardSub: 1  -  HITS LEFT", "END (a block)", "Hud_Title: DESTOROYAH WINS", "lamps held 0"]),
    ("a kill pays more the closer it is", _START + ["secs", 3.5] + _FAR + ["secs", 11] + _NEAR + ["secs", 11] +
     _CLOSE + ["secs", 1],
     ["Hud_Award: FAR KILL X1", "Hud_AwardSub: 1,000,000", "Hud_Award: NEAR KILL X2", "Hud_AwardSub: 2,000,000",
      "SCORE +4000000", "Hud_Line: THE CLOSER IT IS, THE MORE IT PAYS", "Hud_Award: WAVE CLEARED",
      "Hud_AwardSub: 7,000,000  -  INTO THE POT", "Hud_Title: DESTOROYAH", "Hud_Line: THE NEXT WAVE IS COMING"]),
    ("the swarm, the flying form and the perfect form",
     _WAVES + ["secs", 2] + _FLY + ["secs", 3] + _shots([BOSS] * 3, 400) + ["secs", 6],
     ["Hud_AwardSub: 3,000,000  -  INTO THE POT", "Hud_Line: THE NEXT WAVE IS COMING", "Hud_Award: HERE THEY COME",
      "Hud_AwardSub: 4  -  KILLS IN THIS WAVE", "Hud_C1_Label: WAVE 3", "Hud_Title: THE SWARM IS BEATEN",
      "Hud_Title: FLYING DESTOROYAH", "Hud_Award: HE TAKES WING", "Hud_AwardSub: SHOOT THE LEFT RAMP",
      "LAMP SELECT CITY ffffff chase", "Hud_Line: SHOOT THE BIG LOOP", "Hud_C1_Label: HITS",
      "Hud_Award: WING HIT", "Hud_AwardSub: 5,000,000  -  NOW THE BIG LOOP",
      "Hud_AwardSub: 15,000,000  -  NOW THE LEFT RAMP", "Hud_Award: SHOT DOWN", "Hud_Line: HIS PERFECT FORM IS NEXT",
      "Hud_AwardSub: 65,500,000  -  IN THE POT", "Hud_Title: PERFECT DESTOROYAH",
      "Hud_Line: SHOOT THE BUILDING 3 TIMES", "Hud_Line: SUPER JACKPOT: SHOOT THE BUILDING", "Hud_Award: SUPER JACKPOT",
      "SCORE +146500000", "END (a block)", "Hud_Title: DESTOROYAH DEFEATED", "Hud_Line: KILLS 12", "lamps held 0"]),
    ("cash out after the swarm", _WAVES + ["secs", 4, "shot", "Right scoop", "secs", 5],
     ["Hud_Award: CASHED OUT", "Hud_AwardSub: 15,500,000  -  DESTOROYAH WITHDRAWS", "SCORE +15500000",
      "Hud_Title: DESTOROYAH WITHDRAWS", "lamps held 0"]),
    ("the flying form moves on every ten seconds", _WAVES + ["secs", 15],
     ["Hud_Title: FLYING DESTOROYAH", "Hud_Line: SHOOT THE LEFT RAMP", "LAMP LEFT RAMP b428ff chase 60",
      "Hud_Line: SHOOT THE BIG LOOP", "LAMP BIG LOOP b428ff chase 60", "Hud_C3_Label: SECONDS"]),
    ("a wing hit puts the clock back up to fifteen seconds", _WAVES + ["secs", 30, "shot", "Left ramp", "secs", 1],
     ["Hud_C3_Value: 4", "Hud_Award: WING HIT", "Hud_AwardSub: 5,000,000  -  NOW THE BIG LOOP", "Hud_C3_Value: 15"]),
    ("the flying form gets away", _WAVES + ["secs", 45],
     ["Hud_Title: FLYING DESTOROYAH", "Hud_C3_Label: SECONDS", "END (a block)", "Hud_Title: DESTOROYAH WINS",
      "SCORE +3875000", "lamps held 0"]),
    ("the perfect form's clock runs out", _WAVES + ["secs", 2] + _FLY + ["secs", 44],
     ["Hud_Award: PERFECT FORM", "LAMP BUILDING ff001e blink", "END (a block)", "lamps held 0"]),
    ("a drain ends it", _START + ["secs", 3.5] + _FAR + ["ball_end", "secs", 8],
     ["END (ball ended)", "lamps held 0"]),
]
#: the same mode as a Pro gets it (title_alt): the Mecha lane is a close shot
DESK_PRO = [
    ("the Pro: spins, the swarm, the flying form and the perfect form",
     ["shot", SPIN, "ms", 60] * 50 + ["secs", 4] + _SWEEP + ["secs", 1] + ["secs", 2] + _FLY + ["secs", 3] +
     _shots([BOSS] * 3, 400) + ["secs", 6],
     ["[DESTOROYAH] START (a block)", "Hud_Award: WAVE CLEARED", "Hud_Title: FLYING DESTOROYAH",
      "Hud_Award: SHOT DOWN", "Hud_Award: SUPER JACKPOT", "Hud_Title: DESTOROYAH DEFEATED", "lamps held 0"]),
    ("the Pro's close ring takes the Mecha lane", _START + (["shot", "Mecha exit bottom", "secs", 1] * 2 + ["shot", "Powerline left", "secs", 1]) * 40,
     ["Hud_Award: CLOSE KILL X4", "Hud_AwardSub: 4,000,000", "Hud_Line: OR THE MECHA LANE"]),
]
