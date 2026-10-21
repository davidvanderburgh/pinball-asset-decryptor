"""MASER BARRAGE (PAD-658): the C example maser_barrage.c rebuilt in blocks, then (round 2) three stages deep.

The Maser cannons fire in sequence (the Maser tanks of the Showa and Heisei films): make the shots in order, each
one quickly after the last, and the multiplier climbs. Wait too long and the chain breaks. Round 2 (David: "multi-stage
like what we did here"): after Lyman Sheats, the multiplier is carried up through three stages, each with its own
shots and rules, a POT built through them is cashed at the right scoop once a stage is done, and failing still pays a
quarter of it.

- START: the Maser target 3 times in one ball (PAD-371: never the skill shot); 6 the second time this game, 9 the
  third (each start costs more). Once a ball per player. It waits out a multiball: the next Maser hit after it starts
  it.
- STAGE 1, OPEN FIRE (the C's chain): LEFT RAMP, then RIGHT RAMP, then the BUILDING; only the next shot counts:
  1,000,000 x the multiplier. After a step the next must come within the window (7 s; 6 s the second time, 5 s the
  third), or the CHAIN BREAKS: back to x1, from the Left ramp again. The third step is a BARRAGE: 5,000,000 x the
  multiplier into the POT, then the multiplier +1 (up to x5), the clock +5 s, the window 1 s shorter (down to 4 s).
  Two barrages and the stage is done.
- STAGE 2, CROSSFIRE: the three powerlines are tanks to put in line, in any order, each within the window of the last
  (1,000,000 x the multiplier each); all three in line, the Maser target FIRES the volley within the window:
  10,000,000 x the multiplier into the pot, the multiplier +1. The window running out breaks the line: the tanks fall
  back and the multiplier drops one. Two volleys.
- STAGE 3, GODZILLA IN THE SIGHTS: the Big loop takes aim; the Godzilla target then fires within the window (+3 s):
  a DIRECT HIT, 4,000,000 + 250,000 a second left of the window, times the multiplier, into the pot. A miss: he
  moves, aim again. Three direct hits drive Godzilla back: the pot twice over (its own music for this stage).
- CASH OUT: after stage 1 or 2 (or in stage 3) the right scoop chases white: it pays the pot and ends it. The clock
  (40 s, then 40 s and 30 s for the next stages; a step with under 10 s left puts it back to 10 s, PAD-371) or a drain
  pays a quarter of the pot.
- INSERTS: stage 1 the C's (the next shot bright Maser blue, faster as the window closes; the other two dim); stage 2
  the tanks still to place chase blue, the placed ones white, the Maser target blinks white once they are in line;
  stage 3 the Big loop chases blue, then the Godzilla target blinks red, faster as the window closes.
"""
from blk import (AND, OR, SECS_LEFT, a_show, add, add_time, award, callout, change, clip, clips, div, end, eq, every,
                 ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_insert, lt, mul, music, off,
                 off_insert, on_end, on_shot, on_start, on_timer, score, secs_left, set_, set_time, shake, shake_game,
                 show, sound, sounds, start, step, sub, timer_left, timer_start, timer_stop, var, hits, beds)
import pack

SLUG, NAME = "maser_barrage", "MASER BARRAGE"
BLUE, DIM, WHITE, RED = "#005aff", "#001e5a", "#ffffff", "#ff0000"   # the kit's KIT_BLUE, KIT_BLUE_DIM
MASER_BLUE, MASER_ICE, FIRE = "#0078ff", "#8cdcff", "#ff6000"
MASER_XY = (51, 417)                       # the port's lamp place: MASER
GODZILLA_XY = (89, 260)                    # MAGNA GRAB, the Godzilla target's insert
START_SHOT, AIM, TARGET = "Maser target", "Big loop", "Godzilla target"
STEPS = (("Left ramp", "LEFT RAMP"), ("Right ramp", "RIGHT RAMP"), ("Building", "BUILDING"))
TANKS = (("tank l", "Powerline left"), ("tank c", "Powerline center"), ("tank r", "Powerline right"))
TIMERS = ("window", "lights", "next", "tank")
WINDOW_LEFT = timer_left("window")
WINDOW_SECS = div(add(WINDOW_LEFT, 999), 1000)
NEED = pack.need(3, "fired")               # Maser target hits: 3, then 6, then 9


