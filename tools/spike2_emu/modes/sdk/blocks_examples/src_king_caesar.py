"""KING CAESAR (PAD-658): the guardian of Okinawa, woken by the prayer, deeper and deeper or cash out.

Godzilla vs. Mechagodzilla (1974): the Azumi priestess sings and the shrine's stone lion cracks open; King Caesar
catches Mechagodzilla's beams in his eyes and fires them back; he and Godzilla fight side by side until
Mechagodzilla's head comes off. On the playfield he stands beside the pop bumper, at the foot of the Mecha lane.

After Lyman Sheats: a meter that costs more each time (Metallica's Sparky), stages with their own rules and shots
(EHoH's House stages), a pot you may cash out or put at risk to go deeper (Metallica's Crank It Up, Batman '66's
cash the super or take +1x), and failing still pays (a quarter of the pot).

- THE PRAYER: every Pop bumper sings 1, the Right return lane 2, the Mecha lane (Mecha exit bottom) 3; 40 lights
  the Mecha lane (80 the second time he wakes, 120 the third). A multiball's count too. Every 5 a note: HIT THE
  POP BUMPERS, n TO WAKE KING CAESAR.
- STAGE 1, AWAKENING: the Pop bumper, the Right ramp and the Mecha lane each crack the shrine once (3M to the pot
  each; 4.5M from the second time he wakes).
- STAGE 2, REFLECT: Mechagodzilla's beam moves across the Left ramp, Big loop, Right ramp and Building, a shot every
  pack.WINDOW_S (20 s; PAD-658 round 3: it moved every 3.6 s, 2.6 s, then 1.9 s the more he had woken, too fast to
  read); the beam's shot ABSORBS it (up to 3 charges), the Mecha lane fires them back: 5M a charge to the pot.
  Three reflections. The Mecha lane is lit (chasing) only once a charge is in; the beam's shot goes dark while 3 are.
- STAGE 3, TAG TEAM: the Godzilla target opens a pack.WINDOW_S window (it was 6 s) in which the Pop bumper or the
  Mecha lane is a combo: 8M, 16M, 24M to the pot. Three combos.
- STAGE 4, THE FINAL BLOW: three Building hits tear Mechagodzilla's head off: the pot twice over and 25M.
- CASH OUT: after any stage the right scoop chases white: it pays the pot and he goes back to sleep. The clock or a
  drain pays a quarter of it.
- THE CLOCK (PAD-658 round 3): pack.STAGE_S and more for the longer stages: 45 s for AWAKENING and THE FINAL BLOW,
  55 for REFLECT (six shots round a beam that moves every 20 s), 50 for TAG TEAM (six shots); it was 45 s each.
- SAY THE SHOT (PAD-658 round 3, David: "the shots are not explicit enough"): the title names the stage (KING
  CAESAR: REFLECT), the line the shot by the playfield's names, as it moves ("POP BUMPERS, RIGHT RAMP AND MECHA
  LANE", "SHOOT THE MECHA LANE", "ABSORB THE BEAM: SHOOT THE BIG LOOP", "FIRE IT BACK: SHOOT THE MECHA LANE",
  "COMBO: HIT POP BUMPERS OR MECHA LANE"); every note stays pack.NOTE_S and says the next shot.
"""
from itertools import combinations

import blk
from blk import (BALLS, TOTAL, a_show, add, add_time, callout, change, clip, clips, div, end, eq, ge, gt,
                 hud, hud_counter, hud_line, hud_title, if_, light, light_insert, light_mode, lt, mul, off, off_insert,
                 on_drain, on_end, on_shot, on_start, on_timer, score, secs_left, set_, set_time, shake, shake_game,
                 show, sound, sounds, step, sub, timer_left, timer_start, timer_stop, AND, var)
import pack

