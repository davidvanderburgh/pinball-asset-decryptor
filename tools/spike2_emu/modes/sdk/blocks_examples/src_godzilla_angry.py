"""GODZILLA ANGRY (PAD-658): the C example godzilla_angry.c (PAD-379, PAD-416) rebuilt in blocks.

Godzilla vs. Mechagodzilla II (1993): G-Force carries Baby Godzilla away as bait; Godzilla comes for him.

- THE RAGE: every shot the program names fills the meter while the mode is not running (through other modes and
  multiballs too, quietly in a multiball): five stretches of 20, 25, 30, 35, 40 (5 more each after a multiball);
  a note every quarter of a stretch, RAGE n% at each stretch's end; full, GODZILLA IS ANGRY lights the Building.
- THE CHASE: five places, each a set of red shots (any order) and then a lock, 30 s each (a lit shot with under 15 s
  left puts the clock back to 15): ADONOA ISLAND (lock at the captive ball), YOKKAICHI (both ramps, the Maser),
  OSAKA (Big loop and Building, the captive ball), KYOTO (ramps, Building, Big loop, the Maser), MAKUHARI (ramps,
  Big loop, Building, center powerline, the captive ball); then BABY at the Building: the SUPER JACKPOT (5M and
  10,000 a shot through the chase) and a 6-ball multiball.
  A shot pays 500,000 +500,000 a place +25,000 a shot within it and adds an eighth to the JACKPOT; a lock pays
  twice that and adds 250,000 a place.
- FAILING STILL PAYS: a place's clock running out with locks starts a multiball of the locks + 1; with none the trail
  goes cold. A drain mid-chase keeps the place, its locks, the jackpot and the super for the next start.
- ANGRY MULTIBALL: the ramps, Building and Big loop orange, BABY green (it moves every 10 s, the badge counting it,
  and when hit): BABY pays the jackpot times the multiplier, any other lit shot 500,000 and the multiplier +1 (x6).
  One ball left after 20 s ends it, and the meter starts again.
"""
from blk import (AND, BALLS, LIT, NOT, OR, SECS_LEFT, a_show, add, award, change, clip, clips, div, end, eq,
                 every, game_show, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_mode, lt, mul,
                 multiball, ne, off, on_any_shot, on_end, on_shot, on_start, on_timer, score, secs_left, set_, set_time,
                 show, sound, sounds, step, sub, timer_start, timer_stop, var)

SLUG, NAME = "godzilla_angry", "GODZILLA ANGRY"
RED, EMBER, BLUE = "#ff0a00", "#500600", "#2878ff"
WHITE, GREEN, ORANGE = "#ffffff", "#00ff3c", "#ff5000"
START_SHOT = "Building"
LR, RR, BL, BD, PC = "Left ramp", "Right ramp", "Big loop", "Building", "Powerline center"
GT, MT = "Godzilla target", "Maser target"
#: the chase's shots and the flag each one's "done" is kept in (1 = not lit in this place, or made)
CHASE = ((LR, "lr done"), (RR, "rr done"), (BL, "bl done"), (BD, "bd done"), (PC, "pc done"))
#: the places (0-4) and the shots each lights
PLACES = (("ADONOA ISLAND", ()), ("YOKKAICHI", (LR, RR)), ("OSAKA", (BL, BD)), ("KYOTO", (LR, RR, BD, BL)),
          ("MAKUHARI", (LR, RR, BL, BD, PC)))
LOCK_AT = {0: GT, 1: MT, 2: GT, 3: MT, 4: GT}
#: the multiball's jackpot shots, BABY = 1..4 in this order
JP = ((LR, "LEFT RAMP"), (RR, "RIGHT RAMP"), (BD, "BUILDING"), (BL, "BIG LOOP"))
BX, BY = 123, 202                 # the Building's place on the playfield picture (KIT_AT_BUILDING)
MX, MY = 89, 260                  # MAGNA GRAB (KIT_AT_MAGNA): the lock's burst


TIMERS = ("enter", "lights", "made", "lock", "jp", "mbstart")

