"""MINILLA (PAD-658): Godzilla's son grows up, deeper and deeper, or cash out.

Son of Godzilla (1967): Minilla hatches, tries to breathe fire and blows smoke rings until his father stomps on his
tail and a real ray comes out; All Monsters Attack (1969): he stands up to the bully Gabara and beats him; at the
end of Son of Godzilla the two hug in the falling snow. On the playfield he sits beside Mechagodzilla, at the top of
the Mecha lane.

After Lyman Sheats: a start that costs more each time (Metallica's Sparky), stages with their own rules and shots,
a hurry-up (EHoH's), a boss that heals when left alone (KING GHIDORAH's heads), a multiball finale whose jackpots
pay the history back (Batman '66's supers), a pot to cash out or risk, and failing still pays a quarter.

- UP THE LANE: shots up the Mecha lane to its top; 6 light it there (12 the second time, 18 the third; PAD-675: the
  plunge, which passes the top of the lane, is not one), and the next
  one wakes him (PAD-658: the Godzilla target is MELTDOWN's to count, so no two modes share a start). Every shot
  says how many are left (TOP OF THE MECHA, 2 MORE TO WAKE MINILLA).
- STAGE 1, SMOKE RINGS: the ramps, the Big loop and the Building glow cyan; each one is a ring, bigger than the last:
  1M, 2M, 4M, 8M to the pot (twice that from his second time). The line names the ones left (SHOOT THE RAMPS, BIG
  LOOP OR BUILDING; then SHOOT THE BIG LOOP OR BUILDING...). 45 s (STAGE_S + 5).
- STAGE 2, TAIL STOMP: the Godzilla target stomps his tail, then a 20 s hurry-up (WINDOW_S) at the Building from 25M
  (1M a second down to 5M): his first ray, into the pot. Missed, it sputters for 5M. The line: TAIL STOMP: SHOOT
  THE GODZILLA TARGET, then FIRST RAY: SHOOT THE BUILDING. 45 s.
- STAGE 3, GABARA: the bully moves between the Left ramp, the Big loop and the Right ramp every 10 s (a moving target
  stays 10 s at least), the line moving with him (GABARA: SHOOT THE BIG LOOP); each hit 4M to the pot; 5 hits beat
  him (6, 7 the more he has grown), and left alone for 20 s (WINDOW_S) he gets one back. 60 s (STAGE_S + 20: many
  shots at a moving target).
- STAGE 4, FATHER AND SON: a two-ball multiball, 90 s; DAD jackpots at the Godzilla target or the Building, SON
  jackpots at the top of the Mecha lane or the Right ramp, 5M each; a DAD and a SON in a row is a HUG (a quarter of
  the pot): after a DAD the SON shots chase (the DAD ones blink) and the line names them (HUG: TOP OF THE MECHA OR
  RIGHT RAMP), and the other way round; back to one ball, the pot is paid and 20M a hug.
- CASH OUT at the right scoop after stages 1 to 3; the clock or a drain pays a quarter of the pot.
- NOTES (PAD-658 round 3): every one 3 s at least (NOTE_S); each stage is announced by one, and a stage's last note
  stays its NOTE_S before the next stage's; a DAD or SON note names the shots that make the HUG.
"""
import itertools

from blk import (AND, BALLS, a_show, add, award, callout, change, clip, clips, div, end, eq, every, ge,
                 gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_insert, lt, mul, multiball, off,
                 on_any_shot, on_end, on_shot, on_start, on_timer, score, secs_left, set_, set_time, shake, shake_game, show, sound,
                 sounds, step, sub, timer_left, timer_start, timer_stop, var)
import pack

