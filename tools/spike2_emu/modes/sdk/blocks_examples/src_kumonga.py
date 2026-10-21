"""KUMONGA (PAD-658): the giant spider of Sollgel Island, deeper and deeper into her web, or cash out.

Son of Godzilla (1967): Kumonga wakes in the valley, webs Minilla and Godzilla in strands and stabs with her
stinger, until Godzilla and Minilla burn her together. On the playfield she clings above the scoop, on the shield
platform's rim, where the Shield ramp spinner turns.

After Lyman Sheats: a meter that costs more each time (Metallica's Sparky), stages with their own rules and shots,
regrowth that pushes back (KING GHIDORAH's heads, TWD's walkers), a hurry-up (EHoH's), a pot to cash out or risk
(Metallica's Crank It Up), and failing still pays a quarter of it.

- SPIN THE WEB: every spin of the Shield ramp spinner counts; 40 lights the Big loop (20 more each time).
- STAGE 1, THE WEB: the shields turn toward the player; the three Shield targets and both ramps are webbed (purple).
  Each one torn pays 2M and 1M more for each torn before it, to the pot; Kumonga webs one again every 10 s (7 s,
  then 5 s, the more often she has been fought). Tear all five.
- STAGE 2, STRANDS: the shields turn away; every spinner spin cuts a strand (100K): 60 of them (20 more each time),
  5M to the pot each 10.
- STAGE 3, THE STING: a hurry-up at the Big loop from 20M, 250K a second down to 5M, into the pot.
- STAGE 4, FIRE: the Building (Godzilla's ray) then within 8 s the Right ramp (Minilla's): a BURN, 10M each to the
  pot; the third burns her: the pot twice over and 30M.
- CASH OUT at the right scoop after any stage; the clock (45 s a stage) or a drain pays a quarter of the pot.
"""
from blk import (AND, BALLS, a_show, add, add_time, award, callout, change, clip, clips, div, end, eq, every, ge, gt,
                 hud, hud_counter, hud_line, if_, le, light, light_insert, lt, mul, off, off_insert, on_end, on_shot, on_start,
                 on_timer, score, secs_left, set_, set_time, shake, shake_game, shield, show, sound, sounds, step, sub,
                 timer_left, timer_start, timer_stop, var)
import pack

SLUG, NAME = "kumonga", "KUMONGA"
PURPLE, WHITE, AMBER, RED, BLUE = "#b040ff", "#ffffff", "#ffb000", "#ff2000", "#3080ff"
SPIN, START_SHOT = "Shield ramp spinner", "Big loop"
WEBS = (("web l", "Shield target left"), ("web c", "Shield target center"), ("web r", "Shield target right"),
        ("web lr", "Left ramp"), ("web rr", "Right ramp"))
SPINNERS = ("Left spinner", "Top spinner", "Shield ramp spinner")
NEED = add(40, mul(20, var("fought")))
TIMERS = ("tear", "regrow", "next", "burn", "fire")
KX, KY = 251, 302              # her art on the playfield picture, above the scoop


def stage_line(n, words):
    return [hud_line(words), hud_counter(1, n, "OF 4")]


def pot_up(points):
    return [change("pot", points), hud_counter(2, var("pot"), "CASH AT SCOOP")]


def webbed_left():
    return add(add(add(add(var("web l"), var("web c")), var("web r")), var("web lr")), var("web rr"))