SLUG, NAME = "king_caesar", "KING CAESAR"
GOLD, RUBY, BLUE, RED = "#ffb000", "#ff2010", "#3080ff", "#ff0000"
LANE = "Mecha exit bottom"
START_INSERTS = "MECHA LANE,POP BUMPER"
BEAM = ("Left ramp", "Big loop", "Right ramp", "Building")
KC_X, KC_Y = 262, 405
#: the prayer it takes: 25, and 15 more each time he has woken
NEED = pack.need(40, "woken")   # the prayer: 40, then 80, then 120 (PAD-690: was 50; PAD-675: was 25)
#: each stage's clock and title
STAGE_SECS = {1: pack.STAGE_S + 5, 2: pack.STAGE_S + 15, 3: pack.STAGE_S + 10, 4: pack.STAGE_S + 5}
TITLES = {1: "KING CAESAR: AWAKENING", 2: "KING CAESAR: REFLECT", 3: "KING CAESAR: TAG TEAM",
          4: "KING CAESAR: THE FINAL BLOW"}
#: stage 1's three shots and the flag each one's crack is kept in
CRACKS = (("crack pop", "Pop bumper"), ("crack ramp", "Right ramp"), ("crack lane", LANE))
POT_SUB = "POT: CASH AT RIGHT SCOOP"        # a stage done: on to the next, or cash out
TIMERS = ("crack", "beam", "absorb", "say", "combo", "caesar", "next")


def award(text, value=None, sub="", seconds=pack.NOTE_S):
    """blk's award, on the glass NOTE_S at least (PAD-658 round 3: notes stay)."""
    return blk.award(text, value=value, sub=sub, seconds=max(seconds, pack.NOTE_S))


def _words(shot):
    return pack.SHOT_WORDS[shot]


def _say_set(shots):
    """The line naming one or two of AWAKENING's shots still to crack (the pop bumpers are hit, not shot)."""
    w = [_words(s) for s in shots]
    verb = "HIT THE" if "Pop bumper" in shots else "SHOOT THE"
    return "%s %s" % (verb, " AND ".join(w))


def _now_set(shots):
    w = [_words(s) for s in shots]
    return "NOW THE " + w[0] if len(w) == 1 else "NOW " + " AND ".join(w)


def stage_line(n, words=None):
    return [hud_title(TITLES[n])] + ([hud_line(words)] if words else []) + [hud_counter(1, n, "OF 4")]


def pot_up(points):
    return [change("pot", points), hud_counter(2, var("pot"), "CASH AT SCOOP")]


def crack_left():
    """After a crack: the line and the note name the shots still to crack."""
    out = []
    for k in (1, 2):
        for combo in combinations(CRACKS, k):
            shots = [s for _f, s in combo]
            out.append(if_(AND(eq("cracks", 3 - k), *[eq(f, 0) for f, _s in combo]), [
                hud_line(_say_set(shots)), award("THE SHRINE CRACKS", sub=_now_set(shots))]))
    return out


def reflect_lights():
    """Stage 2: the beam's shot lit (red) while it can absorb (under 3 charges); the Mecha lane lit (chasing: it pays
    most) only with a charge to fire; the line names the shot to make now. The third reflection puts them out."""
    return [if_(eq("stage", 2), [if_(lt("reflects", 3), [
        *[if_(AND(eq("beam", i), lt("charge", 3)), [light(shot, RED, "blink", 250)], [off(shot)])
          for i, shot in enumerate(BEAM, 1)],
        if_(gt("charge", 0), [light(LANE, GOLD, "chase", 120), light_insert("MECHA LANE", GOLD, "chase", 120),
                              hud_line("FIRE IT BACK: SHOOT THE MECHA LANE")],
            [off(LANE), off_insert("MECHA LANE"),
             *pack.line_follows("beam", BEAM, verb="ABSORB THE BEAM: SHOOT THE")])],
        [off(s) for s in BEAM] + [off(LANE), off_insert("MECHA LANE")])])]