def pot_up(points):
    return [change("pot", points)]


SHOWS = [
    # the C's own three (it ran them where the card has no "Insert chase" / "Colour fade"), now run for its moments
    a_show("Maser start",
           step("strobe", 450, WHITE, MASER_BLUE, "xy", rate=55, gi="flash", x=MASER_XY[0], y=MASER_XY[1]),
           step("spin", 1600, MASER_ICE, "#000000", "xy", rate=110, gi="dark", x=MASER_XY[0], y=MASER_XY[1]),
           step("sweep_lr", 500, WHITE, MASER_BLUE, "center", gi="dark"),
           step("sweep_rl", 500, WHITE, MASER_BLUE, "center", gi="dark"),
           step("fade", 400, MASER_BLUE, "#000000", "center")),
    a_show("Maser won",
           step("implode", 800, WHITE, MASER_BLUE, "center", gi="dark"),                  # every beam on one spot
           step("strobe", 600, WHITE, "#000000", "center", rate=50, gi="flash"),
           step("chase", 1400, MASER_ICE, MASER_BLUE, "center", rate=45),
           step("rainbow", 1500, "#000000", "#000000", "center", rate=55),
           step("fade", 500, MASER_BLUE, "#000000", "center", blend=250)),
    a_show("Maser lost",
           step("sparkle", 700, RED, MASER_BLUE, "center", gi="dark"),                    # the tanks burning
           step("sweep_down", 900, MASER_BLUE, "#000000", "center", gi="dark"),
           step("fade", 500, MASER_BLUE, "#000000", "center")),
    # round 2: one for every moment
    a_show("Barrage",
           step("sweep_up", 350, MASER_ICE, MASER_BLUE, "center", gi="dark"),
           step("burst", 600, WHITE, MASER_BLUE, "xy", gi="flash", x=123, y=202),        # the beams meet at the Building
           step("fade", 300, MASER_BLUE, "#000000", "center")),
    a_show("Chain broken",
           step("bounce", 700, RED, "#200000", "center", gi="dark"),
           step("fade", 400, RED, "#000000", "center", blend=100)),
    a_show("Crossfire",
           step("fade_in", 500, MASER_BLUE, "#000000", "top", gi="dark"),
           step("sweep_lr", 450, WHITE, MASER_BLUE, "top", gi="dark"),
           step("sweep_rl", 450, WHITE, MASER_BLUE, "top", gi="dark"),
           step("ripple", 1200, MASER_ICE, "#001030", "top", rate=350, gi="dark"),
           step("fade", 400, MASER_BLUE, "#000000", "center", blend=150)),
    a_show("Volley",
           step("strobe", 300, WHITE, MASER_ICE, "xy", rate=45, gi="flash", x=MASER_XY[0], y=MASER_XY[1]),
           step("spiral_out", 900, WHITE, MASER_BLUE, "xy", gi="dark", x=MASER_XY[0], y=MASER_XY[1]),
           step("fade", 400, MASER_BLUE, "#000000", "center")),
    a_show("Final barrage",
           step("solid", 400, MASER_BLUE, "#000000", "center", gi="dark"),
           step("spiral_in", 1200, MASER_ICE, MASER_BLUE, "xy", gi="dark", x=GODZILLA_XY[0], y=GODZILLA_XY[1]),
           step("bolts", 900, WHITE, MASER_BLUE, "center", rate=110, gi="flash"),
           step("fade", 500, MASER_BLUE, "#000000", "center", blend=200)),
    a_show("Direct hit",
           step("burst", 500, WHITE, FIRE, "xy", gi="flash", x=GODZILLA_XY[0], y=GODZILLA_XY[1]),
           step("fire", 900, "#ffc000", FIRE, "xy", gi="dark", x=GODZILLA_XY[0], y=GODZILLA_XY[1]),
           step("fade", 400, FIRE, "#000000", "center")),
    a_show("Withdraw",
           step("solid", 500, WHITE, "#000000", "right", gi="dark"),
           step("sweep_rl", 900, WHITE, MASER_BLUE, "center", gi="dark"),
           step("fade", 900, MASER_BLUE, "#000000", "center", blend=400)),
]


