"""OXYGEN DESTROYER (PAD-658): the C example oxygen_destroyer.c rebuilt in blocks, then (round 2) taken deeper -
Dr. Serizawa's dive in four stages, a pot cashed out at the right scoop, and the super jackpot at the end.

Godzilla (1954): the hurry-up is the C's own rule (stage 1); then the divers go over the side, find Godzilla by
sonar, lower the device to the sea bed, and Serizawa makes his choice.

- START: Left spinner spins in one ball: 40 the first time, 80 the second, 120 the third (pack.need); up to 3 times a
  game per player, and not again for 15 s after it ends. No spin counts in a multiball (PAD-669); counted out
  while one runs, the next spin after it starts it.
  The note OXYGEN DESTROYER / 20 - LEFT SPINNER SPINS TO GO comes on the first spin, every 5 to go and the last 3
  (1 MORE LEFT SPINNER SPIN), 3 s each (round 3: a note on every spin covered itself).
- EVERY STAGE'S CLOCK is pack.STAGE_S (40 s), on every start (round 3, David: "you can't really accomplish much in 10
  seconds. 40 seconds is better"; the C's 25 s, round 2's 30 s and 15 s are gone). A new stage is named by the
  HUD's title (STAGE 2: THE DIVE ...) and its line names the shot; the note the stage before ended on stays its 3 s
  and says what comes next (NOW THE LEFT SPINNER).
- STAGE 1, THE HURRY-UP (the C's rule over the stage's clock): 20,000,000 falling to 0 over 40 s (500,000 a second;
  the C's 800,000 over 25 s). The line: LEFT RAMP COLLECTS  GODZILLA TARGET +2 S. The LEFT RAMP collects it into the
  POT (and 1M now); the Godzilla target holds it off: each hit puts 2 s back, up to 20,000,000, three hold-offs the
  first time, two the second, one the third (then the line is SHOOT THE LEFT RAMP). The value reaching 0 first is
  THE OXYGEN IS GONE.
- STAGE 2, THE DIVE: the sonar ping moves among the three powerlines and the Big loop every 10 s (MOVE_S: the brief's
  "a moving target stays 10 s at least"; the C's 3 s, 2.3 s, 1.6 s) and when hit; the line follows it (SHOOT THE
  CENTER POWERLINE); hit the ping 3 times: 4M, 8M, 12M to the pot (+2M a contact for each earlier start).
- STAGE 3, THE DESCENT: the Left spinner lowers the device: 20 spins (30, 40 on later starts), each 500,000 to the
  pot; the Left ramp is a shortcut of 5 (the line: SPIN THE LEFT SPINNER (LEFT RAMP: 5)). On the sea bed: 15M more
  (+5M a start).
- STAGE 4, SERIZAWA'S CHOICE (its own march): the RIGHT RAMP (hurrying white) sets it off: the SUPER JACKPOT, the pot
  twice over and 25M (+10M a start). GODZILLA IS GONE: every light goes out, its note stays 3 s, then the end.
- CASH OUT: after any stage the right scoop chases white (the POT counter: AT RIGHT SCOOP): it pays the pot and
  the divers surface. The clock or a drain pays a quarter of it (half in stage 4), never less than 1,000,000.
- The ledger for FINAL WARS: "oxygen played" when it starts, "oxygen won" at the super jackpot.
"""
from blk import (AND, OR, SECS_LEFT, a_show, add, add_time, award, callout, change, clip, clips, div, end, eq,
                 every, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, lt, mul, music, off, on_end,
                 on_shot, on_start, on_timer, score, secs_left, set_, set_time, shake, shake_game, show, sound, sounds,
                 start, step, sub, timer_left, timer_start, timer_stop, var, beds)
import pack

