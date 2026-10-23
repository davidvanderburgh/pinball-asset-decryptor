"""GODZILLA ANGRY (PAD-658): the C example godzilla_angry.c (PAD-379, PAD-416) rebuilt in blocks, then (round 2)
made EHoH's Gappa Angry: how many balls are locked decides WHICH multiball.

Godzilla vs. Mechagodzilla II (1993): G-Force carries Baby Godzilla away as bait; Godzilla comes for him, past
Rodan's nest, Mechagodzilla, the Garuda gunship and the reborn Fire Rodan, to Super Mechagodzilla at Makuhari.

- THE RAGE: every playfield switch hit fills the meter while no mode runs (PAD-675, David: "we should have our
  required switch counts in there still that we had before (something like 1000 switch hits)"; not in a multiball,
  as the C): five stretches of 150, 175, 200, 225, 250 (1000) the first time, TWICE that (2000) the second, three
  times (3000) the third (pack.need's rule: each start costs more); a note every quarter of a stretch, RAGE n% at
  each stretch's end; full, GODZILLA IS ANGRY lights the Building.
- THE CHASE, five stages, deeper and deeper: five places, each a set of red shots (any order) and then a lock
  (white, hurrying), pack.STAGE_S (40 s) a place, 45 at KYOTO's five shots and 50 at MAKUHARI's six, the same every
  time (PAD-658 round 3: it was 30 s, and 25 then 20 once the meter had been spent; a lit shot with under 15 s left
  puts the clock back to 15): ADONOA ISLAND (the lock at once, at the Godzilla target), YOKKAICHI (both ramps, the
  Maser target), OSAKA (Big loop and Building, the Godzilla target), KYOTO (ramps, Building, Big loop, the Maser
  target), MAKUHARI (ramps, Big loop, Building, center powerline, the Godzilla target); then BABY at the Building:
  the SUPER JACKPOT (5M and 10,000 a shot through the chase). A shot pays 500,000 +500,000 a place +25,000 a shot
  within it and adds an eighth to the JACKPOT; a lock pays twice that and adds 250,000 a place.
  THE LINE NAMES THE SHOTS (PAD-658 round 3, David: "the shots are not explicit enough"): the place's red shots by
  name once 1 or 2 are left ("SHOOT BOTH RAMPS", "SHOOT THE BIG LOOP AND BUILDING", "SHOOT THE RIGHT RAMP"), "ANY
  LIT SHOT: 4 TO GO" while 3 or more of KYOTO's or MAKUHARI's are; "LOCK IS LIT: SHOOT THE MASER TARGET". The right
  counter says how many are left (SHOTS n TO LIGHT LOCK; LOCK n IS LIT; at BABY the SUPER), a place's last shot's
  note and a lock's note say the next shot ("NOW THE GODZILLA TARGET", "NOW BOTH RAMPS").
- THE MULTIBALL THE LOCKS EARNED (Gappa Angry's Pool Party ... Run For Your Life): the place's clock running out
  with locks, or BABY found, starts the multiball of that many locks, each its own name, clips, music bed, jackpot
  shots, values, light shows and shakes:
    1 lock   2-ball RODAN'S NEST         jackpots round the captive ball, the ramps and the Mecha lane, x1
    2 locks  3-ball MECHAGODZILLA        the ramps, the Mecha lane and the Building, x2
    3 locks  4-ball GARUDA               the Right ramp, the Mecha lane, the Building and the Big loop, x3
    4 locks  5-ball FIRE RODAN           the Mecha lane, the Building, the Big loop and the Maser, x4
    5 locks  6-ball SUPER MECHAGODZILLA  the Building, the Big loop, the Maser and the center powerline, x5
  The JACKPOT (green, chasing) moves along the kind's four shots every pack.WINDOW_S (20 s; it was 11 s, 7 s in the
  6-ball: David could not tell which shot it was) and when hit, and pays the jackpot times the multiplier; the
  kind's other three (orange, blinking faster the bigger the kind) pay 500,000 a lock and raise the multiplier by 1
  (up to 5 over the kind's own). The multiplier starts at the kind's number: going deeper is worth more. The line
  names the jackpot's shot as it moves ("JACKPOT: SHOOT THE RIGHT RAMP"); the counters: JACKPOTS (this multiball),
  JACKPOT (what it pays now, the multiplier in, and its shot under it), MULTIPLIER (ORANGE SHOTS +1); a jackpot's and
  a multiplier's note stay 3 s and say where the jackpot is now. The Mecha lane (a shot of four of the kinds) lights
  its MECHA LANE insert by name: its shot has no light of its own on the playfield, so until round 3 it counted
  dark. One ball left after 20 s ends it, and the meter starts again, twice as long.
- FAILING STILL PAYS: a place's clock with locks still starts their multiball; with none the trail goes cold. A
  drain mid-chase keeps the place, its locks, the jackpot and the super for the next start.
"""
from itertools import combinations

import pack
from blk import (AND, BALLS, LIT, NOT, OR, SECS_LEFT, a_show, add, award, beds, change, clip, clips, div, end, eq,
                 every, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_insert, light_mode, lt,
                 mul, multiball, music, ne, off, off_insert, on_any_shot, on_end, on_shot, on_start, on_switch, on_timer, score,
                 secs_left,
                 set_, set_time, shake, shake_game, show, sound, sounds, step, sub, timer_left, timer_start,
                 timer_stop, var)

SLUG, NAME = "godzilla_angry", "GODZILLA ANGRY"
RED, EMBER, BLUE = "#ff0a00", "#500600", "#2878ff"
WHITE, GREEN, ORANGE = "#ffffff", "#00ff3c", "#ff5000"
AMBER, STEEL, CYAN, FIRE, GOLD = "#ff9000", "#8090ff", "#40d0ff", "#ff3000", "#ffc000"
START_SHOT = "Building"
LR, RR, BL, BD, PC = "Left ramp", "Right ramp", "Big loop", "Building", "Powerline center"
GT, MT, ML = "Godzilla target", "Maser target", "Mecha exit bottom"
#: the chase's shots and the flag each one's "done" is kept in (1 = not lit in this place, or made)
CHASE = ((LR, "lr done"), (RR, "rr done"), (BL, "bl done"), (BD, "bd done"), (PC, "pc done"))
#: the places (0-4) and the shots each lights
PLACES = (("ADONOA ISLAND", ()), ("YOKKAICHI", (LR, RR)), ("OSAKA", (BL, BD)), ("KYOTO", (LR, RR, BD, BL)),
          ("MAKUHARI", (LR, RR, BL, BD, PC)))