def jackpot_sub():
    """The MULTIPLIER counter's words: what a barrage pays now."""
    out = [hud_counter(1, var("mult"), "JACKPOT 25M")]
    for m in (4, 3, 2, 1):
        out = [if_(eq("mult", m), [hud_counter(1, var("mult"), "JACKPOT %dM" % (5 * m))], out)]
    return out


def mult_up():
    return [if_(lt("mult", 5), [change("mult", 1)]), if_(gt("mult", var("best")), [set_("best", var("mult"))])]


def chain_step(i):
    """Stage 1, step ``i`` of the sequence, made in turn: its points, the window, the clock topped up."""
    shot, says = STEPS[i]
    body = [score(mul(1000000, var("mult"))),
            if_(lt(SECS_LEFT, 10), [set_time(10)])]                  # PAD-371
    if i < 2:
        body += [set_("step", i + 1), timer_start("window", var("window")),
                 award("%s X" % says, value=var("mult"), sub="NOW THE %s" % STEPS[i + 1][1], seconds=1),
                 hud_counter(3, WINDOW_SECS, "SECONDS")]
    else:
        nxt = [award("BARRAGE JACKPOT", value=mul(5000000, var("mult")), sub="NOW X5", seconds=3)]
        for m in (3, 2, 1):
            nxt = [if_(eq("mult", m), [award("BARRAGE JACKPOT", value=mul(5000000, var("mult")),
                                             sub="NOW X%d" % (m + 1), seconds=3)], nxt)]
        body += [*pot_up(mul(5000000, var("mult"))), change("barrages", 1), set_("maser won", 1), *nxt,
                 *mult_up(), if_(gt("window", 4000), [change("window", -1000)]),
                 add_time(5), set_("step", 0), timer_stop("window"),
                 sound("barrage"), clip("barrage", "behind"), show("Barrage"), shake(500, "hard"),
                 *jackpot_sub(), hud_counter(3, 0, "NO CLOCK YET"),
                 if_(ge("barrages", 2), [timer_start("next", 700)])]
    return on_shot(shot, if_(AND(eq("stage", 1), eq("step", i)), body + [timer_start("lights", 1)]))


def tank(i):
    """Stage 2: a powerline puts its tank in line (any order, each within the window of the last)."""
    v, shot = TANKS[i]
    return on_shot(shot, if_(AND(eq("stage", 2), eq(v, 0)), [set_(v, 1), timer_start("tank", 1)]))


TANK_PLACED = on_timer("tank",
    change("step", 1), score(mul(1000000, var("mult"))), if_(lt(SECS_LEFT, 10), [set_time(10)]),
    timer_start("window", var("window")), hud_counter(3, WINDOW_SECS, "SECONDS"),
    if_(ge("step", 3), [award("TANKS IN LINE", sub="FIRE: THE MASER TARGET", seconds=2), sound("aim")],
        [award("TANK IN POSITION", value=var("step"), sub="OF 3", seconds=1)]),
    timer_start("lights", 1))


def hurry_pace():
    """The blink of the shot the window is running for: faster as it closes."""
    return [set_("pace", 500),
            if_(gt(WINDOW_LEFT, 0), [
                if_(le(mul(WINDOW_LEFT, 10), mul(var("window"), 6)), [set_("pace", 250)]),
                if_(le(mul(WINDOW_LEFT, 10), mul(var("window"), 3)), [set_("pace", 100)])])]