# ---- the RAGE meter: a fifth of the C's 750 switch hits, as it counts the named shots only ----------------------
L, PLAYS = var("level"), var("plays")
#: the stretch now: 20, 25 ... 40, and 5 more each time the meter has been filled
NEED = add(add(20, mul(5, L)), mul(5, PLAYS))
#: the hits of the stretches done
CUM = add(add(mul(20, L), div(mul(mul(5, L), sub(L, 1)), 2)), mul(mul(5, PLAYS), L))
TOTAL_RAGE = add(150, mul(25, PLAYS))
DONE = add(CUM, var("rage"))
#: the shot's pay in the chase: 500,000 +500,000 a place +25,000 a shot made within it
VALUE = add(add(500000, mul(500000, var("place"))), mul(25000, var("made")))
FLAGS = add(add(add(add(var("lr done"), var("rr done")), var("bl done")), var("bd done")), var("pc done"))


SHOWS = [
    a_show("Rage level",                                   # a rage stretch: a red throb from the flippers
           step("sweep_up", 450, RED, EMBER, "center"),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Angry",                                        # the meter full: the whole playfield throbs
           step("pulse", 900, RED, EMBER, "center", rate=150, gi="dark"),
           step("strobe", 500, WHITE, RED, "center", rate=60, gi="flash"),
           step("implode", 700, RED, EMBER, "xy", x=BX, y=BY)),
    a_show("Angry start",
           step("bolts", 900, WHITE, EMBER, "center", rate=140, gi="dark"),
           step("burst", 800, BLUE, RED, "xy", gi="dark", x=BX, y=BY),
           step("sweep_up", 600, RED, EMBER, "center"),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Lock",
           step("burst", 700, WHITE, RED, "xy", gi="flash", x=MX, y=MY),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Baby found",                                   # green, then every colour
           step("burst", 800, GREEN, WHITE, "xy", gi="flash", x=BX, y=BY),
           step("rainbow", 1500, "#000000", "#000000", "xy", rate=80, x=BX, y=BY),
           step("strobe", 500, WHITE, GREEN, "center", rate=50, gi="flash")),
    a_show("Angry end",
           step("sparkle", 900, RED, EMBER, "center", gi="dark"),
           step("fade", 1000, EMBER, "#000000", "center")),
]


def angry_now():
    return [award("GODZILLA IS ANGRY!", sub="SHOOT THE BUILDING", seconds=3), sound("angry"), show("Angry")]


def lit_building():
    return light_mode(START_SHOT, RED, "pulse")


RAGE = on_any_shot(
    if_(eq("ready", 0), [
        change("rage", 1),
        if_(ge("rage", NEED), [
            change("level", 1), set_("rage", 0),
            if_(ge("level", 5), [
                set_("ready", 1), lit_building(),
                if_(ge(BALLS, 2), [set_("owed", 1)], angry_now())],
                [if_(lt(BALLS, 2), [award("RAGE", value=div(mul(DONE, 100), TOTAL_RAGE), sub="PERCENT"),
                                    sound("rage"), show("Rage level")])])],
            # a quarter of a stretch: how far it is (not in a multiball: it counts quietly)
            [if_(AND(lt(BALLS, 2), ne(div(mul(var("rage"), 4), NEED), div(mul(sub(var("rage"), 1), 4), NEED))), [
                award("MORE TO GODZILLA ANGRY:", value=sub(TOTAL_RAGE, DONE), sub="GODZILLA IS GETTING ANGRY")])]),
    ], [
        # full: lit at the Building again after a start or a new ball, and said once a multiball is over
        if_(NOT(LIT), [lit_building()]),
        if_(AND(eq("owed", 1), lt(BALLS, 2)), [set_("owed", 0)] + angry_now()),
    ]), when="idle")


def enter_place():
    """A place begins: its shots lit (their flags 0), the lock at once at ADONOA ISLAND, 30 s."""
    out = [set_("made", 0), set_("lock lit", 0)] + [set_(f, 1) for _s, f in CHASE]
    for i, (name, shots) in enumerate(PLACES):
        body = [set_(f, 0) for s, f in CHASE if s in shots]
        if not shots:
            body = [set_("lock lit", 1)]
        out.append(if_(eq("place", i), body + [hud_counter(1, var("place"), name)]))
    out.append(if_(eq("place", 5), [hud_counter(1, var("place"), "BABY")]))
    return out + [set_time(30), timer_start("lights", 1)]