SLUG, NAME = "minilla", "MINILLA"
CYAN, GREEN, BLUE, AMBER, RED, WHITE = "#40e0ff", "#40ff60", "#3080ff", "#ffb000", "#ff2000", "#ffffff"
TOP = "Mecha exit top"
RINGS = (("ring lr", "Left ramp"), ("ring rr", "Right ramp"), ("ring bl", "Big loop"), ("ring b", "Building"))
GABARA = ("Left ramp", "Big loop", "Right ramp")
DADS = ("Godzilla target", "Building")
SONS = (TOP, "Right ramp")
NEED = pack.need(6, "grown")    # the top of the Mecha lane: 6 shots, then 12, then 18 (PAD-675: was 3)
TIMERS = ("ring", "ray", "gabara", "heal", "hit", "next", "dad", "son")
MX, MY = 247, 265               # his art beside Mechagodzilla, top right of the playfield picture
MOVE_S = 10                     # Gabara stays this long at least before he moves on
NOTE_MS = pack.NOTE_S * 1000    # a stage's last note stays this long before the next stage's
#: each stage's clock: a stage of many shots at a moving target has more
CLOCK = {1: pack.STAGE_S + 5, 2: pack.STAGE_S + 5, 3: pack.STAGE_S + 20, 4: 90}


def notes_stay(blocks):
    """``blocks`` with every note in them up to NOTE_S at least (pack.count_up's count note shows 2 s): a local
    helper, so pack.py stays as it is; it does nothing once pack's notes are NOTE_S."""
    for b in blocks:
        if b.get("op") == "hud_award":
            b["seconds"] = max(int(b["seconds"]), pack.NOTE_S)
        elif b.get("op") == "if":
            notes_stay(b["then"])
            notes_stay(b["else"] or [])
    return blocks


def stage_line(n, words):
    return [hud_line(words), hud_counter(1, n, "OF 4")]


def pot_up(points):
    return [change("pot", points), hud_counter(2, var("pot"), "CASH AT SCOOP")]


def shot_words(shots):
    """``shots`` as the line says them (both ramps say RAMPS): RAMPS, BIG LOOP OR BUILDING."""
    words = [pack.SHOT_WORDS[s] for s in shots]
    if "Left ramp" in shots and "Right ramp" in shots:
        words = ["RAMPS"] + [w for w in words if w not in ("LEFT RAMP", "RIGHT RAMP")]
    return words[0] if len(words) == 1 else "%s OR %s" % (", ".join(words[:-1]), words[-1])


def say(shots):
    """The line for shooting ``shots``: SHOOT THE RAMPS, BIG LOOP OR BUILDING (SHOOT alone where THE would take it
    past the 40 letters a line holds)."""
    said = shot_words(shots)
    return ("SHOOT THE " if len(said) <= 30 else "SHOOT ") + said


def ring_line():
    """The line naming the rings still to blow (one to three of the four): one if per set left."""
    out = []
    for n in (1, 2, 3):
        for left in itertools.combinations(range(4), n):
            out.append(if_(AND(*[eq(RINGS[k][0], 1 if k in left else 0) for k in range(4)]),
                           [hud_line(say([RINGS[k][1] for k in left]))]))
    return out


def gabara_lights():
    """The bully's shot blinks red, the line names it: it moves with him."""
    return ([if_(eq("gabara at", i), [light(s, RED, "blink", 120)], [off(s)]) for i, s in enumerate(GABARA, 1)]
            + pack.line_follows("gabara at", GABARA, verb="GABARA: SHOOT THE"))


def family(shots, color, pattern, rate):
    out = [light(s, color, pattern, rate) for s in shots]
    if TOP in shots:
        out.append(light_insert("MECHA LANE", color, pattern, rate))
    return out


def fam_lights():
    """Stage 4: after a DAD the SON shots make the HUG: they chase, the DAD ones blink, the line names them (and the
    other way round); with neither, all four chase."""
    return [if_(eq("dad", 1), family(SONS, GREEN, "chase", 120) + family(DADS, BLUE, "blink", 400)
                + [hud_line("HUG: " + shot_words(SONS))], [
        if_(eq("son", 1), family(DADS, BLUE, "chase", 120) + family(SONS, GREEN, "blink", 400)
            + [hud_line("HUG: " + shot_words(DADS))],
            family(DADS, BLUE, "chase", 120) + family(SONS, GREEN, "chase", 120)
            + [hud_line("ANY LIT SHOT: DAD AND SON MAKE A HUG")])])]