SLUG, NAME = "oxygen_destroyer", "OXYGEN DESTROYER"
GREEN, YELLOW, RED, WHITE = "#00ff3c", "#ffc800", "#ff0000", "#ffffff"    # the kit's colours
OXY_DEEP, OXY_AQUA, SONAR = "#001446", "#3cdcff", "#00ffc8"
# the port's lamp places: MAGNA GRAB (the Godzilla target's insert), the ramps, the Left spinner, the sea bed
MAGNA_XY, LRAMP_XY, RRAMP_XY, LSPIN_XY = (89, 260), (69, 272), (199, 189), (55, 373)
SPIN, HOLD, COLLECT, SUPER_SHOT = "Left spinner", "Godzilla target", "Left ramp", "Right ramp"
PINGS = ("Powerline left", "Powerline center", "Powerline right", "Big loop")
NEED = pack.need(40, "ran game")            # 40 spins, then 80, then 120 (PAD-675: was 25)
SPINS_LEFT = sub(NEED, var("spins"))
#: stage 1's hurry-up runs the stage's clock: 20,000,000 falling to 0 over pack.STAGE_S seconds
OXY_MS = pack.STAGE_S * 1000
#: the value now: 20,000,000 times the share of the oxygen timer left, in tens of thousands (as the C shows and pays it)
VALUE = mul(div(mul(timer_left("oxygen"), 2000), OXY_MS), 10000)
#: the brief's rule 5: a moving target stays 10 s at least before it moves on its own (no pack constant: local)
MOVE_S = 10
#: deeper each start: "ran game" is 1 on the first run (counted up as it starts)
MORE = sub(var("ran game"), 1)
HOLDS = sub(4, var("ran game"))             # hold-offs: 3, 2, 1
CONTACT = mul(add(4000000, mul(2000000, MORE)), var("pings"))
FATHOMS = add(20, mul(10, MORE))
SEA_BED = add(15000000, mul(5000000, MORE))
SUPER = add(mul(var("pot"), 2), add(25000000, mul(10000000, MORE)))
TIMERS = ("oxygen", "cool", "next", "ping", "contact")
SW = pack.SHOT_WORDS


def note(text, value=None, sub="", seconds=pack.NOTE_S):
    """An award that stays pack.NOTE_S seconds at least (the brief's rule 3)."""
    return award(text, value=value, sub=sub, seconds=max(seconds, pack.NOTE_S))


def xy(fx, ms, a, b, p, rate=0, gi="keep", blend=0):
    return step(fx, ms, a, b, "xy", rate=rate, gi=gi, blend=blend, x=p[0], y=p[1])