#: each place's clock (PAD-658 round 3: a stage's clock; more for KYOTO's five shots and MAKUHARI's six), then BABY's
PLACE_S = (pack.STAGE_S, pack.STAGE_S, pack.STAGE_S, pack.STAGE_S + 5, pack.STAGE_S + 10, pack.STAGE_S)
#: the next place's shots, as a lock's note says them
NEXT_WORDS = ("NOW BOTH RAMPS", "NOW BIG LOOP, BUILDING", "NOW 4 LIT SHOTS", "NOW 5 LIT SHOTS", "NOW THE BUILDING")
#: the multiball's jackpot shots by number: kind k (= its locks, 1-5) plays shots k to k+3
CODES = ((GT, "CAPTIVE BALL"), (LR, "LEFT RAMP"), (RR, "RIGHT RAMP"), (ML, "MECHA LANE"), (BD, "BUILDING"),
         (BL, "BIG LOOP"), (MT, "MASER"), (PC, "CENTER POWERLINE"))
CODE = {s: i for i, (s, _w) in enumerate(CODES, 1)}
#: the five multiballs: (name, its clip and call at the start, its bed, its jackpot clip and call, the jackpot's
#: award, its jackpot shake, the ending's title, the line, the insert it lights)
KINDS = (
    dict(name="RODAN'S NEST", clip="mb2", call="mb2", bed="mb2", jclip="mb2", jcall="jp2",
         jword="RODAN JACKPOT", shake=shake(600, "medium"), jshake=shake(300, "medium"), title="RODAN'S NEST TOTAL",
         insert="RODAN", color=AMBER),
    dict(name="MECHAGODZILLA", clip="mb3", call="mb3", bed="mb3", jclip="jackpot", jcall="jackpot",
         jword="MECHA JACKPOT", shake=shake(800, "strong"), jshake=shake(450, "strong"), title="MECHAGODZILLA TOTAL",
         insert="ATTACK MECHA", color=STEEL),
    dict(name="GARUDA", clip="mb4", call="mb4", bed="mb4", jclip="mb4", jcall="jp4",
         jword="GARUDA JACKPOT", shake=shake(1000, "strong"), jshake=shake(600, "strong"), title="GARUDA TOTAL",
         insert="HEAT RAY", color=CYAN),
    dict(name="FIRE RODAN", clip="mb5", call="mb5", bed="mb5", jclip="mb5",
         jcall="jp5", jword="FIRE JACKPOT", shake=shake(1000, "hard"), jshake=shake(800, "hard"), title="FIRE RODAN TOTAL",
         insert="RODAN", color=FIRE),
    dict(name="SUPER MECHAGODZILLA", clip="baby", call="baby", bed="mb6", jclip="super", jcall="super",
         jword="BABY JACKPOT", shake=shake(1000, "hard"), jshake=shake_game("jackpot"), title="SUPER MECHA TOTAL",
         insert="MECHA WIZ", color=GREEN),
)
#: places on the playfield picture (the port's lamp lines): the Building (KIT_AT_BUILDING), MAGNA GRAB (the lock's
#: burst), RODAN, ATTACK MECHA, HEAT RAY, MECHA LANE
BX, BY = 123, 202
MX, MY = 89, 260
RX, RY = 178, 421
AX, AY = 200, 381
HX, HY = 180, 144
LX, LY = 282, 393

TIMERS = ("enter", "lights", "made", "lock", "jp", "mbstart", "grace")

# ---- the RAGE meter: 1000 switch hits (PAD-675; the C had 750); x(times spent + 1) ----
L, PLAYS = var("level"), var("plays")
TIMES = add(PLAYS, 1)
#: the stretch now: 150, 175 ... 250 the first time, twice that the second
NEED = mul(add(150, mul(25, L)), TIMES)
#: the hits of the stretches done
CUM = mul(add(mul(150, L), div(mul(mul(25, L), sub(L, 1)), 2)), TIMES)
TOTAL_RAGE = mul(1000, TIMES)
DONE = add(CUM, var("rage"))
#: the shot's pay in the chase: 500,000 +500,000 a place +25,000 a shot made within it
VALUE = add(add(500000, mul(500000, var("place"))), mul(25000, var("made")))
FLAGS = add(add(add(add(var("lr done"), var("rr done")), var("bl done")), var("bd done")), var("pc done"))
#: the place's red shots still to make
TO_GO = sub(5, FLAGS)
#: the multiball: the jackpot's pay, the kind's last shot, how long the jackpot stays before it moves on (PAD-658
#: round 3: a lit shot that times out stays pack.WINDOW_S; it was 12 s less a second a lock, 7 s in the 6-ball)
JP_VALUE = mul(var("jackpot"), var("mult"))
LAST = add(var("place"), 3)
STAY = pack.WINDOW_S
#: 1 once there is a lock (the trail keeps its jackpot and super), 0 at ADONOA ISLAND (it goes cold)
KEEP = div(add(var("place"), 4), 5)


def _turn(by):
    """The JACKPOT's place among the kind's four shots, ``by`` along (round again past the last)."""
    r = add(sub(var("baby"), var("place")), by)
    return add(var("place"), sub(r, mul(4, div(r, 4))))


#: on, as its clock runs out; back one when it is hit (so its four never pay in a row)
ON, BACK = _turn(1), _turn(3)


def _words(shot):
    return pack.SHOT_WORDS[shot]


def _now(shot):
    """A note's sub naming the jackpot's shot now (the center powerline's without THE: it fits under a number)."""
    return ("NOW " if shot == PC else "NOW THE ") + _words(shot)


def _say_set(shots):
    """The line naming one or two of the place's red shots still to make."""
    w = [_words(s) for s in shots]
    if len(w) == 1:
        return "SHOOT THE " + w[0]
    if set(shots) == {LR, RR}:
        return "SHOOT BOTH RAMPS"
    t = "SHOOT THE %s AND %s" % tuple(w)
    return t if len(t) <= 40 else "SHOOT %s AND %s" % tuple(w)


def _x(fx, ms, a, b, x, y, **kw):
    return step(fx, ms, a, b, "xy", x=x, y=y, **kw)