SHOWS = [
    a_show("She wakes",
           step("sparkle", 900, PURPLE, "#100020", "xy", gi="dark", x=KX, y=KY),
           step("spiral_out", 1400, PURPLE, "#100020", "xy", gi="dark", x=KX, y=KY),
           step("strobe", 400, WHITE, PURPLE, "center", rate=55, gi="flash"),
           step("fade", 500, PURPLE, "#000000", "center", blend=200)),
    a_show("Web",
           step("spin", 700, WHITE, PURPLE, "xy", rate=70, gi="dark", x=KX, y=KY),
           step("fade", 300, PURPLE, "#000000", "center")),
    a_show("Tear",
           step("burst", 450, WHITE, PURPLE, "center", gi="flash"),
           step("fade", 250, PURPLE, "#000000", "center")),
    a_show("Strands",
           step("sweep_up", 500, WHITE, PURPLE, "center", gi="dark"),
           step("sweep_down", 500, WHITE, PURPLE, "center", gi="dark"),
           step("fade", 300, PURPLE, "#000000", "center")),
    a_show("Sting",
           step("bolts", 900, RED, "#200000", "xy", rate=110, gi="dark", x=KX, y=KY),
           step("implode", 600, RED, PURPLE, "xy", gi="dark", x=KX, y=KY),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Burn",
           step("strobe", 300, WHITE, AMBER, "center", rate=50, gi="flash"),
           step("fire", 1100, "#ffc000", RED, "xy", gi="dark", x=KX, y=KY),
           step("fade", 400, RED, "#000000", "center", blend=150)),
    a_show("Stage up",
           step("strobe", 400, WHITE, PURPLE, "center", rate=55, gi="flash"),
           step("ripple", 1300, PURPLE, "#100020", "center", rate=450, gi="dark"),
           step("rainbow", 1100, "#000000", "#000000", "center", rate=60),
           step("fade", 500, PURPLE, "#000000", "center", blend=200)),
    a_show("She burns",
           step("strobe", 600, WHITE, RED, "center", rate=45, gi="flash"),
           step("fire", 1600, "#ffc000", RED, "xy", gi="dark", x=KX, y=KY),
           step("burst", 900, WHITE, AMBER, "xy", gi="flash", x=KX, y=KY),
           step("rainbow", 1800, "#000000", "#000000", "center", rate=50),
           step("fade", 700, AMBER, "#000000", "center", blend=300)),
    a_show("She leaves",
           step("implode", 1200, PURPLE, "#000000", "xy", gi="dark", x=KX, y=KY),
           step("fade", 900, PURPLE, "#000000", "center", blend=400)),
]


def web_lights():
    return [if_(eq(v, 1), [light(s, PURPLE, "chase", 110)], [off(s)]) for v, s in WEBS]


def setup_stage():
    return [
        if_(eq("stage", 2), stage_line(2, "STRANDS: SPIN EVERY SPINNER") + [
            shield("away"), timer_stop("regrow"),
            set_("strands", add(60, mul(20, sub(var("fought"), 1)))),
            hud_counter(3, var("strands"), "STRANDS LEFT"),
        ] + [off(s) for _v, s in WEBS] + [light(s, WHITE, "blink", 200) for s in SPINNERS]
          + [light_insert("LEFT SPINNER", WHITE, "blink", 200)]),
        if_(eq("stage", 3), stage_line(3, "THE STING: SHOOT THE BIG LOOP") + [
            set_("sting", 20000000), hud_counter(3, var("sting"), "STING"),
        ] + [off(s) for s in SPINNERS] + [off_insert("LEFT SPINNER"), light(START_SHOT, RED, "hurry")]),
        if_(eq("stage", 4), stage_line(4, "FIRE: BUILDING, THEN RIGHT RAMP") + [
            off(START_SHOT), hud_counter(3, 0, "BURNS"), light("Building", AMBER, "blink", 200),
        ]),
    ]