SHOWS = [
    # the C's own three (its fallback where the card has no "Playfield wave" / "Blue fade"), run now on every title
    a_show("Oxygen start",
           step("sparkle", 900, OXY_AQUA, OXY_DEEP, "center", gi="dark"),                    # the sea bed
           step("sweep_up", 900, WHITE, OXY_DEEP, "center", gi="dark"),                      # bubbles rise
           step("sweep_up", 800, OXY_AQUA, OXY_DEEP, "center", gi="dark"),
           step("pulse", 900, OXY_AQUA, OXY_DEEP, "center", rate=220)),
    a_show("Oxygen won",
           step("strobe", 400, WHITE, "#000000", "center", rate=60, gi="flash"),             # the device fires
           xy("burst", 900, WHITE, OXY_AQUA, RRAMP_XY, gi="dark"),
           step("sparkle", 1200, WHITE, OXY_DEEP, "center", gi="dark"),                      # he dissolves
           step("rainbow", 1200, "#000000", "#000000", "center", rate=70),
           step("fade", 900, OXY_AQUA, "#000000", "center", blend=300)),
    a_show("Oxygen lost",
           step("sweep_down", 900, OXY_AQUA, OXY_DEEP, "center", gi="dark"),                 # the oxygen drains
           step("pulse", 900, RED, "#000000", "center", rate=300, gi="dark"),
           step("fade", 600, OXY_DEEP, "#000000", "center")),
    a_show("Held off",
           xy("implode", 500, WHITE, OXY_AQUA, MAGNA_XY, gi="keep"),
           xy("fade", 300, OXY_AQUA, "#000000", MAGNA_XY)),
    a_show("Collected",
           xy("burst", 600, WHITE, OXY_AQUA, LRAMP_XY, gi="flash"),
           step("sweep_up", 700, OXY_AQUA, OXY_DEEP, "left", gi="dark"),
           step("fade", 400, OXY_AQUA, "#000000", "center")),
    a_show("Deeper",
           step("strobe", 300, WHITE, OXY_AQUA, "center", rate=55, gi="flash"),
           step("spiral_in", 1100, OXY_AQUA, OXY_DEEP, "center", gi="dark"),
           step("sweep_down", 800, WHITE, OXY_DEEP, "center", gi="dark"),
           step("fade", 500, OXY_AQUA, "#000000", "center", blend=200)),
    a_show("Sonar",
           step("ripple", 900, SONAR, OXY_DEEP, "top", rate=300, gi="dark"),
           step("fade", 300, SONAR, "#000000", "top")),
    a_show("Found him",
           step("bolts", 700, WHITE, SONAR, "top", rate=110, gi="flash"),
           step("spiral_out", 900, SONAR, OXY_DEEP, "top", gi="dark"),
           step("fade", 400, SONAR, "#000000", "center")),
    a_show("Sea bed",
           xy("fade_in", 600, OXY_AQUA, "#000000", LSPIN_XY, gi="dark"),
           xy("spin", 1000, WHITE, OXY_AQUA, LSPIN_XY, rate=80, gi="dark"),
           step("sweep_down", 700, OXY_AQUA, OXY_DEEP, "center", gi="dark"),
           step("solid", 500, OXY_DEEP, "#000000", "center", gi="dark"),
           step("fade", 400, OXY_AQUA, "#000000", "center")),
    a_show("The choice",
           step("solid", 700, OXY_DEEP, "#000000", "center", gi="dark"),
           xy("pulse", 1200, WHITE, OXY_DEEP, RRAMP_XY, rate=400, gi="dark"),
           step("bounce", 1000, OXY_AQUA, OXY_DEEP, "center", rate=300, gi="dark"),
           step("fade", 400, OXY_AQUA, "#000000", "center")),
    a_show("Surface",
           step("sweep_up", 700, OXY_AQUA, OXY_DEEP, "flippers", gi="keep"),
           step("sweep_up", 700, WHITE, OXY_AQUA, "flippers", gi="keep"),
           step("burst", 600, WHITE, "#000000", "right", gi="flash"),
           step("fade", 500, WHITE, "#000000", "center", blend=200)),
]


def ping_lights():
    """The sonar ping: its shot chases sea-green fast, the other three dark, and the line names it."""
    return ([if_(eq("ping", i), [light(s, SONAR, "chase", 90)], [off(s)]) for i, s in enumerate(PINGS, 1)]
            + pack.line_follows("ping", PINGS))


def setup_stage():
    """What each stage lights and says as it begins (the "next" timer, once the stage before is done): its title
    names it (the note the stage before ended on keeps the middle its 3 s), its line names the shot."""
    return [
        if_(eq("stage", 2), [
            set_time(pack.STAGE_S), set_("deep", 1), set_("ping", 1), set_("pings", 0),
            hud_title("STAGE 2: THE DIVE"), hud_counter(3, 0, "OF 3", "CONTACTS"),
            clip("dive", "behind"), sound("dive"), *ping_lights(),
            timer_start("ping", MOVE_S * 1000)]),
        if_(eq("stage", 3), [
            set_time(pack.STAGE_S), timer_stop("ping"), *[off(s) for s in PINGS],
            set_("fathoms", FATHOMS), hud_title("STAGE 3: THE DESCENT"),
            hud_line("SPIN THE LEFT SPINNER (LEFT RAMP: 5)"), hud_counter(3, var("fathoms"), "TO GO", "FATHOMS"),
            clip("canister", "behind"), light(SPIN, OXY_AQUA, "chase", 110), light(COLLECT, OXY_AQUA, "pulse", 900)]),
        if_(eq("stage", 4), [
            set_time(pack.STAGE_S), off(SPIN), off(COLLECT), music("finale"),
            hud_title("STAGE 4: SERIZAWA'S CHOICE"), hud_line("THE DEVICE: SHOOT THE RIGHT RAMP"),
            hud_counter(3, SUPER, "RIGHT RAMP", "SUPER"),
            clip("choice", "behind"), light(SUPER_SHOT, WHITE, "hurry")]),
    ]


#: stage 1 while its hurry-up runs (the oxygen timer stopped at the collect reads 0)
HURRYING = AND(eq("stage", 1), gt(timer_left("oxygen"), 0))