SHOWS = [
    a_show("Rage level",                                   # a rage stretch: a red throb from the flippers
           step("sweep_up", 450, RED, EMBER, "flippers"),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Angry",                                        # the meter full: the whole playfield throbs
           step("pulse", 900, RED, EMBER, "center", rate=150, gi="dark"),
           step("strobe", 500, WHITE, RED, "center", rate=60, gi="flash"),
           _x("implode", 700, RED, EMBER, BX, BY)),
    a_show("Angry start",                                  # the chase begins: lightning, his ray from the Building
           step("bolts", 900, WHITE, EMBER, "center", rate=140, gi="dark"),
           _x("burst", 800, BLUE, RED, BX, BY, gi="dark"),
           step("sweep_up", 600, RED, EMBER, "center"),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Chase shot",                                   # a red shot made: a spark at the shot's side
           step("sparkle", 400, RED, EMBER, "top", gi="keep"),
           step("fade", 250, RED, "#000000", "top")),
    a_show("Lock",                                         # a lock: Godzilla smashes through
           _x("burst", 700, WHITE, RED, MX, MY, gi="flash"),
           step("strobe", 300, WHITE, RED, "center", rate=50, gi="flash"),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Place",                                        # on to the next place: the trail leads up the playfield
           step("sweep_up", 500, RED, "#000000", "center", gi="dark"),
           step("chase", 900, RED, EMBER, "center", rate=90, gi="dark"),
           _x("ripple", 900, ORANGE, EMBER, BX, BY, rate=300, gi="dark"),
           step("fade", 400, RED, "#000000", "center", blend=150)),
    a_show("Baby found",                                   # the SUPER: green, then every colour
           _x("burst", 800, GREEN, WHITE, BX, BY, gi="flash"),
           _x("rainbow", 1500, "#000000", "#000000", BX, BY, rate=80),
           step("strobe", 500, WHITE, GREEN, "center", rate=50, gi="flash")),
    a_show("Trail cold",                                   # the chase lost: embers die at the Building
           _x("implode", 900, EMBER, "#000000", BX, BY, gi="dark"),
           step("fade", 900, EMBER, "#000000", "center", blend=300)),
    a_show("Multiplier",                                   # a shot that raises the multiplier
           step("bounce", 500, ORANGE, "#000000", "center", rate=120, gi="keep"),
           step("fade", 200, ORANGE, "#000000", "center")),
    # ---- the five multiballs: a start and a jackpot each -----------------------------------------------------------
    a_show("Rodan start",                                  # Rodan's wings: amber sweeps from his insert
           _x("fade_in", 500, AMBER, "#000000", RX, RY, gi="dark"),
           step("sweep_lr", 400, AMBER, "#000000", "center", gi="dark"),
           step("sweep_rl", 400, AMBER, "#000000", "center", gi="dark"),
           _x("spiral_out", 1100, AMBER, "#301000", RX, RY, gi="dark"),
           step("fade", 400, AMBER, "#000000", "center", blend=150)),
    a_show("Rodan jackpot",
           _x("burst", 600, WHITE, AMBER, RX, RY, gi="flash"),
           step("sweep_down", 400, AMBER, "#000000", "top", gi="dark"),
           step("fade", 300, AMBER, "#000000", "center")),
    a_show("Mecha start",                                  # Mechagodzilla powers up: steel blue scan and bolts
           _x("spin", 1000, STEEL, "#000020", AX, AY, rate=110, gi="dark"),
           step("bolts", 700, WHITE, STEEL, "center", rate=100, gi="dark"),
           _x("burst", 700, WHITE, BLUE, AX, AY, gi="flash"),
           step("fade", 400, BLUE, "#000000", "center", blend=150)),
    a_show("Mecha jackpot",                                # Godzilla's ray hits it: blue then red
           step("sweep_rl", 350, BLUE, "#000000", "center", gi="dark"),
           _x("burst", 500, RED, BLUE, AX, AY, gi="flash"),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Garuda start",                                 # the gunship flies over: cyan beams side to side
           step("sweep_down", 500, CYAN, "#000000", "top", gi="dark"),
           step("bounce", 1100, WHITE, CYAN, "top", rate=140, gi="dark"),
           _x("ripple", 900, CYAN, "#001020", HX, HY, rate=280, gi="dark"),
           step("fade", 400, CYAN, "#000000", "center", blend=150)),
    a_show("Garuda jackpot",                               # its maser cannon
           _x("strobe", 300, WHITE, CYAN, HX, HY, rate=45, gi="flash"),
           step("sweep_down", 400, CYAN, "#000000", "top", gi="dark"),
           step("fade", 300, CYAN, "#000000", "center")),
    a_show("Fire start",                                   # Rodan reborn: fire from his insert, then everywhere
           _x("fade_in", 600, FIRE, "#000000", RX, RY, gi="dark"),
           _x("fire", 1400, GOLD, FIRE, RX, RY, gi="dark"),
           _x("spiral_out", 900, GOLD, FIRE, RX, RY, gi="dark"),
           step("fade", 500, FIRE, "#000000", "center", blend=200)),
    a_show("Fire jackpot",
           step("fire", 700, GOLD, FIRE, "center", gi="dark"),
           _x("burst", 500, WHITE, FIRE, RX, RY, gi="flash"),
           step("fade", 300, FIRE, "#000000", "center")),
    a_show("Super start",                                  # the finale: Super Mechagodzilla, Baby's green light
           step("strobe", 500, WHITE, STEEL, "center", rate=50, gi="flash"),
           _x("spiral_in", 900, STEEL, "#000020", LX, LY, gi="dark"),
           _x("spiral_out", 900, GREEN, "#002010", BX, BY, gi="dark"),
           step("rainbow", 1500, "#000000", "#000000", "center", rate=60),
           step("fade", 500, GREEN, "#000000", "center", blend=200)),
    a_show("Super jackpot",                                # his red spiral ray
           _x("spiral_out", 700, RED, GOLD, BX, BY, gi="dark"),
           _x("burst", 600, WHITE, RED, LX, LY, gi="flash"),
           step("strobe", 300, WHITE, RED, "center", rate=45, gi="flash"),
           step("fade", 400, RED, "#000000", "center", blend=150)),
    a_show("Angry end",                                    # the multiball over: sparks die out
           step("sparkle", 900, RED, EMBER, "center", gi="dark"),
           step("fade", 1000, EMBER, "#000000", "center")),
]
KIND_SHOWS = (("Rodan start", "Rodan jackpot"), ("Mecha start", "Mecha jackpot"), ("Garuda start", "Garuda jackpot"),
              ("Fire start", "Fire jackpot"), ("Super start", "Super jackpot"))


def angry_now():
    return [award("GODZILLA IS ANGRY!", sub="SHOOT THE BUILDING", seconds=3), sound("angry"), show("Angry")]


def lit_building():
    return light_mode(START_SHOT, RED, "pulse")