SCRIPTS = [
    # ---- the start: the Maser target three times in one ball (six the second time, nine the third) -------------------
    on_shot(START_SHOT, if_(eq("ran ball", 0), [
        if_(ge(hits(START_SHOT), NEED), [start()], [
            award("MASER TARGET", value=sub(NEED, hits(START_SHOT)), sub="MORE TO FIRE", seconds=2)]),
    ]), when="idle"),
    on_start(set_("ran ball", 1), change("fired", 1), set_("maser played", 1),
             set_("stage", 1), set_("pot", 0), set_("cashed", 0), set_("won", 0), set_("step", 0),
             set_("barrages", 0), set_("volleys", 0), set_("aimed", 0),
             set_("mult", 1), set_("best", 1),
             # harder each time: the window 7 s, then 6 s, then 5 s (never under 4 s)
             set_("base window", sub(8000, mul(1000, var("fired")))),
             if_(lt("base window", 4000), [set_("base window", 4000)]), set_("window", var("base window")),
             clip("intro", "full"), clip("loop", "loop"), show("Maser start"), shake(600, "strong"),
             award(NAME, sub="LEFT RAMP  >  RIGHT RAMP  >  BUILDING", seconds=3),
             hud_counter(1, 1, "JACKPOT 5M"), hud_counter(3, 0, "NO CLOCK YET"),
             timer_start("lights", 1)),

    # ---- stage 1: open fire (the C's chain) -----------------------------------------------------------------------
    chain_step(0), chain_step(1), chain_step(2),
    on_timer("window",
             change("breaks", 1), set_("step", 0),
             if_(eq("stage", 1), [
                 set_("mult", 1), set_("window", var("base window")),
                 award("CHAIN BROKEN", sub="BACK TO X1 - START AT THE LEFT RAMP", seconds=2),
                 clip("broken", "behind"), hud_counter(1, 1, "JACKPOT 5M")]),
             if_(eq("stage", 2), [
                 *[set_(v, 0) for v, _s in TANKS], if_(gt("mult", 1), [change("mult", -1)]),
                 award("CROSSFIRE BROKEN", sub="THE TANKS FALL BACK", seconds=2), clip("broken", "behind")]),
             if_(eq("stage", 3), [
                 set_("aimed", 0), award("GODZILLA MOVES", sub="AIM AGAIN: THE BIG LOOP", seconds=2)]),
             sound("broken"), show("Chain broken"),
             hud_counter(3, 0, "NO CLOCK YET"), timer_start("lights", 1)),
    every(1, timer_start("lights", 1)),

    # ---- stage 2: crossfire --------------------------------------------------------------------------------------------
    tank(0), tank(1), tank(2), TANK_PLACED,
    on_shot(START_SHOT, if_(AND(eq("stage", 2), ge("step", 3)), [
        timer_stop("window"), *pot_up(mul(10000000, var("mult"))), score(2000000),
        change("volleys", 1), change("barrages", 1), set_("step", 0), *[set_(v, 0) for v, _s in TANKS],
        award("MASER VOLLEY", value=mul(10000000, var("mult")), sub="INTO THE POT", seconds=3),
        *mult_up(), clip("volley", "behind"), sound("volley"), show("Volley"), shake(600, "hard"),
        hud_counter(3, 0, "NO CLOCK YET"),
        if_(ge("volleys", 2), [timer_start("next", 700)]), timer_start("lights", 1)])),

    # ---- stage 3: Godzilla in the sights --------------------------------------------------------------------------------
    on_shot(AIM, if_(AND(eq("stage", 3), eq("aimed", 0), eq("won", 0)), [
        set_("aimed", 1), timer_start("window", add(var("window"), 3000)), score(mul(500000, var("mult"))),
        award("IN THE SIGHTS", sub="FIRE: THE GODZILLA TARGET", seconds=2), sound("aim"),
        hud_counter(3, WINDOW_SECS, "SECONDS"),
        timer_start("lights", 1)])),
    on_shot(TARGET, if_(AND(eq("stage", 3), eq("aimed", 1)), [
        set_("hit value", mul(var("mult"), add(4000000, mul(250, WINDOW_LEFT)))), timer_stop("window"),
        set_("aimed", 0), change("step", 1), change("barrages", 1), *pot_up(var("hit value")),
        clip("direct", "behind"), sound("direct"), show("Direct hit"),
        if_(ge("step", 3), [
            set_("won", 1), score(mul(var("pot"), 2)),
            award("GODZILLA RETREATS", value=mul(var("pot"), 2), sub="THE POT TWICE OVER", seconds=4),
            clip("won", "full"), show("Maser won"), shake_game("multiball_start"),
             timer_start("next", 3000)],
            [award("DIRECT HIT", value=var("hit value"), sub="INTO THE POT", seconds=2), shake(700, "hard")]),
        hud_counter(3, 0, "NO CLOCK YET"), timer_start("lights", 1)])),

    # ---- the playfield, every second and after every shot ---------------------------------------------------------------
    on_timer("lights", *hurry_pace(),
             if_(eq("stage", 1),
                 [if_(eq("step", i), [light(shot, BLUE, "blink", var("pace")), hud_line("SHOOT THE %s" % says)],
                      [light(shot, DIM, "pulse", 1600)]) for i, (shot, says) in enumerate(STEPS)],
                 [off(shot) for shot, _says in STEPS]),
             if_(eq("stage", 2), [
                 *[if_(eq(v, 0), [light(s, BLUE, "chase", 110)], [light(s, WHITE, "solid")]) for v, s in TANKS],
                 if_(ge("step", 3), [light(START_SHOT, WHITE, "blink", var("pace")),
                                     light_insert("MASER READY", WHITE, "blink", var("pace")),
                                     hud_line("FIRE: SHOOT THE MASER TARGET")],
                     [off(START_SHOT), off_insert("MASER READY"), hud_line("CROSSFIRE: SHOOT THE POWERLINES")])],
                 [off(s) for _v, s in TANKS] + [off(START_SHOT), off_insert("MASER READY")]),
             if_(eq("stage", 3), [
                 if_(eq("aimed", 0), [light(AIM, BLUE, "chase", 100), off(TARGET), hud_line("AIM: SHOOT THE BIG LOOP")],
                     [off(AIM), light(TARGET, RED, "blink", var("pace")), hud_line("FIRE: THE GODZILLA TARGET")])])),

    # ---- a stage done: on to the next, or cash out -------------------------------------------------------------------
    on_timer("next", if_(OR(eq("cashed", 1), eq("won", 1)), [end()], [
        change("stage", 1), timer_stop("window"), set_("step", 0), shake_game("jackpot"), *pack.cash_out_lit(),
        hud_counter(1, var("mult"), "MAX X5"), hud_counter(3, 0, "NO CLOCK YET"),
        if_(eq("stage", 2), [set_time(40), award("CROSSFIRE", sub="PUT THE TANKS IN LINE", seconds=3),
                             clip("crossfire", "behind"), show("Crossfire")],
            [set_time(30), award("THE FINAL BARRAGE", sub="AIM AT THE BIG LOOP, THEN FIRE", seconds=3),
             clip("final", "behind"), sound("aim"), show("Final barrage"), music("final")]),
        timer_start("lights", 1)])),
    on_shot(pack.CASH_SHOT, if_(AND(ge("stage", 2), eq("won", 0), eq("cashed", 0)), [
        set_("cashed", 1), timer_stop("window"), score(var("pot")),
        award("CASHED OUT", value=var("pot"), sub="THE TANKS WITHDRAW", seconds=4),
        clip("cashout", "full"), sound("cashout"), show("Withdraw"), shake(400, "medium"), timer_start("next", 1500)])),
    secs_left(10, callout("ten_seconds"), if_(ge("stage", 2), [light(pack.CASH_SHOT, pack.WHITE, "hurry")])),

    # ---- the end ------------------------------------------------------------------------------------------------------
    on_end(*[timer_stop(t) for t in TIMERS],
           if_(AND(eq("won", 0), eq(SECS_LEFT, 0)), [callout("time_up")]),
           if_(eq("won", 1), [hud_title("GODZILLA RETREATS")]),
           if_(eq("cashed", 1), [hud_title("THE TANKS WITHDRAW")]),
           # under the title: the barrages and the best multiplier (the number can only come last)
           *[if_(eq("best", m), [hud_line("BEST X%d  -  BARRAGES" % m, value=var("barrages"))]) for m in range(1, 6)],
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               score(div(var("pot"), 4)), clip("lost", "full"), show("Maser lost")])),
]