SHOWS = [
    a_show("Hatching",
           step("fade_in", 900, GREEN, "#000000", "xy", gi="dark", x=MX, y=MY),
           step("ripple", 1300, GREEN, "#002010", "xy", rate=450, gi="dark", x=MX, y=MY),
           step("burst", 700, WHITE, GREEN, "xy", gi="flash", x=MX, y=MY),
           step("fade", 500, GREEN, "#000000", "center", blend=200)),
    a_show("Smoke ring",
           step("ripple", 900, WHITE, CYAN, "xy", rate=300, gi="dark", x=MX, y=MY),
           step("fade", 300, CYAN, "#000000", "center")),
    a_show("Stomp",
           step("strobe", 300, WHITE, BLUE, "center", rate=50, gi="flash"),
           step("sweep_down", 500, BLUE, "#000000", "top", gi="dark"),
           step("fade", 300, BLUE, "#000000", "center")),
    a_show("First ray",
           step("spiral_out", 1000, CYAN, "#001020", "xy", gi="dark", x=MX, y=MY),
           step("sweep_rl", 500, WHITE, CYAN, "center", gi="dark"),
           step("burst", 600, WHITE, CYAN, "top", gi="flash"),
           step("fade", 400, CYAN, "#000000", "center", blend=150)),
    a_show("Gabara",
           step("bolts", 800, AMBER, "#201000", "center", rate=120, gi="dark"),
           step("fade", 300, AMBER, "#000000", "center")),
    a_show("Stage up",
           step("strobe", 400, WHITE, GREEN, "center", rate=55, gi="flash"),
           step("spiral_out", 1200, GREEN, "#002010", "center", gi="dark"),
           step("rainbow", 1100, "#000000", "#000000", "center", rate=60),
           step("fade", 500, GREEN, "#000000", "center", blend=200)),
    a_show("Family",
           step("sweep_lr", 400, BLUE, "#000000", "center", gi="dark"),
           step("sweep_rl", 400, GREEN, "#000000", "center", gi="dark"),
           step("burst", 700, WHITE, CYAN, "center", gi="flash"),
           step("fade", 400, CYAN, "#000000", "center")),
    a_show("Snow",
           step("sparkle", 2400, WHITE, "#102040", "center", gi="dark"),
           step("rainbow", 1800, "#000000", "#000000", "center", rate=60),
           step("fade", 900, WHITE, "#000000", "center", blend=400)),
    a_show("Goodbye",
           step("implode", 1200, GREEN, "#000000", "xy", gi="dark", x=MX, y=MY),
           step("fade", 900, GREEN, "#000000", "center", blend=400)),
]


def setup_stage():
    return [
        if_(eq("stage", 2), stage_line(2, "TAIL STOMP: " + pack.shoot("Godzilla target")) + [
            set_time(CLOCK[2]), hud_counter(3, 0, "VALUE", "RAY"), light("Godzilla target", BLUE, "blink", 250),
            award("TAIL STOMP", sub=pack.shoot("Godzilla target"), seconds=pack.NOTE_S)]
            + [off(s) for _v, s in RINGS]),
        if_(eq("stage", 3), [hud_counter(1, 3, "OF 4"),
            set_time(CLOCK[3]), off("Building"), off("Godzilla target"),
            set_("gabara", add(5, sub(var("grown"), 1))), set_("gabara at", 1),
            hud_counter(3, var("gabara"), "HITS TO GO", "GABARA"),
            award("GABARA THE BULLY", value=var("gabara"), sub="HITS TO BEAT HIM", seconds=pack.NOTE_S),
            timer_start("gabara", MOVE_S * 1000), timer_start("heal", pack.WINDOW_S * 1000),
            clip("gabara", "behind"), sound("gabara")] + gabara_lights()),
        if_(eq("stage", 4), [hud_counter(1, 4, "OF 4")] + [
            timer_stop("gabara"), timer_stop("heal"), *[off(s) for s in GABARA], *pack.cash_out_off(),
            set_("mb on", 0), set_("dad", 0), set_("son", 0), hud_counter(3, 0, "FATHER AND SON", "HUGS"),
            hud_counter(2, var("pot"), "PAID AT THE END"),
            multiball(2, 15), set_time(CLOCK[4]),             # the badge shows two digits
            award("FATHER AND SON", sub="MULTIBALL: A DAD AND A SON MAKE A HUG", seconds=pack.NOTE_S),
            clip("mb", "full"), sound("jackpot")] + fam_lights()),
    ]