SHOWS = [
    a_show("Awakening",
           step("fade_in", 900, GOLD, "#000000", "xy", gi="dark", x=KC_X, y=KC_Y),
           step("ripple", 1400, GOLD, "#301000", "xy", rate=450, gi="dark", x=KC_X, y=KC_Y),
           step("strobe", 400, "#ffffff", GOLD, "center", rate=55, gi="flash"),
           step("burst", 800, "#ffffff", GOLD, "xy", gi="dark", x=KC_X, y=KC_Y),
           step("fade", 500, GOLD, "#000000", "center", blend=200)),
    a_show("Crack",
           step("bolts", 700, "#ffffff", GOLD, "xy", rate=120, gi="flash", x=KC_X, y=KC_Y),
           step("burst", 500, GOLD, "#000000", "xy", gi="dark", x=KC_X, y=KC_Y),
           step("fade", 300, GOLD, "#000000", "center")),
    a_show("Absorb",
           step("implode", 700, RED, GOLD, "xy", gi="dark", x=KC_X, y=KC_Y),
           step("pulse", 500, GOLD, "#301000", "xy", rate=250, gi="dark", x=KC_X, y=KC_Y),
           step("fade", 300, GOLD, "#000000", "center")),
    a_show("Reflect",
           step("strobe", 300, "#ffffff", GOLD, "center", rate=50, gi="flash"),
           step("sweep_rl", 600, "#ffffff", GOLD, "center", gi="dark"),
           step("burst", 700, GOLD, RED, "top", gi="dark"),
           step("fade", 400, RED, "#000000", "center", blend=150)),
    a_show("Tag team",
           step("sweep_lr", 450, BLUE, "#000000", "center", gi="dark"),
           step("sweep_rl", 450, GOLD, "#000000", "center", gi="dark"),
           step("spin", 900, "#ffffff", BLUE, "center", rate=90, gi="dark"),
           step("fade", 400, GOLD, "#000000", "center")),
    a_show("Stage up",
           step("strobe", 400, "#ffffff", GOLD, "center", rate=55, gi="flash"),
           step("spiral_out", 1200, GOLD, "#200800", "center", gi="dark"),
           step("rainbow", 1200, "#000000", "#000000", "center", rate=60),
           step("fade", 500, GOLD, "#000000", "center", blend=200)),
    a_show("Final blow",
           step("strobe", 600, "#ffffff", RED, "center", rate=45, gi="flash"),
           step("fire", 1400, "#ffc000", RED, "top", gi="dark"),
           step("burst", 900, "#ffffff", GOLD, "top", gi="flash"),
           step("rainbow", 2000, "#000000", "#000000", "center", rate=50),
           step("fade", 700, GOLD, "#000000", "center", blend=300)),
    a_show("Back to sleep",
           step("solid", 600, GOLD, "#000000", "center", gi="dark"),
           step("implode", 1200, GOLD, "#000000", "xy", gi="dark", x=KC_X, y=KC_Y),
           step("fade", 900, GOLD, "#000000", "xy", gi="keep", blend=400, x=KC_X, y=KC_Y)),
]


def setup_stage():
    """What each stage lights and says as it begins (run by the "next" timer once the stage before is done): its
    title, its line, its clock."""
    return [
        if_(eq("stage", 2), stage_line(2) + [
            hud_counter(3, 0, "OF 3", "REFLECTED"), set_time(STAGE_SECS[2]),
            set_("beam", 1), set_("charge", 0),
            timer_start("beam", pack.WINDOW_S * 1000), timer_start("say", 1),
        ]),
        if_(eq("stage", 3), stage_line(3, "SHOOT THE GODZILLA TARGET") + [
            hud_counter(3, 0, "OF 3", "COMBOS"), set_time(STAGE_SECS[3]),
            timer_stop("beam"),
        ] + [off(s) for s in BEAM] + [off(LANE), off_insert("MECHA LANE"),
                                      light("Godzilla target", BLUE, "blink", 300)]),
        if_(eq("stage", 4), stage_line(4, "SHOOT THE BUILDING: TEAR HIS HEAD OFF") + [
            hud_counter(3, 3, "TO GO", "HEAD"), set_time(STAGE_SECS[4]),
            off("Godzilla target"), off("Pop bumper"), off(LANE), off_insert("MECHA LANE"),
            light("Building", RED, "chase", 100),
        ]),
    ]