RAGE = on_switch(
    if_(AND(eq("ready", 0), lt(BALLS, 2)), [         # not in a multiball, as the C (David: "not counting switch hits")
        change("rage", 1),
        if_(ge("rage", NEED), [
            change("level", 1), set_("rage", 0),
            if_(ge("level", 5), [
                set_("ready", 1), lit_building(),
                if_(ge(BALLS, 2), [set_("owed", 1)], angry_now())],
                [if_(lt(BALLS, 2), [award("RAGE", value=div(mul(DONE, 100), TOTAL_RAGE), sub="PERCENT", seconds=pack.NOTE_S),
                                    sound("rage"), show("Rage level")])])],
            # a quarter of a stretch: how far it is (not in a multiball: it counts quietly)
            [if_(AND(lt(BALLS, 2), ne(div(mul(var("rage"), 4), NEED), div(mul(sub(var("rage"), 1), 4), NEED))), [
                award("GODZILLA RAGE", value=sub(TOTAL_RAGE, DONE), sub="MORE TO GODZILLA ANGRY", seconds=pack.NOTE_S)])]),
    ]), when="idle")
#: full: lit at the Building again after a start or a new ball, and said once a multiball is over
RAGE_FULL = on_any_shot(
    if_(eq("ready", 1), [
        if_(NOT(LIT), [lit_building()]),
        if_(AND(eq("owed", 1), lt(BALLS, 2)), [set_("owed", 0)] + angry_now()),
    ]), when="idle")


def enter_place():
    """A place begins: its shots lit (their flags 0), the lock at once at ADONOA ISLAND; its clock (PLACE_S: the same
    every time); after a lock the trail's light show (the "made" -1 of a start skips it)."""
    out = [if_(ge("made", 0), [show("Place")]), set_("made", 0), set_("lock lit", 0)] + [set_(f, 1) for _s, f in CHASE]
    for i, (name, shots) in enumerate(PLACES):
        body = [set_(f, 0) for s, f in CHASE if s in shots]
        if not shots:
            body = [set_("lock lit", 1)]
        out.append(if_(eq("place", i), body + [hud_counter(1, var("place"), name), set_time(PLACE_S[i])]))
    out.append(if_(eq("place", 5), [hud_counter(1, var("place"), "BABY"), set_time(PLACE_S[5])]))
    return out + [timer_start("lights", 1)]


def red_lines():
    """The line for the place's red shots still to make: by name once 1 or 2 are left, else how many."""
    out = [if_(eq(TO_GO, n), [hud_line("ANY LIT SHOT: %d TO GO" % n)]) for n in (3, 4, 5)]
    for k in (1, 2):
        for combo in combinations(CHASE, k):
            out.append(if_(AND(eq(TO_GO, k), *[eq(f, 0) for _s, f in combo]),
                           [hud_line(_say_set([s for s, _f in combo]))]))
    return out


def lights_and_line():
    """The inserts, the instruction line and the right counter for where it is now. In the multiball the JACKPOT's
    shot is named on the line and under the JACKPOT counter as it moves (green, chasing); the orange shots light only
    once it has begun (``mult``), so nothing is lit in the second before the balls come out."""
    mb = []
    for c, (s, _w) in enumerate(CODES, 1):
        # the Mecha lane's shot has no light of its own on the playfield: its MECHA LANE insert, by name
        ins = (lambda *a: [light_insert("MECHA LANE", *a)]) if s == ML else (lambda *a: [])
        rate = sub(560, mul(80, var("place")))
        mb.append(if_(eq("baby", c), [light(s, GREEN, "chase", 90), *ins(GREEN, "chase", 90),
                                      hud_line("JACKPOT: SHOOT THE " + _words(s)), hud_counter(2, JP_VALUE, _words(s))],
                      [if_(AND(gt("mult", 0), le("place", c), ge(LAST, c)),
                           [light(s, ORANGE, "blink", rate), *ins(ORANGE, "blink", rate)],
                           [off(s)] + ([off_insert("MECHA LANE")] if s == ML else []))]))
    chase = [if_(eq(f, 0), [light(s, RED, "blink", 500)], [off(s)]) for s, f in CHASE] + [off(ML)]
    lock_n = [hud_counter(3, add(var("place"), 1), "IS LIT", "LOCK")]
    chase += [
        if_(AND(eq("lock lit", 1), OR(eq("place", 0), eq("place", 2), eq("place", 4))),
            [light(GT, WHITE, "hurry"), hud_line("LOCK IS LIT: SHOOT THE GODZILLA TARGET")] + lock_n, [off(GT)]),
        if_(AND(eq("lock lit", 1), OR(eq("place", 1), eq("place", 3))),
            [light(MT, WHITE, "hurry"), hud_line("LOCK IS LIT: SHOOT THE MASER TARGET")] + lock_n, [off(MT)]),
        if_(eq("place", 5), [light(BD, GREEN, "hurry"), hud_line("SHOOT THE BUILDING: BABY IS THERE"),
                             hud_counter(3, var("super"), "AT THE BUILDING", "SUPER")]),
        if_(AND(lt("place", 5), eq("lock lit", 0)), [hud_counter(3, TO_GO, "TO LIGHT LOCK", "SHOTS")] + red_lines()),
    ]
    return [if_(gt("mb", 0), mb, chase)]


def made_shot():
    """One of the place's red shots made (its flag already set): the place's note, saying the lock's shot after
    the last one."""
    out = [score(VALUE), change("jackpot", div(VALUE, 8)), show("Chase shot"), shake(200, "soft")]
    for i, (name, shots) in enumerate(PLACES):
        if shots:
            lock = "NOW THE MASER TARGET" if i in (1, 3) else "NOW THE GODZILLA TARGET"
            out.append(if_(eq("place", i), [
                if_(eq(FLAGS, 5), [award(name, value=VALUE, sub=lock, seconds=pack.NOTE_S)],
                    [award(name, value=VALUE, seconds=pack.NOTE_S)])]))
    return out + [
        change("made", 1), hud_counter(2, var("jackpot")),
        pack.clock_floor(),
        if_(eq(FLAGS, 5), [set_("lock lit", 1), shake(300, "medium")]),
        timer_start("lights", 1)]


def lock_made():
    # the next place ~1 s later (its light show after the lock's; never two shakes at once); the note says its shots
    notes = [if_(eq("place", p), [award("LOCK", value=p + 1, sub=w, seconds=pack.NOTE_S)])
             for p, w in enumerate(NEXT_WORDS)]
    return [score(mul(2, VALUE)), change("jackpot", mul(250000, add(var("place"), 1))), *notes,
            hud_counter(2, var("jackpot")), clip("lock", "behind"), sound("lock"), show("Lock"),
            shake(500, "strong"), change("place", 1), set_("lock lit", 0), timer_start("enter", 1200)]