SCRIPTS = [
    # ---- the start: 40 spins of the Left spinner (80, 120); a note on the first, every 5 to go and the last 3 --------
    # (PAD-669: no spin counts in a multiball; one counted out but held off starts it on the next spin)
    on_shot(SPIN, if_(AND(lt("ran game", 3), eq("cooling", 0)), [
        if_(ge("spins", NEED), [start()], [if_(pack.ONE_BALL, [
            change("spins", 1),
            if_(ge("spins", NEED), [start()], [
                if_(eq(SPINS_LEFT, 1), [note(NAME, sub="1 MORE LEFT SPINNER SPIN")], [
                    if_(OR(eq("spins", 1), le(SPINS_LEFT, 3), eq(sub(SPINS_LEFT, mul(div(SPINS_LEFT, 5), 5)), 0)),
                        [note(NAME, value=SPINS_LEFT, sub="LEFT SPINNER SPINS TO GO")])])])])]),
    ]), when="idle"),
    on_start(*pack.begin(SLUG), set_("spins", 0), change("ran game", 1), set_("oxygen played", 1),
             set_("stage", 1), set_("pot", 0), set_("holds", 0), set_("won", 0), set_("gone", 0), set_("cashed", 0),
             set_("deep", 0), set_("pings", 0), set_("fathoms", 0),
             timer_start("oxygen", OXY_MS),
             clip("intro", "full"), clip("loop", "loop"), show("Oxygen start"), shake_game("rumble"),
             note(NAME, sub="COLLECT IT AT THE LEFT RAMP"),
             hud_line("LEFT RAMP COLLECTS  GODZILLA TARGET +2 S"), hud_counter(3, HOLDS, "LEFT", "HOLD-OFFS"),
             light(COLLECT, GREEN, "hurry"), light(HOLD, WHITE, "pulse", 1000)),

    # ---- stage 1: the hurry-up ---------------------------------------------------------------------------------------
    # the Left ramp's colour by the value left: green over two thirds, yellow over one, then red
    every(1, if_(HURRYING, [
        if_(gt(mul(VALUE, 3), 40000000), [light(COLLECT, GREEN, "hurry")], [
            if_(gt(mul(VALUE, 3), 20000000), [light(COLLECT, YELLOW, "hurry")], [light(COLLECT, RED, "hurry")])])])),
    on_shot(HOLD, if_(AND(HURRYING, lt("holds", HOLDS)), [
        change("holds", 1),
        set_("t", add(timer_left("oxygen"), 2000)), if_(gt("t", OXY_MS), [set_("t", OXY_MS)]),
        timer_start("oxygen", var("t")), set_time(div(add(var("t"), 999), 1000)),
        note("HELD OFF", sub="+2 SECONDS  -  NOW THE LEFT RAMP"), hud_counter(3, sub(HOLDS, var("holds")), "LEFT"),
        show("Held off"), shake(250, "soft"),
        if_(ge("holds", HOLDS), [off(HOLD), hud_line("SHOOT THE LEFT RAMP")]),
    ])),
    on_shot(COLLECT,
            if_(AND(eq("stage", 1), gt(VALUE, 0)), [
                set_("t", VALUE), change("pot", var("t")), score(1000000), timer_stop("oxygen"),
                off(COLLECT), off(HOLD), hud_counter(2, var("pot"), "AT RIGHT SCOOP", "POT"),
                note("COLLECTED", value=var("t"), sub="INTO THE POT"),
                sound("collect"), clip("collect", "behind"), show("Collected"), shake(400, "strong"),
                timer_start("next", 700)]),
            if_(AND(eq("stage", 3), gt("fathoms", 0)), [change("fathoms", -4), timer_start("contact", 1)])),
    on_timer("oxygen", if_(eq("stage", 1), [set_("gone", 1), end()])),

    # ---- stage 2: the dive, by sonar (the ping moves on every MOVE_S seconds, the line with it) ----------------------
    on_timer("ping", if_(eq("stage", 2), [
        change("ping", 1), if_(gt("ping", 4), [set_("ping", 1)]), *ping_lights(), show("Sonar"),
        timer_start("ping", MOVE_S * 1000)])),
    *[on_shot(s, if_(AND(eq("stage", 2), eq("ping", i), lt("pings", 3)), [timer_start("contact", 1)]))
      for i, s in enumerate(PINGS, 1)],

    # ---- stage 2's contact and stage 3's fathoms (one "subroutine") --------------------------------------------------
    on_timer("contact",
             if_(eq("stage", 2), [
                 change("pings", 1), change("pot", CONTACT), score(1000000), pack.clock_floor(),
                 hud_counter(3, var("pings"), "OF 3"), shake(300, "medium"),
                 if_(ge("pings", 3), [
                     timer_stop("ping"), *[off(s) for s in PINGS], clip("found", "behind"), sound("found"),
                     show("Found him"), note("GODZILLA FOUND", value=var("pot"), sub="NOW THE LEFT SPINNER"),
                     timer_start("next", 700)],
                     [clip("deep", "behind"), show("Sonar"),
                      change("ping", 1), if_(gt("ping", 4), [set_("ping", 1)]), *ping_lights(),
                      *[if_(eq("ping", i), [note("SONAR CONTACT", sub="NOW THE " + SW[s])])
                        for i, s in enumerate(PINGS, 1)],
                      timer_start("ping", MOVE_S * 1000)])]),
             if_(eq("stage", 3), [
                 change("fathoms", -1), change("pot", 500000), score(100000),
                 if_(le("fathoms", 0), [
                     hud_counter(3, 0, "TO GO"), change("pot", SEA_BED), off(SPIN), off(COLLECT),
                     note("ON THE SEA BED", value=var("pot"), sub="NOW THE RIGHT RAMP"), show("Sea bed"),
                     shake(500, "strong"), timer_start("next", 700)],
                     [hud_counter(3, var("fathoms"), "TO GO")])])),

    # ---- stage 3: the descent ----------------------------------------------------------------------------------------
    on_shot(SPIN, if_(AND(eq("stage", 3), gt("fathoms", 0)), [timer_start("contact", 1)])),

    # ---- stage 4: Serizawa's choice (every light out, its note up 3 s, then the end) ----------------------------------
    on_shot(SUPER_SHOT, if_(AND(eq("stage", 4), eq("won", 0), eq("cashed", 0)), [
        set_("won", 1), set_("oxygen won", 1), score(SUPER), off("*"),
        note("SUPER JACKPOT", value=SUPER, sub="GODZILLA IS GONE", seconds=4),
        sound("won"), clip("collect", "behind"), show("Oxygen won"), shake(1000, "hard"),
        timer_start("next", pack.NOTE_S * 1000)])),
    secs_left(10, if_(AND(eq("won", 0), eq("cashed", 0)), [
        callout("ten_seconds"), if_(ge("stage", 2), [light(pack.CASH_SHOT, pack.WHITE, "hurry")])])),

    # ---- a stage done: on to the next, or cash out ------------------------------------------------------------------
    on_timer("next", if_(OR(eq("cashed", 1), eq("won", 1)), [end()], [
        change("stage", 1), if_(lt("stage", 4), [show("Deeper")], [show("The choice")]), shake_game("jackpot"),
        *pack.cash_out_lit(), *setup_stage()])),
    on_shot(pack.CASH_SHOT, if_(AND(ge("stage", 2), eq("won", 0), eq("cashed", 0)), [
        set_("cashed", 1), score(var("pot")),
        note("CASHED OUT", value=var("pot"), sub="THE DIVERS SURFACE", seconds=4),
        clip("surface", "full"), sound("surface"), show("Surface"), shake(500, "medium"), timer_start("next", 1500)])),

    # ---- the end, and 15 s before the spins count again ---------------------------------------------------------------
    on_end(*pack.finish(), *[timer_stop(t) for t in TIMERS if t != "cool"],
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               set_("t", div(var("pot"), 4)), if_(ge("stage", 4), [set_("t", div(var("pot"), 2))]),
               if_(lt("t", 1000000), [set_("t", 1000000)]), score(var("t")),
               if_(OR(eq("gone", 1), eq(SECS_LEFT, 0)), [sound("lost", fallback="time_up")]),
               clip("lost", "full"), show("Oxygen lost"), shake(600, "medium"),
               if_(eq("stage", 1), [hud_title("THE OXYGEN IS GONE"), hud_line("A BREATH OF AIR"),
                                    note("THE OXYGEN IS GONE", value=var("t"), sub="A BREATH OF AIR", seconds=3)],
                   [hud_title("GODZILLA ESCAPES"),
                    if_(ge("stage", 4), [hud_line("HALF THE POT")], [hud_line("A QUARTER OF THE POT")]),
                    note("GODZILLA ESCAPES", value=var("t"), sub="FOR THE DIVE", seconds=3)])]),
           if_(eq("won", 1), [clip("won", "full"), hud_title("GODZILLA IS GONE"), hud_line("THE SUPER JACKPOT")]),
           if_(eq("cashed", 1), [hud_title("THE DIVERS SURFACE"), hud_line("THE POT IS CASHED OUT")]),
           set_("stage", 0), set_("cooling", 1), timer_start("cool", 15000)),
    on_timer("cool", set_("cooling", 0)),
]