def dad_or_son(which, other):
    """A DAD (or SON) jackpot in the multiball; after the other one, a HUG. The note names the shots that make the
    HUG next."""
    nxt = SONS if which == "dad" else DADS
    return [if_(AND(eq("stage", 4), eq("mb on", 1)), [
        score(5000000), shake(250, "medium"), pack.clock_floor(),
        if_(eq(other, 1), [
            set_(other, 0), change("hugs", 1), score(div(var("pot"), 4)), hud_counter(3, var("hugs"), "FATHER AND SON"),
            award("FATHER AND SON", value=div(var("pot"), 4), sub="HUG", seconds=pack.NOTE_S), clip("won", "behind"),
            sound("won"), show("Family"), shake_game("jackpot")],
            [set_(which, 1), sound("jackpot" if which == "dad" else "cry"),
             award("DAD JACKPOT" if which == "dad" else "SON JACKPOT",
                   sub="NOW " + shot_words(nxt), seconds=pack.NOTE_S)]),
        *fam_lights()])]


SCRIPTS = [
    # ---- up the lane: lit at the top of the Mecha lane ------------------------------------------------------------
    # PAD-675 (David: "every plunge increments the necessary switch"): a ball plunged passes the top of the Mecha lane
    # on its way in; the first one of a ball is the plunge, not a shot (any other shot of his first means the plunge
    # went elsewhere). "in play" is a ball's: 0 again each ball and each game (the game's ball-start event comes
    # before the blocks see a new game, whose reset would wipe a flag that event set: emulator, ball 1)
    on_shot(TOP, if_(eq("in play", 0), [set_("in play", 1)],
                     notes_stay(pack.count_up("calls", 1, NEED, "ready", "note at", TOP, GREEN, "MECHA LANE",
                                              "MINILLA IS LIT", "SHOOT THE MECHA LANE TO THE TOP",
                                              pack.SHOT_WORDS[TOP], "MORE TO WAKE MINILLA", step=1))), when="idle"),
    on_any_shot(set_("in play", 1), when="any"),
    pack.relight("ready", TOP, GREEN, "MECHA LANE"),

    # ---- he hatches --------------------------------------------------------------------------------------------------
    on_start(*pack.begin(SLUG),
             set_("ready", 0), set_("calls", 0), set_("note at", 0), change("grown", 1),
             set_("stage", 1), set_("pot", 0), set_("rings", 0), set_("won", 0), set_("cashed", 0), set_("hugs", 0),
             set_("ring value", 1000000), if_(ge("grown", 2), [set_("ring value", 2000000)]),
             *[set_(v, 1) for v, _s in RINGS],
             clip("intro", "full"), clip("loop", "loop"), sound("cry"), show("Hatching"), shake(500, "medium"),
             *stage_line(1, say([s for _v, s in RINGS])),
             award("MINILLA HATCHES", sub="SMOKE RINGS: BIGGER EACH TIME", seconds=pack.NOTE_S),
             hud_counter(2, 0, "CASH AT SCOOP"), hud_counter(3, 0, "OF 4", "RINGS"),
             *[light(s, CYAN, "pulse", 900) for _v, s in RINGS]),

    # ---- stage 1: smoke rings ------------------------------------------------------------------------------------------
    on_shot("Left ramp",
            if_(AND(eq("stage", 1), eq("ring lr", 1)), [set_("ring lr", 0), off("Left ramp"), timer_start("ring", 1)]),
            if_(AND(eq("stage", 3), eq("gabara at", 1)), [timer_start("hit", 1)])),
    on_shot("Right ramp",
            if_(AND(eq("stage", 1), eq("ring rr", 1)), [set_("ring rr", 0), off("Right ramp"), timer_start("ring", 1)]),
            if_(AND(eq("stage", 3), eq("gabara at", 3)), [timer_start("hit", 1)]),
            if_(eq("stage", 4), [timer_start("son", 1)])),
    on_shot("Big loop",
            if_(AND(eq("stage", 1), eq("ring bl", 1)), [set_("ring bl", 0), off("Big loop"), timer_start("ring", 1)]),
            if_(AND(eq("stage", 3), eq("gabara at", 2)), [timer_start("hit", 1)])),
    on_shot("Building",
            if_(AND(eq("stage", 1), eq("ring b", 1)), [set_("ring b", 0), off("Building"), timer_start("ring", 1)]),
            if_(AND(eq("stage", 2), gt(timer_left("ray"), 0)), [
                timer_stop("ray"), off("Building"), *pot_up(var("ray value")), score(3000000), pack.clock_floor(),
                award("MINILLA'S FIRST RAY", value=var("ray value"), sub="INTO THE POT", seconds=pack.NOTE_S),
                clip("ray", "behind"), sound("ray"), show("First ray"), shake(500, "hard"),
                timer_start("next", NOTE_MS)]),
            if_(eq("stage", 4), [timer_start("dad", 1)])),
    on_timer("ring",
             change("rings", 1), score(500000), pack.clock_floor(), *pot_up(var("ring value")), hud_counter(3, var("rings"), "OF 4"),
             award("SMOKE RING", value=var("ring value"), sub="BIGGER EACH TIME", seconds=pack.NOTE_S),
             set_("ring value", mul(var("ring value"), 2)),
             show("Smoke ring"), shake(200, "soft"),
             if_(ge("rings", 4), [clip("puff", "behind"), sound("ring"), timer_start("next", NOTE_MS)],
                 [clip("ring", "behind"), sound("ring"), *ring_line()])),

    # ---- stage 2: the tail stomp and his first ray ------------------------------------------------------------------------
    on_shot("Godzilla target",
            if_(AND(eq("stage", 2), eq(timer_left("ray"), 0)), [
                set_("ray value", 25000000), timer_start("ray", pack.WINDOW_S * 1000), score(1000000),
                pack.clock_floor(), off("Godzilla target"), light("Building", CYAN, "hurry"),
                hud_counter(3, var("ray value"), "VALUE"), hud_line("FIRST RAY: " + pack.shoot("Building")),
                award("DAD STOMPS HIS TAIL", sub="NOW THE BUILDING: HIS FIRST RAY", seconds=pack.NOTE_S),
                clip("stomp", "behind"), sound("stomp"), show("Stomp"), shake(400, "hard")]),
            if_(eq("stage", 4), [timer_start("dad", 1)])),
    every(1, if_(AND(eq("stage", 2), gt(timer_left("ray"), 0), gt("ray value", 5000000)), [
        change("ray value", -1000000), hud_counter(3, var("ray value"), "VALUE")])),
    on_timer("ray", if_(eq("stage", 2), [
        *pot_up(5000000), award("IT SPUTTERS", value=5000000, sub="A SMOKE RING AGAIN", seconds=pack.NOTE_S),
        off("Building"), clip("puff", "behind"), sound("ring"), timer_start("next", NOTE_MS)])),

    # ---- stage 3: Gabara ---------------------------------------------------------------------------------------------------
    on_timer("gabara", if_(AND(eq("stage", 3), gt("gabara at", 0)), [
        change("gabara at", 1), if_(gt("gabara at", 3), [set_("gabara at", 1)]), *gabara_lights(),
        timer_start("gabara", MOVE_S * 1000)])),
    on_timer("heal", if_(AND(eq("stage", 3), gt("gabara at", 0)), [
        change("gabara", 1), hud_counter(3, var("gabara"), "HITS TO GO"), sound("gabara"),
        award("GABARA LAUGHS", value=var("gabara"), sub="HITS TO BEAT HIM", seconds=pack.NOTE_S),
        timer_start("heal", pack.WINDOW_S * 1000)])),
    on_timer("hit",
             change("gabara", -1), *pot_up(4000000), score(1500000), pack.clock_floor(), hud_counter(3, var("gabara"), "HITS TO GO"),
             timer_start("heal", pack.WINDOW_S * 1000), clip("gabara_hit", "behind"), show("Gabara"),
             shake(350, "strong"),
             # beaten: he stops, his shot goes dark at once (it counts no more), the note stays before stage 4's
             if_(le(var("gabara"), 0), [
                 set_("gabara at", 0), timer_stop("gabara"), timer_stop("heal"), *[off(s) for s in GABARA],
                 award("GABARA IS BEATEN", value=var("pot"), sub="POT", seconds=pack.NOTE_S), sound("won"),
                 timer_start("next", NOTE_MS)],
                 [award("MINILLA HITS GABARA", value=var("gabara"), sub="TO GO", seconds=pack.NOTE_S), sound("cry")])),

    # ---- stage 4: father and son ----------------------------------------------------------------------------------------------
    on_shot(TOP, if_(eq("stage", 4), [timer_start("son", 1)])),
    on_timer("dad", *dad_or_son("dad", "son")),
    on_timer("son", *dad_or_son("son", "dad")),
    every(1, if_(eq("stage", 4), [
        if_(ge(BALLS, 2), [set_("mb on", 1)]),
        if_(AND(eq("mb on", 1), lt(BALLS, 2)), [
            set_("won", 1), score(add(var("pot"), mul(20000000, var("hugs")))),
            award("FATHER AND SON", value=add(var("pot"), mul(20000000, var("hugs"))), sub="THE POT AND THE HUGS",
                  seconds=4),
            clip("won", "full"), show("Snow"), shake_game("multiball_start"), end()])])),

    # ---- a stage done: on to the next, or cash out -------------------------------------------------------------------------
    on_timer("next", if_(eq("cashed", 1), [end()], [
        change("stage", 1), show("Stage up"), shake_game("jackpot"),
        if_(lt("stage", 4), pack.cash_out_lit()), *setup_stage()])),
    on_shot(pack.CASH_SHOT, if_(AND(ge("stage", 2), lt("stage", 4), eq("won", 0), eq("cashed", 0)), [
        set_("cashed", 1), score(var("pot")), award("CASHED OUT", value=var("pot"), sub="MINILLA WAVES", seconds=4),
        clip("cashout", "full"), show("Goodbye"), timer_start("next", 1500)])),
    secs_left(10, callout("ten_seconds"), if_(lt("stage", 4), [light(pack.CASH_SHOT, pack.WHITE, "hurry")])),

    on_end(*pack.finish(), set_("stage", 0), *[timer_stop(t) for t in TIMERS],
           if_(eq("won", 1), [hud_title("FATHER AND SON"), hud_line("MINILLA HAS GROWN UP")]),
           if_(eq("cashed", 1), [hud_title("MINILLA WAVES GOODBYE"), hud_line("THE POT IS CASHED OUT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [hud_title("MINILLA CRIES"), hud_line("A QUARTER OF THE POT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               score(div(var("pot"), 4)),
               award("MINILLA CRIES", value=div(var("pot"), 4), sub="A QUARTER OF THE POT", seconds=3),
               clip("lost", "full"), sound("lost"), show("Goodbye")])),
]


PROGRAM = {
    "name": NAME, "seconds": CLOCK[1], "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": pack.pack_vars() + [{"name": n, "reset": "game"} for n in ("calls", "ready", "note at", "grown")] + [{"name": "in play", "reset": "ball"}] + [
        {"name": n, "reset": "mode"} for n in ("stage", "pot", "rings", "ring value", "ray value", "gabara",
                                                "gabara at", "mb on", "dad", "son", "hugs", "won", "cashed")] + [
        {"name": v, "reset": "mode"} for v, _s in RINGS],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud(say([s for _v, s in RINGS]),
               counters=[("STAGE", "OF 4", None), ("POT", "CASH AT SCOOP", None), ("RINGS", "OF 4", None)],
               timer=("MINILLA", "ring")),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "ring", "puff", "stomp", "ray", "gabara", "gabara_hit", "mb", "won", "lost",
                   "cashout"),
    "sounds": sounds({"cry": 3, "ring": 3, "stomp": 3, "ray": 4, "gabara": 4, "jackpot": 3, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 3, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "",
    "about": ("New (PAD-658). Shots up the Mecha lane wake him at its top (6, 12, then 18); four stages "
              "(smoke rings, the tail stomp and his first ray, beating the bully Gabara, a father-and-son "
              "two-ball multiball), the line naming the shots each one wants; cash the pot out at the right scoop. "
              "Son of Godzilla (1967) and All Monsters Attack (1969)."),
    "lost": [],
}

_START = ["trigger", "minilla.start", "secs", 1]
#: each stage's last shot, then 4 s: its note stays 3 s before the next stage's
_STAGE1 = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Big loop", "ms", 300,
           "shot", "Building", "secs", 4]
_STAGE2 = ["shot", "Godzilla target", "secs", 3, "shot", "Building", "secs", 4]
_STAGE3 = ["shot", "Left ramp", "ms", 300] * 5 + ["secs", 4]
_STAGE4 = ["balls", 2, "secs", 2, "shot", "Godzilla target", "ms", 400, "shot", "Mecha exit top", "ms", 400,
           "shot", "Building", "ms", 400, "shot", "Right ramp", "ms", 400, "balls", 1, "secs", 2]
_TOP = ["shot", "Mecha exit top", "ms", 400]
DESK = [
    # PAD-675: each ball's first Mecha exit top is its plunge: _TOP * 7 is the plunge and six
    ("the plunge is not a shot", _TOP * 6 + ["secs", 2],
     ["Hud_AwardSub: 5  -  MORE TO WAKE MINILLA", "Hud_AwardSub: 1  -  MORE TO WAKE MINILLA"]),
    ("six shots the first time, twelve the second", _TOP * 7 + ["shot", "Mecha exit top", "secs", 2, "trigger", "minilla.stop",
                                                                "secs", 4] + _TOP * 11 + ["secs", 3] + _TOP + ["secs", 2],
     ["[MINILLA] START (its lit shot)", "END (trigger file)", "Hud_Award: TOP OF THE MECHA",
      "Hud_AwardSub: 1  -  MORE TO WAKE MINILLA", "Hud_Award: MINILLA IS LIT"]),
    ("up the lane lights it", _TOP * 7 + ["shot", "Mecha exit top", "secs", 2],
     ["Hud_Award: MINILLA IS LIT", "[MINILLA] START (its lit shot)", "LAMP MECHA LANE 40ff60 chase",
      "Hud_Award: MINILLA HATCHES", "Hud_Line: SHOOT THE RAMPS, BIG LOOP OR BUILDING"]),
    ("all four stages", _START + _STAGE1 + _STAGE2 + _STAGE3 + _STAGE4 + ["secs", 6],
     ["Hud_Line: SHOOT RIGHT RAMP, BIG LOOP OR BUILDING", "Hud_Line: SHOOT THE BIG LOOP OR BUILDING",
      "Hud_Line: SHOOT THE BUILDING", "Hud_Award: SMOKE RING",
      "Hud_Award: TAIL STOMP", "Hud_Line: TAIL STOMP: SHOOT THE GODZILLA TARGET",
      "Hud_Line: FIRST RAY: SHOOT THE BUILDING", "Hud_Award: MINILLA'S FIRST RAY",
      "Hud_Award: GABARA THE BULLY", "Hud_Line: GABARA: SHOOT THE LEFT RAMP", "Hud_Award: GABARA IS BEATEN",
      "MULTIBALL 2", "Hud_Line: ANY LIT SHOT: DAD AND SON MAKE A HUG", "Hud_Award: DAD JACKPOT",
      "Hud_AwardSub: NOW TOP OF THE MECHA OR RIGHT RAMP", "Hud_Line: HUG: TOP OF THE MECHA OR RIGHT RAMP",
      "  -  HUG", "Hud_C2_Sub: PAID AT THE END",
      "Hud_Title: FATHER AND SON", "Hud_Award: FATHER AND SON", "END (a block)", "lamps held 0"]),
    ("gabara moves and heals when left alone", _START + _STAGE1 + _STAGE2 + ["secs", 22],
     ["Hud_Line: GABARA: SHOOT THE LEFT RAMP", "Hud_Line: GABARA: SHOOT THE BIG LOOP",
      "Hud_Line: GABARA: SHOOT THE RIGHT RAMP", "Hud_Award: GABARA LAUGHS", "Hud_Timer_Num: 60"]),
    ("the ray sputters, then cash out", _START + _STAGE1 + ["shot", "Godzilla target", "secs", 22,
                                                            "shot", "Right scoop", "secs", 5],
     ["Hud_Title: MINILLA WAVES GOODBYE", "Hud_Award: IT SPUTTERS", "SCORE +20000000", "END (a block)", "lamps held 0"]),
]


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)