SCRIPTS = [
    # ---- spin the web: lit at the Big loop ---------------------------------------------------------------------
    on_shot(SPIN, *pack.count_up("spins", 1, NEED, "ready", "note at", START_SHOT, PURPLE, "",
                                 "KUMONGA IS LIT", "SHOOT THE BIG LOOP", "SPIN THE WEB", "MORE TO WAKE KUMONGA",
                                 step=10), when="idle"),
    pack.relight("ready", START_SHOT, PURPLE),

    # ---- she wakes -----------------------------------------------------------------------------------------------
    on_start(*pack.begin(SLUG),
             set_("ready", 0), set_("spins", 0), set_("note at", 0), change("fought", 1),
             set_("stage", 1), set_("pot", 0), set_("torn", 0), set_("won", 0), set_("cashed", 0), set_("burns", 0),
             *[set_(v, 1) for v, _s in WEBS],
             set_("regrow ms", 10000), if_(ge("fought", 2), [set_("regrow ms", 7000)]),
             if_(ge("fought", 3), [set_("regrow ms", 5000)]),
             timer_start("regrow", var("regrow ms")),
             shield("toward"),
             clip("intro", "full"), clip("loop", "loop"), sound("chitter"), show("She wakes"), shake(600, "strong"),
             *stage_line(1, "THE WEB: TEAR THE PURPLE SHOTS"),
             hud_counter(2, 0, "CASH AT SCOOP"), hud_counter(3, 5, "WEBS LEFT"),
             *web_lights()),

    # ---- stage 1: tear the web -----------------------------------------------------------------------------------
    *[on_shot(s, if_(AND(eq("stage", 1), eq(v, 1)), [set_(v, 0), off(s), timer_start("tear", 1)]))
      for v, s in WEBS if not s.endswith("ramp")],
    on_shot("Left ramp", if_(AND(eq("stage", 1), eq("web lr", 1)), [set_("web lr", 0), off("Left ramp"),
                                                                    timer_start("tear", 1)])),
    on_shot("Right ramp",
            if_(AND(eq("stage", 1), eq("web rr", 1)), [set_("web rr", 0), off("Right ramp"), timer_start("tear", 1)]),
            if_(AND(eq("stage", 4), gt(timer_left("fire"), 0)), [timer_start("burn", 1)])),
    on_timer("tear",
             change("torn", 1), score(500000), *pot_up(add(2000000, mul(1000000, sub(var("torn"), 1)))),
             hud_counter(3, webbed_left(), "WEBS LEFT"),
             clip("tear", "behind"), sound("tear"), show("Tear"), shake(250, "medium"),
             if_(eq(webbed_left(), 0), [award("THE WEB IS TORN", value=var("pot"), sub="POT"), timer_start("next", 1)],
                 [award("WEB TORN", value=webbed_left(), sub="LEFT")])),
    on_timer("regrow",
             if_(eq("stage", 1), [
                 if_(eq("web l", 0), [set_("web l", 1)], [
                     if_(eq("web c", 0), [set_("web c", 1)], [
                         if_(eq("web r", 0), [set_("web r", 1)], [
                             if_(eq("web lr", 0), [set_("web lr", 1)], [
                                 if_(eq("web rr", 0), [set_("web rr", 1)])])])])]),
                 *web_lights(), hud_counter(3, webbed_left(), "WEBS LEFT"),
                 clip("web", "behind"), sound("web"), show("Web"),
                 award("KUMONGA WEBS AGAIN", value=webbed_left(), sub="LEFT"),
                 timer_start("regrow", var("regrow ms"))])),

    # ---- stage 2: cut the strands ----------------------------------------------------------------------------------
    *[on_shot(s, if_(eq("stage", 2), [
        change("strands", -1), score(100000), hud_counter(3, var("strands"), "STRANDS LEFT"),
        change("cut", 1),
        if_(ge("cut", 10), [set_("cut", 0), *pot_up(5000000), sound("tear"), show("Strands"),
                            award("STRANDS CUT", value=var("strands"), sub="LEFT")]),
        if_(le(var("strands"), 0), [award("CUT FREE", value=var("pot"), sub="POT"), clip("strand", "behind"),
                                      timer_start("next", 1)])])) for s in SPINNERS if s != SPIN],
    on_shot(SPIN, if_(eq("stage", 2), [
        change("strands", -1), score(100000), hud_counter(3, var("strands"), "STRANDS LEFT"), change("cut", 1),
        if_(ge("cut", 10), [set_("cut", 0), *pot_up(5000000), sound("tear"), show("Strands"),
                            award("STRANDS CUT", value=var("strands"), sub="LEFT")]),
        if_(le(var("strands"), 0), [award("CUT FREE", value=var("pot"), sub="POT"), clip("strand", "behind"),
                                      timer_start("next", 1)])])),

    # ---- stage 3: the sting -----------------------------------------------------------------------------------------
    every(1, if_(AND(eq("stage", 3), gt("sting", 5000000)), [change("sting", -250000),
                                                              hud_counter(3, var("sting"), "STING")])),
    on_shot(START_SHOT, if_(eq("stage", 3), [
        *pot_up(var("sting")), score(2000000), clip("sting", "behind"), sound("sting"), show("Sting"),
        shake(450, "hard"), award("THE STING", value=var("sting"), sub="INTO THE POT"), timer_start("next", 1)])),

    # ---- stage 4: fire ----------------------------------------------------------------------------------------------
    on_shot("Building", if_(eq("stage", 4), [
        timer_start("fire", 8000), score(1000000), sound("burn"),
        light("Right ramp", AMBER, "blink", 100), award("GODZILLA FIRES", sub="NOW MINILLA: THE RIGHT RAMP")])),
    on_timer("burn",
             timer_stop("fire"), off("Right ramp"), change("burns", 1), *pot_up(10000000), score(3000000),
             hud_counter(3, var("burns"), "BURNS"), clip("burn", "behind"), show("Burn"), shake(500, "hard"),
             if_(ge("burns", 3), [
                 set_("won", 1), score(add(mul(var("pot"), 2), 30000000)),
                 award("KUMONGA BURNS", value=add(mul(var("pot"), 2), 30000000), sub="SUPER JACKPOT", seconds=4),
                 clip("won", "full"), sound("won"), show("She burns"), shake_game("multiball_start"), end()],
                 [award("BURN", value=var("burns"), sub="OF 3")])),
    on_timer("fire", off("Right ramp")),

    # ---- a stage done: on to the next, or cash out -------------------------------------------------------------------
    on_timer("next", change("stage", 1), set_time(45), show("Stage up"), shake_game("jackpot"),
             *pack.cash_out_lit(), *setup_stage()),
    on_shot(pack.CASH_SHOT, if_(AND(ge("stage", 2), eq("won", 0)), [
        set_("cashed", 1), score(var("pot")), award("CASHED OUT", value=var("pot"), sub="KUMONGA RETREATS", seconds=4),
        clip("cashout", "full"), sound("cashout"), show("She leaves"), end()])),
    secs_left(10, callout("ten_seconds"), light(pack.CASH_SHOT, pack.WHITE, "hurry")),

    on_end(*pack.finish(), set_("stage", 0), *[timer_stop(t) for t in TIMERS],
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               score(div(var("pot"), 4)),
               award("CAUGHT IN THE WEB", value=div(var("pot"), 4), sub="A QUARTER OF THE POT", seconds=3),
               clip("lost", "full"), sound("lost"), show("She leaves")])),
]