PROGRAM = {
    "name": NAME, "seconds": pack.STAGE_S, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "ball"} for n in ("spins", "cooling")] +
            [{"name": "ran game", "reset": "game"}] +
            [{"name": n, "reset": "game", "shared": True} for n in ("oxygen played", "oxygen won")] +
            [{"name": n, "reset": "mode"} for n in ("stage", "pot", "holds", "won", "gone", "t", "cashed", "deep",
                                                    "ping", "pings", "fathoms")],
    "timers": [{"name": n} for n in TIMERS],
    # the middle counter follows the value while it falls (the oxygen timer stopped reads 0), then the pot
    "hud": hud("LEFT RAMP COLLECTS  GODZILLA TARGET +2 S",
               counters=[("STAGE", "OF 4", var("stage")), ("HURRY-UP", "LEFT RAMP", add(VALUE, var("pot"))),
                         ("HOLD-OFFS", "LEFT", None)],
               timer=("OXYGEN", "oxygen"),
               # the oxygen in stage 1, then the divers' air: the stage's clock, a pip for each tenth of it
               gauge={"label": "OXYGEN", "kind": "segment", "count": 10, "color": "#00aaff",
                      "value": add(div(add(timer_left("oxygen"), OXY_MS // 10 - 1), OXY_MS // 10),
                                   mul(var("deep"), div(add(SECS_LEFT, pack.STAGE_S // 10 - 1),
                                                        pack.STAGE_S // 10)))}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "collect", "won", "lost", "dive", "deep", "found", "canister", "choice",
                   "surface"),
    "sounds": sounds({"collect": 3, "won": 4, "lost": 4, "dive": 4, "surface": 3, "found": 4}),
    "music": "music.wav",
    "beds": beds("finale"),
    "shows": SHOWS,
    "scripts": None,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 102, "titles": ["godzilla_le", "godzilla_pro"],
    "based_on": "oxygen_destroyer.c",
    # every shot, show and insert it names is on a Pro 1.16 too (its own shows, not the game's): nothing to swap
    "title_alt": {"godzilla_pro": {}},
    "about": ("The C example OXYGEN DESTROYER rebuilt in blocks and taken deeper (PAD-658): 40 Left spinner spins "
              "start it (80 the second time, 120 the third). Four stages of 40 s each: the C's hurry-up (20,000,000 "
              "draining over the stage, the Left ramp collects it into the pot, the Godzilla target holds it off), "
              "the dive (hit the moving sonar ping 3 times: the line names its target), the descent (spin the Left "
              "spinner 20 times to lower the device), and Serizawa's choice (the Right ramp: the pot twice over and "
              "25M). Cash the pot out at the right scoop after any stage; the clock or a drain pays a quarter of "
              "it."),
    "lost": [
        "Every stage has 40 s on every start (PAD-658's round 3: time to do it): the C's hurry-up drained "
        "20,000,000 over 25 s (800,000 a second), and round 2 gave the dive and the descent 30 s and Serizawa's "
        "choice 15 s; the sonar ping moved every 3 s (2.3 s, 1.6 s on later starts), now every 10 s.",
        "A new stage is named by the HUD's title (STAGE 2: THE DIVE ...), not by a note over the one the stage "
        "before ended on (COLLECTED, GODZILLA FOUND, ON THE SEA BED): that note stays its 3 s.",
        "The value falls on a timer the blocks keep in milliseconds, but the clock the HUD badge shows is whole "
        "seconds: a hold-off puts the clock to the next whole second above the value's time (the C counted both "
        "from one drain, and a stalled frame drained at most 100 ms).",
        "The Godzilla target has no 250 ms debounce: a ball rattling on the captive ball can use up two hold-offs "
        "(the C counted one hit a quarter second); a spinner's spins count each one, as the C's did.",
        "The Left ramp blinks faster as the mode's clock runs down (the blocks' Hurry pattern) and changes colour "
        "once a second; the C's blink followed the value itself, every tick, with a flicker in the last 3 s.",
        "No random numbers in blocks: the sonar ping moves in turn (Powerline left, center, right, the Big loop).",
        "The middle counter is the HURRY-UP, then the POT; the C showed a COLLECTED counter beside the super "
        "jackpot. Its gauge is one blue, where the C's ten segments went from deep to pale blue, and the spins' "
        "note says OXYGEN DESTROYER over 20  -  LEFT SPINNER SPINS TO GO on the first spin, every 5 to go and the "
        "last 3, where the C said 24 SPINS TO GO on every spin.",
        "The ending title (GODZILLA IS GONE, THE DIVERS SURFACE, GODZILLA ESCAPES or THE OXYGEN IS GONE) and its "
        "total stay up 3 s, the runtime's: the C kept them 10 s, with OXYGEN DESTROYER TOTAL under the total.",
        "The cooldown is 15 s on a timer that a new ball clears (the C kept each player's own across balls), and "
        "a start from the tab's Start mode now counts toward the 3 a game.",
        "The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).",
        "It plays its own light shows (Oxygen start, Oxygen won, Oxygen lost: the C's fallback shows) on every "
        "title, where the C played the game's Playfield wave and Blue fade when the game had them.",
        "The blocks pack keeps its own FINAL WARS ledger in shared variables ('oxygen played', 'oxygen won'), "
        "which the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not "
        "read the C's ledger.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _spins(n):
    out = []
    for _i in range(n):
        out += ["shot", SPIN, "ms", 60]
    return out


_START = ["trigger", "oxygen_destroyer.start", "secs", 1]
_GT = ["shot", HOLD, "ms", 300]
_S1 = ["shot", COLLECT, "secs", 2]
_S2 = ["shot", "Powerline left", "ms", 400, "shot", "Powerline center", "ms", 400, "shot", "Powerline right",
       "secs", 2]
_S3 = _spins(20) + ["secs", 2]
#: the desk scenarios (make_examples.py --desk): what, the harness's commands, lines its output must hold
DESK = [
    # PAD-669: a multiball's spins count for nothing: back to one ball, 5 more say 35 to go, no start
    ("no spin counts in a multiball", ["balls", 2] + _spins(40) + ["balls", 1, "secs", 1] + _spins(5) + ["secs", 2],
     ["Hud_AwardSub: 35  -  LEFT SPINNER SPINS TO GO", "![OXYGEN DESTROYER] START (a block)"]),
    ("40 spins start it, 80 the second time",
     _GT * 3 + ["secs", 3] + _spins(39) + ["secs", 1] + _spins(1) + ["secs", 5, "trigger", "oxygen_destroyer.stop",
                                                                    "secs", 17] + _spins(40) + ["secs", 2],
     ["Hud_Award: OXYGEN DESTROYER", "Hud_AwardSub: 39  -  LEFT SPINNER SPINS TO GO",
      "Hud_AwardSub: 20  -  LEFT SPINNER SPINS TO GO", "Hud_AwardSub: 2  -  LEFT SPINNER SPINS TO GO",
      "Hud_AwardSub: 1 MORE LEFT SPINNER SPIN", "[OXYGEN DESTROYER] START (a block)",
      "Hud_Line: LEFT RAMP COLLECTS  GODZILLA TARGET +2 S", "Hud_C2_Value: 20.0M", "LAMP LEFT RAMP 00ff3c blink",
      "LAMP MAGNA GRAB ffffff pulse 1000", "END (trigger file)", "Hud_AwardSub: 40  -  LEFT SPINNER SPINS TO GO"]),
    ("held off, collected, then cash out", _START + ["secs", 4] + _GT + ["secs", 2] + _S1 + ["secs", 3, "shot", "Right scoop",
                                                                                          "secs", 5],
     ["Hud_Award: HELD OFF", "Hud_AwardSub: +2 SECONDS  -  NOW THE LEFT RAMP", "Hud_C3_Value: 2",
      "Hud_Award: COLLECTED", "Hud_AwardSub: 17,270,000  -  INTO THE POT", "Hud_Title: STAGE 2: THE DIVE",
      "Hud_Line: SHOOT THE LEFT POWERLINE", "Hud_C2_Label: POT", "Hud_C2_Sub: AT RIGHT SCOOP",
      "LAMP SELECT CITY ffffff chase", "Hud_Title: THE DIVERS SURFACE", "SCORE +17270000",
      "END (a block): 2 scores, total 18270000", "lamps held 0"]),
    ("all four stages and the super jackpot", _START + _S1 + _S2 + _S3 + ["shot", SUPER_SHOT, "secs", 5],
     ["Hud_Award: SONAR CONTACT", "Hud_AwardSub: NOW THE CENTER POWERLINE", "Hud_Line: SHOOT THE RIGHT POWERLINE",
      "Hud_Award: GODZILLA FOUND", "Hud_Title: STAGE 3: THE DESCENT", "Hud_Line: SPIN THE LEFT SPINNER (LEFT RAMP: 5)",
      "Hud_C3_Label: FATHOMS", "Hud_Award: ON THE SEA BED", "Hud_Title: STAGE 4: SERIZAWA'S CHOICE",
      "Hud_Line: THE DEVICE: SHOOT THE RIGHT RAMP", "own clip choice", "Hud_Award: SUPER JACKPOT",
      "Hud_Title: GODZILLA IS GONE", "own clip won", "lamps held 0"]),
    ("the sonar ping moves", _START + _S1 + ["secs", 9.5, "lamps"],
     ["LAMP POWERLINE LEFT 00ffc8 chase 90", "LAMP POWERLINE CENTER 00ffc8 chase 90", "own clip dive",
      "Hud_Line: SHOOT THE CENTER POWERLINE"]),
    ("the value runs out", _START + ["secs", 42] + _spins(4) + ["secs", 1],
     ["LAMP LEFT RAMP ffc800 blink", "LAMP LEFT RAMP ff0000 blink", "CALLOUT 1291", "SCORE +1000000",
      "Hud_Title: THE OXYGEN IS GONE", "lamps held 0"]),
    ("the super missed pays half", _START + _S1 + _S2 + _S3 + ["secs", 42],
     ["Hud_Line: THE DEVICE: SHOOT THE RIGHT RAMP", "LAMP RIGHT RAMP ffffff blink", "END (time ran out)",
      "Hud_Title: GODZILLA ESCAPES", "Hud_Line: HALF THE POT", "lamps held 0"]),
    ("a drain pays a quarter", _START + _S1 + ["secs", 2, "ball_end", "secs", 8],
     ["END (ball ended): 2 scores, total 5862500", "BALL END HOLD", "lamps held 0"]),
]
#: the same mode as a Godzilla Pro 1.16 gets it (nothing differs: the scenarios prove it builds and plays there)
DESK_PRO = [
    ("40 spins start it on the Pro", _spins(40) + ["secs", 2] + _S1,
     ["[OXYGEN DESTROYER] START (a block)", "Hud_Award: COLLECTED", "Hud_Line: SHOOT THE LEFT POWERLINE"]),
    ("all four stages on the Pro", _START + _S1 + _S2 + _S3 + ["shot", SUPER_SHOT, "secs", 5],
     ["Hud_Award: GODZILLA FOUND", "Hud_Award: ON THE SEA BED", "Hud_Title: GODZILLA IS GONE", "lamps held 0"]),
]