_PRAYER = ("KING CAESAR IS LIT", "SHOOT THE MECHA LANE", "HIT THE POP BUMPERS", "TO WAKE KING CAESAR")

SCRIPTS = [
    # ---- the prayer: lit at the Mecha lane --------------------------------------------------------------------
    on_shot("Pop bumper", *pack.count_up("prayer", 1, NEED, "ready", "note at", LANE, GOLD, START_INSERTS, *_PRAYER),
            when="idle"),
    on_shot("Right return lane", *pack.count_up("prayer", 2, NEED, "ready", "note at", LANE, GOLD, START_INSERTS,
                                           *_PRAYER), when="idle"),
    on_shot(LANE, *pack.count_up("prayer", 3, NEED, "ready", "note at", LANE, GOLD, START_INSERTS, *_PRAYER),
            when="idle"),
    pack.relight("ready", LANE, GOLD, START_INSERTS),

    # ---- he wakes ---------------------------------------------------------------------------------------------
    on_start(*pack.begin(SLUG),
             set_("ready", 0), set_("prayer", 0), change("woken", 1),
             set_("note at", 5),
             set_("stage", 1), set_("pot", 0), set_("cracks", 0), set_("won", 0), set_("cashed", 0),
             set_("crack pop", 0), set_("crack ramp", 0), set_("crack lane", 0),
             set_("reflects", 0), set_("combos", 0), set_("head", 0),
             # deeper each time: the stage values grow
             set_("crack value", add(3000000, mul(1500000, sub(var("woken"), 1)))),
             clip("intro", "full"), clip("loop", "loop"), sound("roar"), show("Awakening"),
             shake(700, "strong"),
             *stage_line(1, "POP BUMPERS, RIGHT RAMP AND MECHA LANE"),
             hud_counter(2, 0, "CASH AT SCOOP"), hud_counter(3, 0, "OF 3", "CRACKS"),
             light("Pop bumper", GOLD, "blink", 250), light("Right ramp", GOLD, "blink", 250),
             light(LANE, GOLD, "blink", 250), light_insert("MECHA LANE", GOLD, "blink", 250)),

    # ---- stage 1: the shrine cracks ----------------------------------------------------------------------------
    on_shot("Pop bumper",
            if_(AND(eq("stage", 1), eq("crack pop", 0)), [set_("crack pop", 1), off("Pop bumper"),
                                                         change("cracks", 1), timer_start("crack", 1)]),
            if_(eq("stage", 3), [timer_start("caesar", 1)])),
    on_shot("Right ramp",
            if_(AND(eq("stage", 1), eq("crack ramp", 0)), [set_("crack ramp", 1), off("Right ramp"),
                                                          change("cracks", 1), timer_start("crack", 1)])),
    on_shot(LANE,
            if_(AND(eq("stage", 1), eq("crack lane", 0)), [set_("crack lane", 1), off(LANE), off_insert("MECHA LANE"),
                                                          change("cracks", 1), timer_start("crack", 1)]),
            # stage 2: the charges fired back
            if_(AND(eq("stage", 2), gt("charge", 0)), [
                *pot_up(mul(5000000, var("charge"))), score(2000000), pack.clock_floor(),
                change("reflects", 1), set_("charge", 0), hud_counter(3, var("reflects"), "OF 3"),
                clip("reflect", "behind"), sound("reflect"), show("Reflect"), shake(400, "hard"),
                timer_start("say", 1),
                if_(ge("reflects", 3), [award("MECHA REELS", value=var("pot"), sub=POT_SUB),
                                        timer_start("next", 700)],
                    [if_(eq("beam", i), [award("REFLECTED", value=var("reflects"), sub="NOW THE " + _words(s))])
                     for i, s in enumerate(BEAM, 1)])]),
            if_(eq("stage", 3), [timer_start("caesar", 1)])),
    on_timer("crack",
             pack.clock_floor(), score(1000000), *pot_up(var("crack value")), hud_counter(3, var("cracks"), "OF 3"),
             clip("crack", "behind"), sound("crack"), show("Crack"), shake(300, "medium"),
             if_(ge("cracks", 3), [award("CAESAR AWAKENS", value=var("pot"), sub=POT_SUB), clip("awake", "behind"),
                                   sound("roar"), timer_start("next", 700)],
                 crack_left())),

    # ---- stage 2: absorb and reflect ---------------------------------------------------------------------------
    on_timer("beam",
             if_(eq("stage", 2), [
                 change("beam", 1), if_(gt("beam", 4), [set_("beam", 1)]),
                 timer_start("say", 1),
                 timer_start("beam", pack.WINDOW_S * 1000)])),
    on_timer("say", *reflect_lights()),
    on_shot("Left ramp", if_(AND(eq("stage", 2), eq("beam", 1)), [timer_start("absorb", 1)])),
    on_shot("Big loop", if_(AND(eq("stage", 2), eq("beam", 2)), [timer_start("absorb", 1)])),
    on_shot("Right ramp", if_(AND(eq("stage", 2), eq("beam", 3)), [timer_start("absorb", 1)])),
    on_shot("Building",
            if_(AND(eq("stage", 2), eq("beam", 4)), [timer_start("absorb", 1)]),
            # ---- stage 4: the final blow ---------------------------------------------------------------------
            if_(eq("stage", 4), [
                change("head", 1), hud_counter(3, sub(3, var("head")), "TO GO"), score(3000000), pack.clock_floor(),
                shake(500, "hard"), sound("reflect"),
                if_(ge("head", 3), [
                    set_("won", 1), score(add(mul(var("pot"), 2), 25000000)),
                    award("HEAD TORN OFF", value=add(mul(var("pot"), 2), 25000000), sub="SUPER JACKPOT",
                          seconds=4),
                    clip("won", "full"), sound("won"), show("Final blow"), shake_game("multiball_start"),
                    end()],
                    [clip("absorb", "behind"), award("THE HEAD CRACKS", value=var("head"),
                                                     sub="OF 3: THE BUILDING AGAIN")])])),
    on_timer("absorb",
             if_(lt("charge", 3), [
                 change("charge", 1), score(1000000), add_time(5), pack.clock_floor(),
                 clip("absorb", "behind"), sound("absorb"), show("Absorb"),
                 award("ABSORBED", value=var("charge"), sub="FIRE AT THE MECHA LANE"),
                 timer_start("say", 1)])),

    # ---- stage 3: tag team with Godzilla ----------------------------------------------------------------------
    on_shot("Godzilla target",
            if_(eq("stage", 3), [
                timer_start("combo", pack.WINDOW_S * 1000), sound("tagteam"), score(500000), pack.clock_floor(),
                light("Pop bumper", GOLD, "chase", 100), light(LANE, GOLD, "chase", 100),
                light_insert("MECHA LANE", GOLD, "chase", 100),
                hud_line("COMBO: HIT POP BUMPERS OR MECHA LANE"),
                award("GODZILLA ATTACKS", sub="NOW POP BUMPERS OR MECHA LANE")])),
    on_timer("caesar",
             if_(gt(timer_left("combo"), 0), [
                 timer_stop("combo"), change("combos", 1), *pot_up(mul(8000000, var("combos"))), score(2000000),
                 hud_counter(3, var("combos"), "OF 3"), add_time(5), pack.clock_floor(),
                 clip("tagteam", "behind"), show("Tag team"), shake(350, "strong"),
                 off("Pop bumper"), off(LANE), off_insert("MECHA LANE"), hud_line("SHOOT THE GODZILLA TARGET"),
                 if_(ge("combos", 3), [award("THE TAG TEAM", value=var("pot"), sub=POT_SUB), timer_start("next", 700)],
                     [award("TAG TEAM COMBO", value=var("combos"), sub="NOW THE GODZILLA TARGET")])])),
    # the window ran out: back to the Godzilla target
    on_timer("combo", off("Pop bumper"), off(LANE), off_insert("MECHA LANE"),
             if_(eq("stage", 3), [hud_line("SHOOT THE GODZILLA TARGET")])),

    # ---- a stage done: on to the next, or cash out --------------------------------------------------------------
    on_timer("next",
             if_(eq("cashed", 1), [end()], [
                 change("stage", 1), show("Stage up"), shake_game("jackpot"),
                 *pack.cash_out_lit(), *setup_stage()])),
    on_shot(pack.CASH_SHOT,
            if_(AND(ge("stage", 2), eq("won", 0), eq("cashed", 0)), [
                set_("cashed", 1), score(var("pot")),
                award("CASHED OUT", value=var("pot"), sub="KING CAESAR SLEEPS", seconds=4),
                clip("cashout", "full"), sound("cashout"), show("Back to sleep"), timer_start("next", 1500)])),
    # the scoop hurries in the last 10 s once it cashes out (not in AWAKENING: nothing to cash yet)
    secs_left(10, callout("ten_seconds"), if_(ge("stage", 2), [light(pack.CASH_SHOT, pack.WHITE, "hurry")])),

    # ---- the end -----------------------------------------------------------------------------------------------
    on_end(*pack.finish(), set_("stage", 0),
           if_(eq("won", 1), [hud_title("MECHAGODZILLA DEFEATED"), hud_line("KING CAESAR AND GODZILLA WIN")]),
           if_(eq("cashed", 1), [hud_title("KING CAESAR SLEEPS"), hud_line("THE POT IS CASHED OUT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [hud_title("KING CAESAR FALLS"), hud_line("A QUARTER OF THE POT")]),
           *[timer_stop(t) for t in TIMERS],
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               score(div(var("pot"), 4)),
               award("KING CAESAR FALLS", value=div(var("pot"), 4), sub="A QUARTER OF THE POT", seconds=3),
               clip("lost", "full"), sound("lost"), show("Back to sleep")])),
]


PROGRAM = {
    "name": NAME, "seconds": STAGE_SECS[1], "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": pack.pack_vars() + [
        {"name": n, "reset": "game"} for n in ("prayer", "ready", "note at", "woken")] + [
        {"name": n, "reset": "mode"} for n in ("stage", "pot", "cracks", "crack pop", "crack ramp", "crack lane",
                                                "crack value", "beam", "charge", "reflects", "combos",
                                                "head", "won", "cashed")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("POP BUMPERS, RIGHT RAMP AND MECHA LANE",
               counters=[("STAGE", "OF 4", None), ("POT", "CASH AT SCOOP", None), ("CRACKS", "OF 3", None)],
               timer=("CAESAR", "crystal")),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "crack", "awake", "absorb", "reflect", "tagteam", "won", "lost", "cashout"),
    "sounds": sounds({"roar": 4, "crack": 3, "absorb": 3, "reflect": 3, "tagteam": 4, "won": 4, "lost": 4,
                      "cashout": 4}),
    "music": "music.wav",
    "shows": SHOWS,
    "scripts": None,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 1, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "",
    "about": ("New (PAD-658). The prayer at his pop bumper wakes him at the Mecha lane; four stages, each with its "
              "own shots named on the line (crack the shrine, absorb and reflect the beam, tag team with Godzilla, "
              "the final blow); cash the pot out at the right scoop after any stage. Godzilla vs. Mechagodzilla "
              "(1974)."),
    "lost": [],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _shots(name, n):
    out = []
    for _i in range(n):
        out += ["shot", name, "ms", 300]
    return out


#: the desk scenarios (make_examples.py --desk): what, the harness's commands, lines its output must hold
_START = ["trigger", "king_caesar.start", "secs", 1]
_STAGE1 = ["shot", "Pop bumper", "ms", 400, "shot", "Right ramp", "ms", 400, "shot", "Mecha exit bottom", "secs", 1]
_STAGE2 = ["shot", "Left ramp", "ms", 300, "shot", "Mecha exit bottom", "ms", 300] * 3 + ["secs", 1]
_STAGE3 = ["shot", "Godzilla target", "ms", 500, "shot", "Pop bumper", "ms", 500] * 3 + ["secs", 1]
DESK = [
    ("the prayer lights it", _shots("Pop bumper", 39) + ["secs", 1] + _shots("Pop bumper", 1) +
     ["shot", "Mecha exit bottom", "secs", 2],
     ["WORDS PadMode_king_caesar_Hud_Award: KING CAESAR IS LIT", "[KING CAESAR] START (its lit shot)",
      "Hud_Award: HIT THE POP BUMPERS", "Hud_AwardSub: 39  -  TO WAKE KING CAESAR"]),
    ("stage one then cash out", _START + _STAGE1 + ["shot", "Right scoop", "secs", 5],
     ["Hud_Title: KING CAESAR: AWAKENING", "Hud_Line: POP BUMPERS, RIGHT RAMP AND MECHA LANE",
      "Hud_Line: SHOOT THE RIGHT RAMP AND MECHA LANE", "Hud_AwardSub: NOW RIGHT RAMP AND MECHA LANE",
      "Hud_Line: SHOOT THE MECHA LANE", "Hud_AwardSub: NOW THE MECHA LANE",
      "Hud_Title: KING CAESAR SLEEPS", "Hud_Award: CAESAR AWAKENS", "  -  POT: CASH AT RIGHT SCOOP",
      "Hud_Title: KING CAESAR: REFLECT", "Hud_Line: ABSORB THE BEAM: SHOOT THE LEFT RAMP", "SCORE +9000000",
      "END (a block): 4 scores, total 12000000", "lamps held 0"]),
    ("all four stages", _START + _STAGE1 + _STAGE2 + _STAGE3 +
     ["shot", "Building", "ms", 500, "shot", "Building", "ms", 500, "shot", "Building", "secs", 6],
     ["Hud_Title: MECHAGODZILLA DEFEATED", "Hud_AwardSub: 1  -  FIRE AT THE MECHA LANE",
      "Hud_Line: FIRE IT BACK: SHOOT THE MECHA LANE", "Hud_AwardSub: 1  -  NOW THE LEFT RAMP",
      "Hud_Award: MECHA REELS", "Hud_Title: KING CAESAR: TAG TEAM",
      "Hud_Line: SHOOT THE GODZILLA TARGET", "Hud_Line: COMBO: HIT POP BUMPERS OR MECHA LANE",
      "Hud_AwardSub: 1  -  NOW THE GODZILLA TARGET", "Hud_Award: THE TAG TEAM",
      "Hud_Title: KING CAESAR: THE FINAL BLOW", "Hud_Line: SHOOT THE BUILDING: TEAR HIS HEAD OFF",
      "Hud_AwardSub: 1  -  OF 3: THE BUILDING AGAIN", "SCORE +169000000", "END (a block)"]),
    # (its Godzilla target hits lit MINILLA too: built in beside it)
    # REFLECT's 55 s run out: a quarter of AWAKENING's 9,000,000
    ("the clock pays a quarter", _START + _STAGE1 + ["secs", STAGE_SECS[2] + 5],
     ["Hud_Title: KING CAESAR FALLS", "END (time ran out)", "SCORE +2250000", "lamps held 0"]),
    # the beam stays a window on its shot, then moves on to the next
    ("the beam moves on", _START + _STAGE1 + ["secs", pack.WINDOW_S + 1, "shot", "Big loop", "secs", 3],
     ["Hud_Line: ABSORB THE BEAM: SHOOT THE LEFT RAMP", "Hud_Line: ABSORB THE BEAM: SHOOT THE BIG LOOP",
      "LAMP BIG LOOP ff0000 blink 250", "Hud_Award: ABSORBED", "Hud_Line: FIRE IT BACK: SHOOT THE MECHA LANE",
      "LAMP MECHA LANE ffb000 chase 120"]),
]