PROGRAM = {
    "name": NAME, "seconds": 45, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": pack.pack_vars() + [{"name": n, "reset": "game"} for n in ("spins", "ready", "note at", "fought")] + [
        {"name": n, "reset": "mode"} for n in ("stage", "pot", "torn", "regrow ms", "strands", "cut", "sting",
                                                "burns", "won", "cashed")] + [
        {"name": v, "reset": "mode"} for v, _s in WEBS],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("THE WEB: TEAR THE PURPLE SHOTS",
               counters=[("STAGE", "OF 4", None), ("POT", "CASH AT SCOOP", None), ("WEBS", "LEFT", None)],
               timer=("KUMONGA", "claw")),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "web", "tear", "strand", "sting", "burn", "won", "lost", "cashout"),
    "sounds": sounds({"chitter": 4, "web": 3, "tear": 3, "sting": 4, "burn": 3, "won": 4, "lost": 4, "cashout": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 2, "titles": ["godzilla_le"], "based_on": "",
    "about": ("New (PAD-658). Spin the Shield ramp spinner to wake her at the Big loop; four stages (tear the web "
              "on the shield platform while she webs it again, cut the strands on every spinner, the sting "
              "hurry-up, burn her with Godzilla and Minilla); cash the pot out at the right scoop. Son of "
              "Godzilla (1967)."),
    "lost": [],
}


def _shots(name, n, gap=200):
    out = []
    for _i in range(n):
        out += ["shot", name, "ms", gap]
    return out


_START = ["trigger", "kumonga.start", "secs", 1]
_STAGE1 = ["shot", "Shield target left", "ms", 300, "shot", "Shield target center", "ms", 300,
           "shot", "Shield target right", "ms", 300, "shot", "Left ramp", "ms", 300, "shot", "Right ramp", "secs", 1]
_STAGE2 = _shots("Top spinner", 60, 60) + ["secs", 1]
_STAGE3 = ["secs", 4, "shot", "Big loop", "secs", 1]
_STAGE4 = ["shot", "Building", "ms", 500, "shot", "Right ramp", "ms", 500] * 3 + ["secs", 6]
DESK = [
    ("spinning lights it", _shots(SPIN, 40) + ["shot", "Big loop", "secs", 2],
     ["Hud_Award: KUMONGA IS LIT", "[KUMONGA] START (its lit shot)", "SHIELD toward"]),
    ("the web grows back", _START + ["shot", "Left ramp", "secs", 11],
     ["Hud_Award: KUMONGA WEBS AGAIN", "LAMP LEFT RAMP b040ff chase"]),
    ("all four stages", _START + _STAGE1 + _STAGE2 + _STAGE3 + _STAGE4,
     ["Hud_Award: THE WEB IS TORN", "Hud_Award: CUT FREE", "Hud_Award: THE STING", "SHIELD away",
      "END (a block)", "lamps held 0"]),
    ("cash out after the web", _START + _STAGE1 + ["shot", "Right scoop", "secs", 5],
     ["SCORE +20000000", "END (a block)", "lamps held 0"]),
]


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)