def lights_and_line():
    """The inserts and the instruction line for where it is now."""
    mb = [if_(eq("baby", i), [light(s, GREEN, "blink", 200), hud_line("BABY IS AT THE " + words)],
              [light(s, ORANGE, "blink", 500)]) for i, (s, words) in enumerate(JP, 1)]
    mb += [off(PC), off(GT), off(MT)]
    chase = [if_(eq(f, 0), [light(s, RED, "blink", 500)], [off(s)]) for s, f in CHASE]
    chase += [
        if_(AND(eq("lock lit", 1), OR(eq("place", 0), eq("place", 2), eq("place", 4))),
            [light(GT, WHITE, "hurry"), hud_line("LOCK IS LIT AT THE CAPTIVE BALL")], [off(GT)]),
        if_(AND(eq("lock lit", 1), OR(eq("place", 1), eq("place", 3))),
            [light(MT, WHITE, "hurry"), hud_line("LOCK IS LIT AT THE MASER")], [off(MT)]),
        if_(eq("place", 5), [light(BD, GREEN, "hurry"), hud_line("SHOOT THE BUILDING: BABY IS THERE")]),
    ]
    chase += [if_(AND(eq("place", i), eq("lock lit", 0)), [hud_line(name + ": LIT SHOTS TO GO", sub(5, FLAGS))])
              for i, (name, shots) in enumerate(PLACES) if shots]
    return [if_(gt("mb", 0), mb, chase)]


def made_shot():
    """One of the place's red shots made (its flag already set)."""
    out = [score(VALUE), change("jackpot", div(VALUE, 8))]
    out += [if_(eq("place", i), [award(name, value=VALUE, seconds=2)]) for i, (name, shots) in enumerate(PLACES)
            if shots]
    return out + [
        change("made", 1), hud_counter(2, var("jackpot")),
        if_(lt(SECS_LEFT, 15), [set_time(15)]),
        if_(eq(FLAGS, 5), [set_("lock lit", 1)]),
        timer_start("lights", 1)]


def lock_made():
    out = [score(mul(2, VALUE)), change("jackpot", mul(250000, add(var("place"), 1)))]
    words = ("1 LOCK", "2 LOCKS", "3 LOCKS", "4 LOCKS", "5 LOCKS")
    out += [if_(eq("place", i), [award(w, value=mul(2, VALUE), sub="HE SMASHES THROUGH", seconds=2)])
            for i, w in enumerate(words)]
    return out + [hud_counter(2, var("jackpot")), clip("lock", "behind"), sound("lock"), show("Lock"),
                  change("place", 1), timer_start("enter", 1)]


def jackpot_shot():
    """A lit shot in the multiball (``hit`` = which): BABY's jackpot, or the multiplier up."""
    baby_moves = [change("baby", 1), if_(gt("baby", 4), [set_("baby", 1)])]
    return [
        if_(eq("hit", var("baby")), [
            score(mul(var("jackpot"), var("mult"))),
            award("BABY JACKPOT", value=mul(var("jackpot"), var("mult")), sub="TIMES THE MULTIPLIER", seconds=2),
            if_(ge("mult", 4), [clip("super", "full"), sound("super")], [clip("jackpot", "behind"), sound("jackpot")]),
            set_("mult", 1), change("babies", 1), *baby_moves, set_time(10)],
            [score(500000), if_(lt("mult", 6), [change("mult", 1)]),
             award("BABY X", value=var("mult"), sub="NOW SHOOT BABY", seconds=1)]),
        hud_counter(1, var("mult")), hud_counter(3, var("babies")), timer_start("lights", 1)]


def start_multiball():
    """ANGRY MULTIBALL: 6 balls after BABY FOUND, else the locks + 1 (2 to 6), a 15 s ball save."""
    balls = [if_(eq("place", n - 1), [multiball(n, 15)]) for n in (3, 4, 5)]
    return [
        if_(eq("mb", 2), [multiball(6, 15)], [
            if_(le("place", 1), [multiball(2, 15)]), *balls, if_(ge("place", 5), [multiball(6, 15)])]),
        set_("mult", 1), set_("baby", 1), set_("mb secs", 0),
        if_(lt("jackpot", 2000000), [set_("jackpot", 2000000)]),
        set_time(10), hud_title("ANGRY MULTIBALL"),
        hud_counter(1, var("mult"), "OTHERS RAISE IT", "MULTIPLIER"), hud_counter(2, var("jackpot"), "AT BABY"),
        hud_counter(3, var("babies"), "AT BABY", "JACKPOTS"),
        timer_start("lights", 1)]


def chase_shot(shot, flag, hit):
    out = [if_(AND(eq("mb", 0), lt("place", 5), eq(flag, 0)), [set_(flag, 1), timer_start("made", 1)])]
    if hit:
        out.append(if_(gt("mb", 0), [set_("hit", hit), timer_start("jp", 1)]))
    return out