PROGRAM = {
    "name": NAME, "seconds": 40, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": "ran ball", "reset": "ball"}, {"name": "fired", "reset": "game"}] +
            [{"name": n, "reset": "game", "shared": True} for n in ("maser played", "maser won")] +
            [{"name": n, "reset": "mode"} for n in ("step", "mult", "best", "window", "base window", "barrages",
                                                    "breaks", "pace", "stage", "pot", "cashed", "won", "volleys",
                                                    "aimed", "hit value")] +
            [{"name": v, "reset": "mode"} for v, _s in TANKS],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("LEFT RAMP  >  RIGHT RAMP  >  BUILDING",
               counters=[("MULTIPLIER", "MAX X5", var("mult")), ("POT", "CASH AT SCOOP", var("pot")),
                         ("WINDOW", "SECONDS", div(add(WINDOW_LEFT, 999), 1000))],
               timer=("MASER", "maser"),
               gauge={"label": "CHAIN", "kind": "diamond", "count": 3, "color": "#008cff", "value": var("step")}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "barrage", "broken", "won", "lost", "crossfire", "volley", "final", "direct",
                   "cashout"),
    "sounds": sounds({"barrage": 4, "broken": 3, "volley": 4, "aim": 3, "direct": 4, "cashout": 4}),
    "music": "music.wav",
    "beds": beds("final"),
    "shows": SHOWS,
    "scripts": None,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 103, "titles": ["godzilla_le", "godzilla_pro"],
    "based_on": "maser_barrage.c",
    "about": ("The C example MASER BARRAGE rebuilt in blocks, three stages deep: the Maser target 3 times in a ball "
              "starts it (6 the second time, 9 the third). OPEN FIRE is the C's chain (Left ramp, Right ramp, "
              "Building, each within the window; a barrage pays 5M x the multiplier into the pot, up to x5); "
              "CROSSFIRE puts the three powerline tanks in line and fires the Maser target (10M x); GODZILLA IN THE "
              "SIGHTS aims at the Big loop and fires at the Godzilla target, three direct hits for the pot twice "
              "over. Cash the pot at the right scoop after any stage; failing pays a quarter."),
    "lost": [
        "The start counts every Maser target hit this ball, with no 250 ms debounce, and the chain's shots have none "
        "either: a ball rattling in the Left ramp's entrance can count twice (the C counted one a quarter second).",
        "The next shot's blink quickens once a second as its window closes (the C every tick), and the HUD shows the "
        "multiplier as 2 where the C showed X2, and the window as 0 with NO CLOCK YET where it showed -.",
        "Awards say their numbers under the words: LEFT RAMP X over 2  -  NOW THE RIGHT RAMP, where the C said "
        "LEFT RAMP X2 over 2,000,000.",
        "The ending's line under the title puts the count last (BEST X3  -  BARRAGES 2) where the C said "
        "2 BARRAGES  -  BEST X3, and says BARRAGES for one too; it counts every jackpot of the three stages.",
        "The ending stays up 3 s, the runtime's: the C kept it 10 s.",
        "The counters are MULTIPLIER, POT, WINDOW; the C drew MULTIPLIER, WINDOW, BARRAGES (a barrage now pays into "
        "the pot, where the C scored it at once).",
        "The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).",
        "Godzilla Premium/LE and Pro 1.16 only (a Pro 1.15 has no switch shots): the C also ran on a Pro 1.15. It "
        "played the game's Insert chase at the start and Colour fade at the end, with its own shows where the game "
        "had none; the blocks run its own shows (Maser start, Maser won, Maser lost and seven more) on every title "
        "instead.",
        "The blocks pack keeps its own FINAL WARS ledger in shared variables ('maser played', 'maser won'), which "
        "the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not read "
        "the C's ledger.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


_M = ["shot", START_SHOT, "ms", 300]
MASER3 = _M * 3 + ["secs", 1]
_START = ["trigger", "maser_barrage.start", "secs", 1]
_CHAIN = ["shot", "Left ramp", "ms", 400, "shot", "Right ramp", "ms", 400, "shot", "Building", "ms", 400]
_STAGE1 = _CHAIN * 2 + ["secs", 1]
_LINE = ["shot", "Powerline left", "ms", 400, "shot", "Powerline right", "ms", 400, "shot", "Powerline center",
         "ms", 400]
_STAGE2 = (_LINE + ["shot", START_SHOT, "ms", 500]) * 2 + ["secs", 1]
_SHOT3 = ["shot", AIM, "secs", 2, "shot", TARGET, "secs", 2]
#: the desk scenarios (make_examples.py --desk): what, the harness's commands, lines its output must hold
DESK = [
    ("three Maser hits start it", _M * 2 + ["shot", START_SHOT, "secs", 5],
     ["Hud_Title: MASER TARGET", "Hud_Line: 2  -  MORE TO FIRE", "Hud_Line: 1  -  MORE TO FIRE",
      "[MASER BARRAGE] START (a block)", "Hud_Line: SHOOT THE LEFT RAMP", "LAMP LEFT RAMP 005aff blink 500",
      "LAMP RIGHT RAMP 001e5a pulse 1600", "Hud_C1_Sub: JACKPOT 5M"]),
    # the next ball: three hits do not start it again this game, six do
    ("three hits the first time, six the second", MASER3 + ["trigger", "maser_barrage.stop", "secs", 4, "ball_end",
                                                            "secs", 2] + _M * 3 + ["secs", 1] + _M * 3 + ["secs", 2],
     ["[MASER BARRAGE] START (a block)", "END (trigger file)", "Hud_Line: 3  -  MORE TO FIRE",
      "Hud_Line: 1  -  MORE TO FIRE"]),
    ("a barrage, then the chain breaks", MASER3 +
     ["shot", "Right ramp", "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Building",
      "secs", 1, "shot", "Left ramp", "secs", 7, "shot", "Left ramp", "secs", 1],
     ["SCORE +1000000", "Hud_Award: BARRAGE JACKPOT", "Hud_AwardSub: 5,000,000  -  NOW X2", "Hud_C1_Sub: JACKPOT 10M",
      "SCORE +2000000", "Hud_Award: CHAIN BROKEN", "Hud_C2_Value: 5", "Hud_Line: SHOOT THE RIGHT RAMP"]),
    ("open fire, then cash out", _START + _STAGE1 + ["secs", 4, "shot", "Right scoop", "secs", 5],
     ["Hud_Award: CROSSFIRE", "Hud_Line: CROSSFIRE: SHOOT THE POWERLINES", "LAMP POWERLINE LEFT 005aff chase 110",
      "LAMP SELECT CITY ffffff chase", "Hud_Award: CASHED OUT", "SCORE +15000000", "Hud_Title: THE TANKS WITHDRAW",
      "END (a block)", "lamps held 0"]),
    ("all three stages", _START + _STAGE1 + _STAGE2 + ["secs", 3] + _SHOT3 * 3 + ["secs", 6],
     ["Hud_Award: TANK IN POSITION", "Hud_Award: TANKS IN LINE", "LAMP MASER READY ffffff blink",
      "Hud_Award: MASER VOLLEY", "Hud_AwardSub: 30,000,000  -  INTO THE POT", "Hud_Award: THE FINAL BARRAGE",
      "Hud_Line: AIM: SHOOT THE BIG LOOP", "LAMP MAGNA GRAB ff0000 blink", "Hud_Award: DIRECT HIT",
      "Hud_Award: GODZILLA RETREATS", "Hud_Title: GODZILLA RETREATS", "Hud_C1_Value: 5",
      "END (a block)", "lamps held 0"]),
    ("crossfire breaks, Godzilla moves", _START + _STAGE1 + ["shot", "Powerline left", "secs", 8,
                                                             "shot", "Powerline center", "secs", 2] + _STAGE2 +
     ["shot", AIM, "secs", 12],
     ["Hud_Award: CROSSFIRE BROKEN", "Hud_C1_Value: 2", "Hud_Award: GODZILLA MOVES"]),
    ("the clock pays a quarter", _START + _STAGE1 + ["secs", 45],
     ["END (time ran out)", "CALLOUT 1295", "Hud_Line: BEST X3  -  BARRAGES 2",
      "lamps held 0"]),
    ("a drain ends it", _START + ["shot", "Left ramp", "secs", 1, "ball_end", "secs", 8],
     ["SCORE +1000000", "END (ball ended): 1 scores, total 1000000", "lamps held 0"]),
]

#: the Pro (Godzilla Pro 1.16) has every shot and insert it names (MASER READY too): the same rules, played there
DESK_PRO = [
    ("three Maser hits start it", _M * 2 + ["shot", START_SHOT, "secs", 5],
     ["[MASER BARRAGE] START (a block)", "LAMP LEFT RAMP 005aff blink 500"]),
    ("all three stages", _START + _STAGE1 + _STAGE2 + ["secs", 3] + _SHOT3 * 3 + ["secs", 6],
     ["Hud_Award: MASER VOLLEY", "LAMP MASER READY ffffff blink", "LAMP MAGNA GRAB ff0000 blink",
      "Hud_Title: GODZILLA RETREATS", "lamps held 0"]),
]