def start_multiball():
    """The kind the locks earned (BABY found = the 6-ball): its balls, music, clip, call, light show and words. The
    counters say what the shots do: JACKPOTS made, the JACKPOT (what it pays now; its shot under it), MULTIPLIER
    (ORANGE SHOTS +1)."""
    out = []
    for k, d in enumerate(KINDS, 1):
        out.append(if_(eq("place", k), [
            multiball(k + 1, 15), music(d["bed"]), clip(d["clip"], "full"), sound(d["call"]),
            show(KIND_SHOWS[k - 1][0]), hud_title(d["name"]), d["shake"],
            light_insert(d["insert"], d["color"], "chase", 100)]))
    return out + [
        set_("mult", var("place")), set_("baby", var("place")), timer_start("grace", 20000),
        if_(lt("jackpot", 2000000), [set_("jackpot", 2000000)]),
        set_time(STAY),
        hud_counter(1, var("babies"), "THIS MULTIBALL", "JACKPOTS"),
        hud_counter(3, var("mult"), "ORANGE SHOTS +1", "MULTIPLIER"),
        timer_start("lights", 1)]


def jackpot_shot():
    """A shot in the multiball (``hit`` = its number): the kind's green JACKPOT, or one of its other three. Each
    note stays NOTE_S and says the jackpot's shot now (after a jackpot: where it has moved to)."""
    kinds = [if_(eq("place", k), [clip(d["jclip"], "behind"), sound(d["jcall"]), show(KIND_SHOWS[k - 1][1]),
                                  d["jshake"]] +
                 [if_(eq("baby", c), [award(d["jword"], value=JP_VALUE, sub=_now(CODES[c - 1][0]),
                                            seconds=pack.NOTE_S)]) for c in range(k, k + 4)])
             for k, d in enumerate(KINDS, 1)]
    raised = [if_(eq("baby", c), [award("MULTIPLIER", value=var("mult"), sub=_now(s), seconds=pack.NOTE_S)])
              for c, (s, _w) in enumerate(CODES, 1)]
    return [
        if_(eq("hit", var("baby")), [score(JP_VALUE), set_("baby", BACK), *kinds,
                                     set_("mult", var("place")), change("babies", 1), set_time(STAY)],
            [if_(AND(le("place", var("hit")), ge(LAST, var("hit"))), [
                score(mul(500000, var("place"))), if_(lt("mult", add(var("place"), 5)), [change("mult", 1)]),
                *raised, show("Multiplier")])]),
        hud_counter(3, var("mult")), hud_counter(1, var("babies")), timer_start("lights", 1)]


def chase_shot(flag):
    return [if_(AND(eq("mb", 0), lt("place", 5), eq(flag, 0)), [set_(flag, 1), timer_start("made", 1)])]


def mb_shot(shot):
    return [if_(gt("mult", 0), [set_("hit", CODE[shot]), timer_start("jp", 1)])]      # mult: it has begun


def ending():
    """The ending's title, line, clip, call and light show: the kind's TOTAL after a multiball (GODZILLA AND BABY
    after BABY FOUND), the locks the trail keeps after the chase."""
    titles = [if_(eq("place", k), [hud_title(d["title"])]) for k, d in enumerate(KINDS, 1)]
    return [if_(gt("mb", 0), [
        # the meter starts again, twice (three times...) as long; the trail is forgotten
        set_("ready", 0), set_("level", 0), set_("rage", 0), change("plays", 1),
        set_("trail place", 0), set_("trail jackpot", 0), set_("trail super", 0),
        *titles, hud_line("JACKPOTS", value=var("babies")), show("Angry end"),
        if_(eq("mb", 2), [hud_title("GODZILLA AND BABY"), clip("won", "full"), sound("won"),
                          shake_game("big_hit")],
            [clip("lost", "full"), sound("lost", fallback="time_up")])],
        [
        # the chase: a drain keeps the trail for the next start; at ADONOA ISLAND it goes cold
        set_("trail place", var("place")), set_("trail jackpot", mul(var("jackpot"), KEEP)),
        set_("trail super", mul(var("super"), KEEP)),
        hud_line("LOCKS KEPT FOR THE TRAIL", value=var("place")), show("Trail cold"), shake(400, "medium"),
        clip("lost", "full"), sound("lost", fallback="time_up"), lit_building()])]


SCRIPTS = [
    RAGE,
    RAGE_FULL,
    # ---- the chase -----------------------------------------------------------------------------------------------
    on_start(set_("place", var("trail place")), set_("jackpot", var("trail jackpot")),
             set_("super", var("trail super")), if_(eq("super", 0), [set_("super", 5000000)]),
             set_("mb", 0), set_("made", -1),
             clip("intro", "full"), clip("loop", "loop"), show("Angry start"), shake(700, "strong"),
             hud_title("GODZILLA ANGRY!"),
             hud_counter(2, var("jackpot"), "BUILT BY SHOTS"),
             if_(eq("place", 0), [award("GODZILLA ANGRY!", sub="THEY TOOK BABY GODZILLA", seconds=3)],
                 [award("THE TRAIL AGAIN", value=var("place"), sub="LOCKS KEPT", seconds=3)]),
             timer_start("enter", 1)),
    on_timer("enter", *enter_place()),
    on_timer("lights", *lights_and_line()),
    # every switch hit feeds the SUPER, as the C (on the right counter once BABY is the shot)
    on_switch(if_(eq("mb", 0), [change("super", 10000), if_(eq("place", 5), [hud_counter(3, var("super"))])]),
              when="running"),
    on_shot(LR, *chase_shot("lr done"), *mb_shot(LR)),
    on_shot(RR, *chase_shot("rr done"), *mb_shot(RR)),
    on_shot(BL, *chase_shot("bl done"), *mb_shot(BL)),
    on_shot(BD, *chase_shot("bd done"), *mb_shot(BD),
            if_(AND(eq("mb", 0), eq("place", 5)), [               # BABY FOUND: the super, then the six balls
                score(var("super")),
                award("SUPER JACKPOT", value=var("super"), sub="BABY FOUND", seconds=3),
                show("Baby found"), sound("angry"), shake(1000, "hard"), hud_line("GET READY: MULTIBALL"),
                set_("mb", 2), set_time(10), timer_start("mbstart", 2000), timer_start("lights", 1)])),
    on_shot(PC, *chase_shot("pc done"), *mb_shot(PC)),
    on_shot(ML, *mb_shot(ML)),
    on_timer("made", *made_shot()),
    on_shot(GT, if_(AND(eq("mb", 0), eq("lock lit", 1), OR(eq("place", 0), eq("place", 2), eq("place", 4))),
                    [timer_start("lock", 1)]), *mb_shot(GT)),
    on_shot(MT, if_(AND(eq("mb", 0), eq("lock lit", 1), OR(eq("place", 1), eq("place", 3))),
                    [timer_start("lock", 1)]), *mb_shot(MT)),
    on_timer("lock", *lock_made()),
    # the place's clock: with locks they break loose as their multiball; with none it runs out (the trail goes
    # cold). In the multiball the clock counts the JACKPOT's next move. (The chase's lights go out at the break:
    # nothing counts until the balls are out.)
    secs_left(1,
              if_(gt("mb", 0), [set_("baby", ON), set_time(STAY), timer_start("lights", 1)],
                  [if_(gt("place", 0), [
                      set_("mb", 1), set_time(10), award("LOCKS BREAK LOOSE", value=var("place"), sub="LOCKS",
                                                         seconds=pack.NOTE_S),
                      hud_line("GET READY: MULTIBALL"), timer_start("mbstart", 1500), timer_start("lights", 1)])])),
    # ---- the multiball -----------------------------------------------------------------------------------------
    on_timer("mbstart", *start_multiball()),
    on_timer("jp", *jackpot_shot()),
    every(1, if_(AND(gt("mult", 0), eq(timer_left("grace"), 0), lt(BALLS, 2)), [end()])),   # mult: it has begun
    # ---- the end -----------------------------------------------------------------------------------------------
    on_end(*[timer_stop(t) for t in TIMERS], *ending()),
]