def ending_words():
    """The ending's title and line: GODZILLA AND BABY after BABY FOUND; the multiball's BABY jackpots and locks
    (the number can only come last); the chase's place where the trail waits."""
    mb = [if_(eq("mb", 2), [hud_title("GODZILLA AND BABY")])]
    mb += [if_(eq("place", n), [hud_line("%d LOCK%s  -  BABY JACKPOTS" % (n, "" if n == 1 else "S"),
                                         value=var("babies"))]) for n in range(1, 6)]
    chase = [if_(eq("place", i), [hud_line("THE TRAIL WAITS AT " + name)]) for i, (name, _s) in enumerate(PLACES)]
    chase += [if_(eq("place", 5), [hud_line("THE TRAIL WAITS AT BABY")])]
    return [if_(gt("mb", 0), mb, chase)]


SCRIPTS = [
    RAGE,
    # ---- the chase -----------------------------------------------------------------------------------------------
    on_start(set_("place", var("trail place")), set_("jackpot", var("trail jackpot")),
             set_("super", var("trail super")), if_(eq("super", 0), [set_("super", 5000000)]),
             set_("mb", 0), set_("mult", 1), set_("mb secs", 0),
             clip("intro", "full"), clip("loop", "loop"), game_show("Insert chase"), hud_title("GODZILLA ANGRY!"),
             hud_counter(2, var("jackpot"), "BUILT BY SHOTS"), hud_counter(3, var("super"), "FED BY SWITCHES"),
             if_(eq("place", 0), [award("GODZILLA ANGRY!", sub="THEY TOOK BABY GODZILLA", seconds=3)],
                 [award("THE TRAIL AGAIN", value=var("place"), sub="LOCKS KEPT", seconds=3)]),
             timer_start("enter", 1)),
    on_timer("enter", *enter_place()),
    on_timer("lights", *lights_and_line()),
    on_any_shot(if_(eq("mb", 0), [change("super", 10000), hud_counter(3, var("super"))])),   # every shot feeds the SUPER
    on_shot(LR, *chase_shot(LR, "lr done", 1)),
    on_shot(RR, *chase_shot(RR, "rr done", 2)),
    on_shot(BL, *chase_shot(BL, "bl done", 4)),
    on_shot(BD, *chase_shot(BD, "bd done", 3),
            if_(AND(eq("mb", 0), eq("place", 5)), [               # BABY FOUND: the super and six balls
                score(var("super")),
                award("SUPER JACKPOT", value=var("super"), sub="BABY FOUND", seconds=4),
                show("Baby found"), clip("baby", "full"), sound("baby"),
                set_("mb", 2), timer_start("mbstart", 1)])),
    on_shot(PC, *chase_shot(PC, "pc done", 0)),
    on_timer("made", *made_shot()),
    on_shot(GT, if_(AND(eq("mb", 0), eq("lock lit", 1), OR(eq("place", 0), eq("place", 2), eq("place", 4))),
                    [timer_start("lock", 1)])),
    on_shot(MT, if_(AND(eq("mb", 0), eq("lock lit", 1), OR(eq("place", 1), eq("place", 3))),
                    [timer_start("lock", 1)])),
    on_timer("lock", *lock_made()),
    # the place's clock: with locks they break loose as a multiball; with none it runs out (the trail goes cold).
    # In the multiball the clock counts BABY's next move.
    secs_left(1,
              if_(gt("mb", 0), [change("baby", 1), if_(gt("baby", 4), [set_("baby", 1)]), set_time(10),
                                timer_start("lights", 1)],
                  [if_(gt("place", 0), [
                      set_("mb", 1), award("THE LOCKS BREAK LOOSE", sub="ANGRY MULTIBALL", seconds=3),
                      sound("lock"), clip("lock", "behind"), timer_start("mbstart", 1)])])),
    # ---- the multiball -----------------------------------------------------------------------------------------
    on_timer("mbstart", *start_multiball()),
    on_timer("jp", *jackpot_shot()),
    every(1, if_(gt("mb", 0), [change("mb secs", 1),
                               if_(AND(ge("mb secs", 20), lt(BALLS, 2)), [end()])])),
    # ---- the end -----------------------------------------------------------------------------------------------
    on_end(*[timer_stop(t) for t in TIMERS], game_show("Ember fade"),
           if_(gt("mb", 0), [
               # the meter starts again, each stretch 5 more; the trail is forgotten
               set_("ready", 0), set_("level", 0), set_("rage", 0), change("plays", 1),
               set_("trail place", 0), set_("trail jackpot", 0), set_("trail super", 0),
               if_(eq("mb", 2), [clip("won", "full"), sound("won")],
                   [clip("lost", "full"), sound("lost", fallback="time_up")])],
               [
               # the chase: a drain keeps the trail for the next start; at ADONOA ISLAND it goes cold
               if_(gt("place", 0), [set_("trail place", var("place")), set_("trail jackpot", var("jackpot")),
                                    set_("trail super", var("super"))],
                   [set_("trail place", 0), set_("trail jackpot", 0), set_("trail super", 0)]),
               clip("lost", "full"), sound("lost", fallback="time_up"), lit_building()]),
           *ending_words()),
]