PROGRAM = {
    "name": NAME, "seconds": PLACE_S[0], "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "game"} for n in ("rage", "level", "ready", "plays", "owed", "trail place",
                                                     "trail jackpot", "trail super")] +
            [{"name": n, "reset": "mode"} for n in ("place", "mb", "lock lit", "made", "jackpot", "super", "mult",
                                                     "baby", "babies", "hit")] +
            [{"name": f, "reset": "mode"} for _s, f in CHASE],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("LOCK IS LIT: SHOOT THE GODZILLA TARGET",
               counters=[("LOCKS", "ADONOA ISLAND", None), ("JACKPOT", "BUILT BY SHOTS", None),
                         ("LOCK", "IS LIT", None)],
               timer=("ANGRY", "rage"),
               # PAD-658: the RAGE meter in the top-right corner, as the C drew it (PAD-416), shown whenever the HUD
               # is (David: "it should always be shown"): before the mode, beside another mode's HUD, full while it runs
               gauge=dict(kind="bar", count=20, words=["GODZILLA", "RAGE"], full="ANGRY!", meter=True, icon="rage",
                          label="RAGE", value=div(mul(DONE, 100), TOTAL_RAGE))),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "lock", "baby", "jackpot", "super", "won", "lost",
                   "mb2", "mb3", "mb4", "mb5"),
    "sounds": sounds({"rage": 3, "angry": 4, "lock": 3, "baby": 4, "jackpot": 3, "super": 4, "won": 4, "lost": 4,
                      "mb2": 4, "mb3": 4, "mb4": 4, "mb5": 4, "jp2": 3, "jp4": 3, "jp5": 3}),
    "music": "music.wav",
    "beds": beds("mb2", "mb3", "mb4", "mb5", "mb6"),
    "shows": SHOWS,
}

LOST = [
    "The RAGE meter counts every playfield switch hit (PAD-675), 1000 the first time (stretches of 150 to 250), "
    "where the C had 750 (100 to 200); it waits while another mode runs, where the C counted through them.",
    "No points while the mode is not running: the C pays 1,000,000 (+500,000 a stretch) at each RAGE stretch's end; "
    "the blocks' Score only scores while the mode runs, so a stretch is a note, a roar and a light show only.",
    "No ball save: the C gives a 5 s ball save at the start and keeps one running from the first lock, so a drain "
    "with locks sends the locked balls straight into the multiball. In blocks a drain ends the chase; the place, its "
    "locks, the jackpot and the super wait for the next start at the Building (as the C does for a drain with no lock).",
    "No randomness: each multiball's JACKPOT starts on its kind's first shot, moves on to the next of its four as "
    "its clock runs out and back one when it is hit, where the C's BABY jumped to another of four shots at random.",
    "The multiballs are this blocks version's own (Gappa Angry's kinds, PAD-658 round 2): the C has ONE ANGRY "
    "MULTIBALL of the locks + 1 balls, BABY on the ramps, Building and Big loop, x1 to x6.",
    "A blocks mode holds 12 clips: each kind has its own start clip, and RODAN'S NEST, GARUDA and FIRE RODAN replay "
    "it behind the HUD at their jackpots (MECHAGODZILLA has the ray-at-Mechagodzilla clip, the 6-ball the red "
    "spiral ray); the four smaller kinds share the lost clip at their end (the 6-ball after BABY FOUND has won).",
    "The ending's line says JACKPOTS and the count (the C said 2 BABY JACKPOTS  -  5 LOCKS); after the chase it "
    "says LOCKS KEPT FOR THE TRAIL and the count (the C named the place the trail waits at).",
    "The ending's TOTAL is the runtime's (up 3 s, or until 9 s after the end behind a full-screen ending clip): "
    "the C kept it 10 s.",
    "The instruction line names the place's red shots once one or two are left (\"SHOOT THE BIG LOOP AND "
    "BUILDING\") and says ANY LIT SHOT: 4 TO GO while three or more of KYOTO's or MAKUHARI's are, the place under "
    "the LOCKS counter, where the C names them all while they fit (\"OSAKA: BIG LOOP, BUILDING\"); a start on the "
    "trail says THE TRAIL AGAIN with its locks, not the place's name.",
    "The SUPER is on the glass only once BABY is the shot (the right counter counts the place's red shots to the "
    "lock until then): the C showed it all through the chase.",
    "The badge counts the place's clock in the chase and the JACKPOT's next move in the multiball, where the C hides "
    "it in the multiball; a place's clock with locks turns into the multiball with a second left, not at 0.",
    "One display priority, 180, throughout: the C takes 190 (a wizard's) for the multiball.",
    "Its own light shows replace the game's Insert chase and Ember fade that the C played on a Premium/LE (and its "
    "own on a Pro), so every title sees the same shows.",
    "Not on Godzilla Pro 1.15 (the C ran there): that older build names no switch shots (the Mecha lane, a "
    "jackpot shot of four of the five multiballs) and has no shaker steps.",
    "No tilt rule of its own: the C stops the meter after a tilt until the next ball; here the tilted ball's shots "
    "still count.",
    "Another mode of ours ending on the Building does not keep it from starting this one on that same shot (the C "
    "waits 300 ms after another of ours ends).",
    "A start on the trail after a drain costs no meter (the Building stays lit until the multiball is played), as "
    "in the C; only the meter itself grows each time it is spent.",
]

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 107, "titles": ["godzilla_le", "godzilla_pro"],
    "based_on": "godzilla_angry.c",
    "about": ("The C example GODZILLA ANGRY rebuilt in blocks and made Elvira's Gappa Angry: 1000 playfield switch "
              "hits fill the RAGE meter (2000 the second time, 3000 the third) and light the Building; a chase through five "
              "places, each with its red shots and a lock, to BABY at the Building; how many balls are locked picks "
              "the multiball: RODAN'S NEST (2 balls), MECHAGODZILLA (3), GARUDA (4), FIRE RODAN (5) or SUPER "
              "MECHAGODZILLA (6, after BABY FOUND's super jackpot), each with its own clips, music, jackpot shots, "
              "multiplier, light shows and shakes."),
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
#: each place's shots and lock (a second between, for the place's light show)
_PLACE = [_shots(GT), _shots(LR, RR, MT), _shots(BL, BD, GT), _shots(LR, RR, BD, BL, MT),
          _shots(LR, RR, BL, BD, PC, GT)]