PROGRAM = {
    "name": NAME, "seconds": 30, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "game"} for n in ("rage", "level", "ready", "plays", "owed", "trail place",
                                                     "trail jackpot", "trail super")] +
            [{"name": n, "reset": "mode"} for n in ("place", "mb", "lock lit", "made", "jackpot", "super", "mult",
                                                     "baby", "babies", "hit", "mb secs")] +
            [{"name": f, "reset": "mode"} for _s, f in CHASE],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("LOCK IS LIT AT THE CAPTIVE BALL",
               counters=[("LOCKS", "ADONOA ISLAND", None), ("JACKPOT", "BUILT BY SHOTS", None),
                         ("SUPER", "FED BY SWITCHES", None)],
               timer=("ANGRY", "rage")),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "lock", "baby", "jackpot", "super", "won", "lost"),
    "sounds": sounds({"rage": 3, "angry": 4, "lock": 3, "baby": 4, "jackpot": 3, "super": 4, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

LOST = [
    "The RAGE meter counts only the shots this program names (the ramps, Big loop, Building, center powerline, "
    "captive ball and Maser): the blocks never see a switch's own hit, where the C counts every playfield switch. "
    "So the meter is a fifth as long (stretches of 20, 25, 30, 35, 40 hits, 5 more each after a multiball, where the "
    "C has 100 to 200 and 25 more), and the SUPER JACKPOT grows 10,000 a named shot rather than a switch.",
    "No points while the mode is not running: the C pays 1,000,000 (+500,000 a stretch) at each RAGE stretch's end; "
    "the blocks' Score only scores while the mode runs, so a stretch is a note, a roar and a light show only.",
    "The RAGE meter is not on the glass: the C draws it as a bar with GODZILLA RAGE and its percent at the top right "
    "all game; a blocks HUD shows only while the mode runs, so the meter is the notes alone (every quarter of a "
    "stretch, and RAGE n PERCENT at its end).",
    "No ball save: the C gives a 5 s ball save at the start and keeps one running from the first lock, so a drain "
    "with locks sends the locked balls straight into the multiball. In blocks a drain ends the chase; the place, its "
    "locks, the jackpot and the super wait for the next start at the Building (as the C does for a drain with no lock).",
    "No randomness: BABY starts at the Left ramp and moves to the next shot in turn (Left ramp, Right ramp, Building, "
    "Big loop) every 10 s and when hit, where the C picks another at random.",
    "The ending's line after a multiball puts the BABY jackpots last (5 LOCKS  -  BABY JACKPOTS 2) where the C said "
    "2 BABY JACKPOTS  -  5 LOCKS, and says JACKPOTS for one too.",
    "The ending stays up 3 s, the runtime's: the C kept it 10 s.",
    "The instruction line counts the place's shots still to make (\"KYOTO: LIT SHOTS TO GO 3\") where the C names "
    "them while they fit (\"OSAKA: BIG LOOP, BUILDING\"); the award for a shot says the place and the points, and a "
    "start on the trail says THE TRAIL AGAIN with its locks, not the place's name.",
    "The badge counts the place's 30 s in the chase and BABY's next move (10 s) in the multiball, where the C hides "
    "it in the multiball; a place's clock with locks turns into the multiball with a second left, not at 0.",
    "One display priority, 180, throughout: the C takes 190 (a wizard's) for the multiball.",
    "For Godzilla Premium/LE only: the C also ran on Godzilla Pro, playing its own start and end shows where the "
    "game has no Insert chase or Ember fade; a blocks program cannot ask whether the game has a show. Its own two "
    "are kept under Light shows (Angry start, Angry end), not run, to swap in.",
    "No tilt rule of its own: the C stops the meter after a tilt until the next ball; here the tilted ball's shots "
    "still count.",
    "Another mode of ours ending on the Building does not keep it from starting this one on that same shot (the C "
    "waits 300 ms after another of ours ends).",
]

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 107, "titles": ["godzilla_le"],
    "based_on": "godzilla_angry.c",
    "about": ("The C example GODZILLA ANGRY rebuilt in blocks: shots fill the RAGE meter, which lights the Building; "
              "a chase through five places, each with lit shots and a lock, to BABY at the Building and a six-ball "
              "multiball with BABY's jackpot moving round the ramps, Building and Big loop."),
    "lost": LOST,
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _shots(*names, gap=300):
    out = []
    for n in names:
        out += ["shot", n, "ms", gap]
    return out


_START = ["trigger", "godzilla_angry.start", "secs", 1]
_CHASE = (_shots(GT) + _shots(LR, RR, MT) + _shots(BL, BD, GT) + _shots(LR, RR, BD, BL, MT) +
          _shots(LR, RR, BL, BD, PC, GT) + ["secs", 1])
#: 150 named shots fill the meter (the Big loop's: no other example here counts it while it is not lit)
_FILL = _shots(*([BL] * 150), gap=60) + ["secs", 1]
DESK = [
    ("the rage lights the building", _FILL + ["shot", BD, "secs", 2],
     ["Hud_Award: MORE TO GODZILLA ANGRY: 145", "Hud_Award: RAGE 13", "Hud_Award: GODZILLA IS ANGRY!",
      "[GODZILLA ANGRY] START (its lit shot)", "Hud_Award: GODZILLA ANGRY!"]),
    ("five places then baby and the multiball",
     _START + _CHASE + _shots(BD) + ["secs", 3] + _shots(RR, BD, BL, LR) + ["secs", 20, "balls", 1, "secs", 8],
     ["Hud_Award: 1 LOCK 1,000,000", "Hud_Award: YOKKAICHI 1,000,000", "Hud_Award: YOKKAICHI 1,025,000",
      "Hud_Award: 2 LOCKS 2,100,000", "Hud_Line: OSAKA: LIT SHOTS TO GO 2", "Hud_Award: MAKUHARI 2,600,000",
      "Hud_Award: 5 LOCKS", "Hud_Line: SHOOT THE BUILDING: BABY IS THERE", "Hud_Award: SUPER JACKPOT",
      "MULTIBALL 6 balls, save 15 s", "Hud_Title: ANGRY MULTIBALL", "Hud_C1_Label: MULTIPLIER", "Hud_C3_Label: JACKPOTS", "Hud_Award: BABY X 2",
      "Hud_Award: BABY X 4", "Hud_Award: BABY JACKPOT 27,975,000", "own clip super", "own clip won", "Hud_Title: GODZILLA AND BABY",
      "Hud_Line: 5 LOCKS  -  BABY JACKPOTS 1",
      "END (a block)", "lamps held 0"]),
    ("the clock turns the locks into a multiball",
     _START + _shots(GT) + ["secs", 32, "balls", 1, "secs", 25],
     ["Hud_Award: THE LOCKS BREAK LOOSE", "MULTIBALL 2 balls, save 15 s", "Hud_Title: GODZILLA ANGRY TOTAL",
      "Hud_Line: 1 LOCK  -  BABY JACKPOTS 0",
      "END (a block)", "lamps held 0"]),
    ("a drain keeps the trail", _START + _shots(GT, LR, RR, MT) + ["ball_end", "secs", 8] + _START,
     ["END (ball ended)", "Hud_Award: THE TRAIL AGAIN 2", "Hud_Line: OSAKA: LIT SHOTS TO GO 2",
      "END lamps held 2"]),                   # running again at OSAKA: the Big loop and the Building lit
    ("with no lock the trail goes cold", _FILL + ["shot", BD, "secs", 32] + _shots(BD) + ["secs", 2],
     ["END (time ran out)", "Hud_Title: GODZILLA ANGRY TOTAL", "Hud_Line: THE TRAIL WAITS AT ADONOA ISLAND",
      "Hud_Line: LOCK IS LIT AT THE CAPTIVE BALL", "END lamps held 1"]),    # running again: the lock lit
    ("a lit shot puts the clock back to fifteen", _START + _shots(GT) + ["secs", 20] + _shots(LR) + ["secs", 1],
     ["Hud_Award: YOKKAICHI 1,000,000"]),
]