def _locks(n):
    out = []
    for p in _PLACE[:n]:
        out += p + ["secs", 2]
    return out


#: 1000 playfield switch hits fill the meter (PAD-675)
_FILL = ["switches", 1000, "secs", 1]
_END = ["secs", 20, "balls", 1, "secs", 8]
NL = chr(10)                            # a shake's line ending there: it was not refused
def _mb(n):
    """After n locks: the place's clock runs out, the kind starts, its shake runs out."""
    return ["secs", PLACE_S[n] + 3]


DESK = [
    ("the rage lights the building", _FILL + ["shot", BD, "secs", 2],
     ["GODZILLA RAGE", "962  -  MORE TO GODZILLA ANGRY", "62  -  MORE TO GODZILLA ANGRY", "15  -  PERCENT", "show Rage level",
      "[GODZILLA ANGRY] lit at Building", "show Angry:", "[GODZILLA ANGRY] START (its lit shot)",
      "Hud_AwardSub: THEY TOOK BABY GODZILLA", "Hud_Line: LOCK IS LIT: SHOOT THE GODZILLA TARGET",
      "Hud_C3_Label: LOCK"]),
    # the jackpot starts at the Godzilla target, moves back to the Mecha lane when hit, then the Right ramp
    ("one lock: rodan's nest, 2 balls",
     _START + _locks(1) + _mb(1) + _shots(GT, LR, ML) + _END,
     ["Hud_Award: LOCKS BREAK LOOSE", "Hud_AwardSub: 1  -  LOCKS", "Hud_Line: GET READY: MULTIBALL",
      "MULTIBALL 2 balls, save 15 s", "Hud_Title: RODAN'S NEST", "own clip mb2", "own sound mb2", "show Rodan start",
      "SHAKE 600 ms at 2", "Hud_Line: JACKPOT: SHOOT THE GODZILLA TARGET", "Hud_C2_Sub: GODZILLA TARGET",
      "Hud_C2_Value: 2.00M", "Hud_C1_Label: JACKPOTS", "Hud_C3_Label: MULTIPLIER", "Hud_C3_Sub: ORANGE SHOTS +1",
      "Hud_Award: RODAN JACKPOT", "Hud_AwardSub: 2,000,000  -  NOW THE MECHA LANE",
      "Hud_Line: JACKPOT: SHOOT THE MECHA LANE", "LAMP MECHA LANE 00ff3c chase", "own sound jp2",
      "show Rodan jackpot", "SHAKE 300 ms at 2" + NL,
      "Hud_Award: MULTIPLIER", "Hud_AwardSub: 2  -  NOW THE MECHA LANE", "Hud_C2_Value: 4.00M",
      "Hud_AwardSub: 4,000,000  -  NOW THE RIGHT RAMP", "Hud_Line: JACKPOT: SHOOT THE RIGHT RAMP",
      "Hud_Title: RODAN'S NEST TOTAL", "Hud_Line: JACKPOTS 2", "END (a block)", "lamps held 0"]),
    ("two locks: mechagodzilla, 3 balls",
     _START + _locks(2) + _mb(2) + _shots(LR, RR, BD) + _END,
     ["MULTIBALL 3 balls, save 15 s", "Hud_Title: MECHAGODZILLA", "own clip mb3", "show Mecha start",
      "Hud_Line: JACKPOT: SHOOT THE LEFT RAMP", "Hud_Award: MECHA JACKPOT", "own clip jackpot", "show Mecha jackpot",
      "Hud_Line: JACKPOT: SHOOT THE BUILDING", "Hud_AwardSub: 3  -  NOW THE BUILDING",
      "Hud_Title: MECHAGODZILLA TOTAL", "Hud_Line: JACKPOTS 2", "END (a block)", "lamps held 0"]),
    ("three locks: garuda, 4 balls",
     _START + _locks(3) + _mb(3) + _shots(RR, ML, BL) + _END,
     ["MULTIBALL 4 balls, save 15 s", "Hud_Title: GARUDA", "own clip mb4", "show Garuda start",
      "Hud_Line: JACKPOT: SHOOT THE RIGHT RAMP", "LAMP MECHA LANE ff5000 blink", "Hud_Award: GARUDA JACKPOT",
      "own sound jp4", "show Garuda jackpot",
      "Hud_Line: JACKPOT: SHOOT THE BIG LOOP", "Hud_AwardSub: 4  -  NOW THE BIG LOOP",
      "Hud_Title: GARUDA TOTAL", "Hud_Line: JACKPOTS 2", "END (a block)", "lamps held 0"]),
    ("four locks: fire rodan, 5 balls",
     _START + _locks(4) + _mb(4) + _shots(ML, BD, MT) + _END,
     ["MULTIBALL 5 balls, save 15 s", "Hud_Title: FIRE RODAN", "own clip mb5", "show Fire start",
      "Hud_Line: JACKPOT: SHOOT THE MECHA LANE", "Hud_Award: FIRE JACKPOT", "own sound jp5", "show Fire jackpot",
      "SHAKE 800 ms at 0" + NL, "Hud_AwardSub: 5  -  NOW THE MASER TARGET", "Hud_Title: FIRE RODAN TOTAL",
      "Hud_Line: JACKPOTS 2", "END (a block)", "lamps held 0"]),
    ("five places then baby and the six-ball",
     _START + _locks(5) + _shots(BD) + ["secs", 4] + _shots(BL, MT, BD, PC) + _END,
     ["Hud_Award: LOCK", "Hud_AwardSub: 1  -  NOW BOTH RAMPS", "Hud_Line: SHOOT BOTH RAMPS", "Hud_Award: YOKKAICHI",
      "Hud_AwardSub: 1,000,000", "Hud_Line: SHOOT THE RIGHT RAMP", "Hud_AwardSub: 1,025,000  -  NOW THE MASER TARGET",
      "Hud_Line: LOCK IS LIT: SHOOT THE MASER TARGET", "Hud_C3_Label: SHOTS", "Hud_C3_Sub: TO LIGHT LOCK",
      "Hud_AwardSub: 2  -  NOW BIG LOOP, BUILDING", "Hud_Line: SHOOT THE BIG LOOP AND BUILDING",
      "Hud_AwardSub: 3  -  NOW 4 LIT SHOTS", "Hud_Line: ANY LIT SHOT: 4 TO GO", "Hud_Line: ANY LIT SHOT: 3 TO GO",
      "Hud_AwardSub: 4  -  NOW 5 LIT SHOTS", "Hud_Line: ANY LIT SHOT: 5 TO GO",
      "Hud_Line: SHOOT THE BUILDING AND CENTER POWERLINE", "Hud_Line: SHOOT THE CENTER POWERLINE",
      "Hud_Award: MAKUHARI", "Hud_AwardSub: 2,500,000", "Hud_AwardSub: 2,600,000  -  NOW THE GODZILLA TARGET",
      "Hud_AwardSub: 5  -  NOW THE BUILDING", "Hud_Line: SHOOT THE BUILDING: BABY IS THERE", "Hud_C3_Label: SUPER",
      "Hud_Award: SUPER JACKPOT", "  -  BABY FOUND", "SHAKE 1000 ms at 0", "show Baby found",
      "MULTIBALL 6 balls, save 15 s", "Hud_Title: SUPER MECHAGODZILLA", "own clip baby", "show Super start", "SHAKE 1000 ms at 0",
      "Hud_Line: JACKPOT: SHOOT THE BUILDING", "Hud_C3_Label: MULTIPLIER", "Hud_C1_Label: JACKPOTS",
      "Hud_AwardSub: 6  -  NOW THE BUILDING", "Hud_AwardSub: 7  -  NOW THE BUILDING", "Hud_Award: BABY JACKPOT",
      "  -  NOW CENTER POWERLINE", "Hud_Line: JACKPOT: SHOOT THE CENTER POWERLINE", "own clip super",
      "show Super jackpot", "SHAKE the game's jackpot" + NL, "own clip won", "Hud_Title: GODZILLA AND BABY",
      "Hud_Line: JACKPOTS 2", "END (a block)", "lamps held 0"]),
    ("a drain keeps the trail", _START + _shots(GT) + ["secs", 2] + _shots(LR, RR, MT) + ["ball_end", "secs", 8]
     + _START + ["secs", 3],
     ["END (ball ended)", "Hud_Line: LOCKS KEPT FOR THE TRAIL 2", "Hud_Award: THE TRAIL AGAIN",
      "Hud_AwardSub: 2  -  LOCKS KEPT", "Hud_Line: SHOOT THE BIG LOOP AND BUILDING", "END lamps held 2"]),
    ("with no lock the trail goes cold", _FILL + ["shot", BD, "secs", PLACE_S[0] + 2] + _shots(BD) + ["secs", 4],
     ["END (time ran out)", "Hud_Title: GODZILLA ANGRY TOTAL", "Hud_Line: LOCKS KEPT FOR THE TRAIL 0",
      # again: the lock lit
      "show Trail cold", "Hud_Line: LOCK IS LIT: SHOOT THE GODZILLA TARGET", "END lamps held 1"]),
    # YOKKAICHI's 40 s has run to about 11 when the Left ramp is made
    ("a lit shot puts the clock back to fifteen", _START + _shots(GT) + ["secs", 30] + _shots(LR) + ["secs", 1],
     ["Hud_Award: YOKKAICHI", "Hud_AwardSub: 1,000,000", "Hud_Timer_Num: 11", "Hud_Timer_Num: 15"]),
    # David: each start costs more. 1000 switch hits light it the first time; after its multiball 1000 are only half
    ("the second time the meter is twice as long",
     _START + _locks(1) + _mb(1) + _END + _FILL + ["shot", BD, "secs", 2] + ["switches", 1000]
     + ["secs", 1, "shot", BD, "secs", 2],
     ["Hud_Title: RODAN'S NEST TOTAL", "1,925  -  MORE TO GODZILLA ANGRY", "125  -  MORE TO GODZILLA ANGRY",
      "[GODZILLA ANGRY] lit at Building", "[GODZILLA ANGRY] START (its lit shot)"]),
]


#: PAD-658: as a Godzilla Pro 1.16 gets it - every shot, lock, place and insert it names is on the Pro too (its
#: fixed shields and missing mechanisms play no part), so the rules are the same
DESK_PRO = [
    ("one lock on the Pro: rodan's nest", _START + _locks(1) + _mb(1) + _shots(GT, LR, ML) + _END,
     ["MULTIBALL 2 balls, save 15 s", "Hud_Title: RODAN'S NEST", "Hud_Line: JACKPOT: SHOOT THE GODZILLA TARGET",
      "Hud_Award: RODAN JACKPOT", "Hud_AwardSub: 2  -  NOW THE MECHA LANE",
      "Hud_Title: RODAN'S NEST TOTAL", "Hud_Line: JACKPOTS 2", "END (a block)", "lamps held 0"]),
    ("five places then baby on the Pro", _START + _locks(5) + _shots(BD) + ["secs", 4] + _shots(BL, MT, BD, PC) + _END,
     ["Hud_Award: SUPER JACKPOT", "MULTIBALL 6 balls, save 15 s", "Hud_Title: SUPER MECHAGODZILLA",
      "Hud_Award: BABY JACKPOT", "Hud_Title: GODZILLA AND BABY", "END (a block)", "lamps held 0"]),
]
